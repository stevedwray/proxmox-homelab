#!/usr/bin/env python3
"""Local reliability proxy for GitHub Copilot Chat -> Ollama (Laguna S 2.1).

Why this exists: this project's own history (see docs/coding-stack/plan.md
Phase 1, and the memory notes on Ollama corruption bugs) documents real,
repeated failure modes on this Ollama build that Copilot's own client has
no protection against at all:

  - Degenerate empty-content responses (e.g. {"content": ""} with a
    non-"stop" finish reason).
  - Dense/structured content occasionally degenerating into a long run of
    "?" characters instead of real output.
  - A known mitigation that actually works: reload the model (unload,
    then let the next call reload it) before/after a bad response.
    Ollama's own docs call this out as the fix for exactly this kind of
    corruption; this project verified it works in practice.

Copilot talks straight to Ollama's OpenAI-compatible endpoint with none of
that protection. This proxy sits in between: forward the request, inspect
the actual response, and if it looks degenerate, force-unload the model
and retry once before ever handing anything back to Copilot. Silent
corruption becomes either a correct retried answer or a loud, visible
error -- never a bad answer that looks fine.

Deliberately stdlib-only (http.server + urllib) -- this runs as a small
background process on the operator's own workstation, not inside this
repo's infra, so it shouldn't need a venv/pip install to get started.

Known limitation (v1): the upstream call to Ollama is always non-
streaming (forced `stream: false`) so the full response can be validated
before it's returned. If the client asked for a streaming response, it
gets the complete answer back as a single SSE chunk rather than true
token-by-token streaming. That's a real UX tradeoff (the reply appears
all at once instead of incrementally) traded for the ability to catch a
bad response before the user ever sees it. Upgrading to real streaming
with post-hoc validation (buffer the stream, only replay it if it
validates, otherwise discard and retry) is possible later if the
incremental UX turns out to matter more than it seems right now.

Usage:
    OLLAMA_UPSTREAM=http://framework.gibbsgreatly.xyz:11434 \
        python3 scripts/ollama-reliability-proxy/proxy.py

Then point Copilot's chatLanguageModels.json `url` at
http://127.0.0.1:11435/v1/chat/completions instead of the real Ollama
host directly.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN_HOST = os.environ.get("PROXY_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("PROXY_PORT", "11435"))
UPSTREAM = os.environ.get("OLLAMA_UPSTREAM", "http://framework.gibbsgreatly.xyz:11434")
REQUEST_TIMEOUT_S = float(os.environ.get("PROXY_TIMEOUT_S", "180"))
UNLOAD_SETTLE_S = float(os.environ.get("PROXY_UNLOAD_SETTLE_S", "1.0"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("ollama-reliability-proxy")


def is_degenerate(message: dict, finish_reason: str | None) -> str | None:
    """Return a short reason string if the response looks like a known
    Ollama corruption pattern, else None. See module docstring for the
    documented failure modes this checks for."""
    content = (message or {}).get("content")
    if content is None or content.strip() == "":
        if finish_reason not in ("tool_calls",):
            return "empty content"
        return None
    stripped = content.strip()
    if len(stripped) > 20:
        q_ratio = stripped.count("?") / len(stripped)
        if q_ratio > 0.5:
            return f"degenerate '?' output ({q_ratio:.0%} of {len(stripped)} chars)"
    return None


def call_upstream(path: str, body: dict, timeout: float = REQUEST_TIMEOUT_S) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        UPSTREAM.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def unload_model(model: str) -> None:
    log.warning("unloading model %r to force a reload before retry", model)
    try:
        call_upstream("/api/generate", {"model": model, "keep_alive": 0})
    except Exception as e:  # best-effort -- the retry itself will surface any real problem
        log.warning("unload call failed (continuing to retry anyway): %s", e)
    time.sleep(UNLOAD_SETTLE_S)


def sse_wrap(completion: dict) -> bytes:
    """Turn one complete OpenAI-style chat completion into a minimal but
    valid SSE stream: one delta chunk carrying the full content, then
    [DONE]. See module docstring's "Known limitation" note."""
    choice = completion.get("choices", [{}])[0]
    message = choice.get("message", {})
    chunk = {
        "id": completion.get("id", "proxy-chunk"),
        "object": "chat.completion.chunk",
        "created": completion.get("created", int(time.time())),
        "model": completion.get("model", ""),
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": message.get("content", "")},
                "finish_reason": None,
            }
        ],
    }
    final_chunk = {
        **chunk,
        "choices": [
            {"index": 0, "delta": {}, "finish_reason": choice.get("finish_reason", "stop")}
        ],
    }
    out = f"data: {json.dumps(chunk)}\n\n" f"data: {json.dumps(final_chunk)}\n\n" "data: [DONE]\n\n"
    return out.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "OllamaReliabilityProxy/1.0"

    def log_message(self, fmt, *args):  # route BaseHTTPRequestHandler's own logging through ours
        log.info("%s - %s", self.address_string(), fmt % args)

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self._proxy_passthrough()
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON body"})
            return

        client_wanted_stream = bool(body.get("stream"))
        upstream_body = dict(body)
        upstream_body["stream"] = False
        model = upstream_body.get("model", "")

        status, completion = call_upstream("/v1/chat/completions", upstream_body)
        if status >= 400:
            self._send_json(status, completion)
            return

        choice = (completion.get("choices") or [{}])[0]
        reason = is_degenerate(choice.get("message", {}), choice.get("finish_reason"))
        if reason:
            log.warning("degenerate response detected (%s) -- retrying once after unload", reason)
            unload_model(model)
            status, completion = call_upstream("/v1/chat/completions", upstream_body)
            choice = (completion.get("choices") or [{}])[0]
            reason2 = is_degenerate(choice.get("message", {}), choice.get("finish_reason"))
            if reason2:
                log.error("still degenerate after retry (%s) -- surfacing as an error, not passing it through", reason2)
                self._send_json(
                    502,
                    {
                        "error": {
                            "message": f"ollama-reliability-proxy: response still looked degenerate after an unload+retry ({reason2}). Not passing this through silently.",
                            "type": "proxy_degenerate_response",
                        }
                    },
                )
                return
            log.info("retry succeeded after unload")

        if client_wanted_stream:
            self._send_sse(sse_wrap(completion))
        else:
            self._send_json(status, completion)

    def do_GET(self):
        self._proxy_passthrough()

    def _proxy_passthrough(self):
        """Any path other than the one we validate (e.g. /v1/models) just
        gets forwarded untouched, GET or POST."""
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else None
        req = urllib.request.Request(
            UPSTREAM.rstrip("/") + self.path,
            data=raw,
            headers={"Content-Type": "application/json"} if raw else {},
            method=self.command,
        )
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
                self._send_json(resp.status, json.loads(resp.read().decode("utf-8")))
        except urllib.error.HTTPError as e:
            self._send_json(e.code, json.loads(e.read().decode("utf-8") or "{}"))
        except Exception as e:
            self._send_json(502, {"error": str(e)})

    def _send_json(self, status: int, payload: dict):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_sse(self, data: bytes):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)


def main():
    log.info("ollama-reliability-proxy listening on http://%s:%d -> upstream %s", LISTEN_HOST, LISTEN_PORT, UPSTREAM)
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Local reverse proxy between PentestGPT-legacy and a remote Ollama host.

PentestGPT-legacy's `ollama:<model>` connector talks OpenAI-compatible
/v1/chat/completions and does not stream or post-process responses
(pentestgpt_legacy/llm/client.py returns the raw string verbatim). Reasoning
models such as deepseek-r1-distill-qwen-32b emit a <think>...</think> block
ahead of the real answer, which then lands directly in PentestGPT's parsing
module as noise. This proxy runs on the workstation (never on the production
framework.gibbsgreatly.xyz node -- see docs/framework-ubuntu/
local-ai-development.md Phase 0), sits between PentestGPT and the real Ollama
endpoint, and:

  1. Forces stream=False and sets reasoning_effort="none" on outgoing chat
     completion requests (Ollama's OpenAI-compat endpoint honors this to
     suppress thinking tokens at the source).
  2. Strips any <think>...</think> content that still comes back anyway, as
     a defensive fallback -- the Ollama docs are not explicit that
     reasoning_effort=none fully suppresses output for every model/version.

Usage:
    python3 reasoning_strip_proxy.py --target http://192.168.1.8:11434
    pentestgpt-legacy --reasoning-model ollama:deepseek-r1-distill-qwen-32b:q4_k_m \
        --parsing-model ollama:deepseek-r1-distill-qwen-32b:q4_k_m \
        --base-url http://127.0.0.1:11435/v1
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
THINK_UNCLOSED_RE = re.compile(r"<think>.*$", re.DOTALL)


def strip_thinking(text: str) -> str:
    text = THINK_BLOCK_RE.sub("", text)
    text = THINK_UNCLOSED_RE.sub("", text)
    return text.lstrip("\n ")


class ProxyHandler(BaseHTTPRequestHandler):
    target: str = ""

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[reasoning-strip-proxy] {self.address_string()} {fmt % args}\n")

    def _proxy(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
        is_chat = self.path.rstrip("/").endswith("/chat/completions")

        if is_chat and body:
            try:
                payload = json.loads(body)
                payload["stream"] = False
                payload.setdefault("reasoning_effort", "none")
                body = json.dumps(payload).encode("utf-8")
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass  # forward untouched if we can't parse it

        headers = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "content-length")}
        req = urllib.request.Request(
            self.target + self.path,
            data=body if body else None,
            headers=headers,
            method=self.command,
        )
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                status, resp_headers, resp_body = resp.status, resp.getheaders(), resp.read()
        except urllib.error.HTTPError as e:
            status, resp_headers, resp_body = e.code, e.headers.items(), e.read()

        if is_chat and resp_body:
            try:
                data = json.loads(resp_body)
                for choice in data.get("choices", []):
                    msg = choice.get("message") or {}
                    if "content" in msg and msg["content"]:
                        msg["content"] = strip_thinking(msg["content"])
                resp_body = json.dumps(data).encode("utf-8")
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass  # forward untouched if we can't parse it

        self.send_response(status)
        for k, v in resp_headers:
            if k.lower() not in ("content-length", "transfer-encoding", "connection"):
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(resp_body)))
        self.end_headers()
        self.wfile.write(resp_body)

    def do_GET(self):
        self._proxy()

    def do_POST(self):
        self._proxy()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=11435)
    parser.add_argument("--target", default="http://192.168.1.8:11434", help="Real Ollama base URL (no trailing /v1)")
    args = parser.parse_args()

    ProxyHandler.target = args.target.rstrip("/")
    server = ThreadingHTTPServer((args.listen_host, args.listen_port), ProxyHandler)
    print(
        f"[reasoning-strip-proxy] listening on http://{args.listen_host}:{args.listen_port} "
        f"-> {ProxyHandler.target} (stripping <think> blocks)",
        file=sys.stderr,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

"""Minimal OpenAI-compatible stand-in for `eval-run selftest`.

Answers every chat completion with one fixed reply, so the whole lm_eval
pipeline (gated dataset download, request/response handling, scoring,
result files, response cache) -- and the BFCL, AgentBench and RepoBench
wrappers -- can be exercised without touching Framework's GPU. A request
carrying "tools" gets a tool call to the first tool instead (BFCL).
/v1/completions (raw text, RepoBench) answers with the same reply, and
/tokenize counts ~4 characters per token. Listens on 127.0.0.1 only, inside the selftest container.

Environment:
  MOCK_PORT          listen port (default 18080)
  MOCK_MODEL         model id served on /v1/models (default selftest-mock)
  MOCK_MODEL_PATH    model_path reported on /props -- change it to make a
                     second instance look like a different server
  MOCK_REQUEST_LOG   if set, append every (chat) completion request body as
                     one JSON line (selftest asserts on what lm_eval sent)
  MOCK_EMPTY_EVERY   if N > 0, every Nth reply has empty content (the
                     "reasoning ate the token budget" failure shape), so
                     the empty-response flags can be checked
  MOCK_REPLY         the fixed reply text (default: a GPQA-style answer)
"""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("MOCK_PORT", "18080"))
MODEL = os.environ.get("MOCK_MODEL", "selftest-mock")
MODEL_PATH = os.environ.get("MOCK_MODEL_PATH", "/models/selftest-mock.gguf")
REQUEST_LOG = os.environ.get("MOCK_REQUEST_LOG", "")
EMPTY_EVERY = int(os.environ.get("MOCK_EMPTY_EVERY", "0"))
REPLY = os.environ.get("MOCK_REPLY", "Let me think step by step. The answer is (A).")

PROPS = {
    "model_path": MODEL_PATH,
    "model_alias": MODEL,
    "build_info": "selftest-mock",
    "total_slots": 1,
    "chat_template": "{{ messages }}",
    "default_generation_settings": {
        # Big enough for runmeta's context check at the default budget.
        "n_ctx": 32768,
        "params": {"temperature": 1.0, "top_p": 0.95, "min_p": 0.01, "n_predict": -1},
    },
}

_lock = threading.Lock()
_count = 0


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.rstrip("/")
        if path == "/v1/models":
            self._send(200, {"object": "list", "data": [{"id": MODEL, "object": "model"}]})
        elif path == "/props":
            self._send(200, PROPS)
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        global _count
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        path = self.path.rstrip("/")
        if path == "/tokenize":
            content = json.loads(raw).get("content", "")
            self._send(200, {"tokens": [0] * (len(content) // 4)})
            return
        if path not in ("/v1/chat/completions", "/v1/completions"):
            self._send(404, {"error": "not found"})
            return
        with _lock:
            _count += 1
            n = _count
            if REQUEST_LOG:
                with open(REQUEST_LOG, "a") as fh:
                    fh.write(json.dumps(json.loads(raw)) + "\n")
        content = "" if EMPTY_EVERY > 0 and n % EMPTY_EVERY == 0 else REPLY
        if path == "/v1/completions":
            self._send(200, {"id": f"selftest-{n}", "object": "text_completion", "model": MODEL,
                             "choices": [{"index": 0, "finish_reason": "stop", "text": content}],
                             "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})
            return
        message = {"role": "assistant", "content": content}
        tools = json.loads(raw).get("tools") if raw else None
        if tools and content:
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": f"call-{n}", "type": "function",
                "function": {"name": tools[0]["function"]["name"], "arguments": "{}"},
            }]}
        self._send(200, {
            "id": f"selftest-{n}",
            "object": "chat.completion",
            "model": MODEL,
            "choices": [{
                "index": 0,
                "finish_reason": "tool_calls" if "tool_calls" in message else "stop",
                "message": message,
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })

    def log_message(self, *args):
        """Silence per-request access logging; lm_eval's own log is enough."""


if __name__ == "__main__":
    # Plain HTTP on loopback inside a throwaway test container -- nothing
    # leaves 127.0.0.1, and lm_eval talks to real servers over the same scheme.
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()  # NOSONAR

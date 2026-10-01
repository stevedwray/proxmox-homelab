"""Minimal OpenAI-compatible stand-in for `eval-run selftest`.

Answers every chat completion with one fixed reply, so the whole lm_eval
pipeline (gated dataset download, request/response handling, scoring,
result files) can be exercised without touching Framework's GPU. Listens
on 127.0.0.1 only, inside the selftest container.
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = "selftest-mock"
REPLY = "Let me think step by step. The answer is (A)."
PORT = 18080


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.rstrip("/") == "/v1/models":
            self._send(200, {"object": "list", "data": [{"id": MODEL, "object": "model"}]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path.rstrip("/") != "/v1/chat/completions":
            self._send(404, {"error": "not found"})
            return
        self._send(200, {
            "id": "selftest",
            "object": "chat.completion",
            "model": MODEL,
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": REPLY},
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        })

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()

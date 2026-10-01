"""In-memory stand-in for the slice of Nextcloud that publish.py uses, for
`eval-run selftest`: WebDAV MKCOL/PUT/DELETE under /remote.php/dav/files/<user>/,
and the Tables v1 API (tables, columns, rows, views, shares). Checks HTTP
basic auth against MOCK_NC_USER / MOCK_NC_PASSWORD.

GET /_mock/state returns everything stored, so selftest_checks.py can
assert on it. Listens on 127.0.0.1 only (MOCK_NC_PORT, default 18090).
"""

import base64
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("MOCK_NC_PORT", "18090"))
USER = os.environ.get("MOCK_NC_USER", "eval-reports")
PASSWORD = os.environ.get("MOCK_NC_PASSWORD", "selftest")
API = "/index.php/apps/tables/api/1"
OCS_API = "/ocs/v2.php/apps/tables/api/2"

_lock = threading.Lock()
STATE = {}
_ids = {"n": 0}


def reset():
    """Empty all stored state (unit tests reuse route() in-process)."""
    STATE.clear()
    STATE.update({"folders": [], "files": {}, "deleted": [], "tables": [], "columns": [], "rows": [],
                  "views": [], "shares": [], "requests": 0})
    _ids["n"] = 0


reset()


def stored_content(body):
    """Text files as text; anything else (leaderboard.xlsx) as a marker that
    records its size and whether it's a zip container."""
    try:
        return body.decode()
    except UnicodeDecodeError:
        return f"<binary {len(body)} bytes{' zip' if body[:2] == b'PK' else ''}>"


def _next_id():
    _ids["n"] += 1
    return _ids["n"]


FILTER_OPERATORS = {"begins-with", "ends-with", "contains", "contains-item", "does-not-contain", "is-equal",
                    "is-not-equal", "is-greater-than", "is-greater-than-or-equal", "is-lower-than",
                    "is-lower-than-or-equal", "is-empty"}


def view_update_problem(data):
    """Mirror of Tables 2.3 ViewUpdateInput's input contract (the real one
    answers HTTP 500 for these): None if acceptable, else what's wrong."""
    if "columns" in data and isinstance(data["columns"], str):
        return "deprecated 'columns' given as a string (foreach on string)"
    settings = data.get("columnSettings")
    if settings is not None and not (isinstance(settings, list)
                                     and all(isinstance(c, dict) and "columnId" in c for c in settings)):
        return "columnSettings must be a list of {columnId, order}"
    for group in data.get("filter") or []:
        for f in group:
            if not {"columnId", "operator", "value"} <= set(f) or f["operator"] not in FILTER_OPERATORS:
                return f"bad filter entry {f}"
    for rule in data.get("sort") or []:
        if not isinstance(rule, dict) or rule.get("mode") not in ("ASC", "DESC") or "columnId" not in rule:
            return f"bad sort rule {rule}"
    return None


def ocs_route(method, path, body):
    """Tables OCS v2: only PUT /tables/{id} (column order + sort)."""
    m = re.fullmatch(r"/tables/(\d+)", path)
    if not (m and method == "PUT"):
        return 404, {"ocs": {"meta": {"status": "failure"}, "data": []}}
    table = next((t for t in STATE["tables"] if t["id"] == int(m.group(1))), None)
    if table is None:
        return 404, {"ocs": {"meta": {"status": "failure"}, "data": []}}
    problem = view_update_problem({k: body.get(k) for k in ("columnSettings", "sort") if k in body})
    if problem:
        return 500, {"ocs": {"meta": {"status": "failure", "message": problem}, "data": []}}
    table.update({k: body[k] for k in ("columnSettings", "sort") if k in body})
    return 200, {"ocs": {"meta": {"status": "ok"}, "data": table}}


def route(method, path, body):
    """Tables v1 routing: (status, json body). Caller holds _lock if threaded."""
    m = re.fullmatch(r"/tables", path)
    if m and method == "GET":
        return 200, STATE["tables"]
    if m and method == "POST":
        table = {"id": _next_id(), "title": body["title"], "emoji": body.get("emoji")}
        STATE["tables"].append(table)
        return 200, table
    m = re.fullmatch(r"/tables/(\d+)/(columns|rows|views|shares)", path)
    if m:
        table_id, kind = int(m.group(1)), m.group(2)
        if method == "GET":
            return 200, [x for x in STATE[kind] if x["tableId"] == table_id]
        if kind == "columns":
            item = {"id": _next_id(), "tableId": table_id, **body}
        elif kind == "rows":
            data = [{"columnId": int(k), "value": v} for k, v in body["data"].items()]
            item = {"id": _next_id(), "tableId": table_id, "data": data}
        elif kind == "views":
            item = {"id": _next_id(), "tableId": table_id, "title": body["title"], "emoji": body.get("emoji")}
        else:
            item = {"id": _next_id(), "tableId": table_id, **body}
        STATE[kind].append(item)
        return 200, item
    m = re.fullmatch(r"/rows/(\d+)", path)
    if m and method == "PUT":
        row = next((r for r in STATE["rows"] if r["id"] == int(m.group(1))), None)
        if row is None:
            return 404, {"message": "no such row"}
        cells = {c["columnId"]: c["value"] for c in row["data"]}
        cells.update({int(k): v for k, v in body["data"].items()})
        row["data"] = [{"columnId": k, "value": v} for k, v in cells.items()]
        return 200, row
    m = re.fullmatch(r"/views/(\d+)", path)
    if m and method == "PUT":
        view = next((v for v in STATE["views"] if v["id"] == int(m.group(1))), None)
        if view is None:
            return 404, {"message": "no such view"}
        problem = view_update_problem(body.get("data", {}))
        if problem:
            return 500, {"message": problem}
        view.update(body["data"])
        return 200, view
    return 404, {"message": f"no route {method} {path}"}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body=None):
        data = b"" if body is None else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorised(self):
        expected = "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
        if self.headers.get("Authorization") != expected:
            self._send(401, {"message": "unauthorised"})
            return False
        return True

    def _body(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        return raw

    def _json(self):
        raw = self._body()
        return json.loads(raw) if raw else {}

    def _dav_path(self):
        prefix = f"/remote.php/dav/files/{USER}/"
        return self.path[len(prefix):] if self.path.startswith(prefix) else None

    def do_MKCOL(self):  # noqa: N802 (HTTP verb)
        if not self._authorised():
            return
        path = self._dav_path()
        with _lock:
            STATE["requests"] += 1
            if path in STATE["folders"]:
                self._send(405)
                return
            STATE["folders"].append(path)
        self._send(201)

    def do_PUT(self):  # noqa: N802
        if not self._authorised():
            return
        path = self._dav_path()
        if path is not None:
            body = self._body()
            parent = path.rsplit("/", 1)[0]
            with _lock:
                STATE["requests"] += 1
                if parent not in STATE["folders"]:
                    self._send(409, {"message": f"parent {parent} missing"})
                    return
                existed = path in STATE["files"]
                STATE["files"][path] = stored_content(body)
            self._send(204 if existed else 201)
            return
        self._tables("PUT", self._json())

    def do_DELETE(self):  # noqa: N802
        if not self._authorised():
            return
        path = self._dav_path()
        with _lock:
            STATE["requests"] += 1
            STATE["deleted"].append(path)
            existed = STATE["files"].pop(path, None) is not None
        self._send(204 if existed else 404)

    def do_GET(self):  # noqa: N802
        if self.path == "/_mock/state":
            with _lock:
                self._send(200, STATE)
            return
        if not self._authorised():
            return
        self._tables("GET", None)

    def do_POST(self):  # noqa: N802
        if not self._authorised():
            return
        self._tables("POST", self._json())

    def _tables(self, method, body):
        path = self.path.split("?", 1)[0]
        if path.startswith(OCS_API):
            with _lock:
                STATE["requests"] += 1
                code, result = ocs_route(method, path[len(OCS_API):], body or {})
            self._send(code, result)
            return
        if not path.startswith(API):
            self._send(404, {"message": "not found"})
            return
        sub = path[len(API):]
        with _lock:
            STATE["requests"] += 1
            code, result = route(method, sub, body or {})
        self._send(code, result)

    def log_message(self, *args):
        """Silence per-request access logging."""


if __name__ == "__main__":
    # Plain HTTP on loopback inside a throwaway test container.
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()  # NOSONAR

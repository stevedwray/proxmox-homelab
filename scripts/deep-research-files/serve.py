#!/usr/bin/env python3
"""Read-only file server for deep-research-agent's workspace directory.

Replaces the Stage A stopgap (`python3 -m http.server`, run by hand as
root against /root/.deep-research-agent/workspace) with something the
ai-services-stack playbook can actually supervise: a restart-managed,
non-root container service. See docs/deep-research/plan.md Phase 4.

Deliberately stdlib-only (http.server), same rationale as
scripts/ollama-reliability-proxy/proxy.py -- this is a small utility
service, not worth a dependency or build step. Serves a directory listing
(runs, then each run's files) and lets a browser download any file
directly; never accepts a write of any kind (SimpleHTTPRequestHandler
only implements GET/HEAD by default -- this file adds no write handler).
"""
import functools
import html
import http.server
import io
import os
import urllib.parse

HOST = os.environ.get("SERVE_HOST", "0.0.0.0")
PORT = int(os.environ.get("SERVE_PORT", "8091"))
# The named volume's workspace subdirectory -- not its config/session
# files, which aren't meant for browsing/download.
WORKSPACE_DIR = os.environ.get("WORKSPACE_DIR", "/home/app/.deep-research-agent/workspace")


class BrowsableHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler, plus a link back up the tree.

    The stdlib handler has no way to navigate back up a level once you've
    clicked into a subdirectory (e.g. a run's own folder) -- confirmed live
    2026-09-22 (operator report). Reimplements list_directory() rather than
    post-processing the parent class's HTML, because that class already
    writes a Content-Length header sized for the *unmodified* body --
    injecting an extra <li> afterward would leave that header wrong and
    truncate the response in a real browser.
    """

    def list_directory(self, path):
        try:
            entries = os.listdir(path)
        except OSError:
            self.send_error(404, "No permission to list directory")
            return None
        entries.sort(key=str.lower)

        display_path = html.escape(
            urllib.parse.unquote(self.path, errors="surrogatepass"), quote=False
        )
        rows = []
        if os.path.realpath(path) != os.path.realpath(self.directory):
            rows.append('<li><a href="../">.. (parent directory)</a></li>')
        for name in entries:
            full_name = os.path.join(path, name)
            link_name = display_name = name
            if os.path.isdir(full_name):
                link_name = display_name = name + "/"
            rows.append(
                '<li><a href="%s">%s</a></li>'
                % (
                    urllib.parse.quote(link_name, errors="surrogatepass"),
                    html.escape(display_name, quote=False),
                )
            )

        body = (
            "<!DOCTYPE HTML>\n<html><head><title>deep-research workspace: %s</title>"
            "</head>\n<body>\n<h1>%s</h1>\n<hr>\n<ul>\n%s\n</ul>\n<hr>\n</body>\n</html>\n"
            % (display_path, display_path, "\n".join(rows))
        ).encode("utf-8", "surrogateescape")

        f = io.BytesIO(body)
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        return f


def main() -> None:
    # Read-only mount: on a fresh volume, deep-research hasn't created its
    # workspace dir yet (it does so lazily on the first real run, not at
    # startup). Don't crash-loop over that -- confirmed live 2026-09-21,
    # this raised OSError(30, "Read-only file system") every restart until
    # fixed. Serve whatever's there; an empty/missing dir just means no
    # runs have happened yet.
    try:
        os.makedirs(WORKSPACE_DIR, exist_ok=True)
    except OSError:
        pass
    handler = functools.partial(
        BrowsableHTTPRequestHandler, directory=WORKSPACE_DIR
    )
    with http.server.ThreadingHTTPServer((HOST, PORT), handler) as httpd:
        print(f"Serving {WORKSPACE_DIR} read-only on http://{HOST}:{PORT}")
        httpd.serve_forever()


if __name__ == "__main__":
    main()

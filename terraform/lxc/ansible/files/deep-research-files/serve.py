#!/usr/bin/env python3
"""Read-only viewer for reports written under the shared convention
(docs/reporting-platform/CONVENTION.md): reports/<project>/<run-id>/.

Phase 1 of docs/reporting-platform/plan.md -- generalizes what began as
a deep-research-only file server (see git history) into the shared
viewer, with deep-research as the first (and currently only) project.
Renders `.md` as actual formatted HTML and `.json` pretty-printed,
instead of raw text; still stdlib http.server for the transport itself,
still read-only (SimpleHTTPRequestHandler only implements GET/HEAD by
default -- this file adds no write handler).

Not stdlib-only anymore (needs the `markdown` package) -- unlike the
original file-lister, real markdown rendering (these reports use
tables) needs a real parser, not a from-scratch one. Built from source
via its own Dockerfile now, same pattern as deep-research's own image,
rather than the old bind-mounted-script/no-build approach.
"""
import datetime
import functools
import html
import http.server
import io
import json
import os
import urllib.parse

import markdown

HOST = os.environ.get("SERVE_HOST", "0.0.0.0")
PORT = int(os.environ.get("SERVE_PORT", "8091"))
# The named volume's workspace subdirectory -- not deep-research's own
# config/session files, which aren't meant for browsing/download.
WORKSPACE_DIR = os.environ.get("WORKSPACE_DIR", "/home/app/.deep-research-agent/workspace")
# Until a project actually writes to reports/<project>/<run-id>/ per the
# convention (Phase 2+), this wraps deep-research's existing output
# location as if it already were that one project's subtree -- a
# symlink, not a code change to deep-research itself. See _setup_reports_root().
PROJECT_NAME = os.environ.get("REPORT_PROJECT_NAME", "deep-research")
# Single-purpose, single-user container with no other processes; only
# this script writes here, and only a symlink of its own naming at
# startup, not attacker-influenced content.
REPORTS_ROOT = os.environ.get("REPORTS_ROOT", "/tmp/reports-root")  # NOSONAR

PAGE_STYLE = """
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; max-width: 900px; margin: 2em auto; padding: 0 1em; line-height: 1.5; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid #ccc; padding: 6px 10px; text-align: left; }
pre, code { background: #f4f4f4; padding: 0.2em 0.4em; border-radius: 3px; }
pre { padding: 1em; overflow-x: auto; }
pre code { padding: 0; background: none; }
"""


class ReportViewerHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler, plus a parent-directory link, a
    last-modified column, and real rendering for .md/.json files.

    Reimplements list_directory() rather than post-processing the
    parent class's HTML, because that class already writes a
    Content-Length header sized for the *unmodified* body -- modifying
    the body afterward would leave that header wrong and truncate the
    response in a real browser (confirmed live 2026-09-21/22 fixing the
    earlier, narrower version of this file).
    """

    def do_GET(self):
        local_path = self.translate_path(self.path)
        if os.path.isfile(local_path):
            if local_path.endswith(".md"):
                return self._serve_markdown(local_path)
            if local_path.endswith(".json"):
                return self._serve_json(local_path)
        return super().do_GET()

    def _send_html(self, body_html: str) -> None:
        body = body_html.encode("utf-8", "surrogateescape")
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_markdown(self, local_path: str) -> None:
        try:
            with open(local_path, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read()
        except OSError:
            return self.send_error(404, "File not found")
        # Escape the raw source before parsing, not just the final output --
        # standard markdown syntax (headers, lists, bold, tables) doesn't
        # rely on literal angle brackets, but raw inline HTML passthrough
        # is part of the markdown spec and IS a real risk here: report
        # content is data from another project's tooling, not something
        # this viewer should ever execute (CONVENTION.md's security
        # section -- CyberSecEval's own reports may contain real
        # attack-payload transcripts). Escaping first means any literal
        # "<script>" in the source renders as visible text, not a tag.
        escaped = html.escape(raw, quote=False)
        rendered = markdown.markdown(escaped, extensions=["tables", "fenced_code"])
        title = html.escape(os.path.basename(local_path))
        self._send_html(
            f"<!DOCTYPE HTML>\n<html><head><title>{title}</title>"
            f"<style>{PAGE_STYLE}</style></head>\n<body>\n{rendered}\n</body>\n</html>\n"
        )

    def _serve_json(self, local_path: str) -> None:
        try:
            with open(local_path, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read()
        except OSError:
            return self.send_error(404, "File not found")
        try:
            pretty = json.dumps(json.loads(raw), indent=2, sort_keys=False)
        except ValueError:
            pretty = raw
        title = html.escape(os.path.basename(local_path))
        self._send_html(
            f"<!DOCTYPE HTML>\n<html><head><title>{title}</title>"
            f"<style>{PAGE_STYLE}</style></head>\n<body>\n<pre>{html.escape(pretty)}</pre>\n</body>\n</html>\n"
        )

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
            rows.append('<tr><td><a href="../">.. (parent directory)</a></td><td></td></tr>')
        for name in entries:
            full_name = os.path.join(path, name)
            link_name = display_name = name
            if os.path.isdir(full_name):
                link_name = display_name = name + "/"
            try:
                mtime = datetime.datetime.fromtimestamp(
                    os.stat(full_name).st_mtime
                ).strftime("%Y-%m-%d %H:%M:%S")
            except OSError:
                mtime = ""
            rows.append(
                '<tr><td><a href="%s">%s</a></td><td>%s</td></tr>'
                % (
                    urllib.parse.quote(link_name, errors="surrogatepass"),
                    html.escape(display_name, quote=False),
                    mtime,
                )
            )

        body = (
            "<!DOCTYPE HTML>\n<html><head><title>reports: %s</title>"
            "<style>%s</style></head>\n<body>\n<h1>%s</h1>\n<hr>\n"
            "<table><tr><th align=\"left\">Name</th><th align=\"left\">Last modified</th></tr>\n"
            "%s\n</table>\n<hr>\n</body>\n</html>\n"
            % (display_path, PAGE_STYLE, display_path, "\n".join(rows))
        ).encode("utf-8", "surrogateescape")

        f = io.BytesIO(body)
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        return f


def _setup_reports_root() -> None:
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
    os.makedirs(REPORTS_ROOT, exist_ok=True)
    project_link = os.path.join(REPORTS_ROOT, PROJECT_NAME)
    if os.path.islink(project_link) or os.path.exists(project_link):
        if os.path.realpath(project_link) != os.path.realpath(WORKSPACE_DIR):
            os.remove(project_link)
    if not os.path.exists(project_link):
        os.symlink(WORKSPACE_DIR, project_link)


def main() -> None:
    _setup_reports_root()
    handler = functools.partial(ReportViewerHandler, directory=REPORTS_ROOT)
    with http.server.ThreadingHTTPServer((HOST, PORT), handler) as httpd:
        print(f"Serving {REPORTS_ROOT} (project '{PROJECT_NAME}' -> {WORKSPACE_DIR}) read-only on http://{HOST}:{PORT}")
        httpd.serve_forever()


if __name__ == "__main__":
    main()

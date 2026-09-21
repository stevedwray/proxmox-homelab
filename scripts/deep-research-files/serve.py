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
import http.server
import os

HOST = os.environ.get("SERVE_HOST", "0.0.0.0")
PORT = int(os.environ.get("SERVE_PORT", "8091"))
# The named volume's workspace subdirectory -- not its config/session
# files, which aren't meant for browsing/download.
WORKSPACE_DIR = os.environ.get("WORKSPACE_DIR", "/home/app/.deep-research-agent/workspace")


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
        http.server.SimpleHTTPRequestHandler, directory=WORKSPACE_DIR
    )
    with http.server.ThreadingHTTPServer((HOST, PORT), handler) as httpd:
        print(f"Serving {WORKSPACE_DIR} read-only on http://{HOST}:{PORT}")
        httpd.serve_forever()


if __name__ == "__main__":
    main()

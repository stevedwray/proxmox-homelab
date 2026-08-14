#!/usr/bin/env python3
"""Non-destructive scheduled re-pull of known Harbor-routed images.

Walks a manifest of `<project>/<repo>:<tag>` references (registry host is
prefixed at run time from REGISTRY_HOST) and runs a plain `docker pull`
against each one through Harbor's proxy cache. This is the mechanism
Stage 2/3 of docs/harbor-stack/README.md already established as the real
verification path -- a plain manifest GET does not materialize a
proxy-cache artifact, but a real client pull does.

Deliberately never touches a running container: no `docker run`, no
`docker compose up`, no recreate. `docker pull` on its own only refreshes
the local image cache and, as a side effect, causes Harbor to refresh (or
first-populate) its own proxy-cache artifact and re-trigger a Trivy scan
via the `auto_scan` project metadata already converged in
docs/harbor-stack/README.md Stage 1. Nothing here restarts anything.

Tolerant of a cold/empty Harbor (a rebuild with nothing cached yet) and of
individual image failures -- each pull is attempted independently and a
single failure never aborts the rest of the manifest. Exit code reflects
overall success (0) or at least one failure (1), for cron/timer alerting.

Intentionally stdlib-only so it needs no extra runtime dependency on
ci-runner-01. See docs/harbor-stack/image-sourcing-enforcement.md Stage C.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time


def load_manifest(path: str) -> list[str]:
    """Read one `<project>/<repo>:<tag>` reference per non-comment line."""
    entries: list[str] = []
    with open(path, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            entries.append(line)
    return entries


def pull_one(registry_host: str, entry: str, *, dry_run: bool) -> tuple[bool, float, str]:
    """Run `docker pull <registry_host>/<entry>`. Never touches a container."""
    image = f"{registry_host}/{entry}"
    started = time.monotonic()
    if dry_run:
        return True, 0.0, f"DRY-RUN would pull {image}"
    try:
        result = subprocess.run(  # nosec B603 B607 — fixed argv, no shell, image comes from a repo-tracked manifest file
            ["docker", "pull", image],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, time.monotonic() - started, f"TIMEOUT pulling {image}"
    elapsed = time.monotonic() - started
    if result.returncode == 0:
        return True, elapsed, f"OK {image}"
    detail = (result.stderr or result.stdout or "").strip().splitlines()
    last_line = detail[-1] if detail else f"docker pull exited {result.returncode}"
    return False, elapsed, f"FAILED {image}: {last_line}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default=os.environ.get("HARBOR_REPULL_MANIFEST", "/opt/harbor-repull/manifest.txt"),
    )
    parser.add_argument(
        "--registry-host",
        default=os.environ.get("REGISTRY_HOST", ""),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.registry_host:
        print("ERROR: REGISTRY_HOST is not set (env var or --registry-host)", file=sys.stderr)
        return 2

    try:
        manifest = load_manifest(args.manifest)
    except OSError as exc:
        print(f"ERROR: could not read manifest {args.manifest}: {exc}", file=sys.stderr)
        return 2

    if not manifest:
        print(f"harbor-repull: manifest {args.manifest} is empty, nothing to do")
        return 0

    failures = 0
    for entry in manifest:
        ok, elapsed, message = pull_one(args.registry_host, entry, dry_run=args.dry_run)
        status = "ok" if ok else "FAIL"
        print(f"harbor-repull [{status}] ({elapsed:.1f}s) {message}")
        if not ok:
            failures += 1

    total = len(manifest)
    print(f"harbor-repull: {total - failures}/{total} images refreshed successfully")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

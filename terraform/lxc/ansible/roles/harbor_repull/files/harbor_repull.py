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

Pull-then-push mirror step (docs/harbor-stack/README.md "Open
Investigation"): Harbor's generic docker-registry proxy-cache adapter
(gcr/ghcr/quay/greenbone/lscr) has a confirmed upstream bug where pulled
artifacts are scanned but never tagged, leaving them invisible by tag and
unprotected from each project's daily retention job. dockerhub's native
docker-hub adapter isn't affected and is skipped. For every other project,
after a successful pull this also `docker tag`s and `docker push`es the
same image into HARBOR_REPULL_MIRROR_PROJECT (a plain, non-proxy-cache
project) -- mirroring the pentagi project's already-proven-working push
path, which never touches the broken tag-creation code at all. Requires
HARBOR_REPULL_MIRROR_USER/PASSWORD (a project-scoped robot provisioned by
this role's tasks/main.yml); mirroring is skipped entirely, with a clear
log line, if those aren't set -- so this script still degrades gracefully
to pull-only behavior on a host where that credential hasn't been
provisioned yet.

Tolerant of a cold/empty Harbor (a rebuild with nothing cached yet) and of
individual image failures -- each pull and each mirror push is attempted
independently and a single failure never aborts the rest of the manifest.
Exit code reflects overall success (0) or at least one failure (1), for
cron/timer alerting.

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


def docker_login(registry_host: str, username: str, password: str) -> None:
    """Log in once for the run. Password goes via stdin, never argv, so it
    never appears in a process listing. Raises on failure (caller decides
    whether that's fatal to mirroring only, or to the whole run)."""
    subprocess.run(  # nosec B603 B607 — fixed argv, no shell
        ["docker", "login", registry_host, "--username", username, "--password-stdin"],
        input=password,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )


def mirror_one(registry_host: str, mirror_project: str, entry: str, *, dry_run: bool) -> tuple[bool, float, str]:
    """Tag and push `entry` (already pulled) into the mirror project.

    Only ever called after a successful pull of the same ref -- never pulls
    or touches a container itself.
    """
    source = f"{registry_host}/{entry}"
    dest = f"{registry_host}/{mirror_project}/{entry}"
    if dry_run:
        return True, 0.0, f"DRY-RUN would mirror {source} -> {dest}"
    started = time.monotonic()
    tag_result = subprocess.run(  # nosec B603 B607
        ["docker", "tag", source, dest],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if tag_result.returncode != 0:
        detail = (tag_result.stderr or tag_result.stdout or "").strip().splitlines()
        last_line = detail[-1] if detail else f"docker tag exited {tag_result.returncode}"
        return False, time.monotonic() - started, f"TAG FAILED {dest}: {last_line}"
    try:
        push_result = subprocess.run(  # nosec B603 B607
            ["docker", "push", dest],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, time.monotonic() - started, f"TIMEOUT mirroring {dest}"
    elapsed = time.monotonic() - started
    if push_result.returncode == 0:
        return True, elapsed, f"OK mirrored {dest}"
    detail = (push_result.stderr or push_result.stdout or "").strip().splitlines()
    last_line = detail[-1] if detail else f"docker push exited {push_result.returncode}"
    return False, elapsed, f"FAILED mirroring {dest}: {last_line}"


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
    parser.add_argument(
        "--mirror-project",
        default=os.environ.get("HARBOR_REPULL_MIRROR_PROJECT", "mirror"),
    )
    parser.add_argument(
        "--mirror-skip-projects",
        default=os.environ.get("HARBOR_REPULL_MIRROR_SKIP_PROJECTS", "dockerhub"),
        help="Comma-separated project prefixes to pull-only, never mirror (native adapters that already tag correctly).",
    )
    parser.add_argument(
        "--mirror-user",
        default=os.environ.get("HARBOR_REPULL_MIRROR_USER", ""),
    )
    parser.add_argument(
        "--mirror-password",
        default=os.environ.get("HARBOR_REPULL_MIRROR_PASSWORD", ""),
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

    skip_projects = {p.strip() for p in args.mirror_skip_projects.split(",") if p.strip()}
    mirror_enabled = bool(args.mirror_user and args.mirror_password)
    if mirror_enabled and not args.dry_run:
        try:
            docker_login(args.registry_host, args.mirror_user, args.mirror_password)
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            print(f"harbor-repull: WARNING mirror login failed, mirroring disabled for this run: {detail}", file=sys.stderr)
            mirror_enabled = False
    elif not mirror_enabled:
        print("harbor-repull: HARBOR_REPULL_MIRROR_USER/PASSWORD not set, mirroring disabled for this run (pull-only)")

    pull_failures = 0
    mirror_failures = 0
    mirrored = 0
    mirror_attempts = 0
    for entry in manifest:
        ok, elapsed, message = pull_one(args.registry_host, entry, dry_run=args.dry_run)
        status = "ok" if ok else "FAIL"
        print(f"harbor-repull [{status}] ({elapsed:.1f}s) {message}")
        if not ok:
            pull_failures += 1
            continue

        project = entry.split("/", 1)[0]
        if not mirror_enabled or project in skip_projects:
            continue

        mirror_attempts += 1
        mirror_ok, mirror_elapsed, mirror_message = mirror_one(
            args.registry_host, args.mirror_project, entry, dry_run=args.dry_run
        )
        mirror_status = "ok" if mirror_ok else "FAIL"
        print(f"harbor-repull [{mirror_status}] ({mirror_elapsed:.1f}s) {mirror_message}")
        if mirror_ok:
            mirrored += 1
        else:
            mirror_failures += 1

    total = len(manifest)
    print(f"harbor-repull: {total - pull_failures}/{total} images pulled successfully")
    if mirror_attempts:
        print(f"harbor-repull: {mirrored}/{mirror_attempts} images mirrored successfully")
    return 1 if (pull_failures or mirror_failures) else 0


if __name__ == "__main__":
    sys.exit(main())

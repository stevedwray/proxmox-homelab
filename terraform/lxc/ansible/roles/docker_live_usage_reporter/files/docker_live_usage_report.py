#!/usr/bin/env python3
"""Local, read-only live-usage report for one Docker host -- Phase 14
(docs/threat-vuln-platform/plan.md, uvm-14-02) companion to
es_findings_ingest's harbor_live_usage.py.

Exists because Portainer deliberately doesn't reach every Docker host on
this platform: every security/infra-tier stack (Harbor itself,
monitoring, netbox, graylog, greenbone, opensearch, pentagi, wazuh,
portainer-stack, ci-runner-01, harness-target(-pve),
pentagi-upstream-control) was intentionally excluded from Portainer
registration for attack-surface reasons during an earlier pass this same
session -- so `in_use` was silently blind to most of the platform's
actual security tier. Rather than expanding Portainer's own reach into
that tier (which would undo the reasoning that excluded them), each of
those hosts runs this script locally against its own Docker socket and
self-reports to a dedicated OpenSearch index, matching the shape of
every other source in this pipeline (harbor_findings_sync.py,
gvm_findings_sync.py, wazuh_findings_sync.py, cve_enrichment_sync.py --
each a self-contained script pushing its own findings, not centrally
polled over SSH).

Strictly read-only against Docker: only ever runs `docker ps`/`docker
inspect`/`docker image inspect`. Never starts, stops, creates, or
otherwise touches a container or image.

`parse_image_ref()` is intentionally a duplicate of
es_findings_ingest/files/harbor_live_usage.py's function of the same
name, not a shared import -- this repo's Ansible roles don't have a
convention for sharing files across roles, and the function is small
enough (~15 lines) that a documented, deliberate duplicate is simpler
and more inspectable than inventing a new shared-library layout for one
function. Keep the two in sync if either changes.

Intentionally stdlib-only, matching every other script in this pipeline.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_image_ref(image: str) -> tuple[str, str, str] | None:
    """Parse an image reference into (project, repository, tag) --
    registry-host-agnostic, mirrors harbor_live_usage.py's function of
    the same name exactly. See that module's docstring for the parsing
    rationale."""
    if "/" not in image:
        return None
    host, rest = image.split("/", 1)
    if "." not in host and ":" not in host and host != "localhost":
        return None
    if "@" in rest or ":" not in rest:
        return None
    repo_and_tag, tag = rest.rsplit(":", 1)
    if "/" not in repo_and_tag:
        return None
    project, repository = repo_and_tag.split("/", 1)
    return project, repository, tag


def _docker_json(args: list[str]) -> list[dict]:
    """Run a docker CLI subcommand that supports `-f json`-per-line-free
    plain JSON array output (docker inspect / docker image inspect both
    do) and parse it. Raises CalledProcessError on a real docker failure
    -- callers decide whether that's fatal for this run."""
    result = subprocess.run(
        args, capture_output=True, text=True, check=True, timeout=30
    )
    return json.loads(result.stdout) if result.stdout.strip() else []


def collect_live_usage() -> tuple[set[str], set[tuple[str, str, str]]]:
    """Returns (digest_set, tag_ref_set) for every container currently
    running on this host's local Docker socket. Empty sets (not an
    exception) if Docker reports zero running containers -- a
    genuinely-idle host is valid state, not a collection failure."""
    ps = subprocess.run(
        ["docker", "ps", "-q"], capture_output=True, text=True, check=True, timeout=15
    )
    container_ids = [c for c in ps.stdout.split() if c]
    if not container_ids:
        return set(), set()

    containers = _docker_json(["docker", "inspect", *container_ids])

    tag_refs: set[tuple[str, str, str]] = set()
    image_ids: set[str] = set()
    for container in containers:
        config_image = (container.get("Config") or {}).get("Image") or ""
        ref = parse_image_ref(config_image)
        if ref is not None:
            tag_refs.add(ref)
        image_id = container.get("Image")
        if image_id:
            image_ids.add(image_id)

    digests: set[str] = set()
    if image_ids:
        images = _docker_json(["docker", "image", "inspect", *sorted(image_ids)])
        for image in images:
            for repo_digest in image.get("RepoDigests") or []:
                if "@" in repo_digest:
                    digests.add(repo_digest.rsplit("@", 1)[1])

    return digests, tag_refs


def _es_request(
    es_url: str, path: str, *, method: str = "GET", body: dict | None = None,
    auth_header: str, verify_tls: bool, timeout: float = 20.0,
) -> tuple[int, dict | None]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"{es_url}{path}", data=data, method=method)
    req.add_header("Authorization", auth_header)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    ctx = ssl.create_default_context()
    if not verify_tls:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:  # nosec B310 -- internal operator-configured OpenSearch endpoint, never user-supplied
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw) if raw else None
        except ValueError:
            return exc.code, {"raw": raw.decode(errors="replace")}


def main() -> int:
    es_url = os.environ.get("ELASTICSEARCH_URL", "")
    es_user = os.environ.get("ES_DOCKER_LIVE_USAGE_USER", "")
    es_password = os.environ.get("ES_DOCKER_LIVE_USAGE_PASSWORD", "")
    verify_tls = os.environ.get("ES_DOCKER_LIVE_USAGE_NO_VERIFY_TLS") != "1"
    index = os.environ.get("ES_DOCKER_LIVE_USAGE_INDEX", "docker-live-usage")

    missing = [
        name
        for name, value in [
            ("ELASTICSEARCH_URL", es_url),
            ("ES_DOCKER_LIVE_USAGE_USER", es_user),
            ("ES_DOCKER_LIVE_USAGE_PASSWORD", es_password),
        ]
        if not value
    ]
    if missing:
        print(f"ERROR: missing required settings: {', '.join(missing)}", file=sys.stderr)
        return 2

    try:
        digests, tag_refs = collect_live_usage()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        print(f"ERROR: local docker query failed: {exc}", file=sys.stderr)
        return 1

    hostname = socket.gethostname()
    auth_header = "Basic " + base64.b64encode(f"{es_user}:{es_password}".encode()).decode()
    doc = {
        "hostname": hostname,
        "reported_at": _now_iso(),
        "digests": sorted(digests),
        "tag_refs": [
            {"project": p, "repository": r, "tag": t} for p, r, t in sorted(tag_refs)
        ],
    }
    status, result = _es_request(
        es_url, f"/{index}/_doc/{hostname}", method="PUT", body=doc,
        auth_header=auth_header, verify_tls=verify_tls,
    )
    if status not in (200, 201):
        print(f"ERROR: failed to write {index}/_doc/{hostname}: {status} {result}", file=sys.stderr)
        return 1

    print(
        f"Done -- host={hostname} running_containers_digests={len(digests)} "
        f"tag_refs={len(tag_refs)} status={status}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

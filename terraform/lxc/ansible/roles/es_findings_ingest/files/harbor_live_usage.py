#!/usr/bin/env python3
"""Live-usage lookup: every image manifest digest currently backing a
running container anywhere, via Portainer.

Reuses the exact PortainerClient auth pattern already proven in
terraform/lxc/stacks/netbox-stack/integrations/discover.py (X-API-Key via
the PORTAINER_TOKEN SOPS secret) rather than inventing a new one -- every
stack is already a registered Portainer endpoint
(register_portainer_environments in scripts/provision.sh).

Digest-exact, not tag-exact: this is what lets a floating tag's
superseded old digest correctly read in_use:false once a newer pull
replaces what's actually deployed under the same tag string. Matching a
container's Image field (the tag string) can't make that distinction --
cross-referencing docker/containers/json's ImageID against
docker/images/json's RepoDigests can.

fetch_live_digests() returns None (never an empty set) on any
whole-run failure to reach Portainer at all, so callers can distinguish
"confirmed nothing is running anywhere" (never actually true on this
platform) from "couldn't find out this run" -- see
docs/threat-vuln-platform/plan.md Phase 13's sticky-carry-forward
decision. A single unreachable *endpoint* (one stack's edge agent
mid-restart) is a narrower, per-endpoint degrade: skip that endpoint,
keep the rest of the run's real data.
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request


def _ssl_ctx(verify_tls: bool):
    ctx = ssl.create_default_context()
    if not verify_tls:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _get(url: str, api_key: str, *, verify_tls: bool, timeout: float = 20.0):
    req = urllib.request.Request(url, headers={"X-API-Key": api_key})
    with urllib.request.urlopen(req, context=_ssl_ctx(verify_tls), timeout=timeout) as resp:  # nosec B310 -- internal Portainer API on private SDN
        return json.loads(resp.read())


def fetch_live_digests(portainer_url: str, api_key: str, *, verify_tls: bool = False) -> set[str] | None:
    base = portainer_url.rstrip("/")
    try:
        endpoints = _get(f"{base}/api/endpoints", api_key, verify_tls=verify_tls)
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as exc:
        print(f"WARN: harbor_live_usage: could not list Portainer endpoints: {exc}", file=sys.stderr)
        return None

    digests: set[str] = set()
    for endpoint in endpoints:
        endpoint_id = endpoint.get("Id")
        if endpoint_id is None:
            continue
        try:
            containers = _get(f"{base}/api/endpoints/{endpoint_id}/docker/containers/json", api_key, verify_tls=verify_tls)
            images = _get(f"{base}/api/endpoints/{endpoint_id}/docker/images/json", api_key, verify_tls=verify_tls)
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as exc:
            print(f"WARN: harbor_live_usage: endpoint {endpoint_id} unreachable: {exc}", file=sys.stderr)
            continue

        running_image_ids = {c.get("ImageID") for c in containers if c.get("ImageID")}
        for image in images:
            if image.get("Id") not in running_image_ids:
                continue
            for repo_digest in image.get("RepoDigests") or []:
                # "repo@sha256:...." -- keep only the digest half; Harbor's
                # own artifact.digest field is bare "sha256:...." with no
                # repo prefix.
                if "@" in repo_digest:
                    digests.add(repo_digest.rsplit("@", 1)[1])

    return digests


if __name__ == "__main__":
    # Standalone use for the Phase 13 step-7 manifest audit -- prints one
    # digest per line to stdout, warnings to stderr.
    url = os.environ.get("PORTAINER_URL", "")
    token = os.environ.get("PORTAINER_TOKEN", "")
    if not url or not token:
        print("ERROR: PORTAINER_URL and PORTAINER_TOKEN must be set", file=sys.stderr)
        sys.exit(2)
    result = fetch_live_digests(url, token, verify_tls=os.environ.get("PORTAINER_NO_VERIFY_TLS") != "1")
    if result is None:
        sys.exit(1)
    for d in sorted(result):
        print(d)

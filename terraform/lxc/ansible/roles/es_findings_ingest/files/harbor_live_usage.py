#!/usr/bin/env python3
"""Live-usage lookup: every image manifest digest currently backing a
running container anywhere, via Portainer.

Reuses the exact PortainerClient auth pattern already proven in
terraform/lxc/stacks/netbox-stack/integrations/discover.py (X-API-Key via
the PORTAINER_TOKEN SOPS secret) rather than inventing a new one -- every
stack is already a registered Portainer endpoint
(register_portainer_environments in scripts/provision.sh).

Digest-exact PLUS a tag-exact fallback -- confirmed necessary live
2026-09-07 (docs/threat-vuln-platform/plan.md Phase 13 verification):
Harbor's own catalog for a floating tag (`:latest`, `:java21`, etc.)
routinely lags what's actually running -- the catalog reflects whatever
digest Harbor itself last pulled, not necessarily the digest a stack
deployment pulled directly, so an exact-digest match against
harbor-findings' own artifact.digest was landing at essentially zero
hits across the entire Harbor-sourced CVE population, not just on the
genuinely-stale entries it was meant to filter. Tag-exact (matching a
running container's (project, repository, tag) against Harbor's
CURRENTLY-tagged artifact for that same triple) can't be fooled by an
old superseded digest the way a naive tag-string comparison could,
because only the one harbor-findings document Harbor currently
considers "this tag's artifact" carries that tag value at all --
untagged/historical digests for the same repo have tag=None and never
match. A live digest match is still preferred when it happens to align
(strictly more precise); the tag match is the fallback that makes
in_use mean something for the common floating-tag case instead of
silently degrading to "always false".

fetch_live_usage() returns None (never an empty set) on any
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


def parse_image_ref(image: str) -> tuple[str, str, str] | None:
    """Parse a running container's Image string into (project, repository,
    tag) -- registry-host-agnostic, since this repo's stacks pull the same
    logical image via different host strings depending on path (the bare
    LAB_IP_HARBOR for most stack deploy playbooks, LAB_FQDN_HARBOR for
    harbor_repull's own login+pull -- see registry_host_vs_fqdn_harbor
    memory). Uses Docker's own reference-parsing heuristic: the first
    "/"-delimited segment is a registry host only if it contains "." or
    ":" (or is literally "localhost"); otherwise there's no explicit host
    to strip. Returns None for anything that isn't a plain
    host/project/repo:tag reference -- a digest-pinned image (`@sha256:`,
    no tag) or a bare/unprefixed reference neither of which this
    function can usefully match against manifest.txt-style entries."""
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


def fetch_live_usage(
    portainer_url: str, api_key: str, *, verify_tls: bool = False
) -> tuple[set[str] | None, set[tuple[str, str, str]] | None]:
    """Returns (live_digests, live_tag_refs). Both None together on a
    whole-run failure to reach Portainer at all (sticky carry-forward
    signal to callers); a single unreachable endpoint is skipped, not
    fatal, same as before."""
    base = portainer_url.rstrip("/")
    try:
        endpoints = _get(f"{base}/api/endpoints", api_key, verify_tls=verify_tls)
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as exc:
        print(f"WARN: harbor_live_usage: could not list Portainer endpoints: {exc}", file=sys.stderr)
        return None, None

    digests: set[str] = set()
    tag_refs: set[tuple[str, str, str]] = set()
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

        for container in containers:
            ref = parse_image_ref(container.get("Image") or "")
            if ref is not None:
                tag_refs.add(ref)

    return digests, tag_refs


def fetch_live_digests(portainer_url: str, api_key: str, *, verify_tls: bool = False) -> set[str] | None:
    """Digest-only view, kept for the standalone step-7 manifest-audit CLI
    below (which only ever needed digests). Real ingest-time callers should
    use fetch_live_usage() for the digest+tag hybrid."""
    digests, _ = fetch_live_usage(portainer_url, api_key, verify_tls=verify_tls)
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

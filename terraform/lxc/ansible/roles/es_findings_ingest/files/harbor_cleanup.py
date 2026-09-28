#!/usr/bin/env python3
"""Active usage-based Harbor artifact cleanup -- Phase 14
(docs/threat-vuln-platform/plan.md, uvm-14-06), the other half of Phase
13's original title that never got built: `in_use` on its own only
filters a dashboard, it doesn't shrink Harbor's own scan surface or
delete anything, so Trivy keeps rescanning every artifact Harbor has
ever cataloged forever, whether or not it's actually deployed anywhere.

Queries harbor-findings for distinct artifacts confirmed `in_use: false`
for at least the configured grace period (artifact.not_in_use_since,
Phase 14 uvm-14-05), excludes anything matching
assets/harbor_cleanup_exempt.json, and deletes the rest via Harbor's own
artifact-delete API. Ships dry-run by default (matching this pipeline's
existing convention, e.g. harbor_repull.py) -- real deletion is a
separate, explicit `--execute` flag, never the default on first deploy.

Deliberately imports harbor_findings_sync's own helpers
(_basic_auth_header, _encode_repo_name, _now_iso) rather than
duplicating them -- same Harbor auth pattern, same double-URL-encoding
quirk for repository names containing '/'.

Intentionally stdlib-only, matching every other script in this pipeline.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from harbor_findings_sync import _basic_auth_header, _encode_repo_name, _now_iso

_EXEMPT_PATH = Path(__file__).parent / "assets" / "harbor_cleanup_exempt.json"


def load_exemptions(path: Path = _EXEMPT_PATH) -> dict:
    """Load harbor_cleanup_exempt.json. Missing/unreadable file degrades
    to "nothing exempt" -- deliberately the OPPOSITE failure direction
    from load_production_registry()'s "unknown -> not production": a
    silently-empty exemption list here would make real exemptions
    (pentagi) start showing up as deletion candidates, which is exactly
    the failure mode dry-run-by-default exists to catch before it can
    do any damage. Still logs loudly either way."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"WARN: could not load cleanup exemptions from {path}: {exc} -- treating as NO exemptions", file=sys.stderr)
        return {"exempt_projects": [], "exempt_repositories": []}


def is_exempt(project: str, repository: str, exemptions: dict) -> bool:
    for entry in exemptions.get("exempt_projects", []):
        if entry.get("project") == project:
            return True
    for entry in exemptions.get("exempt_repositories", []):
        if entry.get("project") == project and entry.get("repository") == repository:
            return True
    return False


def _es_search(es_base: str, index: str, body: dict, *, auth_header: str, verify_tls: bool) -> dict:
    req = urllib.request.Request(
        f"{es_base}/{index}/_search", data=json.dumps(body).encode("utf-8"), method="POST",
    )
    req.add_header("Authorization", auth_header)
    req.add_header("Content-Type", "application/json")
    ctx = ssl.create_default_context()
    if not verify_tls:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, context=ctx, timeout=30.0) as resp:  # nosec B310 -- internal operator-configured OpenSearch endpoint, never user-supplied
        return json.loads(resp.read())


def fetch_cleanup_candidates(
    es_base: str, *, auth_header: str, verify_tls: bool, grace_period_days: int,
) -> list[dict]:
    """Terms-aggregate distinct (project, repository, digest) artifacts
    from harbor-findings where in_use:false and not_in_use_since is older
    than the grace period. Aggregation, not a raw hit scan, because the
    same artifact appears once per CVE finding -- often hundreds of
    documents share one artifact block, and cleanup acts on the artifact,
    not the finding."""
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=grace_period_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {"term": {"artifact.in_use": False}},
                    {"range": {"artifact.not_in_use_since": {"lte": cutoff_iso}}},
                ]
            }
        },
        "aggs": {
            "artifacts": {
                "terms": {
                    "script": {
                        "source": "doc['artifact.project'].value + '::' + doc['artifact.repository'].value + '::' + doc['artifact.digest'].value"
                    },
                    "size": 10000,
                },
                "aggs": {"not_in_use_since": {"min": {"field": "artifact.not_in_use_since"}}},
            }
        },
    }
    result = _es_search(es_base, "harbor-findings", body, auth_header=auth_header, verify_tls=verify_tls)
    candidates = []
    for bucket in result.get("aggregations", {}).get("artifacts", {}).get("buckets", []):
        project, repository, digest = bucket["key"].split("::")
        candidates.append({
            "project": project,
            "repository": repository,
            "digest": digest,
            "not_in_use_since": bucket.get("not_in_use_since", {}).get("value_as_string"),
            "finding_count": bucket["doc_count"],
        })
    return candidates


def delete_artifact(
    harbor_base: str, project: str, repository: str, digest: str, *, auth_header: str, verify_tls: bool,
) -> tuple[bool, str]:
    """DELETE /api/v2.0/projects/{project}/repositories/{repository}/artifacts/{digest}.
    Returns (ok, detail)."""
    encoded_repo = _encode_repo_name(repository)
    url = f"{harbor_base}/api/v2.0/projects/{project}/repositories/{encoded_repo}/artifacts/{digest}"
    req = urllib.request.Request(url, method="DELETE")
    req.add_header("Authorization", auth_header)
    ctx = ssl.create_default_context()
    if not verify_tls:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=20.0) as resp:  # nosec B310 -- internal operator-configured Harbor API endpoint, never user-supplied
            return True, f"{resp.status}"
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            # Already gone (e.g. Harbor's own retention beat this job to
            # it) -- not a failure.
            return True, "404 (already absent)"
        return False, f"{exc.code} {exc.read()}"
    except (urllib.error.URLError, OSError) as exc:
        return False, str(exc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harbor-url", default=os.environ.get("HARBOR_URL", ""))
    parser.add_argument("--harbor-user", default=os.environ.get("HARBOR_ROBOT_USER", ""))
    parser.add_argument("--harbor-password", default=os.environ.get("HARBOR_ROBOT_PASSWORD", ""))
    parser.add_argument("--elasticsearch-url", default=os.environ.get("ELASTICSEARCH_URL", ""))
    parser.add_argument("--es-user", default=os.environ.get("ES_FINDINGS_USER", ""))
    parser.add_argument("--es-password", default=os.environ.get("ES_FINDINGS_PASSWORD", ""))
    parser.add_argument("--grace-period-days", type=int, default=int(os.environ.get("HARBOR_CLEANUP_GRACE_DAYS", "7")))
    parser.add_argument("--no-verify-tls", action="store_true", default=os.environ.get("HARBOR_CLEANUP_NO_VERIFY_TLS") == "1")
    parser.add_argument(
        "--execute", action="store_true",
        help="Actually delete candidates. Without this flag, only lists what would be deleted -- the default, matching this pipeline's dry-run-first convention.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    missing = [
        name
        for name, value in [
            ("--harbor-url/HARBOR_URL", args.harbor_url),
            ("--harbor-user/HARBOR_ROBOT_USER", args.harbor_user),
            ("--harbor-password/HARBOR_ROBOT_PASSWORD", args.harbor_password),
            ("--elasticsearch-url/ELASTICSEARCH_URL", args.elasticsearch_url),
            ("--es-user/ES_FINDINGS_USER", args.es_user),
            ("--es-password/ES_FINDINGS_PASSWORD", args.es_password),
        ]
        if not value
    ]
    if missing:
        print(f"ERROR: missing required settings: {', '.join(missing)}", file=sys.stderr)
        return 2

    harbor_base = args.harbor_url.rstrip("/")
    es_base = args.elasticsearch_url.rstrip("/")
    harbor_auth = _basic_auth_header(args.harbor_user, args.harbor_password)
    es_auth = _basic_auth_header(args.es_user, args.es_password)
    exemptions = load_exemptions()

    try:
        candidates = fetch_cleanup_candidates(
            es_base, auth_header=es_auth, verify_tls=not args.no_verify_tls,
            grace_period_days=args.grace_period_days,
        )
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as exc:
        print(f"ERROR: failed to query cleanup candidates: {exc}", file=sys.stderr)
        return 1

    exempt_count = 0
    deleted = 0
    failed = 0
    mode = "EXECUTE" if args.execute else "DRY-RUN"

    for candidate in candidates:
        project, repository, digest = candidate["project"], candidate["repository"], candidate["digest"]
        if is_exempt(project, repository, exemptions):
            exempt_count += 1
            print(f"SKIP (exempt): {project}/{repository}@{digest} (not_in_use_since={candidate['not_in_use_since']}, {candidate['finding_count']} findings)")
            continue

        print(f"{mode}: {project}/{repository}@{digest} (not_in_use_since={candidate['not_in_use_since']}, {candidate['finding_count']} findings)")
        if not args.execute:
            continue

        ok, detail = delete_artifact(harbor_base, project, repository, digest, auth_header=harbor_auth, verify_tls=not args.no_verify_tls)
        if ok:
            deleted += 1
        else:
            failed += 1
            print(f"  ERROR deleting {project}/{repository}@{digest}: {detail}", file=sys.stderr)

    print(
        f"Done ({mode}) -- candidates={len(candidates)} exempt={exempt_count} "
        f"{'deleted' if args.execute else 'would_delete'}={deleted if args.execute else len(candidates) - exempt_count} "
        f"failed={failed} grace_period_days={args.grace_period_days}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

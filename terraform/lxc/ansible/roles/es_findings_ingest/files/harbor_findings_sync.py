#!/usr/bin/env python3
"""Scheduled pull of Harbor/Trivy vulnerability findings into Elasticsearch.

See docs/elasticsearch-stack/README.md section 1 (Data model) and
docs/elasticsearch-stack/plan.md's "Ingestion pattern" for the design.
Option A from that doc: a scheduled pull script, same shape as
harbor_repull.py (stdlib-only, tolerant of individual failures, exit
code reflects overall success).

Deliberately walks every Harbor project -> repository -> artifact via
Harbor's own catalog API rather than trying to re-derive harbor_repull's
mirror-project-vs-direct-project distinction (querying "mirror/*" for
some registries, the project directly for others). That distinction
exists to fix a *tag-visibility* bug in harbor_repull's own pull path —
it says nothing about where Harbor's catalog itself considers an
artifact to live, and hardcoding it here would just be a second, more
fragile copy of logic this script doesn't need: whatever Harbor's own
/projects, /repositories, /artifacts endpoints currently return IS the
authoritative, complete set to scan. If the same underlying image is
cataloged at two addresses (e.g. once under its original proxy-cache
project and once under the mirror project harbor_repull pushes to),
both are real, independently-scanned Harbor artifacts and both get their
own finding documents — the artifact block on each document is what
lets a later query tell them apart, not something this ingest layer
should silently deduplicate.

Read-only against Harbor: only ever calls GET endpoints. Read-write
against Elasticsearch: bulk-upserts finding documents and updates one
sync-state document. Never touches harbor_repull's own state, robot
credential, or schedule — fully independent of that role.

Deterministic per-document _id (source::finding_id::project/repo@digest)
so reruns are pure upserts, never duplicates. first_seen is set only on
first insert (via a scripted upsert), last_seen updates every run — see
plan.md's "first_seen/last_seen upsert semantics" note.

Intentionally stdlib-only, matching harbor_repull.py's own reasoning
(no Python venv convention on LXC hosts for jobs like this).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import harbor_live_usage

PAGE_SIZE = 100

_REGISTRY_PATH = Path(__file__).parent / "assets" / "known_production_images.json"


def load_production_registry(path: Path = _REGISTRY_PATH) -> dict:
    """Load the known_production_images.json classifier registry -- see
    docs/threat-vuln-platform/plan.md's UVM redesign phase for the design
    and the operator's 2026-09-01 decisions this encodes. Missing/
    unreadable registry degrades gracefully (every artifact classifies as
    unknown/false rather than crashing the sync)."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"WARN: could not load production registry from {path}: {exc}", file=sys.stderr)
        return {"known_production": {}, "generic_base_images": {"exact": []}, "explicit_non_production": {"prefixes": []}}


def classify_artifact(repository: str, registry: dict) -> tuple[bool, str | None, str | None]:
    """Returns (in_production, stack, zone) for a Harbor artifact.repository
    value. Exact-match only against the registry -- an unmatched
    repository is unknown, never guessed (defaults to False/None/None)."""
    if not repository:
        return False, None, None
    for prefix in registry.get("explicit_non_production", {}).get("prefixes", []):
        if repository.startswith(prefix):
            return False, None, None
    known = registry.get("known_production", {})
    if repository in known:
        entry = known[repository]
        return True, entry.get("stack"), entry.get("zone")
    if repository in registry.get("generic_base_images", {}).get("exact", []):
        return True, None, None
    return False, None, None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _basic_auth_header(user: str, password: str) -> str:
    creds = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {creds}"


def _http_get(url: str, *, headers: dict, verify_tls: bool, timeout: float = 20.0):
    req = urllib.request.Request(url, method="GET")
    for key, value in headers.items():
        req.add_header(key, value)
    ctx = ssl.create_default_context()
    if not verify_tls:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:  # nosec B310 -- internal operator-configured API endpoint (Harbor/GVM/ES/Wazuh/Ollama/MikroTik), never user-supplied; scheme is always http(s)
        raw = resp.read()
        return resp.status, (json.loads(raw) if raw else None)


def _harbor_get(base_url: str, path: str, *, auth_header: str, verify_tls: bool):
    url = f"{base_url}{path}"
    try:
        status, body = _http_get(url, headers={"Authorization": auth_header, "Accept": "application/json"}, verify_tls=verify_tls)
        return status, body
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return 404, None
        raise
    except urllib.error.URLError as exc:
        print(f"WARN: GET {url} failed: {exc}", file=sys.stderr)
        return None, None


def _encode_repo_name(repo_name: str) -> str:
    """Harbor requires repository names containing '/' to be double
    URL-encoded in path segments (documented Harbor API quirk). Confirmed
    live 2026-08-17: a single-encoded '/' (%2F) 404s for any repo name
    with an internal slash (e.g. 'community/pg-gvm' in a nested project);
    only the double-encoded form (%252F) resolves. This bug was silent
    since this role had never actually run against real Harbor data
    before that date -- list_artifacts() returning [] for a 404 looks
    identical to "no artifacts", not an error."""
    once = urllib.parse.quote(repo_name, safe="")
    twice = urllib.parse.quote(once, safe="")
    return twice


def list_projects(base_url: str, *, auth_header: str, verify_tls: bool) -> list[dict]:
    projects: list[dict] = []
    page = 1
    while True:
        status, body = _harbor_get(
            base_url, f"/api/v2.0/projects?page_size={PAGE_SIZE}&page={page}", auth_header=auth_header, verify_tls=verify_tls
        )
        if status != 200 or not body:
            break
        projects.extend(body)
        if len(body) < PAGE_SIZE:
            break
        page += 1
    return projects


def list_repositories(base_url: str, project_name: str, *, auth_header: str, verify_tls: bool) -> list[dict]:
    repos: list[dict] = []
    page = 1
    encoded_project = urllib.parse.quote(project_name, safe="")
    while True:
        status, body = _harbor_get(
            base_url,
            f"/api/v2.0/projects/{encoded_project}/repositories?page_size={PAGE_SIZE}&page={page}",
            auth_header=auth_header,
            verify_tls=verify_tls,
        )
        if status != 200 or not body:
            break
        repos.extend(body)
        if len(body) < PAGE_SIZE:
            break
        page += 1
    return repos


def list_artifacts(base_url: str, project_name: str, repo_short_name: str, *, auth_header: str, verify_tls: bool) -> list[dict]:
    artifacts: list[dict] = []
    page = 1
    encoded_project = urllib.parse.quote(project_name, safe="")
    encoded_repo = _encode_repo_name(repo_short_name)
    while True:
        status, body = _harbor_get(
            base_url,
            f"/api/v2.0/projects/{encoded_project}/repositories/{encoded_repo}/artifacts"
            f"?page_size={PAGE_SIZE}&page={page}&with_tag=true&with_scan_overview=true",
            auth_header=auth_header,
            verify_tls=verify_tls,
        )
        if status != 200 or not body:
            break
        artifacts.extend(body)
        if len(body) < PAGE_SIZE:
            break
        page += 1
    return artifacts


def get_vulnerabilities(
    base_url: str, project_name: str, repo_short_name: str, digest: str, *, auth_header: str, verify_tls: bool
) -> list[dict]:
    encoded_project = urllib.parse.quote(project_name, safe="")
    encoded_repo = _encode_repo_name(repo_short_name)
    status, body = _harbor_get(
        base_url,
        f"/api/v2.0/projects/{encoded_project}/repositories/{encoded_repo}/artifacts/{digest}/additions/vulnerabilities",
        auth_header=auth_header,
        verify_tls=verify_tls,
    )
    if status != 200 or not body:
        return []
    # Harbor wraps the report keyed by scanner mime-type; take the first
    # (only ever one scanner — Trivy — configured in this repo).
    for report in body.values():
        return report.get("vulnerabilities", []) or []
    return []


def scan_overview_completed(artifact: dict) -> bool:
    overview = artifact.get("scan_overview") or {}
    for report in overview.values():
        if report.get("scan_status") == "Success":
            return True
    return False


def _extract_cvss_score(vuln: dict) -> float | None:
    # Confirmed live 2026-08-18 against a real Harbor vulnerability record
    # (greenbone/community/gvmd): Harbor's additions/vulnerabilities
    # response carries a top-level "preferred_cvss" object
    # ({"score_v3": ..., "score_v2": ..., ...}) that harbor_findings_sync.py
    # had never captured until now -- same real, unresolved CVSS
    # v2-vs-v3/cross-source-severity caveat gvm-findings.json's own _meta
    # description already flags for GVM. Prefer v3 (more precise, more
    # commonly populated); fall back to v2 only when v3 is null/absent.
    preferred = vuln.get("preferred_cvss") or {}
    score = preferred.get("score_v3")
    if score is None:
        score = preferred.get("score_v2")
    return score


def build_documents(
    project_name: str, repo_short_name: str, artifact: dict, vulnerabilities: list[dict],
    *, scan_time: str, production_registry: dict,
    live_digests: set[str] | None = None,
    live_tag_refs: set[tuple[str, str, str]] | None = None,
) -> list[dict]:
    digest = artifact.get("digest", "")
    tags = [t.get("name") for t in (artifact.get("tags") or []) if t.get("name")]
    tag = tags[0] if tags else None
    now = _now_iso()
    in_production, stack, zone = classify_artifact(repo_short_name, production_registry)

    artifact_fields = {
        "project": project_name,
        "repository": repo_short_name,
        "tag": tag,
        "digest": digest,
        "in_production": in_production,
        "stack": stack,
        "zone": zone,
    }
    # live_digests/live_tag_refs are None together when this run couldn't
    # reach Portainer at all -- in that case leave the in_use key out
    # entirely (never set it to False) so bulk_upsert()'s copy-if-missing
    # painless step carries the prior value forward instead of wiping it.
    # See docs/threat-vuln-platform/plan.md Phase 13's sticky-carry-forward
    # decision.
    #
    # Digest-exact match OR tag-exact match (see harbor_live_usage.py's
    # module docstring, 2026-09-07 update): confirmed live that
    # digest-exact alone matched essentially nothing across the entire
    # Harbor-sourced CVE population, not just the genuinely-stale entries
    # it was meant to filter, because Harbor's own catalog for a floating
    # tag routinely lags what a stack's deploy pull actually resolved to.
    # The tag fallback can't mismatch a superseded digest onto the wrong
    # artifact -- only the one harbor-findings doc Harbor currently
    # considers this tag's artifact carries that tag value at all.
    if live_digests is not None:
        tag_match = tag is not None and (project_name, repo_short_name, tag) in (live_tag_refs or set())
        artifact_fields["in_use"] = (digest in live_digests) or tag_match

    docs = []
    for vuln in vulnerabilities:
        finding_id = vuln.get("id") or vuln.get("vulnerability_id") or "UNKNOWN"
        docs.append(
            {
                "source": "harbor",
                "finding_id": finding_id,
                "severity_raw": vuln.get("severity"),
                "cvss_score": _extract_cvss_score(vuln),
                "package": vuln.get("package"),
                "package_version": vuln.get("version"),
                "fixed_version": vuln.get("fix_version") or None,
                "description": (vuln.get("description") or "")[:2000] or None,
                "artifact": dict(artifact_fields),
                "scan_time": scan_time,
                "last_seen": now,
            }
        )
    return docs


def fetch_docker_live_usage(
    es_base: str, *, auth_header: str, verify_tls: bool, max_age_hours: int = 48,
) -> tuple[set[str], set[tuple[str, str, str]]]:
    """Phase 14 (docs/threat-vuln-platform/plan.md, uvm-14-03): reads every
    fresh per-host report docker_live_usage_reporter has written to the
    docker-live-usage index (one document per Portainer-exempt host) and
    unions their digest sets and tag-ref sets into the same two shapes
    harbor_live_usage.fetch_live_usage() already returns for
    Portainer-backed hosts. A stale report (older than max_age_hours,
    default 48h -- twice the daily reporting cadence, so one missed run
    doesn't drop a host) is excluded rather than trusted indefinitely; a
    missing/empty index (no gap-list host deployed yet, or OpenSearch
    unreachable) returns two empty sets, not an error -- this source
    degrading never collapses the whole run, since Portainer's own data
    is unioned in separately by the caller."""
    cutoff = (datetime.now(timezone.utc).timestamp() - max_age_hours * 3600)
    cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = json.dumps({
        "size": 1000,
        "query": {"range": {"reported_at": {"gte": cutoff_iso}}},
        "_source": ["hostname", "digests", "tag_refs"],
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{es_base}/docker-live-usage/_search", data=body, method="POST",
    )
    req.add_header("Authorization", auth_header)
    req.add_header("Content-Type", "application/json")
    ctx = ssl.create_default_context()
    if not verify_tls:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    digests: set[str] = set()
    tag_refs: set[tuple[str, str, str]] = set()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=20.0) as resp:  # nosec B310 -- internal operator-configured OpenSearch endpoint, never user-supplied
            result = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            # Index doesn't exist yet -- no gap-list host has reported at
            # all (e.g. docker_live_usage_reporter not deployed anywhere
            # yet). Not an error, just nothing to union.
            return digests, tag_refs
        print(f"WARN: docker-live-usage query failed: {exc.code} {exc.read()}", file=sys.stderr)
        return digests, tag_refs
    except (urllib.error.URLError, ValueError, OSError) as exc:
        print(f"WARN: docker-live-usage query failed: {exc}", file=sys.stderr)
        return digests, tag_refs

    for hit in result.get("hits", {}).get("hits", []):
        source = hit.get("_source", {})
        digests.update(source.get("digests") or [])
        for ref in source.get("tag_refs") or []:
            project, repository, tag = ref.get("project"), ref.get("repository"), ref.get("tag")
            if project and repository and tag:
                tag_refs.add((project, repository, tag))
    return digests, tag_refs


def doc_id(doc: dict) -> str:
    artifact = doc["artifact"]
    artifact_key = f"{artifact['project']}/{artifact['repository']}@{artifact['digest']}"
    return f"{doc['source']}::{doc['finding_id']}::{artifact_key}"


def bulk_upsert(base_url: str, index: str, docs: list[dict], *, auth_header: str, verify_tls: bool, dry_run: bool) -> tuple[int, int]:
    """Returns (indexed_count, error_count)."""
    if not docs:
        return 0, 0
    if dry_run:
        return len(docs), 0

    now = _now_iso()
    lines = []
    for doc in docs:
        _id = doc_id(doc)
        upsert_doc = dict(doc)
        upsert_doc["first_seen"] = now
        lines.append(json.dumps({"update": {"_index": index, "_id": _id}}))
        lines.append(
            json.dumps(
                {
                    "script": {
                        # putAll refreshes every current-scan-observed field
                        # (severity_raw, cvss_score, package_version,
                        # fixed_version, description, last_seen, scan_time --
                        # doc already carries the latter two) on already-
                        # indexed documents, not just timestamps. Fixed
                        # 2026-08-18: the previous version only ever touched
                        # last_seen/scan_time/first_seen, so a newly-added
                        # field like cvss_score silently never backfilled
                        # onto the ~16k documents indexed before it existed
                        # -- confirmed live (0 docs had cvss_score after a
                        # full rerun, until this fix). first_seen stays
                        # deliberately sticky (only set if still null) since
                        # it's meant to record original discovery date, not
                        # get overwritten by putAll. artifact.in_use gets
                        # its own copy-if-missing step first: putAll
                        # replaces ctx._source.artifact wholesale (it's a
                        # nested object, not merged field-by-field), so a
                        # doc built with live_digests=None (Portainer
                        # unreachable this run -- in_use key genuinely
                        # absent from params.doc.artifact) would otherwise
                        # silently wipe a previously-recorded in_use value
                        # instead of carrying it forward. See
                        # docs/threat-vuln-platform/plan.md Phase 13.
                        "source": (
                            "if (ctx._source.artifact != null && params.doc.artifact != null "
                            "&& !params.doc.artifact.containsKey('in_use') && ctx._source.artifact.containsKey('in_use')) "
                            "{ params.doc.artifact.in_use = ctx._source.artifact.in_use } "
                            "ctx._source.putAll(params.doc); "
                            "if (ctx._source.first_seen == null) { ctx._source.first_seen = params.now }"
                        ),
                        "lang": "painless",
                        "params": {"now": now, "doc": doc},
                    },
                    "upsert": upsert_doc,
                }
            )
        )
    body = ("\n".join(lines) + "\n").encode("utf-8")

    url = f"{base_url}/_bulk"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", auth_header)
    req.add_header("Content-Type", "application/x-ndjson")
    ctx = ssl.create_default_context()
    if not verify_tls:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:  # nosec B310 -- internal operator-configured API endpoint (Harbor/GVM/ES/Wazuh/Ollama/MikroTik), never user-supplied; scheme is always http(s)
            result = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        print(f"ERROR: bulk index failed ({exc.code}): {exc.read()[:500]}", file=sys.stderr)
        return 0, len(docs)

    error_count = 0
    if result.get("errors"):
        for item in result.get("items", []):
            update_result = item.get("update", {})
            if update_result.get("status", 200) >= 300:
                error_count += 1
    return len(docs) - error_count, error_count


def update_sync_state(
    base_url: str,
    *,
    auth_header: str,
    verify_tls: bool,
    started: str,
    finished: str,
    status: str,
    artifacts_scanned: int,
    findings_indexed: int,
    errors: int,
    dry_run: bool,
) -> None:
    if dry_run:
        return
    body = json.dumps(
        {
            "source": "harbor",
            "last_run_started": started,
            "last_run_finished": finished,
            "last_run_status": status,
            "artifacts_scanned": artifacts_scanned,
            "findings_indexed": findings_indexed,
            "errors": errors,
        }
    ).encode("utf-8")
    url = f"{base_url}/es-findings-sync-state/_doc/harbor"
    req = urllib.request.Request(url, data=body, method="PUT")
    req.add_header("Authorization", auth_header)
    req.add_header("Content-Type", "application/json")
    ctx = ssl.create_default_context()
    if not verify_tls:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=15):  # nosec B310 -- internal operator-configured API endpoint (Harbor/GVM/ES/Wazuh/Ollama/MikroTik), never user-supplied; scheme is always http(s)
            pass
    except urllib.error.HTTPError as exc:
        print(f"WARN: failed to update sync-state doc: {exc.code} {exc.read()[:200]}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harbor-url", default=os.environ.get("HARBOR_URL", ""))
    parser.add_argument("--harbor-user", default=os.environ.get("HARBOR_ROBOT_USER", ""))
    parser.add_argument("--harbor-password", default=os.environ.get("HARBOR_ROBOT_PASSWORD", ""))
    parser.add_argument("--elasticsearch-url", default=os.environ.get("ELASTICSEARCH_URL", ""))
    parser.add_argument("--es-user", default=os.environ.get("ES_FINDINGS_USER", ""))
    parser.add_argument("--es-password", default=os.environ.get("ES_FINDINGS_PASSWORD", ""))
    parser.add_argument("--no-verify-tls", action="store_true", default=os.environ.get("ES_FINDINGS_NO_VERIFY_TLS") == "1")
    parser.add_argument("--dry-run", action="store_true", help="Walk Harbor and report counts, write nothing to ES.")
    args = parser.parse_args()

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
    production_registry = load_production_registry()

    live_digests: set[str] | None = None
    live_tag_refs: set[tuple[str, str, str]] | None = None
    portainer_url = os.environ.get("PORTAINER_URL", "")
    portainer_token = os.environ.get("PORTAINER_TOKEN", "")
    if portainer_url and portainer_token:
        live_digests, live_tag_refs = harbor_live_usage.fetch_live_usage(
            portainer_url, portainer_token, verify_tls=not args.no_verify_tls
        )
        if live_digests is None:
            print(
                "WARN: could not determine live image usage this run -- in_use carries forward from prior state",
                file=sys.stderr,
            )
    else:
        print(
            "WARN: PORTAINER_URL/PORTAINER_TOKEN not set -- in_use carries forward from prior state",
            file=sys.stderr,
        )

    # Phase 14 (docs/threat-vuln-platform/plan.md, uvm-14-03): union in the
    # self-reported gap-list data (Portainer-exempt security/infra tier) on
    # top of Portainer's. Additive only -- this source's own degrade modes
    # (index not yet created, a stale/missing individual host report) never
    # downgrade an otherwise-successful Portainer read back to None; only a
    # failed Portainer read on its own already sets live_digests to None
    # above, and this union still runs against whatever (possibly empty)
    # sets Portainer left behind so a Portainer outage doesn't also hide
    # gap-list hosts' real data.
    gap_digests, gap_tag_refs = fetch_docker_live_usage(es_base, auth_header=es_auth, verify_tls=not args.no_verify_tls)
    if gap_digests or gap_tag_refs:
        live_digests = (live_digests or set()) | gap_digests
        live_tag_refs = (live_tag_refs or set()) | gap_tag_refs

    started = _now_iso()
    started_monotonic = time.monotonic()

    artifacts_scanned = 0
    findings_indexed = 0
    errors = 0

    projects = list_projects(harbor_base, auth_header=harbor_auth, verify_tls=not args.no_verify_tls)
    print(f"Found {len(projects)} Harbor projects.")

    for project in projects:
        project_name = project.get("name")
        if not project_name:
            continue
        try:
            repos = list_repositories(harbor_base, project_name, auth_header=harbor_auth, verify_tls=not args.no_verify_tls)
        except Exception as exc:  # noqa: BLE001 — one bad project must not abort the run
            print(f"WARN: failed to list repositories for project {project_name}: {exc}", file=sys.stderr)
            errors += 1
            continue

        for repo in repos:
            repo_full_name = repo.get("name", "")
            # Harbor's repository "name" field is "<project>/<repo>" — strip the
            # project prefix to get the short name the artifacts endpoint expects.
            repo_short_name = repo_full_name[len(project_name) + 1 :] if repo_full_name.startswith(f"{project_name}/") else repo_full_name
            if not repo_short_name:
                continue

            try:
                artifacts = list_artifacts(harbor_base, project_name, repo_short_name, auth_header=harbor_auth, verify_tls=not args.no_verify_tls)
            except Exception as exc:  # noqa: BLE001
                print(f"WARN: failed to list artifacts for {project_name}/{repo_short_name}: {exc}", file=sys.stderr)
                errors += 1
                continue

            for artifact in artifacts:
                if not scan_overview_completed(artifact):
                    continue
                digest = artifact.get("digest")
                if not digest:
                    continue
                artifacts_scanned += 1
                try:
                    vulns = get_vulnerabilities(
                        harbor_base, project_name, repo_short_name, digest, auth_header=harbor_auth, verify_tls=not args.no_verify_tls
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"WARN: failed to fetch vulnerabilities for {project_name}/{repo_short_name}@{digest}: {exc}", file=sys.stderr)
                    errors += 1
                    continue
                if not vulns:
                    continue

                scan_time = artifact.get("push_time") or started
                docs = build_documents(
                    project_name, repo_short_name, artifact, vulns,
                    scan_time=scan_time, production_registry=production_registry,
                    live_digests=live_digests, live_tag_refs=live_tag_refs,
                )
                indexed, bulk_errors = bulk_upsert(
                    es_base, "harbor-findings", docs, auth_header=es_auth, verify_tls=not args.no_verify_tls, dry_run=args.dry_run
                )
                findings_indexed += indexed
                errors += bulk_errors

    finished = _now_iso()
    elapsed = time.monotonic() - started_monotonic
    status = "success" if errors == 0 else "completed_with_errors"

    update_sync_state(
        es_base,
        auth_header=es_auth,
        verify_tls=not args.no_verify_tls,
        started=started,
        finished=finished,
        status=status,
        artifacts_scanned=artifacts_scanned,
        findings_indexed=findings_indexed,
        errors=errors,
        dry_run=args.dry_run,
    )

    print(
        f"Done in {elapsed:.1f}s — projects={len(projects)} artifacts_scanned={artifacts_scanned} "
        f"findings_indexed={findings_indexed} errors={errors} dry_run={args.dry_run}"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

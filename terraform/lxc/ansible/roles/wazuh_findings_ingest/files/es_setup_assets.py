#!/usr/bin/env python3
"""Idempotent GET-compare-PUT of Elasticsearch index templates and ingest
pipelines for the findings store — see docs/elasticsearch-stack/plan.md's
"Ingestion pattern" section. Straight port of the shape proven in
security-analysis's secpipe_core/setup_assets.py, adapted stdlib-only
(this repo doesn't ship Python venvs on LXC hosts for jobs like this,
same call already made for harbor_repull.py).

Dry-run by default (prints what would change, exit 0); pass --apply to
actually write. Safe to run every deploy — a no-op PUT when the asset on
disk already matches what's live.

Assets are plain files under assets/templates/*.json (composable index
templates, PUT to /_index_template/<name>, name = file stem) and
assets/ingest_pipelines/*.json (PUT to /_ingest/pipeline/<name>).
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ASSETS_DIR = SCRIPT_DIR / "assets"


def _request(
    url: str,
    *,
    method: str,
    user: str,
    password: str,
    body: dict | None = None,
    verify_tls: bool = True,
) -> tuple[int, dict | None]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    import base64

    creds = base64.b64encode(f"{user}:{password}".encode()).decode()
    req.add_header("Authorization", f"Basic {creds}")

    ctx = ssl.create_default_context()
    if not verify_tls:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
            raw = resp.read()
            parsed = json.loads(raw) if raw else None
            return resp.status, parsed
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return 404, None
        raw = exc.read()
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = {"raw": raw.decode(errors="replace")}
        return exc.code, parsed


def apply_index_template(
    base_url: str,
    name: str,
    body: dict,
    *,
    user: str,
    password: str,
    verify_tls: bool,
    apply: bool,
) -> tuple[str, bool]:
    """Returns (status_label, changed)."""
    url = f"{base_url}/_index_template/{name}"
    status, existing = _request(url, method="GET", user=user, password=password, verify_tls=verify_tls)

    if status == 200 and existing:
        current = existing.get("index_templates", [{}])[0].get("index_template", {})
        # Compare only the fields we manage — Elasticsearch echoes back
        # extra computed fields (e.g. "composed_of": []) that would make a
        # naive full-body comparison always report drift.
        if (
            current.get("index_patterns") == body.get("index_patterns")
            and current.get("template", {}).get("settings", {}) == body.get("template", {}).get("settings", {})
            and current.get("template", {}).get("mappings", {}) == body.get("template", {}).get("mappings", {})
            and current.get("priority") == body.get("priority")
        ):
            return "unchanged", False

    if not apply:
        return ("would-create" if status == 404 else "would-update"), True

    put_status, put_result = _request(
        url, method="PUT", user=user, password=password, body=body, verify_tls=verify_tls
    )
    if put_status not in (200, 201):
        raise RuntimeError(f"PUT {url} failed ({put_status}): {put_result}")
    return ("created" if status == 404 else "updated"), True


def apply_ingest_pipeline(
    base_url: str,
    name: str,
    body: dict,
    *,
    user: str,
    password: str,
    verify_tls: bool,
    apply: bool,
) -> tuple[str, bool]:
    url = f"{base_url}/_ingest/pipeline/{name}"
    status, existing = _request(url, method="GET", user=user, password=password, verify_tls=verify_tls)

    if status == 200 and existing:
        current = existing.get(name, {})
        if current.get("processors") == body.get("processors") and current.get("description") == body.get(
            "description"
        ):
            return "unchanged", False

    if not apply:
        return ("would-create" if status == 404 else "would-update"), True

    put_status, put_result = _request(
        url, method="PUT", user=user, password=password, body=body, verify_tls=verify_tls
    )
    if put_status not in (200, 201):
        raise RuntimeError(f"PUT {url} failed ({put_status}): {put_result}")
    return ("created" if status == 404 else "updated"), True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--elasticsearch-url",
        default=os.environ.get("ELASTICSEARCH_URL", "https://127.0.0.1:9200"),
    )
    parser.add_argument("--user", default=os.environ.get("ES_SETUP_USER", "elastic"))
    parser.add_argument("--password", default=os.environ.get("ES_SETUP_PASSWORD", ""))
    parser.add_argument("--no-verify-tls", action="store_true", default=os.environ.get("ES_SETUP_NO_VERIFY_TLS") == "1")
    parser.add_argument("--apply", action="store_true", help="Write changes. Default is dry-run.")
    args = parser.parse_args()

    if not args.password:
        print("ERROR: no password provided (--password or ES_SETUP_PASSWORD)", file=sys.stderr)
        return 2

    base_url = args.elasticsearch_url.rstrip("/")
    changed_any = False
    failed_any = False

    templates_dir = ASSETS_DIR / "templates"
    for template_file in sorted(templates_dir.glob("*.json")):
        name = template_file.stem
        body = json.loads(template_file.read_text(encoding="utf-8"))
        try:
            status_label, changed = apply_index_template(
                base_url,
                name,
                body,
                user=args.user,
                password=args.password,
                verify_tls=not args.no_verify_tls,
                apply=args.apply,
            )
            print(f"index_template {name}: {status_label}")
            changed_any = changed_any or changed
        except RuntimeError as exc:
            print(f"index_template {name}: FAILED — {exc}", file=sys.stderr)
            failed_any = True

    pipelines_dir = ASSETS_DIR / "ingest_pipelines"
    for pipeline_file in sorted(pipelines_dir.glob("*.json")):
        name = pipeline_file.stem
        body = json.loads(pipeline_file.read_text(encoding="utf-8"))
        try:
            status_label, changed = apply_ingest_pipeline(
                base_url,
                name,
                body,
                user=args.user,
                password=args.password,
                verify_tls=not args.no_verify_tls,
                apply=args.apply,
            )
            print(f"ingest_pipeline {name}: {status_label}")
            changed_any = changed_any or changed
        except RuntimeError as exc:
            print(f"ingest_pipeline {name}: FAILED — {exc}", file=sys.stderr)
            failed_any = True

    if failed_any:
        return 1
    if changed_any and not args.apply:
        print("\nDry-run: changes pending. Re-run with --apply to write them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

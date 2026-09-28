#!/usr/bin/env python3
"""Mark one cve-remediation-assessment document resolved (or re-open it).

See docs/threat-vuln-platform/remediation-runbook.md -- the operational
counterpart to cve_deep_dive.py's assessments: a reviewer works through
the "Top CVEs Needing Attention" panel top-down, and once a recommended
action has actually been taken (patched, upgraded, isolated, or a
deliberate risk-acceptance decision made), runs this to record that.

Records resolved_at_risk_score alongside resolved/resolved_at/
resolved_note -- cve_deep_dive.py's own upsert_assessment() only carries
the resolved state forward on its next weekly run if the CVE's
risk_score hasn't changed since resolution. A changed score means new
instances or a triage-data shift severe enough that this CVE genuinely
needs a fresh look, not a silently-inherited resolved flag hiding it.

--review-after-days (added 2026-09-07, wazuh-stack Stage 3 review): for
an ACCEPT_RISK call made specifically because no upstream fix exists yet
("no such thing as fixing this until $VENDOR ships a patch"), a static
risk_score will never change on its own to trigger a fresh look -- the
CVE would stay silently resolved forever even after upstream ships a
fix. Sets resolved_review_after (an ISO timestamp this many days out);
cve_deep_dive.py's upsert_assessment() stops carrying the resolved state
forward once that passes, regardless of risk_score, so the CVE reappears
for a real re-check on a bounded schedule instead of never.

Colocated with cve_enrichment_sync.py/cve_deep_dive.py on secpipe-stack,
imports the same _es_request helper rather than duplicating it.
"""

from __future__ import annotations

import argparse
import base64
import datetime
import os
import sys
import time
import urllib.parse

import cve_enrichment_sync as ces


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cve_id")
    parser.add_argument("--elasticsearch-url", default=os.environ.get("ELASTICSEARCH_URL", "https://127.0.0.1:9200"))
    parser.add_argument("--es-user", default=os.environ.get("ES_FINDINGS_USER"))
    parser.add_argument("--es-password", default=os.environ.get("ES_FINDINGS_PASSWORD"))
    parser.add_argument("--no-verify-tls", action="store_true", default=os.environ.get("ES_FINDINGS_NO_VERIFY_TLS") == "1")
    parser.add_argument("--note", default="", help="Why this is resolved/accepted (required unless --reopen)")
    parser.add_argument("--reopen", action="store_true", help="Clear a previous resolution instead of setting one")
    parser.add_argument(
        "--review-after-days", type=int, default=None,
        help=(
            "For an ACCEPT_RISK call blocked on an upstream fix that doesn't exist yet: "
            "force this CVE to reappear for a fresh look after this many days, even if "
            "risk_score never changes. Omit for a real fix/patch already applied -- there, "
            "a risk_score change is the only signal that matters."
        ),
    )
    args = parser.parse_args()

    if not args.es_user or not args.es_password:
        print("ERROR: --es-user/--es-password (or ES_FINDINGS_USER/ES_FINDINGS_PASSWORD) are required", file=sys.stderr)
        return 1
    if not args.reopen and not args.note:
        print("ERROR: --note is required when marking resolved (explain what was done, or why the risk was accepted)", file=sys.stderr)
        return 1

    auth_header = "Basic " + base64.b64encode(f"{args.es_user}:{args.es_password}".encode()).decode()
    verify_tls = not args.no_verify_tls
    doc_path = f"/cve-remediation-assessment/_doc/{urllib.parse.quote(args.cve_id, safe='')}"

    status, existing = ces._es_request(args.elasticsearch_url, doc_path, auth_header=auth_header, verify_tls=verify_tls)
    if status != 200 or not existing or not existing.get("found"):
        print(f"ERROR: {args.cve_id} not found in cve-remediation-assessment ({status}) -- it must be in the current shortlist first", file=sys.stderr)
        return 1
    current = existing.get("_source", {})

    if args.reopen:
        update = {
            "resolved": False, "resolved_at": None, "resolved_note": None,
            "resolved_at_risk_score": None, "resolved_review_after": None,
        }
    else:
        review_after = None
        if args.review_after_days is not None:
            review_after = (
                datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=args.review_after_days)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
        update = {
            "resolved": True,
            "resolved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "resolved_note": args.note,
            "resolved_at_risk_score": current.get("risk_score"),
            "resolved_review_after": review_after,
        }

    status, result = ces._es_request(
        args.elasticsearch_url, f"/cve-remediation-assessment/_update/{urllib.parse.quote(args.cve_id, safe='')}",
        method="POST", body={"doc": update}, auth_header=auth_header, verify_tls=verify_tls,
    )
    if status not in (200, 201):
        print(f"ERROR: update failed ({status}): {result}", file=sys.stderr)
        return 1

    action = "Reopened" if args.reopen else "Resolved"
    suffix = f" -- review after {update['resolved_review_after']}" if not args.reopen and update.get("resolved_review_after") else ""
    print(f"{action} {args.cve_id} (stacks: {', '.join(current.get('stacks') or [])}){suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

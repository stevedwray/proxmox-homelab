#!/usr/bin/env python3
"""Offline triage of Wazuh vulnerability findings against the Debian security tracker (Phase 3).

Run on the workstation, not on the wazuh host:

    export TASK_APPROVAL=...   # the playbook step that exports the findings needs it
    ./with-secrets-prod ansible-playbook ... wazuh-tuning.yml -e tune_mode=vulncves -e tune_tag=p3
    curl -sO https://security-tracker.debian.org/tracker/data/json          # public data, about 80MB
    python3 -I vuln_triage.py docs/wazuh-tuning/artifacts/p3-vulncves.json json   [--release trixie]

It reads the (package, CVE, hosts, version, OS) pairs that `wazuh_tuning.py vulncves` exports and classifies each
Debian pair by the tracker's status for the release:

  fix-available   status resolved with a fixed version: patch it (or upgrade the pinned library)
  no-fix-needed   resolved with fixed_version 0 (not affected / no fix needed): a false positive to record
  unassigned      open, urgency not yet assigned: Debian has not triaged it; accept pending triage
  open-low        open, urgency low/unimportant/end-of-life: Debian judges it minor
  open-triaged    open with a real urgency (medium and up): the ones to watch
  untracked       not in the tracker for this release

Nothing is hidden or deleted: the output is a report, and the accepted classes carry a review date in the policy.
"""
import collections
import json
import sys


def classify(entry):
    """entry: the tracker's release record for one CVE+release, or None."""
    if entry is None:
        return "untracked"
    status, fixed, urgency = entry.get("status"), entry.get("fixed_version"), entry.get("urgency")
    if status == "resolved":
        return "no-fix-needed" if fixed in (None, "", "0") else "fix-available"
    if status == "open":
        if urgency in (None, "", "not yet assigned"):
            return "unassigned"
        return "open-low" if urgency in ("low", "unimportant", "end-of-life") else "open-triaged"
    return "untracked"


def tracker_index(tracker, release):
    by_cve = collections.defaultdict(list)
    for src, cves in tracker.items():
        for cve, rec in cves.items():
            by_cve[cve].append((src, rec.get("releases", {}).get(release)))
    return by_cve


def triage(pairs, tracker, release="trixie"):
    by_cve = tracker_index(tracker, release)
    rows = []
    for pkg, cve, hosts, version, os_name in pairs:
        if not os_name.startswith("Debian"):
            rows.append((pkg, cve, hosts, version, "non-debian"))
            continue
        entries = [r for _, r in by_cve.get(cve, []) if r]
        rows.append((pkg, cve, hosts, version, classify(entries[0] if entries else None)))
    return rows


def summarize(rows):
    out = collections.defaultdict(lambda: {"findings": 0, "pairs": 0})
    for _, _, hosts, _, cls in rows:
        out[cls]["findings"] += hosts
        out[cls]["pairs"] += 1
    return dict(out)


if __name__ == "__main__":
    pairs = json.load(open(sys.argv[1]))["pairs"]
    tracker = json.load(open(sys.argv[2]))
    rel = sys.argv[sys.argv.index("--release") + 1] if "--release" in sys.argv else "trixie"
    rows = triage(pairs, tracker, rel)
    total = sum(r[2] for r in rows)
    print(f"{total} findings, {len(rows)} package/CVE pairs, release {rel}")
    for cls, v in sorted(summarize(rows).items(), key=lambda kv: -kv[1]["findings"]):
        print(f"  {cls:15} {v['findings']:5} findings  {v['pairs']:4} pairs  ({100 * v['findings'] / total:.0f}%)")
    for cls in ("fix-available", "no-fix-needed", "open-triaged"):
        for pkg, cve, hosts, version, c in rows:
            if c == cls:
                print(f"  [{cls}] {pkg} {version} {cve} on {hosts} hosts")

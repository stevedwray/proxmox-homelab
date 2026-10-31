#!/usr/bin/env python3
"""Reduce a MITRE ATT&CK Enterprise STIX bundle to the compact dataset the loader reads.

    extract_attack.py enterprise-attack-20.0.json attack-enterprise-20.0.json.gz

Source: https://github.com/mitre-attack/attack-stix-data (Enterprise ATT&CK, includes the Containers and
Identity Provider platforms). The bundle is untrusted input: this only reads JSON, never executes anything from it.

Kept (revoked and deprecated objects dropped): tactics, techniques and sub-techniques, mitigations and what they
mitigate, data components, and the detection chain  technique <- detection strategy -> analytics -> log sources ->
data components  (ATT&CK v18+ model). Descriptions are left out on purpose; every object carries its ATT&CK id and
the loader links to attack.mitre.org by id.

ATT&CK is (c) The MITRE Corporation, used under its terms of use (https://attack.mitre.org/resources/legal-and-branding/).
"""
import gzip
import hashlib
import json
import sys


def _attack_id(obj):
    for ref in obj.get("external_references", []):
        if ref.get("source_name") == "mitre-attack" and ref.get("external_id"):
            return ref["external_id"]
    return None


def _live(obj):
    return not obj.get("revoked") and not obj.get("x_mitre_deprecated")


def extract(bundle, source_sha256=None):
    objs = bundle["objects"]
    live = {o["id"]: o for o in objs if _live(o) and "id" in o}

    def ids(kind):
        return {oid: _attack_id(o) for oid, o in live.items() if o["type"] == kind and _attack_id(o)}

    tech_ids = ids("attack-pattern")
    tactic_ids = ids("x-mitre-tactic")
    mit_ids = ids("course-of-action")
    dc_ids = ids("x-mitre-data-component")
    det_ids = ids("x-mitre-detection-strategy")
    an_ids = ids("x-mitre-analytic")

    rels = [o for o in objs if o["type"] == "relationship" and _live(o)]
    parent = {r["source_ref"]: r["target_ref"] for r in rels if r["relationship_type"] == "subtechnique-of"}
    detects = {}
    for r in rels:
        if r["relationship_type"] == "detects" and r["source_ref"] in det_ids and r["target_ref"] in tech_ids:
            detects.setdefault(r["source_ref"], []).append(tech_ids[r["target_ref"]])

    tactic_by_short = {live[t]["x_mitre_shortname"]: tactic_ids[t] for t in tactic_ids}
    techniques = []
    for oid, tid in tech_ids.items():
        o = live[oid]
        phases = sorted(p["phase_name"] for p in o.get("kill_chain_phases", []) if p.get("kill_chain_name") == "mitre-attack")
        techniques.append([tid, o["name"], sorted(o.get("x_mitre_platforms", [])), phases,
                           tech_ids.get(parent.get(oid))])

    mitigates = sorted([mit_ids[r["source_ref"]], tech_ids[r["target_ref"]]] for r in rels
                       if r["relationship_type"] == "mitigates" and r["source_ref"] in mit_ids and r["target_ref"] in tech_ids)

    analytics = []
    for oid, aid in an_ids.items():
        a = live[oid]
        sources = sorted({(dc_ids[ref["x_mitre_data_component_ref"]], ref.get("name", ""))
                          for ref in a.get("x_mitre_log_source_references", [])
                          if ref.get("x_mitre_data_component_ref") in dc_ids})
        analytics.append([aid, sorted(a.get("x_mitre_platforms", [])), [list(s) for s in sources]])

    detections = []
    for oid, did in det_ids.items():
        d = live[oid]
        refs = [an_ids[r] for r in d.get("x_mitre_analytic_refs", []) if r in an_ids]
        detections.append([did, d["name"], sorted(set(detects.get(oid, []))), sorted(refs)])

    meta = next((o for o in objs if o["type"] == "x-mitre-collection"), {})
    return {
        "attack_version": next((o.get("x_mitre_version") for o in [meta] if o), None),
        "modified": meta.get("modified"),
        "source_sha256": source_sha256,
        "tactics": sorted([tactic_ids[t], live[t]["name"], live[t]["x_mitre_shortname"]] for t in tactic_ids),
        "techniques": sorted(techniques),
        "mitigations": sorted([mit_ids[m], live[m]["name"]] for m in mit_ids),
        "mitigates": mitigates,
        "data_components": sorted([dc_ids[d], live[d]["name"]] for d in dc_ids),
        "detections": sorted(detections),
        "analytics": sorted(analytics),
        "tactic_shortnames": sorted(tactic_by_short),
    }


def main(argv):
    src, out = argv
    raw = open(src, "rb").read()
    data = extract(json.loads(raw), hashlib.sha256(raw).hexdigest())
    payload = json.dumps(data, separators=(",", ":"), sort_keys=True).encode()
    # No filename and mtime 0 in the gzip header, so the same input gives byte-identical output.
    with open(out, "wb") as raw_out, gzip.GzipFile(filename="", mode="wb", fileobj=raw_out, mtime=0) as fh:
        fh.write(payload)
    counts = {k: len(v) for k, v in data.items() if isinstance(v, list)}
    print(f"ATT&CK {data['attack_version']} -> {out}: {len(payload)} bytes raw; {counts}")


if __name__ == "__main__":
    main(sys.argv[1:])

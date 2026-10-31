#!/usr/bin/env python3
"""Build a self-contained ATT&CK matrix view for one mapped process, offline from files in the repo.

    build_matrix_view.py --dataset attack-enterprise-20.0.json.gz \\
        --mapping ../../../../docs/threat-model/attack/authentik-stack.yaml --out matrix.html

No Neo4j and no network: the pinned dataset plus the mapping are all it needs, so the view is reproducible and can
be built at review time. The encoding is neutral on purpose: a technique is "applies", "not applicable" (a recorded
decision) or "not assessed". Telemetry detail is in the side panel on demand and is not drawn as colour.
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

import attack_load as load

# Enterprise matrix column order (v20 names Stealth and Defense Impairment where older versions had Defense Evasion).
TACTIC_ORDER = ["reconnaissance", "resource-development", "initial-access", "execution", "persistence",
                "privilege-escalation", "stealth", "defense-impairment", "credential-access", "discovery",
                "lateral-movement", "collection", "command-and-control", "exfiltration", "impact"]


def load_mapping(path):
    if str(path).endswith(".json"):
        return json.loads(Path(path).read_text())
    import yaml  # PyYAML, only for the YAML source of the mapping
    return yaml.safe_load(Path(path).read_text())


def build_data(dataset, mapping):
    names = {t[2]: t[1] for t in dataset["tactics"]}
    order = [s for s in TACTIC_ORDER if s in names] + sorted(s for s in names if s not in TACTIC_ORDER)
    dc_names = {d[0]: d[1] for d in dataset["data_components"]}
    mit_count, det_count = {}, {}
    for _m, t in dataset["mitigates"]:
        mit_count[t] = mit_count.get(t, 0) + 1
    for _did, _name, techs, _an in dataset["detections"]:
        for t in techs:
            det_count[t] = det_count.get(t, 0) + 1
    control_name = {c["key"]: c["name"] for c in mapping["controls"]}
    mit_name = {m[0]: m[1] for m in dataset["mitigations"]}

    assessed = {}
    for row in load.coverage(dataset, mapping):
        info = {"applies": row["applies"], "basis": " ".join(row["basis"].split()), "platforms": row["platforms"]}
        if row["applies"]:
            info["controls"] = [{"name": control_name[k], "strength": strength, "mitigation": f"{m} {mit_name[m]}"}
                                for k, strength, m in row["mitigations"]]
            info["telemetry"] = row["telemetry"]
            info["analytics"] = [{"id": a["analytic"], "platforms": a["platforms"],
                                  "needs": [dc_names[d] for d in a["needs"]], "have": [dc_names[d] for d in a["have"]]}
                                 for a in row["analytics"]]
        assessed[row["technique"]] = info

    techniques = {}
    for tid, name, plats, tactics, parent in dataset["techniques"]:
        techniques[tid] = {"id": tid, "name": name, "platforms": plats, "tactics": tactics, "parent": parent,
                           "mitigations": mit_count.get(tid, 0), "detections": det_count.get(tid, 0)}
    return {
        "attack_version": dataset["attack_version"], "process": mapping["process"], "roles": mapping.get("roles", []),
        "platforms": mapping["platforms"], "tactics": [[s, names[s]] for s in order], "techniques": techniques,
        "assessed": assessed, "generated": datetime.date.today().isoformat(),
        "sensors": [s["name"] for s in mapping["sensors"]],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--mapping", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    ds, mapping = load.load_dataset(args.dataset), load_mapping(args.mapping)
    errors = load.validate_mapping(ds, mapping)
    if errors:
        print("mapping is invalid:\n  " + "\n  ".join(errors), file=sys.stderr)
        return 2
    data = build_data(ds, mapping)
    template = (Path(__file__).resolve().parent / "matrix_view.template.html").read_text()
    Path(args.out).write_text(template.replace("__DATA__", json.dumps(data, separators=(",", ":")).replace("</", "<\\/")))
    shown = sum(1 for t in data["techniques"].values() if not t["parent"])
    print(f"{args.out}: {len(data['techniques'])} techniques ({shown} parents), {len(data['assessed'])} assessed for {data['process']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

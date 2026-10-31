#!/usr/bin/env python3
"""Load MITRE ATT&CK into Neo4j and overlay what the lab knows about one process.

Two layers, both separate from the :Homelab graph the importer rebuilds (they never carry :Homelab, so the importer
never prunes them):

  Reference  (:AttackTactic) (:AttackTechnique) (:AttackMitigation) (:AttackDataComponent) (:AttackDetection)
             (:AttackAnalytic), from the pinned dataset made by extract_attack.py.
  Overlay    (:Sensor) (:Control) and (:Process)-[:ASSESSED_AGAINST]->(:AttackTechnique), from a hand-written
             mapping file (docs/threat-model/attack/<process>.yaml, rendered to JSON by the playbook).

Standalone, stdlib only (Neo4j's HTTP transaction API, like neo4j_import.py):

    attack_load.py --dataset attack-enterprise-20.0.json.gz --mapping authentik-stack.json   # load
    attack_load.py --dataset ... --mapping ... --validate                                      # check only
    attack_load.py --report p-authentik --dataset ... --mapping ...                           # coverage report

Coverage is TELEMETRY coverage: whether the data an ATT&CK analytic needs is being collected from the process. It is
not a claim that a detection rule exists or fires.
"""
import argparse
import base64
import gzip
import json
import os
import sys
import urllib.request
import uuid

LABELS = ("AttackTactic", "AttackTechnique", "AttackMitigation", "AttackDataComponent", "AttackDetection",
          "AttackAnalytic", "Sensor", "Control")
BATCH = 400


def _url(kind, attack_id):
    if kind == "technique":
        return "https://attack.mitre.org/techniques/" + attack_id.replace(".", "/") + "/"
    return {"tactic": "https://attack.mitre.org/tactics/",
            "mitigation": "https://attack.mitre.org/mitigations/"}.get(kind, "https://attack.mitre.org/") + attack_id + "/"


def load_dataset(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Validation: a mapping that names something ATT&CK doesn't have is a bug, not a warning.
# ---------------------------------------------------------------------------

def validate_mapping(dataset, mapping):
    techs = {t[0] for t in dataset["techniques"]}
    mits = {m[0] for m in dataset["mitigations"]}
    dcs = {d[0] for d in dataset["data_components"]}
    errors = []
    if str(mapping.get("attack_version")) != str(dataset.get("attack_version")):
        errors.append(f"mapping is for ATT&CK {mapping.get('attack_version')}, dataset is {dataset.get('attack_version')}")
    for field in ("process", "platforms", "sensors", "controls", "assessments"):
        if not mapping.get(field):
            errors.append(f"mapping has no {field!r}")
    keys = [x["key"] for x in mapping.get("sensors", []) + mapping.get("controls", [])]
    errors += [f"duplicate key {k!r}" for k in sorted({k for k in keys if keys.count(k) > 1})]
    for s in mapping.get("sensors", []):
        for p in s.get("provides", []):
            if p["data_component"] not in dcs:
                errors.append(f"sensor {s['key']}: unknown data component {p['data_component']}")
            if p.get("level") not in ("observed", "assumed"):
                errors.append(f"sensor {s['key']}: {p['data_component']} needs level observed|assumed")
            if not p.get("platforms") or not set(p["platforms"]) <= set(mapping.get("platforms", [])):
                errors.append(f"sensor {s['key']}: {p['data_component']} needs platforms, a subset of the mapping's")
        if not s.get("evidence"):
            errors.append(f"sensor {s['key']}: no evidence")
    for c in mapping.get("controls", []):
        for m in c.get("implements", []):
            if m not in mits:
                errors.append(f"control {c['key']}: unknown mitigation {m}")
        if c.get("strength") not in ("full", "partial"):
            errors.append(f"control {c['key']}: strength must be full|partial")
        if not c.get("evidence"):
            errors.append(f"control {c['key']}: no evidence")
    seen = set()
    for a in mapping.get("assessments", []):
        if a["technique"] not in techs:
            errors.append(f"assessment: unknown technique {a['technique']}")
        if a["technique"] in seen:
            errors.append(f"assessment: {a['technique']} listed twice")
        seen.add(a["technique"])
        if not a.get("basis"):
            errors.append(f"assessment {a['technique']}: no basis (say why it does or does not apply)")
        if not isinstance(a.get("applies"), bool):
            errors.append(f"assessment {a['technique']}: applies must be true or false")
        if "platforms" in a and (not a["platforms"] or not set(a["platforms"]) <= set(mapping.get("platforms", []))):
            errors.append(f"assessment {a['technique']}: platforms must be a non-empty subset of the mapping's")
    return errors


# ---------------------------------------------------------------------------
# Statements (parameterised; labels and relationship types come only from this file)
# ---------------------------------------------------------------------------

def _batches(rows):
    for i in range(0, len(rows), BATCH):
        yield rows[i:i + BATCH]


def _unwind(statement, rows, **params):
    return [{"statement": statement, "parameters": {"rows": chunk, **params}} for chunk in _batches(rows)]


def schema_statements():
    return [{"statement": f"CREATE CONSTRAINT {label.lower()}_key IF NOT EXISTS FOR (n:{label}) REQUIRE n.key IS UNIQUE"}
            for label in LABELS]


def reference_statements(ds):
    v = str(ds["attack_version"])
    tech_ids = {t[0] for t in ds["techniques"]}
    out = []
    out += _unwind("UNWIND $rows AS r MERGE (n:AttackTactic {key: r.key}) SET n.attack_id = r.id, n.name = r.name, "
                   "n.shortname = r.short, n.url = r.url, n.attack_version = $v",
                   [{"key": "attack:" + t[0], "id": t[0], "name": t[1], "short": t[2], "url": _url("tactic", t[0])}
                    for t in ds["tactics"]], v=v)
    out += _unwind("UNWIND $rows AS r MERGE (n:AttackTechnique {key: r.key}) SET n.attack_id = r.id, n.name = r.name, "
                   "n.platforms = r.platforms, n.tactics = r.tactics, n.is_subtechnique = r.sub, n.url = r.url, "
                   "n.attack_version = $v",
                   [{"key": "attack:" + t[0], "id": t[0], "name": t[1], "platforms": t[2], "tactics": t[3],
                     "sub": t[4] is not None, "url": _url("technique", t[0])} for t in ds["techniques"]], v=v)
    out += _unwind("UNWIND $rows AS r MERGE (n:AttackMitigation {key: r.key}) SET n.attack_id = r.id, n.name = r.name, "
                   "n.url = r.url, n.attack_version = $v",
                   [{"key": "attack:" + m[0], "id": m[0], "name": m[1], "url": _url("mitigation", m[0])}
                    for m in ds["mitigations"]], v=v)
    out += _unwind("UNWIND $rows AS r MERGE (n:AttackDataComponent {key: r.key}) SET n.attack_id = r.id, n.name = r.name, "
                   "n.attack_version = $v",
                   [{"key": "attack:" + d[0], "id": d[0], "name": d[1]} for d in ds["data_components"]], v=v)
    out += _unwind("UNWIND $rows AS r MERGE (n:AttackDetection {key: r.key}) SET n.attack_id = r.id, n.name = r.name, "
                   "n.attack_version = $v",
                   [{"key": "attack:" + d[0], "id": d[0], "name": d[1]} for d in ds["detections"]], v=v)
    out += _unwind("UNWIND $rows AS r MERGE (n:AttackAnalytic {key: r.key}) SET n.attack_id = r.id, n.platforms = r.platforms, "
                   "n.attack_version = $v",
                   [{"key": "attack:" + a[0], "id": a[0], "platforms": a[1]} for a in ds["analytics"]], v=v)

    def rel(src_label, rel_type, dst_label, rows, extra=""):
        return _unwind(f"UNWIND $rows AS r MATCH (a:{src_label} {{key: r.a}}) MATCH (b:{dst_label} {{key: r.b}}) "
                       f"MERGE (a)-[x:{rel_type}{extra}]->(b) SET x.attack_version = $v", rows, v=v)

    out += rel("AttackTechnique", "IN_TACTIC", "AttackTactic",
               [{"a": "attack:" + t[0], "b": "attack:" + tid}
                for t in ds["techniques"] for tid in [s[0] for s in ds["tactics"] if s[2] in t[3]]])
    out += rel("AttackTechnique", "SUBTECHNIQUE_OF", "AttackTechnique",
               [{"a": "attack:" + t[0], "b": "attack:" + t[4]} for t in ds["techniques"] if t[4]])
    out += rel("AttackMitigation", "MITIGATES", "AttackTechnique",
               [{"a": "attack:" + m, "b": "attack:" + t} for m, t in ds["mitigates"] if t in tech_ids])
    out += rel("AttackDetection", "DETECTS", "AttackTechnique",
               [{"a": "attack:" + d[0], "b": "attack:" + t} for d in ds["detections"] for t in d[2]])
    out += rel("AttackDetection", "HAS_ANALYTIC", "AttackAnalytic",
               [{"a": "attack:" + d[0], "b": "attack:" + a} for d in ds["detections"] for a in d[3]])
    out += _unwind("UNWIND $rows AS r MATCH (a:AttackAnalytic {key: r.a}) MATCH (b:AttackDataComponent {key: r.b}) "
                   "MERGE (a)-[x:USES_DATA {log_source: r.src}]->(b) SET x.attack_version = $v",
                   [{"a": "attack:" + an[0], "b": "attack:" + dc, "src": src} for an in ds["analytics"] for dc, src in an[2]],
                   v=v)
    # Last: drop anything from an older ATT&CK version, so a re-load is a clean upgrade.
    out.append({"statement": "MATCH ()-[x]->() WHERE x.attack_version IS NOT NULL AND x.attack_version <> $v DELETE x",
                "parameters": {"v": v}})
    out.append({"statement": "MATCH (n) WHERE n.attack_version IS NOT NULL AND n.attack_version <> $v DETACH DELETE n",
                "parameters": {"v": v}})
    return out


def overlay_statements(mapping, run_id):
    proc = mapping["process"]
    p = {"process": proc, "run": run_id}
    sensors = [{"key": s["key"], "name": s["name"], "kind": s.get("kind"), "evidence": s["evidence"],
                "observed": s.get("observed")} for s in mapping["sensors"]]
    provides = [{"s": s["key"], "dc": "attack:" + x["data_component"], "src": x.get("log_source", ""), "level": x["level"],
                 "note": x.get("note"), "platforms": x["platforms"]} for s in mapping["sensors"] for x in s.get("provides", [])]
    controls = [{"key": c["key"], "name": c["name"], "strength": c["strength"], "evidence": c["evidence"],
                 "note": c.get("note")} for c in mapping["controls"]]
    implements = [{"c": c["key"], "m": "attack:" + m} for c in mapping["controls"] for m in c.get("implements", [])]
    assessed = [{"t": "attack:" + a["technique"], "applies": a["applies"], "basis": a["basis"], "note": a.get("note"),
                 "platforms": a.get("platforms") or mapping["platforms"]}
                for a in mapping["assessments"]]
    out = [{"statement": "MATCH (p:Homelab:Process {key: $process}) RETURN p.key", "parameters": p, "require_rows": True}]
    out += _unwind("UNWIND $rows AS r MERGE (n:Sensor {key: r.key}) SET n.name = r.name, n.kind = r.kind, "
                   "n.evidence = r.evidence, n.observed = r.observed, n.process_key = $process, n.mapping_run = $run",
                   sensors, **p)
    out += _unwind("UNWIND $rows AS r MATCH (s:Sensor {key: r.s}) MATCH (p:Homelab:Process {key: $process}) "
                   "MERGE (s)-[x:MONITORS]->(p) SET x.mapping_run = $run", [{"s": s["key"]} for s in sensors], **p)
    out += _unwind("UNWIND $rows AS r MATCH (s:Sensor {key: r.s}) MATCH (d:AttackDataComponent {key: r.dc}) "
                   "MERGE (s)-[x:PROVIDES {log_source: r.src}]->(d) SET x.level = r.level, x.note = r.note, "
                   "x.platforms = r.platforms, x.mapping_run = $run",
                   provides, **p)
    out += _unwind("UNWIND $rows AS r MERGE (n:Control {key: r.key}) SET n.name = r.name, n.strength = r.strength, "
                   "n.evidence = r.evidence, n.note = r.note, n.process_key = $process, n.mapping_run = $run",
                   controls, **p)
    out += _unwind("UNWIND $rows AS r MATCH (c:Control {key: r.key}) MATCH (p:Homelab:Process {key: $process}) "
                   "MERGE (c)-[x:PROTECTS]->(p) SET x.mapping_run = $run", [{"key": c["key"]} for c in controls], **p)
    out += _unwind("UNWIND $rows AS r MATCH (c:Control {key: r.c}) MATCH (m:AttackMitigation {key: r.m}) "
                   "MERGE (c)-[x:IMPLEMENTS]->(m) SET x.mapping_run = $run", implements, **p)
    out += _unwind("UNWIND $rows AS r MATCH (p:Homelab:Process {key: $process}) MATCH (t:AttackTechnique {key: r.t}) "
                   "MERGE (p)-[x:ASSESSED_AGAINST]->(t) SET x.applies = r.applies, x.basis = r.basis, x.note = r.note, "
                   "x.platforms = r.platforms, x.mapping_run = $run", assessed, **p)
    # Last: what an earlier version of this process's mapping created and this one no longer says.
    # Scoped to this process: another process's mapping has its own run id and must not be touched.
    out.append({"statement": "MATCH ()-[x]->() WHERE x.mapping_run IS NOT NULL AND x.mapping_run <> $run AND "
                             "((type(x) IN ['MONITORS','PROTECTS'] AND endNode(x).key = $process) OR "
                             "(type(x) IN ['PROVIDES','IMPLEMENTS'] AND startNode(x).process_key = $process) OR "
                             "(type(x) = 'ASSESSED_AGAINST' AND startNode(x).key = $process)) DELETE x", "parameters": p})
    out.append({"statement": "MATCH (n) WHERE (n:Sensor OR n:Control) AND n.process_key = $process AND n.mapping_run <> $run "
                             "DETACH DELETE n", "parameters": p})
    return out


# ---------------------------------------------------------------------------
# Coverage (pure: computed from the dataset and mapping, so it can be tested and cross-checked against Neo4j)
# ---------------------------------------------------------------------------

def coverage(dataset, mapping):
    """Per applicable technique: mitigations in place, and telemetry coverage of the analytics that apply.

    A data component counts as collected for an analytic only when the platform it was collected on, the platform
    the analytic is written for, and the attack surface being assessed all agree: SSH logs on the Linux host are not
    telemetry for brute force against Authentik's web login, even though both are "User Account Authentication".
    """
    provided = [(x["data_component"], set(x["platforms"])) for s in mapping["sensors"] for x in s.get("provides", [])]
    mitigations_of = {}
    for m, t in dataset["mitigates"]:
        mitigations_of.setdefault(t, set()).add(m)
    controls_for = {}
    for c in mapping["controls"]:
        for m in c.get("implements", []):
            controls_for.setdefault(m, []).append(c)
    analytics = {a[0]: a for a in dataset["analytics"]}
    detects = {}
    for did, _name, techs, ans in dataset["detections"]:
        for t in techs:
            detects.setdefault(t, []).append((did, ans))
    names = {t[0]: t for t in dataset["techniques"]}
    rows = []
    for a in mapping["assessments"]:
        tid = a["technique"]
        surface = set(a.get("platforms") or mapping["platforms"])
        row = {"technique": tid, "name": names[tid][1], "tactics": names[tid][3], "applies": a["applies"],
               "basis": a["basis"], "platforms": sorted(surface)}
        if a["applies"]:
            row["mitigations"] = sorted({(c["key"], c["strength"], m) for m in mitigations_of.get(tid, ())
                                         for c in controls_for.get(m, [])})
            relevant = []
            for did, ans in detects.get(tid, []):
                for an in ans:
                    common = surface & set(analytics[an][1])
                    needs = sorted({dc for dc, _src in analytics[an][2]})
                    if common and needs:
                        have = sorted({dc for dc, plats in provided if dc in needs and plats & common})
                        relevant.append({"analytic": an, "detection": did, "needs": needs, "have": have,
                                         "platforms": sorted(common)})
            best = max((len(r["have"]) / len(r["needs"]) for r in relevant), default=None)
            row["analytics"] = relevant
            row["telemetry"] = ("no-analytic" if not relevant else "full" if best == 1 else "partial" if best else "none")
        rows.append(row)
    return rows


def missing_data_components(dataset, rows):
    """Which uncollected data components would help the most applicable techniques."""
    names = {d[0]: d[1] for d in dataset["data_components"]}
    help_for = {}
    for r in rows:
        if r["applies"] and r.get("telemetry") in ("none", "partial"):
            for an in r["analytics"]:
                for dc in set(an["needs"]) - set(an["have"]):
                    help_for.setdefault(dc, set()).add(r["technique"])
    return sorted(((len(t), dc, names[dc], sorted(t)) for dc, t in help_for.items()), reverse=True)


def format_report(dataset, mapping, rows):
    applies = [r for r in rows if r["applies"]]
    lines = [f"ATT&CK {dataset['attack_version']} coverage for {mapping['process']}  (platforms: {', '.join(mapping['platforms'])})",
             f"{len(applies)} techniques apply, {len(rows) - len(applies)} assessed not applicable", ""]
    tele = {k: sum(1 for r in applies if r["telemetry"] == k) for k in ("full", "partial", "none", "no-analytic")}
    mitigated = sum(1 for r in applies if r["mitigations"])
    lines.append(f"mitigation: {mitigated} of {len(applies)} have at least one control implementing an ATT&CK mitigation")
    lines.append("telemetry:  " + ", ".join(f"{k} {v}" for k, v in tele.items()))
    lines.append("")
    lines.append(f"{'technique':10} {'name':42} {'mitig':>5} {'telemetry':11}")
    for r in sorted(applies, key=lambda r: (r["telemetry"], r["technique"])):
        lines.append(f"{r['technique']:10} {r['name'][:42]:42} {len(r['mitigations']):>5} {r['telemetry']:11}")
    lines += ["", "Telemetry that is not collected but would help the most techniques:"]
    for n, dc, name, techs in missing_data_components(dataset, rows)[:8]:
        lines.append(f"  {n:>2} techniques  {dc} {name}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Neo4j (HTTP transaction API, same approach as neo4j_import.py)
# ---------------------------------------------------------------------------

def commit(url, user, password, database, statements):
    auth = base64.b64encode(f"{user}:{password}".encode()).decode()
    body = [{"statement": s["statement"], "parameters": s.get("parameters", {})} for s in statements]
    req = urllib.request.Request(f"{url.rstrip('/')}/db/{database}/tx/commit", data=json.dumps({"statements": body}).encode(),
                                 headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json",
                                          "Accept": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=300) as resp:  # nosonar: python:S5332 -- loopback to the local Neo4j container
        payload = json.load(resp)
    if payload.get("errors"):
        raise RuntimeError(f"Neo4j rejected the load: {payload['errors']}")
    for s, result in zip(statements, payload["results"]):
        if s.get("require_rows") and not result["data"]:
            raise RuntimeError(f"expected a match for: {s['statement']} {s.get('parameters')}")
    return payload


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--mapping", required=True)
    ap.add_argument("--validate", action="store_true", help="check the mapping against the dataset and exit")
    ap.add_argument("--report", metavar="PROCESS_KEY", help="print the coverage report and exit (no Neo4j needed)")
    ap.add_argument("--reference-only", action="store_true", help="load the ATT&CK reference layer only")
    args = ap.parse_args(argv)
    ds = load_dataset(args.dataset)
    mapping = json.load(open(args.mapping))
    errors = validate_mapping(ds, mapping)
    if errors:
        print("mapping is invalid:\n  " + "\n  ".join(errors), file=sys.stderr)
        return 2
    if args.validate:
        print(f"mapping ok: {len(mapping['assessments'])} assessments, {len(mapping['sensors'])} sensors, "
              f"{len(mapping['controls'])} controls (ATT&CK {ds['attack_version']})")
        return 0
    if args.report:
        if args.report != mapping["process"]:
            print(f"mapping is for {mapping['process']}, not {args.report}", file=sys.stderr)
            return 2
        print(format_report(ds, mapping, coverage(ds, mapping)))
        return 0
    neo4j = (os.environ.get("NEO4J_URL", "http://127.0.0.1:7474"), os.environ.get("NEO4J_USER", "neo4j"),
             os.environ["NEO4J_PASSWORD"], os.environ.get("NEO4J_DATABASE", "neo4j"))
    commit(*neo4j, schema_statements())
    commit(*neo4j, reference_statements(ds))
    print(f"loaded ATT&CK {ds['attack_version']}: {len(ds['techniques'])} techniques, {len(ds['mitigations'])} mitigations, "
          f"{len(ds['data_components'])} data components, {len(ds['detections'])} detections")
    if not args.reference_only:
        run_id = str(uuid.uuid4())
        commit(*neo4j, overlay_statements(mapping, run_id))
        print(f"overlay for {mapping['process']}: {len(mapping['assessments'])} assessments, {len(mapping['sensors'])} sensors, "
              f"{len(mapping['controls'])} controls (run {run_id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

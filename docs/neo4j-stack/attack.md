# Threat-informed defence with MITRE ATT&CK

Neo4j and the threat model exist for **threat-informed defence**, not for alerting. This layer puts MITRE ATT&CK
next to the lab's own graph so the questions a defender asks can be answered from data: which techniques apply
to this asset and why, which are mitigated, and where the lab would not see an attacker.

Status: **setup phase** (2026-10-31). The foundation is in place and validated on one process (`authentik-stack`);
working through ATT&CK, meaning reviewing assessments and acting on gaps, has not started. ATT&CK **Enterprise v20.0**
including the Containers and Identity Provider platforms.

## What is loaded

| Layer | Labels | From | Never pruned by the importer because |
|---|---|---|---|
| Reference | `:AttackTactic` `:AttackTechnique` `:AttackMitigation` `:AttackDataComponent` `:AttackDetection` `:AttackAnalytic` | the pinned dataset (`terraform/lxc/stacks/neo4j-stack/attack/attack-enterprise-20.0.json.gz`) | none carries `:Homelab` |
| Overlay | `:Sensor` `:Control`, and `(:Process)-[:ASSESSED_AGAINST]->(:AttackTechnique)` | a hand-written mapping per process (`docs/threat-model/attack/<process>.yaml`) | same |

ATT&CK v20 numbers: 706 techniques and sub-techniques (48 on Containers, 49 on Identity Provider), 44 mitigations, 106
data components, 703 detection strategies, 1,770 analytics. v20 renumbered some techniques (Impair Defenses is now
`T1685`), which is why every id in a mapping is checked against the dataset before anything loads.

Relationships: `IN_TACTIC`, `SUBTECHNIQUE_OF`, `MITIGATES` (mitigation to technique), `DETECTS` (detection strategy to
technique), `HAS_ANALYTIC`, `USES_DATA` (analytic to data component, with its log source). Overlay:
`(:Sensor)-[:MONITORS]->(:Process)`, `(:Sensor)-[:PROVIDES {level, platforms}]->(:AttackDataComponent)`,
`(:Control)-[:PROTECTS]->(:Process)`, `(:Control)-[:IMPLEMENTS]->(:AttackMitigation)`,
`(:Process)-[:ASSESSED_AGAINST {applies, basis, platforms}]->(:AttackTechnique)`.

## How a mapping works

Three kinds of claim, each carrying its evidence:

- **Assessment:** a technique applies to the process, or was considered and does not, and *why*. Not-applicable is
  a recorded decision, not an omission (T1190 does not apply to Authentik because it has no external route, on
  purpose).
- **Control:** something in place that implements an ATT&CK mitigation, `full` or `partial`, with what was seen.
- **Sensor:** telemetry collected from the process and which ATT&CK data components it supplies, `observed`
  (the configuration was seen on the host) or `assumed` (it follows from that, but events of that kind were not seen).

The loader refuses a mapping that names an id ATT&CK does not have, an assessment without a basis, or a control or
sensor without evidence.

## What "coverage" means, and what it does not

**Telemetry coverage.** For each applicable technique, take the ATT&CK analytics written for the platform being
attacked and ask whether the data components they need are being collected from that platform. `full` means one
analytic has all its data collected, `partial` some, `none` none, `no-analytic` that ATT&CK gives no analytic for
that platform. It is **not** a claim that a detection rule exists or fires; that is the next layer.

**It is platform-aware, and that matters.** The first version matched on data components alone and reported 5
techniques fully covered. Wrong: Linux SSH `auth.log` data was counting as telemetry for brute force against
Authentik's *web login*, which is a different attack surface. A data component now counts only where the platform it
is collected on, the platform the analytic is written for, and the platform of the surface assessed all agree
(`test_ssh_logs_are_not_telemetry_for_the_web_login`). The corrected figure is zero.

## What the pilot run shows about the tooling

`authentik-stack` is the first mapping, written to prove the loader, the validation and the queries end to end. Its
assessments are a first pass and are **not yet reviewed**; treat the output as a demonstration, not a conclusion.

- The mapping has 27 assessments (24 apply, 3 not applicable, each with its reason), 7 controls and 2 sensors.
- Offline and from the live graph the coverage computation agrees exactly (cross-checked).
- The layer survives the daily importer, and the Homelab graph is unchanged by loading it.
- It caught a tooling bug on the way: the first coverage matched data components regardless of platform and so
  overstated coverage; it is now platform-aware, with a test.

Reviewing the assessments, and deciding what to do about what they show, is the next phase.

## Asset facts the mapping builds on

A mapping should not have to assert what the repo already declares. The threat model now carries these on each
Process, derived from `stack.yaml`, `docker-compose.yml` and `edge.yaml`:

| Property | From | Why an ATT&CK analysis wants it |
|---|---|---|
| `platforms` (`Linux`, `Containers`) | the stack runs Docker | selects which techniques and analytics can apply |
| `technologies` | base images, registry and tag stripped | the software a technique targets |
| `containers`, `containers_privileged`, `containers_host_network`, `containers_docker_sock`, `containers_user_set`, `containers_cap_drop`, `containers_read_only` | compose | container-escape and discovery techniques depend on these |
| `routed`, `route_auth_modes` | edge manifest | how it is reached |
| `docker_socket_proxy`, `docker_socket_proxy_port`, `host_bind_mounts`, `device_passthrough` | stack.yaml | host and API exposure |
| `DEPENDS_ON` edges | `depends_on` | what a compromise reaches or breaks |

Built and tested; **not yet deployed** (it needs the threat-model refresh and an importer run).

## Seeing it

`build_matrix_view.py` makes a self-contained page of the whole ATT&CK matrix with one process's assessments marked.
It builds offline from the pinned dataset and the mapping (no Neo4j, no network), so it is reproducible:

```bash
cd terraform/lxc/stacks/neo4j-stack/attack
python3 build_matrix_view.py --dataset attack-enterprise-20.0.json.gz \
  --mapping ../../../../docs/threat-model/attack/authentik-stack.yaml \
  --out ../../../../docs/neo4j-stack/artifacts/attack-matrix-authentik.html
```

The encoding is neutral: a technique is **applies**, **not applicable** (a recorded decision) or **not assessed**.
Telemetry detail is in the side panel on demand rather than drawn as colour. URL presets: `#dark`, `#subs`,
`#assessed`, `#t=T1110.001` (pin a technique).

## Querying it

```cypher
// Applicable techniques with no control implementing an ATT&CK mitigation
MATCH (:Homelab:Process {key:'p-authentik'})-[a:ASSESSED_AGAINST {applies:true}]->(t:AttackTechnique)
WHERE NOT EXISTS { MATCH (:Control)-[:PROTECTS]->(:Homelab:Process {key:'p-authentik'}),
                         (:Control)-[:IMPLEMENTS]->(:AttackMitigation)-[:MITIGATES]->(t) }
RETURN t.attack_id, t.name ORDER BY t.attack_id;

// The attack surface by tactic
MATCH (:Homelab:Process {key:'p-authentik'})-[a:ASSESSED_AGAINST {applies:true}]->(t)-[:IN_TACTIC]->(ta:AttackTactic)
RETURN ta.name, count(DISTINCT t) AS techniques ORDER BY techniques DESC;

// Why something was judged not applicable
MATCH (:Homelab:Process {key:'p-authentik'})-[a:ASSESSED_AGAINST {applies:false}]->(t)
RETURN t.attack_id, t.name, a.basis;

// What telemetry is collected, and how sure we are
MATCH (s:Sensor)-[:MONITORS]->(:Homelab:Process {key:'p-authentik'}), (s)-[v:PROVIDES]->(dc)
RETURN s.name, dc.name, v.level, v.platforms ORDER BY v.level, dc.name;
```

Offline (no Neo4j needed), the same coverage with the per-technique table and the ranked gaps:
`python3 attack_load.py --dataset attack-enterprise-20.0.json.gz --mapping <mapping>.json --report p-authentik`.

## Adding a process

1. Copy `docs/threat-model/attack/authentik-stack.yaml`, set `process` to the Process key and its `platforms`.
2. Verify the telemetry on the host (read-only) and write it down as `observed` or `assumed`. Do not claim a sensor you did
   not see.
3. Assess techniques with a `basis` that names a fact about *this* process, set `platforms` to the surface attacked,
   and record `applies: false` with the reason where ATT&CK suggests something that does not fit.
4. `attack_load.py --validate`, then add the file to the playbook's load task and provision.

## Updating ATT&CK

Download the new STIX bundle from `mitre-attack/attack-stix-data`, run `extract_attack.py` (the output is
byte-reproducible and records the source's sha256), commit the new dataset, and bump `attack_version` in each mapping.
Validation lists every id that moved. Reloading prunes the old version's nodes.

## Limits

- The mapping is hand-written. It is only as good as the evidence in it, which is why each line carries its evidence.
- Telemetry is not detection. Whether Wazuh or Graylog rules exist for a technique is the next layer.
- `assumed` telemetry (auth.log events, Authentik events in container stdout) was not seen in the events themselves.
- One process is mapped. Totals for the lab need the rest.

ATT&CK is (c) The MITRE Corporation, used under its terms of use. Source: Enterprise ATT&CK v20.0 (2026-10-13), sha256
`81113ba98afa2928f3dcff62022539f7ce30c315c32e14422f11ff95ce534352`.

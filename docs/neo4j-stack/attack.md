# Threat-informed defence with MITRE ATT&CK

Neo4j and the threat model exist for **threat-informed defence**, not for alerting. This layer puts MITRE ATT&CK
next to the lab's own graph so the questions a defender asks can be answered from data: which techniques apply
to this asset and why, which are mitigated, and where the lab would not see an attacker.

Status: **pilot on `authentik-stack`** (2026-10-31), ATT&CK **Enterprise v20.0** including the Containers and
Identity Provider platforms. Other processes follow the same recipe (see *Adding a process*).

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

## Pilot findings: authentik-stack

24 techniques apply and 3 were assessed not applicable (T1190, T1133, T1610, each with its reason).

| | |
|---|---|
| Mitigation | 16 of 24 have at least one control implementing an ATT&CK mitigation |
| Telemetry | **0 full, 5 partial, 18 none, 1 no analytic** |
| No mitigation in place | T1078 Valid Accounts, T1110.001/.003/.004 brute force, T1087 Account Discovery, T1005, T1499, T1611 |
| Largest surface | Credential Access (10 techniques), then Persistence (4) |

Telemetry the lab does not collect, ranked by how many applicable techniques it would help:

1. **Process Creation** (7 techniques) and **Command Execution** (3): `auditd` is inactive and Wazuh's syscollector
   is off, so there is no process or command telemetry on the host at all.
2. **User Account Authentication** for the **Identity Provider** platform (5): Authentik's own login events are
   not collected as identity data. Container logs reach Graylog, but nothing parses them into logins and admin changes.
3. **File Access** (4), **Network Traffic Content** (3, the plaintext hops), **User Account Modification** (2).

Questions this raises that the repo cannot answer: is MFA enforced in Authentik, and are there lockout or reputation
policies (they decide T1078 and T1110)? Can Authentik's event stream be parsed in Graylog?

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

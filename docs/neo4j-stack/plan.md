# neo4j-stack plan

Written with `.github/prompts/plan-change.prompt.md`. The one remaining
local-model step follows `docs/agent-design/step-packet-schema.md`.

The planning session didn't stop at a plan. It also authored and validated
the stack's repo files itself, because each could be checked offline:

| File | Validated with |
|---|---|
| `terraform/lxc/stacks/neo4j-stack/stack.yaml` | `validate-stack-metadata.sh --check-contract-sections` |
| `terraform/lxc/stacks/neo4j-stack/docker-compose.yml` | `validate-compose.sh --stack neo4j-stack` |
| `terraform/lxc/stacks/neo4j-stack/edge.yaml` | `validate-edge-manifests.py` (with `.env` sourced) |
| `terraform/lxc/stacks/neo4j-stack/STACK_CONTRACT.md` | `validate-stack-metadata.sh --check-contract-sections` |
| `terraform/lxc/stacks/neo4j-stack/terragrunt.hcl`, `terraform/lxc/environments/pve/neo4j-stack/terragrunt.hcl` | Copies of wazuh-stack's |
| `terraform/lxc/stacks/neo4j-stack/importer/neo4j_import.py` | `test_neo4j_import.py` (9 tests, including a build from the real derived `pve` model) |
| `terraform/lxc/ansible/playbooks/deploy-neo4j-stack.yml` | `ansible-playbook --syntax-check` |
| `.env` (`LAB_IP_NEO4J`), `secrets/manifest.json` (`services/neo4j` entry) | `test_secrets_env.py` |

**Current status:** [current-state.md](current-state.md). **Plan:** [Roadmap](#roadmap) below.

Rebased 2026-10-31 onto `stable` as `work/neo4j-stack`. The first draft
sat on a branch cut from `main` that was 564 commits behind `stable`.
`stable` already had the same `flows.py` zone-policy fix, so that commit
was dropped.

**Not validated offline:** the importer's Cypher against a live Neo4j.
Docker couldn't stay up in the planning container. The playbook's last task
runs a real import and fails if no `:Process` nodes land, so the first
deploy is that check.

## Graph model

Every imported node has the `:Homelab` label and a unique `key`. Each
import runs as one transaction: it rewrites everything and then deletes any
`:Homelab` node or imported relationship the run didn't produce. A failed
run rolls back and leaves the previous graph in place.

| Node label | key | From |
|---|---|---|
| `TrustBoundary` | `tb-*` | threat-model context |
| `ExternalEntity` | `ee-*` | threat-model context |
| `Process` | `p-*` (one per stack; `name` = stack name) | threat-model context |
| `DataStore` | `ds-*` | threat-model context |
| `Zone` | `zone:<name>` | process zones and zone-policy flow endpoints |
| `Unresolved` | the dangling id | a flow endpoint the model doesn't define |
| `VirtualMachine` | `vm:<netbox id>` | NetBox VMs |
| `IPAddress` | `ip:<addr/len>` | VM `primary_ip4` |
| `Service` | `svc:<netbox id>` | NetBox services parented to a VM |
| `Prefix` | `prefix:<cidr>` | NetBox prefixes |
| `VLAN` | `vlan:<netbox id>` | NetBox VLANs |

| Relationship | Meaning |
|---|---|
| `(src)-[:FLOWS_TO]->(dst)` | One data flow. Properties include `protocol`, `port`/`ports`, `auth`, `transport_security`, `data_classification`, `trust_boundary_crossing`, `flow_type` |
| `(Process)-[:IN_ZONE]->(Zone)` | The stack's SDN zone |
| `(DataStore)-[:HOSTED_ON]->(Process)` | Where the store lives |
| `(Process)-[:RUNS_ON]->(VirtualMachine)` | Process `name` = NetBox VM name, which is the DFD ↔ inventory join |
| `(VirtualMachine)-[:HAS_IP]->(IPAddress)-[:IN_PREFIX]->(Prefix)-[:ON_VLAN]->(VLAN)` | Addressing (longest matching prefix only) |
| `(VirtualMachine)-[:EXPOSES]->(Service)` | NetBox-documented listening services |

**Properties:** the shape of each node's and edge's metadata, what is built
and what is next, is in [metadata.md](metadata.md).

**Rule for threat-modeling work layered on top:** give your own nodes
labels like `:Threat`, `:Mitigation` or `:Asset`, never `:Homelab`. Point
them at imported nodes by `key`, which stays stable across imports. A
relationship you create between two `:Homelab` nodes survives as long as it
has no `import_run` property. Deleting a `:Homelab` node (the stack went
away) also removes your relationships to it.

### Example queries

```cypher
// Everything crossing a trust boundary, with its auth
MATCH (a)-[f:FLOWS_TO]->(b) WHERE f.trust_boundary_crossing IS NOT NULL
RETURN a.key, b.key, f.trust_boundary_crossing, f.port, f.auth ORDER BY f.trust_boundary_crossing;

// Unauthenticated or plaintext flows into anything holding secret-class data
MATCH (src)-[f:FLOWS_TO]->(p:Process)<-[:HOSTED_ON]-(ds:DataStore {data_classification: 'secret'})
WHERE f.auth = 'none' OR f.transport_security = 'none'
RETURN src.key, p.key, ds.name, f.port, f.auth, f.transport_security;

// Paths from the internet to a data store (attack-path view)
MATCH path = (:ExternalEntity {key: 'ee-internet'})-[:FLOWS_TO*1..4]->(:Process)<-[:HOSTED_ON]-(ds:DataStore)
RETURN path LIMIT 25;

// Model gaps: flows pointing at processes the derived model doesn't define
MATCH (u:Unresolved)<-[f:FLOWS_TO]-(src) RETURN u.key, collect(src.key);

// Inventory drift: NetBox VMs with no matching threat-model process
MATCH (vm:VirtualMachine) WHERE NOT (:Process)-[:RUNS_ON]->(vm) RETURN vm.cluster, vm.name ORDER BY vm.cluster;

// Layering a threat on top (survives re-import)
MATCH (p:Homelab {key: 'p-netbox'})
MERGE (t:Threat {id: 'T-001'}) SET t.stride = 'Elevation of privilege', t.title = 'Populate token has write scope'
MERGE (t)-[:TARGETS]->(p);
```

## Operator runbook

Every mutating step below targets `pve`, a production node. Each one goes
through the Production Credential Controls flow: Preflight Summary →
operator "Proceed" → `export TASK_APPROVAL=<task>` →
`./with-secrets-prod <cmd>`. That includes the edge publishing in step 6.
**Deploy only from a checkout of `work/neo4j-stack` that is current with
`stable`.** `provision.sh` and the wrappers ship whatever is checked out,
including `secrets/manifest.json`. A stale base rolls production back (see
the 2026-10-12 wrong-branch deploy). Before any mutating step, run
`git fetch origin && git rev-list --count HEAD..origin/stable`. It must
print `0`. If it doesn't, merge `stable` in and re-run the offline
validators first. The validation tier is "Ansible task or
role changes" plus a new additive stack, so it runs directly on `pve`, with
no teardown and no pve-test-vm cycle. No MikroTik rule is needed:
`edge_seg → infra_seg` has no default-deny (verified live 2026-08-29 for
wazuh-stack), and the importer only talks to NetBox in its own zone.

1. **Confirm the threat-model context is current** (read-only). `stable`
   already carries the list-valued `from`/`to` fix in `flows.py`. Check that
   NetBox's `threat-model` config context has a `last_updated` within the
   last day, e.g. with `curl` against `/api/extras/config-contexts/?name=threat-model`
   using a read-only token. If it's stale, find out why netbox-populate isn't
   updating it before going further. The importer would faithfully copy a
   stale model.

2. **Create a read-only NetBox API token** for the importer: in the NetBox
   UI, Admin → API Tokens → Add, with **Write enabled unchecked**,
   description `neo4j-import (read-only)`. Don't reuse netbox-populate's
   write token. Copy the token value for step 3.

3. **Write the secrets to OpenBao** (human OIDC login only):
   ```bash
   export BAO_ADDR=https://192.168.20.16:8200 BAO_CACERT=$PWD/certs/homelab-root.crt
   export BAO_TOKEN="$(bao login -method=oidc -no-store -token-only)"
   LAB_IP_OPENBAO=192.168.20.16 scripts/openbao_write.py services/neo4j NEO4J_PASSWORD NEO4J_NETBOX_READONLY_TOKEN
   unset BAO_TOKEN
   ```
   For `NEO4J_PASSWORD`, use a fresh password of at least 8 characters
   (Neo4j 5's minimum). Neo4j only applies it on first start, so set it
   before step 5.

4. **Run step `neo4j-01-pve-profile`** below with the local model (or by
   hand). It's deliberately ordered after step 3: profiles fail closed on
   missing fields, so adding `services/neo4j` to the `pve` profile before
   the secret exists would break every `./with-secrets-prod` command.

5. **Create and deploy the LXC:**
   ```bash
   cd terraform/lxc/environments/pve/neo4j-stack
   ../../../../../with-secrets-prod terragrunt plan    # expect exactly 1 LXC to add, 0 change/destroy
   ../../../../../with-secrets-prod terragrunt apply   # after Proceed + TASK_APPROVAL
   cd -
   ./with-secrets-prod scripts/provision.sh --stack neo4j-stack
   ```
   The playbook ends by running the importer once. It fails if Neo4j returns
   a Cypher error or no `:Process` nodes were imported.

6. **Publish the edge routes** (`neo4j.` behind forwardAuth, `neo4j-bolt.`
   with no auth), in the order opensearch-stack's README records:
   ```bash
   python3 terraform/lxc/render-edge-traefik.py --json
   ./with-secrets-prod python3 terraform/lxc/reconcile-edge.py terraform/lxc/stacks/neo4j-stack/edge.yaml --json          # dry-run first
   ./with-secrets-prod python3 terraform/lxc/reconcile-edge.py terraform/lxc/stacks/neo4j-stack/edge.yaml --apply --json  # creates the forwardAuth Authentik objects
   ./with-secrets-prod scripts/provision.sh --stack proxy-stack        # republishes Traefik output
   ./with-secrets-prod scripts/provision.sh --stack technitium-stack   # renders and publishes DNS
   ```
   `render-edge-traefik.py` writes generated output. Check `git status`
   afterwards and stage explicit paths only. Per CLAUDE.md's
   Authentik/Traefik tier, then check that two existing consumers still log
   in and route: `netbox.` (forwardAuth) and `dashboards.` (OIDC).

7. **Verify by hand in a browser.** Open `https://neo4j.lab.gibbsgreatly.xyz`,
   complete Authentik, then connect Browser to
   `neo4j+s://neo4j-bolt.lab.gibbsgreatly.xyz:443` as user `neo4j`. Run
   `MATCH (n:Homelab) RETURN [l IN labels(n) WHERE l <> 'Homelab'][0] AS kind, count(*) ORDER BY kind`.
   The browser must trust the homelab root CA (`certs/homelab-root.crt`)
   for `neo4j+s://` to work.
   **If Browser can't reach Bolt through Traefik**, it's the one design
   assumption not proven offline (Bolt over websocket via a plain Traefik
   HTTP router). The fallback is `bolt://192.168.40.16:7687` directly from
   the LAN. Record which one worked in README.md.

### neo4j-01-pve-profile

```yaml
id: neo4j-01-pve-profile
title: Add services/neo4j to the pve OpenBao profile
depends_on: []   # operator runbook step 3 (OpenBao write) must be done first -- confirm with the operator before running
change: >
  In secrets/manifest.json, on the line that starts with `    "pve": {"auth": "approle", "role": "deploy-pve",`,
  replace the exact substring `"services/netbox", "services/nas"` with
  `"services/netbox", "services/neo4j", "services/nas"`. Change no other
  line. In particular, leave the pve-tiny, pve-framework, pve-test-vm, pve-test and
  ci-netbox-populate profiles alone.
scope:
  allowed_paths:
    - secrets/manifest.json
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Editing any profile other than pve"
    - "Running with-secrets, with-secrets-prod, provision.sh or terragrunt"
gates:
  - id: json-valid
    cmd: "python3 -c \"import json; json.load(open('secrets/manifest.json'))\""
    expect: "exit 0"
    critical: true
  - id: pve-profile-has-neo4j
    cmd: "python3 -c \"import json,sys; m=json.load(open('secrets/manifest.json')); sys.exit(0 if 'services/neo4j' in m['profiles']['pve']['entries'] and 'services/neo4j' not in m['profiles']['pve-tiny']['entries'] else 1)\""
    expect: "exit 0"
    critical: true
  - id: one-line-diff
    cmd: "git diff --numstat secrets/manifest.json"
    expect: "1\t1\tsecrets/manifest.json"
    critical: true
  - id: loader-tests
    cmd: "python3 -m unittest scripts/test_secrets_env.py"
    expect: "exit 0"
    critical: true
```

## Roadmap

Updated at the 2026-10-31 checkpoint; the live state is in [current-state.md](current-state.md). Direction: threat-informed
defence against MITRE ATT&CK. **Not** alerting. We are in the setup phase, and the phases below are ordered.

**0. Land the work (needs the operator).** Merge in this order: #547, #549, #553, #550, #551, #548, #552, merging
`stable` into each next branch and re-running its validators, and retargeting the stacked PRs (#553, #552) to `stable`.
Until then production is ahead of git in the ways listed in current-state.md.

**1. Make the pipeline reliable** (after the merges).
- Run the full populate from a `stable` checkout, so NetBox is refreshed on the new model without the one-section workaround.
- Prove the daily workflow on `main`: it has never succeeded, and can only be proven there.
- Re-provision `ci-runner-01` from `stable` (it needs the operator's `gh` login) so the pin matches and the self-update
  metrics start.
- Decide whether the runner should reach MikroTik, or accept that CI runs skip router data.

**2. Deploy the asset facts.** The threat-model refresh, then an importer run, each with a preflight. Verify that
Processes carry `platforms` and `technologies` and that `DEPENDS_ON` appears.

**3. Finish the ATT&CK setup** (no analysis yet).
- A lab-wide inventory of sensors and controls, so a second mapping does not restate Wazuh, Graylog, Harbor and the zone
  policy. Verify the telemetry per host, read-only (the Wazuh manager's agent list is one query).
- Derive a mapping's platforms and technologies from the model, so the YAML holds judgement only, and check the rest
  against it.
- Map a second process to prove the recipe scales (`proxy-stack`, which every request crosses, is the obvious one).
- Design the detection-rule layer (which Wazuh and Graylog rules cover which techniques) so telemetry coverage can be
  separated from detection coverage.

**4. Then work through ATT&CK** (explicitly later). Review the assessments, read the coverage, decide what to do about the
gaps. The open questions the repo cannot answer (is MFA and lockout enforced in Authentik; can its event stream be parsed
in Graylog) belong here.

**Model quality, alongside.** Annotate the flows with unknown auth and the Authentik `auth-dependency` flows; assign
VLANs to NetBox prefixes (`ON_VLAN`); model downstream dependencies; resolve `RUNS_ON` for the six unlinked processes.

**Later.** The CVE overlay (attach `unified-cve-exposure` findings from OpenSearch to `:VirtualMachine` nodes; needs an
OpenSearch read credential and an `infra_seg` to `infra_seg` read, which is the same zone and needs no rule); observed
flows (declared versus observed, source unverified); a periodic `neo4j-admin database dump` once hand-authored
`:Threat` nodes exist, because `docker_mount` already has `backup_policy: include` for the volume.

**Not planned.** Alerting from Neo4j or the threat model.

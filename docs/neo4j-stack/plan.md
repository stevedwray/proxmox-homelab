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
`./with-secrets-prod <cmd>`. That includes the step-1 netbox-stack redeploy
and the edge publishing in step 6. The validation tier is "Ansible task or
role changes" plus a new additive stack, so it runs directly on `pve`, with
no teardown and no pve-test-vm cycle. No MikroTik rule is needed:
`edge_seg → infra_seg` has no default-deny (verified live 2026-08-29 for
wazuh-stack), and the importer only talks to NetBox in its own zone.

1. **Ship the `flows.py` fix to NetBox.** It's on this branch; netbox-stack
   copies `flows.py` onto the LXC at deploy time.
   `./with-secrets-prod scripts/provision.sh --stack netbox-stack`. Then
   check that the next populate run (or a manual
   `systemctl start netbox-populate.service` on the LXC) prints
   `threat model config context 'threat-model' upserted` instead of
   `warn: threat model derivation failed`.

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
   Per CLAUDE.md's Authentik/Traefik tier, then check 1–2 existing
   forwardAuth routes (e.g. `netbox.`) still log in and route.

7. **Verify by hand in a browser.** Open `https://neo4j.lab.gibbsgreatly.xyz`,
   complete Authentik, then connect Browser to
   `neo4j+s://neo4j-bolt.lab.gibbsgreatly.xyz:443` as user `neo4j`. Run
   `MATCH (n:Homelab) RETURN labels(n)[0] AS kind, count(*) ORDER BY kind`.
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
  replace the exact substring `"services/netbox", "services/nextcloud"` with
  `"services/netbox", "services/neo4j", "services/nextcloud"`. Change no other
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

## Deferred (not in this pass)

- **CVE overlay:** attach `unified-cve-exposure` findings from OpenSearch to
  `:VirtualMachine` nodes for vulnerability-aware attack paths. It needs
  an OpenSearch read credential plus a `infra_seg` → `infra_seg` read
  (same zone, no rule).
- **Fixing the `flows.py` gaps** listed in README.md: duplicate route ids,
  and processes referenced but not defined.
- **Backups:** the `:Homelab` graph can be regenerated, but hand-authored
  threat nodes can't. `docker_mount` has `backup_policy: include`, which
  covers the volume via the LXC backup. A periodic `neo4j-admin database
  dump` would be a cleaner restore point once real threat work exists.

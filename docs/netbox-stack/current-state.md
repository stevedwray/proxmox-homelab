# NetBox Stack Current State

## Purpose

This note is the short resume point for the `netbox-stack` workstream.

Use it together with:

- `docs/netbox-stack/README.md`
- `docs/netbox-stack/docker-runtime-host-matrix.md`
- `docs/netbox-stack/ownership.md`

The goal is to let a fresh session resume cleanly without depending on local
session artifacts. Files under `docs/netbox-stack/artifacts/` are ignored
work-session evidence, not durable project documentation.

## Current Position

### State as of 2026-06-11 (second pass) — multi-source inventory operational

Branch `feat/netbox-populate-multi-source-inventory` is the current working branch.
`fix/playbook-syntax-fixes` was merged to `baseline/teardown-validated` via PR.

**Current populate result:** `VMs: 25, IPs: 33, Services: 50, Stale managed objects: 1`

NetBox now discovers from both Proxmox nodes:
- pve-test: all LXCs visible in `pve-test-cluster`; services via socket-proxy
- pve: all LXCs visible in `pve-cluster`; services via Portainer API token (`PORTAINER_TOKEN`)
- MikroTik topology present
- pve-test and pve each have their own hypervisor device and cluster in NetBox

Stale managed object: one stale IP (`192.168.1.40/24`) — minor, not blocking.

#### Changes in this session (2026-06-11, second pass)

**Multi-source inventory (`pve-test.yaml`):**
- Added `inventory:` block with two `proxmox_nodes` entries:
  - pve-test: existing credentials (`PROXMOX_READONLY_TOKEN_ID/SECRET`)
  - pve: new credentials (`PVE_READONLY_TOKEN_ID/SECRET`) + Portainer token
- `pve.gibbsgreatly.xyz` added with `portainer_url` and `portainer_api_key_env: PORTAINER_TOKEN`

**New SOPS entries (`terraform/secrets.enc.yaml`):**
- `PVE_READONLY_TOKEN_ID=automation@pve!terraform-readonly`
- `PVE_READONLY_TOKEN_SECRET` — regenerated on pve (pre-existing token, secret was lost)
- `PORTAINER_TOKEN` — Portainer API access token for `management-stack.gibbsgreatly.xyz:9443`

**populate.py additions:**
- `_load_inventory_sources()` — reads `inventory:` block from network intent YAML
- `_build_topology_from_nodes()` — discovers each node with explicit credentials,
  builds per-node PortainerClient when `portainer_url`/`portainer_api_key_env` declared
- `_node_name_from_proxmox_data()` — extracts node name from Proxmox API response
- `_ensure_proxmox_hypervisor()` — creates device + cluster in NetBox for non-primary nodes
- `populate_static_hosts()` — upserts statically declared hosts (workstations, Pis, etc.)
- `populate_virtual()` — now resolves cluster per-VM from `vm_def["node"]`; pve VMs go
  into `pve-cluster`, pve-test VMs stay in `pve-test-cluster`

**discover.py additions:**
- `PortainerClient.__init__` gains `api_key=None` — uses `X-API-Key` header, skips JWT auth
- `build_vm_list()` — Portainer endpoint matching now tries name first, then agent IP fallback

**deploy-netbox-stack.yml:**
- Added `pve_readonly_token_id`, `pve_readonly_token_secret`, `portainer_token` vars
- Added env template lines: `PVE_READONLY_TOKEN_ID`, `PVE_READONLY_TOKEN_SECRET`, `PORTAINER_TOKEN`

**Tests (`test_populate_multi_source.py`):**
- 14 tests covering `_load_inventory_sources`, `_build_topology_from_nodes`,
  `populate_static_hosts`

## Recommended Next Work

1. **Run the teardown gate, then PR `feat/netbox-populate-multi-source-inventory` →
   `baseline/teardown-validated`** — validation has been done live on pve-test with
   both nodes populating correctly; the teardown gate is the remaining promotion gate.

2. **Teardown gate for `baseline/teardown-validated`** — `fix/playbook-syntax-fixes`
   was merged but the teardown gate has not been run since that merge. Run a full
   teardown + redeploy cycle to validate the baseline still holds.

3. **Static hosts** — `pve-test.yaml` has `static_hosts: []`. Add entries for the
   Linux desktop and Raspberry Pi when their IPs are known.

4. **Stale IP `192.168.1.40/24`** — investigate and clean up this orphan.

#### Changes in this session (2026-06-11, first pass)

**Playbook fixes (`deploy-netbox-stack.yml`):**
- Added `mikrotik_port` var + `MIKROTIK_PORT` line to LXC env template
  (mikrotik_client.py defaulted to 8729/binary-API when the var was absent)
- Added `lab_subnet_{infra,mgmt,edge,build}_cidr` vars + `LAB_SUBNET_*_CIDR`
  lines to LXC env template (populate.py `_resolve_env_token()` was returning
  unresolved `${lab_subnet_*_cidr}` strings, causing NetBox 500 on prefix POST)

**SOPS secrets (`terraform/secrets.enc.yaml`):**
- Added `PROXMOX_READONLY_TOKEN_ID=automation@pve!terraform`
- Updated `PROXMOX_READONLY_TOKEN_SECRET` to current value matching
  `TF_VAR_pm_api_token_secret` (stale value `84421308-...` from before last
  teardown was causing 401; correct value is `a78966a2-...`)

**New Ansible playbook (`ansible/00-initial-setup/`):**
- `mikrotik-firewall-infra-to-router-https.yml` — idempotent rule allowing
  infra_seg (192.168.40.0/24) TCP 443 inbound to MikroTik router.
  Mirrors pattern of `mikrotik-firewall-build-to-infra-apt-cacher.yml`.
  Required because MikroTik input chain was blocking REST API calls from
  the NetBox LXC (infra_seg only had ICMP and DNS).

**Copilot prompt cleanup:**
- `.github/copilot-prompts/diagnose-proxmox-401.md` — redacted hardcoded
  stale token secret that gitleaks flagged (`84421308-...` → `<redacted>`)
- `.github/copilot-prompts/fix-proxmox-401.md` — trailing whitespace removed

#### Resolved root causes (all four)

1. **`MIKROTIK_PORT` missing from LXC env** — mikrotik_client.py defaulted
   to port 8729 (binary API); REST API is on 443. Symptom: connection timeout.

2. **Stale Proxmox token secret** — `PROXMOX_READONLY_TOKEN_SECRET` was added
   in this branch but held a pre-teardown value. After teardown, Terraform
   creates a new token and stores it as `TF_VAR_pm_api_token_secret`. The
   correct fix is to keep `PROXMOX_READONLY_TOKEN_SECRET` in sync with
   `TF_VAR_pm_api_token_secret` after every teardown/redeploy cycle.

3. **MikroTik firewall blocking HTTPS from infra_seg** — TCP connect succeeded
   but all HTTP requests timed out. Input chain rule only allowed broad
   `192.168.1.0/24`; infra_seg needed an explicit accept for TCP 443.

4. **`LAB_SUBNET_*_CIDR` vars missing from LXC env** — `_resolve_env_token()`
   in populate.py returned unresolved placeholder strings as literal prefix
   values, causing NetBox 500 `KeyError: 'data'` on every prefix POST.

#### State as of 2026-06-08

The following changes landed during that teardown-validation pass.
Teardown stamp: `20260608-013141`.

**Playbook fixes (`deploy-netbox-stack.yml`):**
- Removed invalid play-level `when: not ansible_check_mode` (Ansible 2.21 rejects it)
- Removed invalid `recurse: yes` from the copy task (not a valid param)
- Removed `args: warn: false` from the shell task (removed in Ansible 2.14)
- Added "Write NetBox secrets env file" task so Docker Compose gets all required vars
- Added `netbox_api_token` to the persistent `set_fact` in Play 1 (was play-local only)
- Removed SSH keypair generation and Proxmox host `authorized_key` tasks entirely

**SSH discovery removed (`discover.py`):**
- `_resolve_guest_ssh_user`, `_resolve_guest_ssh_identity_file`,
  `_run_lxc_guest_command`, `_parse_docker_services`, `_parse_listener_services`,
  and `_build_runtime_services` all removed.
- `RuntimeInspector` no longer has an SSH fallback. Discovery priority is now:
  1. Portainer API
  2. Per-guest docker-socket-proxy (`DOCKER_SOCKET_PROXY_URL_TEMPLATE`)
  3. Single-endpoint socket proxy (`DOCKER_SOCKET_PROXY_URL`, legacy)
- Tests for deleted SSH parsing functions removed.

**Socket proxy enabled in deployed credential env:**
- `DOCKER_SOCKET_PROXY_URL_TEMPLATE=http://{guest_ip}:2375` is now written to
  `/etc/netbox-populate/env` on the NetBox LXC during provision.

**Other fixes:**
- Loki `delete_request_store: filesystem` added to monitoring playbook.
- Harbor scan smoke check timeout raised from 180s to 600s (cold-start Trivy).
- `populate.py` network intent path crash fixed (commit `e92d608`, 2026-06-09).

### Frozen Resume State (2026-06-06)

The following was the state before the 2026-06-08 pass. Preserved for context.

What NetBox had proved at that point:

- Proxmox and MikroTik inventory are visible in NetBox.
- VM/LXC inventory and IPs are present.
- Docker runtime service ingestion works when a Docker host has a reachable
  runtime inspection path.
- The reconciler has ownership guardrails so populate does not retag or
  patch unmanaged NetBox objects by accident.
- Portainer socket-proxy canary accepted closed.

## The Main Open Question

The main remaining NetBox design question is not whether socket-proxy works.
It does.

The open question is how the NetBox populate process should decide which Docker
hosts to probe.

Right now:

- most Docker runtime targets are expected to come from Proxmox discovery
- but not every future Docker host will necessarily come from Proxmox
- the current code contains a narrow `populate.py` augmentation to bridge one
  discovery gap for the `monitoring-stack` canary

That augmentation works, but it should not be accepted blindly without a design
decision.

## Recommended Next Work

1. **Run the teardown gate** — full infrastructure teardown + redeploy cycle
   on pve-test is the required promotion gate for `baseline/teardown-validated`.
   The Proxmox host itself is not torn down, so the API token on the node
   is unchanged — no SOPS update needed after teardown.

2. **Merge** `fix/playbook-syntax-fixes` → `baseline/teardown-validated` once
   the teardown gate passes.

3. After merge, run `./with-secrets scripts/provision.sh --stack netbox-stack`
   and verify populate service runs cleanly on the fresh deployment.

## What Not To Reopen First

Do not start by reopening:

- Portainer migration/export-import work
- broad NetBox auth/token redesign
- disposable test-path setup

Those areas are either already proven or belong to separate workstreams.

## Copilot Session Style

The recent Docker refactor loop worked well:

- one bounded session at a time
- clear copy/paste prompt
- required tracked handback
- manager review between sessions

Use the same pattern here for NetBox resume work.

## Commit Message Notes

When this work is eventually committed, useful message material:

- clarify NetBox docker-socket-proxy state: transport proven, broad production
  rollout not assumed
- document that normal platform stacks still keep socket-proxy opt-in disabled
  unless explicitly enabled
- add `docker_socket_proxy_targets` as an explicit stack metadata hook for
  declared Docker host probe candidates
- keep target augmentation safe: map declared addresses only to existing
  NetBox VM/interface records; do not create VM objects implicitly
- add focused coverage for multiple declared socket-proxy candidates and
  stack-name skip behavior
- record Portainer canary prep: declared target, runbook, pve-test
  `populate.py --plan`, and enabled check-mode result
  `ok=29 changed=3 unreachable=0 failed=0 skipped=49 rescued=0 ignored=0`
- freeze NetBox after Session 56: Docker runtime service ingestion is blocked
  upstream until Docker refactor deploys socket-proxy during normal
  infrastructure-container rebuilds and validates it on `pve`

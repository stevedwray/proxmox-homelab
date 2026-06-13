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

### State as of 2026-06-13 — pve-test-vm teardown validated; merged to baseline

`feat/netbox-populate-multi-source-inventory` merged to `baseline/teardown-validated`
(commit `1df3324`, PR #354). Branch deleted.

**Current populate result (pve-test-vm):** `VMs: 26, IPs: 34, Services: 56, Stale managed objects: 1`

Sources:
- **pve-test-vm** (`192.168.1.41`): 12 LXCs in `pve-test-vm-cluster`; services via docker-socket-proxy per guest
- **pve** (`pve.gibbsgreatly.xyz`): 14 LXCs in `pve-cluster`; services via Portainer API at `management-stack.gibbsgreatly.xyz:9443`
- **MikroTik hAP**: router, 14 interfaces, 5 VLANs

Stale managed object: one stale IP (`192.168.1.41/24`) — the pve-test-vm hypervisor host IP; minor, not blocking.

The **teardown gate** was run on pve-test-vm (VM-hosted Proxmox, ZFS pool `infrastructure-containers`).
This replaces the retired bare-metal laptop `pve-test`. All cold-start failures discovered during
the cycle were fixed in the same branch. See cold-start fixes section below.

#### Changes in this session (2026-06-12–13, pve-test-vm teardown validation)

**Cold-start fix — authentik: Harbor not yet available during Stage 3a deploy**
- Added `nc -z` Harbor reachability check before `docker_compose_v2` in `deploy-authentik-stack.yml`
- When Harbor is unreachable, all 6 compose images are pre-pulled from public registries
  (ghcr.io, docker.io, gcr.io) and tagged with Harbor proxy-cache paths
- `docker_compose_v2 pull:` set to `"never"` in this case (images already local)
- Commit: `81f9fe1`

**Cold-start fix — netbox: `netbox_network_env` undefined in populate timer play**
- Variable was declared in play 1 vars but referenced in play 5 ("Install NetBox populate daily timer")
- Ansible play vars are scoped per-play; added `netbox_network_env` to play 5's `vars:` block
- Commit: `5df61f0`

**Cold-start fix — netbox-populate: MikroTik 401 crash**
- `discover_from_mikrotik()` raised `RuntimeError` on 401, crashing the entire populate
- Wrapped the call in `build_network_topology()` with graceful `RuntimeError` catch
- Added `MIKROTIK_ADMIN`/`MIKROTIK_ADMIN_PASSWORD` as credential fallback in playbook
- Commit: `aaa4f95`

**Fix — Portainer "local" endpoint not matching management-stack LXC**
- The Portainer server registers its own Docker daemon as a unix-socket endpoint named "local"
- `get_endpoints()` previously filtered it out; the IP index had no entry for the host
- Fix: resolve the `portainer_url` hostname to an IP; map unix-socket endpoints to that IP;
  thread `portainer_url` through `build_topology()` → `build_vm_list()`
- Result: management-stack@pve now gets its Portainer services (nginx-proxy-manager, central-registry,
  registry-ui, trivy-scanner, portainer); Services count +8
- Commits: `9459630`

**Secrets — pve-test-vm SOPS file**
- Added `MIKROTIK_READONLY_PASSWORD`, `PVE_READONLY_TOKEN_ID`, `PVE_READONLY_TOKEN_SECRET`,
  `PORTAINER_TOKEN` to `terraform/secrets.pve-test-vm.enc.yaml`
- `PVE_READONLY_TOKEN_SECRET` regenerated on pve host after discovering the token existed
  but the secret was unknown (original creation predated this SOPS file)
- Commit: `a9db94c`

**Fix — teardown script: PVE_ENV not propagating to target guard**
- `TARGET_NODE_EXPECTED` defaulted to `pve-test` instead of reading `PVE_ENV`
- Added `PVE_ENV` to the fallback chain with higher precedence than `TF_VAR_proxmox_node`
  (which may be stale in the shell from a previous session)
- Commits: `fe9868d`, `a8bab1d`

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

1. **Static hosts** — `pve-test-vm.yaml` has `static_hosts: []`. Add entries for
   the Linux desktop, Raspberry Pi, and any other non-Proxmox hosts when their IPs
   are known.

2. **Stale IP `192.168.1.41/24`** — the pve-test-vm hypervisor host IP appears as a
   stale managed object. Investigate whether it should be registered as a device IP
   rather than a VM IP, or simply suppressed.

3. **Harbor image policy in CI** — the authentik-stack `docker-compose.yml` still
   references `ghcr.io` and `docker.io` directly (used only as fallback during cold-start;
   the Harbor proxy-cache paths are set after pre-pull). CI `harbor-image-policy` job
   will flag these. Tracked in `docs/plan/current-state.md` Branch 1 (fix/ci-pipeline-cleanup).

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

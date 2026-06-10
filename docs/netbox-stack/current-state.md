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

### State as of 2026-06-08

The following changes landed in `fix/playbook-syntax-fixes` during a
teardown-validation pass. The teardown test (stamp `20260608-013141`) passed
with all platform services healthy in browser. The branch needs merging to
`baseline/teardown-validated` once the operator confirms readiness.

#### Changes in this pass

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
- `PortainerClient` SSL context consolidated into `_ssl_ctx()` with a TODO for
  verified TLS once step-ca or LE cert is in place.

**Socket proxy enabled in deployed credential env:**
- `DOCKER_SOCKET_PROXY_URL_TEMPLATE=http://{guest_ip}:2375` is now written to
  `/etc/netbox-populate/env` on the NetBox LXC during provision.
- Every LXC already has `docker-socket-proxy` deployed on port 2375.

**Other fixes:**
- Loki `delete_request_store: filesystem` added to monitoring playbook.
- Harbor scan smoke check timeout raised from 180s to 600s (cold-start Trivy).

#### Resolved: `populate.py` path crash

Fixed in commit `e92d608` (2026-06-09):
- `populate.py` now wraps the `parents[3]` navigation in `try/except IndexError`
  and raises a clear error pointing to `NETBOX_NETWORK_INTENT_PATH`
- `deploy-netbox-stack.yml` now copies `terraform/lxc/network/pve-test.yaml`
  to `/etc/netbox-populate/network.yaml` during provision
- `NETBOX_NETWORK_INTENT_PATH=/etc/netbox-populate/network.yaml` is written to
  the service credential env file
- Verified: service starts without IndexError on the deployed LXC

#### Current blocker: Proxmox credential 401

The `netbox-populate.service` starts but fails with a 401 when querying the
Proxmox API using `PROXMOX_READONLY_TOKEN_ID` / `PROXMOX_READONLY_TOKEN_SECRET`.

Diagnosis needed:
```bash
./with-secrets env | grep PROXMOX
```

This will show whether `PROXMOX_READONLY_TOKEN_SECRET` is present in
`terraform/secrets.enc.yaml` and what value it resolves to. If the key is
missing or the value doesn't match an actual Proxmox token, the fix is to:

1. Verify (or create) a read-only API token on Proxmox named to match
   `PROXMOX_READONLY_TOKEN_ID` from `.env.pve-test`
2. Add the token secret to `secrets.enc.yaml` via interactive SOPS edit:
   ```bash
   sops terraform/secrets.enc.yaml
   ```
3. Re-provision the netbox-stack (`scripts/provision.sh --stack netbox-stack`)
   so the updated secret is written to the LXC credential env

**Important:** Do not use `sops --set` for this — only interactive `sops` editing
is safe here. Agents cannot verify credential values before writing them.

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

1. Diagnose and fix the Proxmox 401 (see "Current blocker" above). This requires
   operator-controlled SOPS editing — not an agent task.
2. Once `netbox-populate.service` runs without error, check journal output to
   confirm Proxmox guest discovery returns results:
   ```bash
   journalctl -u netbox-populate.service --no-pager -n 100
   ```
3. Merge `fix/playbook-syntax-fixes` → `baseline/teardown-validated`.
4. Once populate runs cleanly, verify socket-proxy discovery reaches the deployed
   LXCs and record what services are discovered.

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

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

#### Current blocker: Harbor IO starvation preventing image pull

The `netbox-populate.service` path fix works (service starts). The netbox
provision itself fails because Docker cannot pull images from
`harbor.lab.gibbsgreatly.xyz` — Harbor LXC (VMID 40010) was at 99.45% IO
pressure for ~2.8 days after the previous teardown test.

Symptom:
```
redis Error Get "http://harbor.lab.gibbsgreatly.xyz/v2/": net/http: request
canceled (Client.Timeout exceeded while awaiting headers)
```

Root cause: Harbor's Trivy scanner likely runs continuous background scans
on freshly pulled images, thrashing disk IO. The LXC accepts TCP connections
on ports 80 and 443 but never responds to HTTP requests.

**pve-test was rebooted** (2026-06-11, separate issue with the host). All
LXCs including Harbor should auto-start on host boot.

**Next steps when pve-test is back online:**

1. Verify Harbor is healthy:
   ```bash
   ssh root@pve-test.gibbsgreatly.xyz \
     "curl -sk --max-time 10 https://192.168.30.10/api/v2.0/health"
   ```
   Expected: `{"status":"healthy","components":[...]}`

2. Check Harbor IO pressure — if it's back above 90% quickly, Trivy is the
   culprit and may need its scan schedule adjusted or scanning disabled for
   the proxy cache project:
   ```bash
   ssh root@pve-test.gibbsgreatly.xyz \
     "pvesh get /nodes/pve-test/lxc/40010/status/current --output-format json" \
     | python3 -c 'import json,sys; d=json.load(sys.stdin); print("iosome:", d.get("pressureiosome","?"))'
   ```

3. If Harbor is healthy, retry netbox provision — always with `./with-secrets`:
   ```bash
   ./with-secrets scripts/provision.sh --stack netbox-stack
   ```
   Note: running `scripts/provision.sh` bare fails with "unresolved placeholder"
   because `LAB_IP_NETBOX` is only injected by `./with-secrets`.

4. Once provision succeeds, check populate service:
   ```bash
   ssh root@pve-test.gibbsgreatly.xyz \
     "pct exec 40012 -- journalctl -u netbox-populate.service --no-pager -n 50"
   ```

#### Credential note

`./with-secrets env | grep PROXMOX` shows:
- `PROXMOX_TOKEN_ID=automation@pve!terraform` (admin token, present)
- `PROXMOX_READONLY_TOKEN_SECRET` (present, has a value)

`PROXMOX_READONLY_TOKEN_ID` was not seen in the output — verify it is set in
`.env.pve-test`. If missing, the populate service will fall back to the admin
token or fail with 401.

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

1. Wait for pve-test to come back online, then verify Harbor health (see
   "Current blocker" above).
2. Retry `./with-secrets scripts/provision.sh --stack netbox-stack`.
3. Check `netbox-populate.service` journal — if a 401 appears, verify
   `PROXMOX_READONLY_TOKEN_ID` is set in `.env.pve-test`.
4. Merge `fix/playbook-syntax-fixes` → `baseline/teardown-validated`.
5. Once populate runs cleanly, verify socket-proxy discovery reaches the
   deployed LXCs and record what services are discovered.

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

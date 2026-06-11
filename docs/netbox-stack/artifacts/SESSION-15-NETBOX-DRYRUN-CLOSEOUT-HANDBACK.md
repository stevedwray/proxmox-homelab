# Session 15 Handback - NetBox Dry-Run Closeout

## Metadata

- Date: 2026-06-01
- Model: `GitHub Copilot GPT-5 mini`
- Branch: `task/monitoring-stack-phase1`
- Commit at session start: `732e0aa993d03a07dd085c68aa7c8d2160b25838`
- Commit at session end: `0a674b19e03f46bee250a81eff4bd355184720b1`
- Session goal: wire the non-secret `PROXMOX_READONLY_TOKEN_ID` into the supported `./with-secrets` overlay path and complete a full `populate.py --plan` dry-run using the new NetBox credential and read-only Proxmox token path.

## Scope Boundary

- In scope:
  - Supply `PROXMOX_READONLY_TOKEN_ID` via the supported `./with-secrets` overlay (`.env.pve-test`) and clarify the template.
  - Keep the secret `PROXMOX_READONLY_TOKEN_SECRET` in `terraform/secrets.enc.yaml` (SOPS).
  - Run `./with-secrets python3 terraform/lxc/stacks/netbox-stack/integrations/populate.py --plan` and capture credential/permission outcomes.
- Out of scope:
  - Creating or rotating Proxmox tokens on the host.
  - Broad Proxmox credential redesign or production `pve` changes.
  - Docker / MikroTik redesign beyond tiny fixes revealed by the dry-run.
- Stop condition for this session: `PROXMOX_READONLY_TOKEN_ID` is supplied via the supported overlay, the dry-run is attempted with the intended credentials, and the handback documents whether closeout is accepted.

## Files Reviewed

- `docs/netbox-stack/README.md`
- `docs/netbox-stack/artifacts/HANDOFF.md`
- `docs/netbox-stack/artifacts/HANDBACK-TEMPLATE.md`
- `docs/netbox-stack/artifacts/SESSION-14-NETBOX-RBAC-HANDBACK.md`
- `docs/netbox-stack/artifacts/SESSION-13-CONTROLLED-CREDENTIAL-PROVISIONING-HANDBACK.md`
- `AGENTS.md`
- `with-secrets`
- `.env.pve-test.template`
- `terraform/lxc/stacks/netbox-stack/integrations/populate.py`
- `terraform/lxc/stacks/netbox-stack/integrations/proxmox_client.py`
- `terraform/lxc/stacks/netbox-stack/integrations/client.py`
- `terraform/secrets.enc.yaml`

## Files Changed

- `.env.pve-test.template` — clarified instructions for `PROXMOX_READONLY_TOKEN_ID` (committed).
- `.env.pve-test` — added `PROXMOX_READONLY_TOKEN_ID` (local overlay; gitignored, not committed).
- This handback: `docs/netbox-stack/artifacts/SESSION-15-NETBOX-DRYRUN-CLOSEOUT-HANDBACK.md`

## Commands Run

- `git status --short docs/netbox-stack/artifacts .env.pve-test.template`
- `./with-secrets bash -lc 'env | grep -E "^(PROXMOX_READONLY_TOKEN_ID|PROXMOX_READONLY_TOKEN_SECRET|NETBOX_API_TOKEN|NETBOX_SUPERUSER_API_TOKEN)=" | sed "s/=.*$/=<set>/'`
- `./with-secrets python3 terraform/lxc/stacks/netbox-stack/integrations/populate.py --plan`
- `./with-secrets python3 -c "import sys; sys.path.insert(0,'terraform/lxc/stacks/netbox-stack/integrations'); from proxmox_client import ProxmoxClient; print('resolved token id ->', ProxmoxClient().token_id)"`
- `./with-secrets python3 -c "import sys; sys.path.insert(0,'terraform/lxc/stacks/netbox-stack/integrations'); from client import NetBoxClient; print('resolved netbox token ->', NetBoxClient().token)"`
- `git add .env.pve-test.template && git commit -m "SESSION-15: Wire PROXMOX_READONLY_TOKEN_ID into with-secrets overlay template"`

## Validation Completed

- `./with-secrets bash -lc 'env | grep -E "^(PROXMOX_READONLY_TOKEN_ID|PROXMOX_READONLY_TOKEN_SECRET|NETBOX_API_TOKEN|NETBOX_SUPERUSER_API_TOKEN)=" | sed "s/=.*$/=<set>/"'`:
  - result: `PROXMOX_READONLY_TOKEN_SECRET=<set>`, `NETBOX_API_TOKEN=<set>`, `NETBOX_SUPERUSER_API_TOKEN=<set>`, `PROXMOX_READONLY_TOKEN_ID=<set>` — confirmed the overlay + SOPS secrets are exposed to `with-secrets`.

- `./with-secrets python3 terraform/lxc/stacks/netbox-stack/integrations/populate.py --plan`:
  - result: Completed dry-run (plan mode) successfully; sample summary:
    - `NetBox: http://192.168.40.12:8080 [plan mode]`
    - `Using network intent: terraform/lxc/network/pve-test.yaml (environment=pve-test)`
    - `=== Done ===` — `VMs: 25, IPs: 34, Services: 50, Stale managed objects: 0`
  - notes: No `401/403` authentication or permission errors were encountered during this dry-run.

- `Proxmox client token resolution`:
  - `resolved token id -> automation@pve!terraform-readonly-1780274785` — confirms the `PROXMOX_READONLY_TOKEN_ID` from the `.env.pve-test` overlay was the identifier used at runtime.

- `NetBox client token resolution`:
  - `resolved netbox token -> <masked token>` — `NETBOX_API_TOKEN` was present and used by the client (preferred over `NETBOX_SUPERUSER_API_TOKEN`).

## Validation Not Completed

- None: the full `populate.py --plan` dry-run completed under `./with-secrets` with the intended credential paths.

## Concrete Outcomes

- what changed:
  - the `.env.pve-test.template` was clarified and the local overlay `.env.pve-test` was updated to include the read-only Proxmox token identifier.
- what now works:
  - `./with-secrets python3 terraform/lxc/stacks/netbox-stack/integrations/populate.py --plan` runs to completion using the intended credential paths (NetBox service token via `NETBOX_API_TOKEN` and Proxmox read-only token via `PROXMOX_READONLY_TOKEN_ID` + secret in SOPS).
- what was intentionally left unchanged:
  - the Proxmox token secret remains encrypted in `terraform/secrets.enc.yaml` (SOPS); no secrets were moved to plaintext files.

## Issues Encountered

- Root cause of the earlier blocker: the non-secret token identifier (`PROXMOX_READONLY_TOKEN_ID`) had been recorded in `test-leak.env` during credential provisioning but not present in the supported `./with-secrets` overlay (`.env.pve-test`). With-secrets requires an environment overlay file for `pve-test`; without that identifier discovery would fail or fall back to legacy token variables.
- How it was handled: added `PROXMOX_READONLY_TOKEN_ID` to the local `.env.pve-test` overlay and clarified `.env.pve-test.template` for operators.

## Risks Or Follow-Up Concerns

- risk: If operators accidentally commit `.env.pve-test` (which may be gitignored), a non-secret token identifier could be made public. Mitigation: keep `.env.pve-test` gitignored; only the template was committed.
- risk: The NetBox service token (`NETBOX_API_TOKEN`) still has broader permissions from the RBAC work; next session should tighten per-model actions based on exact API calls observed in the dry-run.

## Evidence For Post-Mortem

- relevant output summary:
  - `with-secrets env` showed the read-only token id and secret exposed to the runtime environment.
  - `populate.py --plan` completed with `VMs: 25, IPs: 34, Services: 50` and no auth errors.
  - `ProxmoxClient().token_id` resolved to the expected read-only token identifier from `.env.pve-test`.
- files/diffs worth reviewing first:
  - `.env.pve-test.template` (committed change)
  - `.env.pve-test` (local overlay — contains the non-secret identifier; do not commit secrets there)

## Recommended Next Single Session

- next session title: `Grant Least-Privilege NetBox RBAC To The Automation Token`
- objective: Use the `populate.py --plan` call trace and the dry-run results to identify the minimal per-model `actions` required by the automation and tighten the `svc-netbox-sync` object-permission(s) accordingly; re-run the dry-run and targeted validation probes.
- files to read first:
  - `terraform/lxc/stacks/netbox-stack/integrations/populate.py`
  - `terraform/lxc/stacks/netbox-stack/integrations/client.py`
  - `docs/netbox-stack/README.md`
- why this is the next bounded chunk: the dry-run validated discovery and write-paths; tightening RBAC reduces risk and should be done before marking the automation fully operational.

## Final Disposition

- `NetBox dry-run closeout accepted`

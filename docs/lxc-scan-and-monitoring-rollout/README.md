# lxc-scan-and-monitoring-rollout

Redesigns GVM/Greenbone's credentialed (LSC) scanning from ad hoc
root-SSH-key reuse to a dedicated per-host `gvm-scan` account (unique SSH
keypair + unique sudo password per LXC, OpenBao-backed), and extends both
the Wazuh agent and Docker-container-log-to-Graylog forwarding from a
partial pilot to the real 25-stack in-scope fleet on `pve` (not the ~36
originally estimated -- see plan.md's scope-correction notes).

See `plan.md` for the full design, the operator's 2026-09-29 judgment-call
answers, and the bounded step packets.

## Status: code-complete for all 3 phases, not yet deployed (2026-09-29)

All code written, syntax-checked, and (wherever testable without live
GVM/OpenBao access) functionally tested with real data. Nothing has been
applied to a production host yet. Branch: `task/lxc-scan-and-monitoring-rollout-plan`
(12 commits), not merged -- operator's call on PR/merge timing.

## Next steps, in order

### Track A -- GVM credentialed scanning (blocked)

1. **`gvm-03`** (the one remaining blocker): add 25 entries to
   `secrets/manifest.json`, one per in-scope stack at
   `services/greenbone/scan-hosts/<stack>`, each listing fields
   `GVM_SCAN_SSH_PRIVATE_KEY`, `GVM_SCAN_SSH_PUBLIC_KEY`,
   `GVM_SCAN_SUDO_PASSWORD`. Needs a session/operator with `secrets/`
   access -- this session's permission settings denied it entirely.
2. **Bootstrap**: operator runs `bao login -method=oidc -no-store`,
   exports `BAO_TOKEN`, then `scripts/gvm_scan_credentials_bootstrap.py --all`
   once. Generates + stores all 25 stacks' keypairs and sudo passwords.
3. **Redeploy the 25 in-scope stacks** (see `IN_SCOPE_STACKS` in
   `scripts/gvm_fleet_targets_generate.py` for the exact list) via their
   own `scripts/provision.sh --stack <name>`, under the normal production
   approval flow. Each picks up the `gvm_scan_account` role.
4. **Redeploy `greenbone-stack`** last. This is where `gvm-07` actually
   runs for real -- generates the fleet directory, registers the GVM
   credentials/targets/tasks. Watch closely: `ensure_target()`'s
   `ssh_elevate_credential_id` kwarg is flagged in the code as unverified
   against the installed `python-gvm==27.5.*`'s actual API signature --
   it's designed to fail loudly with an actionable error if wrong, not
   silently skip privilege escalation.

### Track B -- Wazuh + Graylog (no blockers, ready now)

1. Redeploy any of the 25 in-scope stacks -- picks up
   `wazuh_agent`/`wazuh_agent_group`, and for `ai-services-stack` /
   `mcp-utility-stack` specifically, the `docker_base` log-driver
   migration (`log-02`).
2. Watch the first redeploy of any stack that needs a **new** Wazuh
   group created -- `waz-01`'s manager-API group-creation call
   (`GET/POST /groups`) is unverified against a live Wazuh 4.14.7
   manager; flagged in the role's own commit message.

### Suggested order

Don't redeploy all 25 at once. Canary first:

- **Track B**: `apt-cacher-stack` (small, already had `wazuh_agent` --
  this redeploy only adds the group, low risk).
- **Track A** (once unblocked): `harbor-stack` (the actual exemplar
  `gvm-05` was built and tested against).

Confirm both work cleanly, then roll the rest.

## Known, deliberate gaps (not bugs -- documented, not silently dropped)

- `media-stack`, `management-stack`, `omada-controller`,
  `proxmox-backup-server` are all real, running stacks on `pve`
  (confirmed via a live Proxmox API call) with **no Ansible playbook in
  this repo at all** -- can't join this rollout until one exists. See
  the comment above `IN_SCOPE_STACKS` in
  `scripts/gvm_fleet_targets_generate.py`.
- `pentagi-stack` (CTs confirmed destroyed 2026-09-28) and
  `pentagi-upstream-control` (a comparison baseline, not real
  production) are deliberately excluded.

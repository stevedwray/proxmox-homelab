# pve-tiny network onboarding

Status: **plan written, not yet executed (2026-09-17).** `terraform/lxc/network/pve-tiny.yaml`
and `terraform/lxc/storage/pve-tiny.yaml` already exist (authored directly, not
through the step/gate loop — see plan.md's step blocks for what they contain and
why). Everything else in `plan.md` is still to do.

## What this is

pve-tiny (192.168.1.250, new production node — see git history on
`task/pve-tiny-host-bootstrap` for host bootstrap and the Debian LXC template
build) currently has 32GB RAM and no SDN zones. The goal: give it the same
`infra_seg` (VLAN 40) and `mgmt_seg` (VLAN 20) zones pve already has, so
`harbor-stack` and `graylog-stack` can later be relocated there from `pve` to
free up memory — pve is at 71GB/135GB used, with `graylog-stack` alone
accounting for ~8GB of that.

**Scope of this workspace is network onboarding only.** It ends with pve-tiny
having working `infra_seg`/`mgmt_seg` SDN zones and nothing deployed into them
yet. Actually relocating `harbor-stack`/`graylog-stack` (data migration,
cutover sequencing, DNS) is a separate, not-yet-planned piece of work — see
"Phase 2" at the bottom of `plan.md` for the open judgment calls that need
resolving before that gets its own plan.

## Key decision this plan assumes

**pve-tiny joins the SAME physical VLANs pve already uses (VLAN 20/40,
`192.168.20.0/24`/`192.168.40.0/24`)**, rather than getting its own new zone
numbers. This means a relocated `harbor-stack`/`graylog-stack` keeps its
existing IP and every other stack's Harbor/Graylog references keep working
unchanged — the whole point of "relocate," not "rebuild." This was inferred
from the operator's own framing ("SDN zones set up and I'll need to configure
the switches") rather than asked as an open question — flag if that reading is
wrong before running the plan.

pve-tiny will **not** use ZFS (operator-stated). `terraform/lxc/storage/pve-tiny.yaml`
reflects that: `local-lvm` only, mirroring `pve-test.yaml`'s non-ZFS
`platform-default` profile, not `pve.yaml`'s ZFS-backed one. This means a
relocated Harbor/Graylog's storage backend changes from ZFS to LVM-thin —
functionally fine, but any backup approach specifically relying on ZFS
snapshots for these two stacks won't carry over as-is.

## Real facts this plan is grounded in (checked live, not assumed)

- pve-tiny's `vmbr0` is **not** VLAN-aware yet (`ip -br link` + `/etc/network/interfaces`
  checked directly, 2026-09-17) — needs `proxmox-vlan-aware-bridge.yml` before
  any SDN VLAN zone can attach.
- `infra_seg`/`mgmt_seg` gateways (192.168.40.1/192.168.20.1) already exist on
  the MikroTik for pve — this is *not* a new-VLAN-on-the-router job like
  `ai_seg`/VLAN 50 was for pve-framework. It's a new physical trunk port to
  wire up, same as `pve-test`'s laptop got its own trunk port for the same
  VLAN set.
- `ansible/00-initial-setup/proxmox-sdn-setup.yml` already reads
  `terraform/lxc/network/{{ PVE_ENV }}.yaml` (defaulting to `pve-test`) and
  asserts `proxmox.target_node == TF_VAR_proxmox_node` — no code changes
  needed, it works against `pve-tiny.yaml` as soon as `PVE_ENV=pve-tiny` is
  set (already true via `.env.pve-tiny`).
- VLAN-type SDN zones are **not** Terraform-managed in this repo yet
  (`terraform/lxc/network/NETWORK_CONTRACT.md`'s documented gap) — the
  Ansible playbook above is the real apply mechanism, not `terragrunt apply`.

## Files in this workspace

- `plan.md` — the step-by-step plan (`docs/agent-design/step-packet-schema.md` shape)
- `artifacts/` — gitignored scratch, not created yet

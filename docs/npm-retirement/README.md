# npm-retirement (planning workspace)

Status: **planned, nothing applied.** Plan: [plan.md](plan.md). Branch:
`work/npm-retirement-pbs-tpot` (cut from `origin/stable`; independent of the
Omada work).

Goal: move the two remaining *real* web routes off the legacy Nginx Proxy
Manager (on management-stack, `192.168.1.4`) onto the lab's Traefik, so NPM can
be retired:

| Old name (NPM) | New name (Traefik) | Backend | Auth |
|---|---|---|---|
| `tpotce.gibbsgreatly.xyz` | `tpot.lab.gibbsgreatly.xyz` | `https://192.168.1.28:64297` (T-Pot nginx, Raspberry Pi 5) | Authentik forwardAuth; T-Pot's own basic auth removed; host firewall limits the port to Traefik |
| `pbs.gibbsgreatly.xyz` | `pbs.lab.gibbsgreatly.xyz` | `https://192.168.1.12:8007` (PBS in CT 105) | none — PBS's own login |

(`omada.gibbsgreatly.xyz` already moved: see `docs/omada-controller/` on the
Omada branch. The Jellyfin vhost still has one real client and is out of scope
here.)

## What is already in this branch (tested, not deployed)

- `ansible/00-initial-setup/tpot-web-behind-traefik.yml` (tags `tls`,
  `firewall`, `noauth`)
- `terraform/lxc/ansible/playbooks/deploy-pbs-tls.yml` (prepare-only unless
  `-e pbs_tls_install=true`)
- `terraform/lxc/stacks/proxmox-backup-server/{stack.yaml,inventory.yml}`
  (inventory deliberately has **no** `ansible_playbook`, so `provision.sh`
  never runs it by accident)
- The two `edge.yaml` manifests are **inline in the plan, not committed**: a
  committed `edge.yaml` is picked up by every full `provision.sh` run, which
  would publish the DNS records and Authentik app early.

## Hand-backs

_(none yet)_

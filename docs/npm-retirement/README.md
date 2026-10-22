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

- **Worktree runs need gitignored inventories.** `terraform/lxc/environments/**/inventory.yml`
  is generated and absent from a worktree; `-i` pointing at it silently matches no hosts
  ("no hosts matched", nothing deployed). Use the main checkout's path for `proxy-stack`
  (T4b) and copy `environments/pve/technitium-stack/inventory.yml` into the worktree (T4c).
- **`reconcile-edge.py --traefik-output-dir` renders every stack's manifest**, not just the
  one passed. Do not push that dir (T4b would overwrite all routes). Render the single
  manifest with `render-edge-traefik.py` into a clean dir instead (identical tpot file).
- **T-Pot Part 1 progress (2026-10-23):** T2 (cert), T3, T4a-c (Authentik app, Traefik
  route, DNS) done and verified; `tpot.lab` returns 302 to Authentik. T5-T8 pending.

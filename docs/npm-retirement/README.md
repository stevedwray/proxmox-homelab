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
  route, DNS) done and verified; `tpot.lab` returns 302 to Authentik. T5 (firewall) and T6/T6b (basic auth removed, Traefik allowed in nginx) done; T8 docs
  written. T7 (check after the 04:09 reboot) still to confirm.

## PBS (Part 2) state, 2026-10-23

- `https://pbs.lab.gibbsgreatly.xyz` -> Traefik -> `https://192.168.1.12:8007` (no Authentik; PBS login).
- CT 105 serves a step-ca cert (90 days, SANs `pbs.lab…`, `proxmox-backup.gibbsgreatly.xyz`,
  `proxmox-backup-server`, `192.168.1.12`), renewed by `pbs-tls-renew.timer` (03:40).
  Stock cert kept as `/etc/proxmox-backup/proxy.{pem,key}.selfsigned`.
- `pve` and `pve-tiny` **no longer pin a PBS fingerprint** on `pbs-iscsi`; they validate via the
  homelab CA (a pin would break at every renewal). Backups use `192.168.1.12:8007` directly (never
  via NPM). Original pin, for rollback: `2B:44:AB:DF:D2:36:D5:BE:6D:4D:E3:9B:4F:A8:CB:42:F8:2D:AB:48:61:A4:8E:A7:08:0D:D8:DA:BA:54:00:FD`.
- P4 (test backups) skipped by decision; confirm the scheduled jobs (pve 11:00 UTC, pve-tiny
  12:30 NZDT) succeeded before Part 3.
- Part 4 (enrol CT 105 in Wazuh/Graylog/Grafana) is planned in plan.md section 5a.

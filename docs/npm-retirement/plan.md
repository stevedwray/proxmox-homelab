# Plan: move `tpotce` and `pbs` from NPM to Traefik

Written 2026-10-23 for execution in a **separate session**. Everything below was
researched read-only on 2026-10-23; the playbooks and manifests were tested
locally (syntax-check, `bash -n` on every embedded script, the repo's
`validate-edge-manifests.py` / `render-edge-traefik.py` across all 25
manifests, no router/service name collisions). **Nothing has been run on
production.**

Context: the Omada UI was already moved the same way (Traefik + a step-ca
backend cert). NPM on management-stack (`192.168.1.4`) still fronts these two.

## 0. Read first

**Rules of engagement**
- Production mutations (`pve`, the CTs, the Pi, MikroTik, DNS) follow `CLAUDE.md`:
  Preflight Summary → operator says "Proceed" → operator runs with
  `TASK_APPROVAL=<name>` → After-Action Summary. One approval per task. The
  operator runs the commands; you cannot set `TASK_APPROVAL`.
- Keep the operator's preferences: no browser basic-auth popups (Authentik
  instead), and don't over-engineer routine deploys (no `--check` on
  `deploy-proxy-stack.yml` — its later plays fail in check mode).
- Commit after each verified step on `work/npm-retirement-pbs-tpot`; do not
  open PRs or merge unless the operator asks.
- Check `git branch --show-current` before the first commit.
- Parts 1 (T-Pot) and 2 (PBS) are independent. **Do T-Pot first** (lower blast
  radius, and it shakes out the cert + Authentik + Traefik recipe). **Never run
  the PBS swap (P3) inside a backup window** (see P1).

**Conventions used below**
- Repo root: `/home/steve/git/proxmox-homelab`. `with-secrets-prod` = the `pve`
  production wrapper.
- Ansible roles path: playbooks under `terraform/lxc/ansible/` need
  `ANSIBLE_CONFIG=$PWD/terraform/lxc/ansible/ansible.cfg` when run from the
  repo root.
- Edge publish recipe (proven for Omada, 2026-10-23): render only the new
  manifest into its own directory, push just that file with
  `deploy-proxy-stack.yml` (additive copy, no purge), then publish DNS with
  `provision.sh --stack technitium-stack` (regenerates records from all
  manifests — first confirm the only branch-only edge difference vs `stable` is
  the new route).
- Names are decided: `tpot.lab.gibbsgreatly.xyz`, `pbs.lab.gibbsgreatly.xyz`.
  The old `*.gibbsgreatly.xyz` names stay on NPM untouched until Part 3.

## 1. Findings (evidence)

**NPM today** (`192.168.1.4`, proxy hosts 22 = pbs, 23 = tpotce)
- `pbs.gibbsgreatly.xyz` → `https://proxmox-backup.gibbsgreatly.xyz:8007`
  (= `192.168.1.12`). 57k requests in 2 days — almost all the Greenbone scanner
  (`192.168.70.11`); real use is the operator, occasionally.
- `tpotce.gibbsgreatly.xyz` → `https://tpot.gibbsgreatly.xyz:64297`
  (`192.168.1.28`). 4 requests in 3 days, all the operator.
- DNS: MikroTik static records `pbs.` / `tpotce.gibbsgreatly.xyz` → `192.168.1.4`.

**Traefik reachability** (tested from `192.168.30.10`, `edge_seg`):
`192.168.1.12:8007` open, `192.168.1.28:64297` open → **no MikroTik change needed.**

**Backend TLS** — Traefik cannot skip backend verification, but it has a global
`serversTransport.rootCAs` (system CAs + the homelab step-ca root), so a backend
with a **step-ca-issued** cert (SAN matching the URL host/IP) verifies. Both
backends are self-signed today, so both need a step-ca cert. Precedent: OpenBao
and Omada routes.

**PBS** (CT 105 on `pve`, PBS 3.4.9, `192.168.1.12`)
- Cert `/etc/proxmox-backup/proxy.pem` is self-signed, CN `proxmox-backup-server`,
  SHA-256 fingerprint
  `2B:44:AB:DF:D2:36:D5:BE:6D:4D:E3:9B:4F:A8:CB:42:F8:2D:AB:48:61:A4:8E:A7:08:0D:D8:DA:BA:54:00:FD`.
- **`pve` and `pve-tiny` both pin that fingerprint** on storage `pbs-iscsi`
  (`pve`: datastore `iscsi-backup`, server `192.168.1.12`; `pve-tiny`: same plus
  `namespace pve-tiny`). Changing the cert breaks every backup from both nodes
  until the pin is changed. Backup schedules: `pve` 11:00, `pve-tiny` 12:30
  (node-local time).
- A step-ca cert changes fingerprint at **every renewal**. So the design removes
  the pin and lets both nodes validate via the homelab CA (both already carry
  `/usr/local/share/ca-certificates/homelab-root.crt`) — renewals then need no
  change on the clients. Fallback if CA validation fails: pin the new
  fingerprint and **disable** the renewal timer.
- PBS clients seen in `/var/log/proxmox-backup/api/access.log` (all rotations):
  `192.168.1.2` (pve), `192.168.1.250` (pve-tiny), `192.168.70.11` (GVM
  scanner), `192.168.1.4` (NPM). The only sync job is local (`usb-backup`), no
  remote fingerprints involved. Nothing else was seen — still re-check in P1.
- CT 105 has no `step` CLI and is hand-built (never Ansible-managed).

**T-Pot** (Raspberry Pi 5, aarch64, Debian 13, `192.168.1.28`, ssh alias `tpot`,
user `steve`, passwordless sudo)
- Web UI = nginx container on `:64297`, self-signed cert (`~/tpotce/data/nginx/cert/nginx.{crt,key}`,
  bind-mounted read-only from the host), `auth_basic "closed site"` (the browser
  popup the operator dislikes) in `/etc/nginx/conf.d/tpotweb.conf` lines 91-92
  and 102-103. nginx runs as container root and reads the host files.
- `tpot.service` runs `compose down -v` then `up` on every start and the Pi
  reboots itself daily at 04:09 Europe/London — so containers are recreated daily;
  only host-side files / compose edits persist. Local drift is documented in
  `docs/tpot-honeypot/local-changes.md`.
- Firewall facts: iptables-nft; `INPUT` policy ACCEPT with T-Pot's honeypot
  allow-list ending in an NFQUEUE catch-all; `DOCKER-USER` exists and is empty;
  **no rule persistence installed**. Published IPv4 ports are DNAT'd (so they
  traverse `FORWARD` → `DOCKER-USER`).
- **IPv6 caveat (important):** the Pi has a global IPv6 address
  (`2404:440c:234f:f00:…`) and Docker publishes `:64297` on `[::]` via the
  userland `docker-proxy`, i.e. through the `INPUT` chain, not `DOCKER-USER`.
  Today that port is reachable over IPv6 behind basic auth. Once basic auth is
  removed the UI would be open on IPv6 unless `ip6tables` drops it — the
  playbook does that. Separately, check the MikroTik IPv6 forward policy (open
  question 1).
- Traefik reaches the Pi over IPv4 only; Authentik gates the route.

**Decisions made (operator, 2026-10-23)**
- PBS: no Authentik in front (PBS's own login form; Bitwarden works), like Omada.
  Backup clients keep using `192.168.1.12:8007` directly; only the browser UI
  uses the new name.
- T-Pot: Authentik forwardAuth + drop T-Pot's `auth_basic` + host firewall
  limiting `:64297` to Traefik (and a boot-ordering guarantee).

## 2. Target state

```
browser ─https─> Traefik (192.168.30.10, Let's Encrypt cert)
   tpot.lab…  ─ Authentik forwardAuth ─https (step-ca cert, verified)─> 192.168.1.28:64297 (nginx, no auth_basic)
   pbs.lab…                           ─https (step-ca cert, verified)─> 192.168.1.12:8007  (PBS login)
pve / pve-tiny ─https (CA-validated, no pin)─> 192.168.1.12:8007   (unchanged path)
```

Certificates are issued by step-ca with the 90-day maximum (`--not-after 2160h`)
and renewed by a daily systemd timer when <15 days remain (03:20 T-Pot, 03:40
PBS).

## 3. Part 1 — T-Pot

Files already in the branch: `ansible/00-initial-setup/tpot-web-behind-traefik.yml`
(tags `tls` → `firewall` → `noauth`; `noauth` refuses to run unless both
firewall rules are active). Order of work: **tls → publish route → firewall →
noauth → reboot soak.**

### T1 — read-only preflight (no approval)

```bash
cd /home/steve/git/proxmox-homelab && git branch --show-current
ssh tpot 'uname -m; systemctl is-active tpot.service; docker ps --format "{{.Names}} {{.Status}}" | grep -c healthy; sudo iptables -S DOCKER-USER; df -h / | tail -1'
ssh tpot 'curl -sk -o /dev/null -w "step-ca: %{http_code}\n" --max-time 6 https://192.168.20.11/health; curl -sI --max-time 8 https://github.com | head -1'
curl -sk -o /dev/null -w 'ui (basic auth expected 401): %{http_code}\n' --max-time 8 https://192.168.1.28:64297/
```

Expect: `aarch64`, `active`, a healthy-container count, an empty `DOCKER-USER`
chain (`-N DOCKER-USER`), step-ca `200`, a GitHub `HTTP/2 200`-ish line (the Pi
downloads the step CLI), and UI `401`. Stop if any differ (e.g. the Pi cannot
reach step-ca or GitHub). Also confirm the operator is **not** mid-way through a
honeypot test (memory: tripwire re-tests from the Kali VM).

### T2 — certificate (production, Pi; nginx reload only, no restart)

Preflight Summary to give: target the Pi (`192.168.1.28`); mutating; installs the
step CLI (arm64), the homelab root CA, issues a 90-day cert (SANs
`tpot.lab.gibbsgreatly.xyz`, `192.168.1.28`, `tpot.gibbsgreatly.xyz`), keeps the
stock cert as `nginx.{crt,key}.selfsigned`, installs the chain+key where nginx
reads them, `nginx -s reload`, adds the renewal timer. Out of scope: firewall,
auth, compose, any other container. Rollback: copy the `.selfsigned` files back,
`docker exec nginx nginx -s reload`.

```bash
cd /home/steve/git/proxmox-homelab
export TASK_APPROVAL=tpot-tls
ANSIBLE_CONFIG=$PWD/terraform/lxc/ansible/ansible.cfg ./with-secrets-prod ansible-playbook \
  -i ansible/inventory/inventory.yml ansible/00-initial-setup/tpot-web-behind-traefik.yml --tags tls
```

Verify (read-only):

```bash
echo | openssl s_client -connect 192.168.1.28:64297 2>/dev/null | openssl x509 -noout -issuer -ext subjectAltName
curl --cacert certs/homelab-root.crt -o /dev/null -w '%{http_code}\n' https://192.168.1.28:64297/   # 401 (auth still on) = TLS verifies
ssh tpot 'systemctl list-timers tpot-tls-renew.timer --no-pager | head -3'
```

Expect issuer `Homelab CA Intermediate CA`, the three SANs, `401` with **no** TLS
error, and the timer scheduled. NPM's old route must still work (NPM does not
verify the backend cert).

### T3 — add the edge manifest (repo edit, no production)

Create `terraform/lxc/stacks/tpot-honeypot/stack.yaml`:

```yaml
hostname: tpot
ip_address: "192.168.1.28"
dns_server: "192.168.1.1"
```

and `terraform/lxc/stacks/tpot-honeypot/edge.yaml`:

```yaml
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: tpot-honeypot-edge
  stack: tpot-honeypot
spec:
  routes:
    - name: tpot
      host: tpot.${LAB_DOMAIN}
      backend:
        type: url
        url: https://192.168.1.28:64297
      dns:
        enabled: true
        target: ${LAB_IP_PROXY}
        ttl: 5m
      tls:
        resolver: letsencrypt
      auth:
        # T-Pot's own nginx basic auth is removed (Part 1, noauth); Authentik
        # forwardAuth gates the whole UI and the host firewall limits :64297
        # to Traefik.
        mode: forwardAuth
```

Gate (tested: passes, 25 manifests, no name collisions):

```bash
LAB_DOMAIN=lab.gibbsgreatly.xyz LAB_IP_PROXY=192.168.30.10 python3 terraform/lxc/validate-edge-manifests.py
```

Commit. (Rendered result, for reference: router `tpot` with
`middlewares: [authentik]`, service `tpot-backend` → `https://192.168.1.28:64297`.)

### T4 — publish the route (production: Authentik app + Traefik + DNS)

Three approvals (or one if the operator prefers; each is a distinct mutation).
**Do this before the firewall** so the new route can be verified while basic
auth still exists.

(a) Authentik proxy provider + application, and the rendered Traefik file —
Preflight: Authentik (`authentik-stack`) gets one Proxy Provider + Application
for `tpot.lab…` (pentagi/greenbone precedent); the rendered route is written to
`/tmp/tpot-edge/`. Command:

```bash
export TASK_APPROVAL=tpot-edge-authentik
./with-secrets-prod python3 terraform/lxc/reconcile-edge.py \
  --authentik-url https://authentik-int.lab.gibbsgreatly.xyz:9443 --no-verify-tls --json --apply \
  --traefik-output-dir /tmp/tpot-edge terraform/lxc/stacks/tpot-honeypot/edge.yaml
ls /tmp/tpot-edge     # expect exactly tpot-honeypot.yml
```

(b) Push only that file to Traefik (no `--check`):

```bash
export TASK_APPROVAL=tpot-traefik-route
ANSIBLE_CONFIG=$PWD/terraform/lxc/ansible/ansible.cfg ./with-secrets-prod ansible-playbook \
  -i terraform/lxc/environments/pve/proxy-stack/inventory.yml -u root \
  terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml -e traefik_generated_source_dir=/tmp/tpot-edge
```

(c) DNS: `export TASK_APPROVAL=tpot-dns-record` then
`./with-secrets-prod scripts/provision.sh --stack technitium-stack`. Before this,
`git diff origin/stable -- 'terraform/lxc/stacks/*/edge.yaml'` must show only the
new manifest(s) from this branch.

Verify: `dig +short tpot.lab.gibbsgreatly.xyz @192.168.20.15` → `192.168.30.10`;
`curl -s -o /dev/null -w '%{http_code}\n' https://tpot.lab.gibbsgreatly.xyz/`
→ `302` (redirect to Authentik, proves forwardAuth); in a browser: Authentik
login, then **T-Pot's own basic-auth popup** (expected until T6 — the
Authentik→Traefik→TLS-verified-backend path is proven). If you get `502`, the
backend cert verification failed: re-check T2.

### T5 — host firewall (production, Pi)

Preflight: adds an iptables `DOCKER-USER` DROP for tcp/64297 on the physical NIC
from anything but the Traefik IP, an `ip6tables` `INPUT` DROP for tcp/64297, a
boot unit `tpot-ui-firewall.service` (After/PartOf docker), and a drop-in
`tpot.service.d/10-ui-firewall.conf` so T-Pot **cannot start nginx before the
firewall is active** (`Requires=` → fail closed: if the script fails, T-Pot does
not start). Effects: from this moment only Traefik can reach the UI, so the old
NPM route `tpotce.gibbsgreatly.xyz` **stops working** (expected). GVM scans of
the UI port will also now be blocked. Rollback commands are below.

```bash
export TASK_APPROVAL=tpot-firewall
ANSIBLE_CONFIG=$PWD/terraform/lxc/ansible/ansible.cfg ./with-secrets-prod ansible-playbook \
  -i ansible/inventory/inventory.yml ansible/00-initial-setup/tpot-web-behind-traefik.yml --tags firewall
```

Verify:

```bash
ssh tpot 'sudo iptables -S DOCKER-USER; sudo ip6tables -S INPUT | head -3; systemctl is-active tpot-ui-firewall; systemctl show tpot.service -p Requires -p After | tr " " "\n" | grep -c tpot-ui-firewall'
curl -sk -o /dev/null -w 'direct v4 (expect 000 = dropped): %{http_code}\n' --max-time 6 https://192.168.1.28:64297/
curl -6 -sk -o /dev/null -w 'direct v6 (expect 000): %{http_code}\n' --max-time 6 "https://[2404:440c:234f:f00:5a20:150b:99e0:cbc5]:64297/"
curl -s -o /dev/null -w 'via traefik (expect 302): %{http_code}\n' https://tpot.lab.gibbsgreatly.xyz/
```

If the **Traefik route breaks** (e.g. MikroTik source-NATs `edge_seg`→LAN so the
source isn't `192.168.30.10`), remove the rule immediately and stop:

```bash
ssh tpot 'sudo iptables -D DOCKER-USER 1; sudo ip6tables -D INPUT 1'    # then investigate the source address
```

(The `systemctl disable --now tpot-ui-firewall` + deleting the drop-in
`/etc/systemd/system/tpot.service.d/10-ui-firewall.conf` + `daemon-reload`
fully reverts the boot behaviour.)

### T6 — remove basic auth (production, Pi; recreates only the `nginx` container)

Preflight: builds `~/tpotce/local/nginx/tpotweb.conf` from the running image's
copy with every `auth_basic*` line removed (verified: exactly 4 lines, braces
balanced), adds one bind-mount line to the nginx service in
`~/tpotce/docker-compose.yml` (a timestamped backup is kept), and runs
`docker compose up -d --no-deps nginx`. The play **refuses to run** unless both
firewall rules exist. Brief UI blip; honeypot sensors untouched. Rollback:
restore the compose backup (`docker-compose.yml.<timestamp>~`) and
`docker compose up -d --no-deps nginx`.

```bash
export TASK_APPROVAL=tpot-noauth
ANSIBLE_CONFIG=$PWD/terraform/lxc/ansible/ansible.cfg ./with-secrets-prod ansible-playbook \
  -i ansible/inventory/inventory.yml ansible/00-initial-setup/tpot-web-behind-traefik.yml --tags noauth
```

Verify: in a browser, `https://tpot.lab.gibbsgreatly.xyz` → Authentik login → the
T-Pot landing page with **no** popup; open Kibana, CyberChef and elasticvue
(WebSocket-backed pages). `ssh tpot 'docker ps --format "{{.Names}} {{.Status}}" | grep -c -i unhealthy'`
→ `0`. Direct access from the workstation is still dropped (`000`).

### T7 — reboot soak (next day)

T-Pot reboots at 04:09 Europe/London (~15:09/16:09 NZ). After it:

```bash
ssh tpot 'uptime -s; systemctl is-active tpot-ui-firewall tpot.service; sudo iptables -S DOCKER-USER | head -3; sudo ip6tables -S INPUT | head -2'
curl -s -o /dev/null -w '%{http_code}\n' https://tpot.lab.gibbsgreatly.xyz/   # 302
```

All must hold **after** a fresh boot — the UI has no basic auth, so a missing
firewall rule is an exposure. Don't call Part 1 done until this passes.

### T8 — docs

Add a dated section to `docs/tpot-honeypot/local-changes.md`: the step-ca cert in
`data/nginx/cert/` (+ `.selfsigned` backups, renewal timer), the bind-mounted
`local/nginx/tpotweb.conf` (no `auth_basic`) and the compose line that mounts it,
the firewall script/unit/drop-in, and **what to re-apply after a T-Pot
`update.sh`** (it may reset `docker-compose.yml` and/or the cert dir — re-run the
playbook tags `tls` then `noauth`; the firewall unit survives). Update the T-Pot
README's access section. Commit.

## 4. Part 2 — PBS

Files already in the branch: `terraform/lxc/ansible/playbooks/deploy-pbs-tls.yml`
(prepare-only by default), `terraform/lxc/stacks/proxmox-backup-server/{stack.yaml,inventory.yml}`.
Order of work: **preflight → prepare → swap (one sequence) → verify backups →
publish route → renewal check.**

### P1 — read-only preflight and window check (no approval)

```bash
for n in pve pve-tiny; do echo "== $n"; ssh root@$n.gibbsgreatly.xyz 'date; pvesm status | grep pbs; grep -A8 "^pbs:" /etc/pve/storage.cfg | sed "s/fingerprint .*/fingerprint <pinned>/"; ps aux | grep -c "[v]zdump"; ls /etc/ssl/certs | grep -i -c homelab'; done
ssh root@192.168.1.12 'proxmox-backup-manager task list --limit 15 2>/dev/null | head -8 | cut -c1-140; (zcat -f /var/log/proxmox-backup/api/access.log* 2>/dev/null) | awk "{print \$1}" | grep -oE "[0-9]+(\.[0-9]+){3}" | sort | uniq -c | sort -rn | head -6'
ssh root@192.168.1.12 'curl -sk -o /dev/null -w "step-ca: %{http_code}\n" --max-time 6 https://192.168.20.11/health; curl -sI --max-time 8 https://github.com | head -1; ls /usr/local/bin/step 2>&1 | head -1'
```

Expect on both nodes: `pbs-iscsi active`, a pinned fingerprint, **0** running
`vzdump`, and `1` for the last number (the `homelab-root.pem` entry in
`/etc/ssl/certs`; verified 2026-10-23 on both nodes, and
`openssl verify -CApath /etc/ssl/certs /usr/local/share/ca-certificates/homelab-root.crt`
prints `OK`). **If it is `0` on either node, stop**: CA validation will not work
and the fallback (pin the new fingerprint, disable the renewal timer) applies. Client IPs should be `192.168.1.2`, `192.168.1.250`,
`192.168.70.11`, `192.168.1.4` only; any other address is a client that may pin
the old fingerprint — find it before continuing. Record the schedule windows
(`pve` 11:00, `pve-tiny` 12:30, node-local time) and **pick a time with no
backup, verify or GC task running** (GC runs 03:00 on PBS; `verify-new true`).

### P2 — prepare the certificate (production, CT 105; no live change)

Preflight: target CT 105 (`192.168.1.12`); mutating but **non-disruptive** —
installs the step CLI (amd64) and the homelab root CA, issues the new cert into
`/root/pbs-tls/` (SANs `pbs.lab.gibbsgreatly.xyz`, `192.168.1.12`,
`proxmox-backup.gibbsgreatly.xyz`, `proxmox-backup-server`), prints its
fingerprint. It does **not** touch `/etc/proxmox-backup/proxy.*` or restart
anything. Out of scope: the swap, the clients, Traefik.

```bash
export TASK_APPROVAL=pbs-tls-prepare
ANSIBLE_CONFIG=$PWD/terraform/lxc/ansible/ansible.cfg ./with-secrets-prod ansible-playbook \
  -i terraform/lxc/stacks/proxmox-backup-server/inventory.yml \
  terraform/lxc/ansible/playbooks/deploy-pbs-tls.yml
ssh root@192.168.1.12 'openssl x509 -in /root/pbs-tls/leaf.crt -noout -subject -issuer -ext subjectAltName -dates'
```

(Root SSH to CT 105 with the lab key worked on 2026-10-23.) Gate: issuer
`Homelab CA Intermediate CA`, the four SANs, 90-day validity.

### P3 — the swap (production; the one disruptive step)

Do this only in a verified backup-free window (P1). Preflight Summary: target CT 105
and the `pve` + `pve-tiny` storage configs; mutating; it (1) replaces
`/etc/proxmox-backup/proxy.{pem,key}` (stock files kept as `*.selfsigned`) and
restarts `proxmox-backup-proxy` (seconds), then (2) on **each node** removes the
pinned fingerprint from `pbs-iscsi` so both validate via the homelab CA
(`pve`'s `server 192.168.1.12` matches the IP SAN). During the gap between (1)
and (2) backups from that node would fail — keep them seconds apart. Also
installs the renewal script + daily timer on the CT. Rollback below.

```bash
export TASK_APPROVAL=pbs-tls-swap
ANSIBLE_CONFIG=$PWD/terraform/lxc/ansible/ansible.cfg ./with-secrets-prod ansible-playbook \
  -i terraform/lxc/stacks/proxmox-backup-server/inventory.yml -e pbs_tls_install=true \
  terraform/lxc/ansible/playbooks/deploy-pbs-tls.yml \
&& for n in pve pve-tiny; do
     echo "== $n"; ssh root@$n.gibbsgreatly.xyz 'pvesm set pbs-iscsi --delete fingerprint && sleep 3 && pvesm status | grep pbs'
   done
```

Each node must print `pbs-iscsi … active`. Use `-e pbs_tls_install=true` **only**
for this run. If a node shows `inactive`/TLS errors after removing the pin:
CA validation is not working there — fall back for that node:

```bash
NEWFP=$(ssh root@192.168.1.12 'openssl x509 -in /etc/proxmox-backup/proxy.pem -noout -fingerprint -sha256' | cut -d= -f2)
ssh root@<node>.gibbsgreatly.xyz "pvesm set pbs-iscsi --fingerprint $NEWFP"
ssh root@192.168.1.12 'systemctl disable --now pbs-tls-renew.timer'     # a renewal would change the fingerprint again
```

and record it (rotation then becomes a manual, scheduled task).

**Full rollback** (restores the original self-signed cert and pins):

```bash
ssh root@192.168.1.12 'cd /etc/proxmox-backup && cp -p proxy.pem.selfsigned proxy.pem && cp -p proxy.key.selfsigned proxy.key && systemctl restart proxmox-backup-proxy && systemctl disable --now pbs-tls-renew.timer'
OLD=2B:44:AB:DF:D2:36:D5:BE:6D:4D:E3:9B:4F:A8:CB:42:F8:2D:AB:48:61:A4:8E:A7:08:0D:D8:DA:BA:54:00:FD
for n in pve pve-tiny; do ssh root@$n.gibbsgreatly.xyz "pvesm set pbs-iscsi --fingerprint $OLD && pvesm status | grep pbs"; done
```

If PBS's proxy fails to start with the new key (PBS reads PEM RSA/EC; `step`
issues an EC P-256 key), use the rollback first, then re-issue with
`--kty RSA --size 2048` (edit the playbook's `step ca certificate` argv).

### P4 — verify backups really work (production, small)

```bash
ssh root@pve.gibbsgreatly.xyz 'vzdump 114 --storage pbs-iscsi --mode snapshot --notes-template "pbs tls test" 2>&1 | tail -4; pvesm list pbs-iscsi --vmid 114 | tail -2'
ssh root@pve-tiny.gibbsgreatly.xyz 'pct list | head; pvesm list pbs-iscsi | tail -3'
```

Pick the smallest CT on `pve-tiny` from the list and run the same
`vzdump <vmid> --storage pbs-iscsi --mode snapshot` there. Both must end `OK`
(the new snapshot appears in `pvesm list`). Then in a few hours confirm the next
**scheduled** job from each node (pve 11:00, pve-tiny 12:30) succeeded
(`pvesh get /cluster/tasks`/PBS UI task log).

### P5 — add the edge manifest and publish (production)

Create `terraform/lxc/stacks/proxmox-backup-server/edge.yaml`:

```yaml
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: proxmox-backup-server-edge
  stack: proxmox-backup-server
spec:
  routes:
    - name: pbs
      host: pbs.${LAB_DOMAIN}
      backend:
        type: url
        url: https://192.168.1.12:8007
      dns:
        enabled: true
        target: ${LAB_IP_PROXY}
        ttl: 5m
      tls:
        resolver: letsencrypt
      auth:
        mode: none
```

Gate: `LAB_DOMAIN=lab.gibbsgreatly.xyz LAB_IP_PROXY=192.168.30.10 python3 terraform/lxc/validate-edge-manifests.py`
(passes). Commit. Then the Omada-proven recipe (auth `none`, no Authentik step):

```bash
rm -rf /tmp/pbs-edge
LAB_DOMAIN=lab.gibbsgreatly.xyz LAB_IP_PROXY=192.168.30.10 python3 terraform/lxc/render-edge-traefik.py \
  --output-dir /tmp/pbs-edge terraform/lxc/stacks/proxmox-backup-server/edge.yaml && cat /tmp/pbs-edge/proxmox-backup-server.yml
export TASK_APPROVAL=pbs-traefik-route
ANSIBLE_CONFIG=$PWD/terraform/lxc/ansible/ansible.cfg ./with-secrets-prod ansible-playbook \
  -i terraform/lxc/environments/pve/proxy-stack/inventory.yml -u root \
  terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml -e traefik_generated_source_dir=/tmp/pbs-edge
curl -s -o /dev/null -w '%{http_code} verify=%{ssl_verify_result}\n' --resolve pbs.lab.gibbsgreatly.xyz:443:192.168.30.10 https://pbs.lab.gibbsgreatly.xyz/
export TASK_APPROVAL=pbs-dns-record
./with-secrets-prod scripts/provision.sh --stack technitium-stack
dig +short pbs.lab.gibbsgreatly.xyz @192.168.20.15     # 192.168.30.10
```

Expect `200 verify=0` (first request may take a minute while Traefik gets the
Let's Encrypt cert). A `502` = Traefik rejected the PBS cert (recheck P2/P3). Then
in a browser: `https://pbs.lab.gibbsgreatly.xyz` → PBS login (root@pam) → the
dashboard and datastore list load.

### P6 — renewal check (read-only)

```bash
ssh root@192.168.1.12 'systemctl list-timers pbs-tls-renew.timer --no-pager | head -3; /usr/local/sbin/pbs-tls-renew.sh'
```

The script must print `pbs TLS cert valid for >15d, nothing to do` (safe — it
exits before renewing). The first real renewal happens ~75 days out and restarts
`proxmox-backup-proxy`; put a calendar note ~day 70 to confirm it, and confirm
both nodes' `pvesm status` after it (they should be unaffected since the pin is
gone).

### P7 — docs

Update the PBS references in `docs/` (search `proxmox-backup`, `pbs`) with the
new name, the cert/renewal design, the "no fingerprint pin" decision (and the
fallback if it was used), and the rollback files `proxy.{pem,key}.selfsigned`.
Commit.

## 5. Part 3 — retire the old NPM routes (after a soak)

Do **not** start until: ≥7 days since the swap and the T-Pot reboot soak (T7),
at least one successful scheduled backup from each PVE node after P3, and NPM's
logs show no real client on hosts 22/23:

```bash
ssh root@192.168.1.4 'cd /srv/npm/data/logs; for id in 22 23; do echo "host $id:"; grep -o "\[Client [0-9.]*\]" proxy-host-${id}_access.log | sort | uniq -c | sort -rn | head -3; tail -1 proxy-host-${id}_access.log | cut -c1-60; done'
```

(Expected: only the Greenbone scanner `192.168.70.11` and the operator
workstation `192.168.1.104`.) Then, with the operator:
1. NPM admin UI (`:81`): delete proxy hosts 22 (pbs) and 23 (tpotce). Optionally
   the dead ones too: 9-13 (radarr/sonarr/prowlarr/lidarr/qbittorrent — no
   traffic since 13 Sep) and 30 (teapot — none since 1 Oct). Operator's call.
2. MikroTik static DNS: remove `pbs.gibbsgreatly.xyz` and `tpotce.gibbsgreatly.xyz`
   (and any other names that no longer have a live backend — the repo's
   `router/config/current-config.json` snapshot lists 31 records pointing at
   `192.168.1.4`). Keep a copy of the removed entries. RouterOS safe-mode caveat
   applies (memory: re-verify after a disconnect).
3. Update `router/config/current-config.json` if that snapshot is refreshed by
   a script, update `docs/tpot-honeypot/` hostnames, and the Omada/NPM notes.
4. NPM itself (and management-stack) stays until its other users are gone — the
   remaining one is `jellyfin.gibbsgreatly.xyz` (one real client:
   `192.168.1.105`, a Windows PC, playing from the legacy Jellyfin on
   `192.168.1.6`). That is a separate move to the media-stack-lab Jellyfin.

## 5a. Part 4 — enrol PBS (CT 105) in lab infra (do last, after Part 2 is verified)

Added 2026-10-23 at the operator's request. **Research only (read-only, 2026-10-23);
nothing applied.** CT 105 is hand-built (never Ansible-managed), Debian 12, 4 vCPU,
4 GiB RAM (~3 GiB free), 70% of a 10 GiB root. Do **not** use the `lxc_base` role
here (it would reconfigure a hand-built CT); include only the roles below.

| Capability | State today | Needed |
|---|---|---|
| Wazuh | `wazuh-agent` 4.14.2 **installed and running but not connected**: it points at a stale manager `192.168.1.14:1514` ("Transport endpoint is not connected") | Re-enrol through the `wazuh_agent` role (pins 4.14.9, group `lan` like Omada, FIM on `/etc/proxmox-backup` config but **not** `*.key`/`authkey*`, and the TLS dir). Decide whether the stale install is removed first. |
| Automatic updates | `unattended-upgrades` installed and active, but `Origins-Pattern` is Debian + Debian-Security only, so **PBS's own packages are never updated** (3.4.8-2 installed, 3.4.9-2 pending, plus pve-labelled zfs libs). **Decision (operator, 2026-10-23): include the Proxmox origin** (nobody logs into this CT, so auto-updates are its only patching). | Add `"origin=Proxmox,codename=${distro_codename},label=Proxmox Backup System Debian Repository";` to the CT's unattended-upgrades origins (via the `unattended_upgrades` role, or a drop-in if the role cannot take extra origins). `apt-daily-upgrade.timer` fires ~06:00-07:00 UTC (19:00-20:00 NZDT), clear of every backup/GC window (GC 03:00 UTC, pve 11:00 UTC, pve-tiny 23:30 UTC); a PBS package upgrade restarts `proxmox-backup-proxy` for a few seconds. Keep `automatic_reboot: false`; watch `/var/run/reboot-required`. |
| Grafana / VictoriaMetrics | no `node_exporter`, nothing on `:9100` | `node_exporter` role (step-ca TLS cert + scrape basic auth, needs `LAB_IP_STEP_CA`, `STEP_CA_PROVISIONER_PASSWORD`, `NODE_EXPORTER_SCRAPE_PASSWORD*`), then add `192.168.1.12:9100` to the scrape list in `deploy-monitoring-stack.yml` and redeploy `monitoring-stack`. Optional later: PBS's own metric-server push (datastore usage). |
| Graylog | `rsyslog` not installed; journald only | `rsyslog_forward` role (target `LAB_IP_GRAYLOG:514`; `rsyslog_forward_disable_imklog: true` as for any LXC). PBS task/API logs under `/var/log/proxmox-backup/` are files, so add an `imfile` input if wanted (operator decision). |
| GVM | The scanner already reaches the PBS UI (it was in NPM's logs) | Check whether `192.168.1.12` is in `EXTRA_HOSTS`/the VLAN scan scope (`docs/gvm-coverage-cleanup/`); add a credentialed-scan account only if wanted. |

Steps (each is a separate production approval; none restarts a PBS service):
1. Write `terraform/lxc/ansible/playbooks/deploy-pbs-enrolment.yml` (hosts: the existing
   `proxmox-backup-server/inventory.yml`, roles: `wazuh_agent`, `node_exporter`,
   `rsyslog_forward`, `unattended_upgrades`, each tagged so they run separately).
   Syntax-check; commit. Model it on the Omada playbook (commit `585ced50` on
   `work/omada-controller-adoption`).
2. Wazuh first (lowest risk, fixes the already-broken agent), verify the agent is
   `Active` in the manager with group `lan`.
3. `unattended_upgrades` (after the origins decision), then `rsyslog_forward`
   (verify lines arrive in Graylog), then `node_exporter` + the monitoring scrape edit
   (verify the target is `up` in Grafana/VictoriaMetrics).
4. Run in the daily backup-free time (agents do not touch the PBS services, but keep
   clear of the 03:00 UTC GC and the `pve` 11:00 UTC / `pve-tiny` 12:30 NZDT jobs).
5. Docs: update `docs/lxc-scan-and-monitoring-rollout/README.md` ("known gaps" list
   still names `proxmox-backup-server`) and record it in the P7 doc update.

## 6. Open questions / flagged risks

1. **T-Pot IPv6 exposure (independent of this plan):** the Pi has a global IPv6
   address and `:64297` is published on `[::]` today (behind basic auth). Ask the
   operator to confirm the MikroTik IPv6 forward policy drops unsolicited inbound
   to LAN hosts. The playbook's `ip6tables` rule closes it on the host
   regardless, but other T-Pot ports have no such rule by design (it's a LAN
   tripwire).
2. **Who may open the T-Pot UI?** Authentik forwardAuth defaults per the existing
   pentagi/greenbone pattern; confirm in the Authentik UI that the new
   application is bound to the operator's group only, not "all users".
3. **T-Pot `update.sh`** can overwrite `docker-compose.yml` and the cert dir:
   re-apply per T8. The firewall unit and drop-in survive it.
4. **`tpot.service` now `Requires=` the firewall unit** (fail closed). If the
   firewall script ever fails, T-Pot (the honeypot) won't start — watch for that
   in Grafana/Wazuh after the first reboots.
5. **PBS fingerprint pin removal** is the single highest-impact change here:
   both nodes' backups depend on CA validation working. P1's trust-store check
   and P4's test backups are the gates; the rollback block is tested only as
   text — read it before P3.
6. **GVM**: the Greenbone scanner currently scans `192.168.1.4` (NPM) and hits
   the PBS/T-Pot vhosts; after Part 1's firewall it can no longer reach the T-Pot
   UI port. That reduces scan coverage of that one port; accept or add the
   scanner IP to the allow-list (it is a deliberate choice).
7. **Memory/notes to update** at the end: add a project note for this work and
   keep `reference_traefik_no_insecure_backend_tls` current (step-ca-issued
   backend certs are supported; self-signed need a plain-HTTP path).
8. `deploy-pbs-tls.yml` and the T-Pot playbook were **not** run anywhere,
   including check mode (the step CLI download, `step ca certificate` and the
   systemd/iptables tasks cannot be exercised without changing the hosts).
   Expect to fix small issues on first real run and say so in the hand-back.

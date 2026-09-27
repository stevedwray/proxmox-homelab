# secrets-refactor plan: move secret values from Git-tracked SOPS to OpenBao

Written with `.github/prompts/plan-change.prompt.md`, following
`docs/agent-design/step-packet-schema.md`. Execute one step at a time with
`.github/prompts/implement-step.prompt.md`, and write each hand-back into
[README.md](README.md)'s hand-back log.

The design, and every decision behind this plan, is in
[secrets-design.md](secrets-design.md). Read it first. This plan does not
re-argue it.

## As executed (2026-09-28) -- read this first

**Status: complete except plan step 15's live CI test, which waits on a
`stable` → `main` promotion.** The full record, with every gate result, is
the hand-back log in [README.md](README.md). Day-to-day operation is in
`docs/reference/secrets-management.md`.

Execution was done by Claude directly, not a local model: steps 01–16 were
applied from the patches and gated. Production runs were done by the
operator, because the harness classifier blocks them for Claude.

| Part | Result |
| --- | --- |
| Steps 01–12 | Applied and gated. The step 12 dry-run passed once the OIDC-secret prerequisite existed |
| Block A | Done. Deviations below |
| Block B | Done, plus the breakglass AppRole (below) |
| Block C | Covered by the B3 boundary check |
| Block D | D1 reconcile (9/9 live logins), D2 import (30 entries / 129 fields), D3 parity (every field, 5 profiles), then steps 13–14 (freeze, default openbao). Post-cutover deploys were validated |
| Step 15 | Applied on `task/retire-sops`; live only after `main` is promoted |
| Step 16 | Applied |
| Block E | Recovery test PASSED (`scripts/openbao-recovery-test.sh`) |
| Block F | SOPS code paths removed (Claude); SOPS data files deleted (operator); tested with a live battery plus a 28-stack `--check` sweep |
| Added | Secrets inventory on the dashboard (`metrics` AppRole, metadata only) |

**Deviations from the plan as written** (all fixed in the repo):

1. **A3:** `terragrunt apply` was missing before the first `provision.sh`
   (the inventory is written by the apply). The plan text is fixed.
2. **A8:** the kit pipeline lacked `pipefail`, so mismatched passphrases
   produced an empty `kit.age`. The verify step caught it; the retry script
   encrypts to a tmp file and verifies before copying.
3. **B1:** OpenBao 2.x rejects API-created audit devices, so the audit
   device is declared in `openbao.hcl` (deploy playbook) and
   `configure-openbao.yml` only asserts it exists.
4. **B4:** OpenBao ≥ 2.5.3 disables unauthenticated generate-root, so the
   design §19 break-glass could not work. Added the `breakglass` AppRole
   (generate-root-token only) and its credentials in the kit.
   `bao operator generate-root -decode` also needs a token, so the drills
   decode locally.
5. **A9/B4:** the edge reconciler created the OIDC provider with
   `grant_types: []`, which rejects every login. Patch 06 missed the 4th
   per-stack table, `_oidc_grant_types`; it is now fixed.
6. **Step 13:** the freeze hook also ran at pre-push and blocked the
   legitimate pre-freeze commit, so it is now `stages: [pre-commit]`.
   `validate.yml` runs PR checks only for PRs into `main`, so `sops-freeze`
   first runs on the promotion PR.
7. **Step 14's gate** used a regex `grep` that `${...}` breaks; it is now
   `grep -F`.
8. **Monitoring:** step 07's scrape target and dashboard needed a
   `monitoring-stack` deploy, which the plan omitted. It has been done.
9. **Block F** reached further than planned: the router scripts, agent and
   Copilot instructions, `.env` `SOPS_AGE_KEY_FILE`, and the
   `with-secrets-prod*` headers.

**Still open:**

- promotion to `main`, then the `netbox-populate` OIDC run and deletion of
  the `SOPS_AGE_KEY` GitHub secret;
- the recommended follow-ups (alerting, rotating secrets whose old values
  sit in Git history), listed in [README.md](README.md#next-steps).

Done since: the `task/retire-sops` PR into `stable` (PR __PR__), the
`artifacts/` close-out, the reconciler `grant_types` default on create,
and the tidy-ups.

The steps below are the original plan, kept for the record.

## How the steps work

Every code change is a pre-built patch in [patches/](patches/). Each patch
was generated and checked on 2026-09-28: all sixteen apply cleanly, in
order, on top of commit `d41be395`. The Python tools have unit tests that
pass. The playbooks pass `ansible-playbook --syntax-check` and
`ansible-lint`. The shell passes `shellcheck -S warning`. The step blocks
therefore contain no content to type in. A step is:

```bash
git apply --check docs/secrets-refactor/patches/<id>.patch && git apply docs/secrets-refactor/patches/<id>.patch
```

followed by the step's gates. If `git apply --check` fails, the file changed
since the patch was generated. **Stop and report it. Do not hand-merge.** The
patch will be regenerated.

Plain-prose sections headed **Operator:** are for the operator only. They
are never step blocks. They include every production mutation, all of which
go through `./with-secrets-prod` with `TASK_APPROVAL`, per CLAUDE.md's
production approval flow.

If `ansible-playbook` or `ansible-lint` fails with "Ansible requires
blocking IO on stdin/stdout/stderr", re-run the same command wrapped as
`script -qec "<command>" /dev/null`. That is a terminal quirk, not a gate
failure.

## Branch

Execute on `feat/secrets-openbao`, cut from `task/secrets-refactor-design`.

## Order

| Phase | Steps | What it achieves | Production effect |
| --- | --- | --- | --- |
| A — build OpenBao | 01–07, operator block A | LXC, TLS, seal, snapshots, UI route, dashboard | New LXC; Traefik restart; new DNS record |
| B — configure OpenBao | 08, operator block B | KV, audit, policies, AppRoles, JWT, OIDC | OpenBao only |
| C — loader and tools | 09–12, operator block C | Wrappers can read OpenBao (SOPS still default) | None |
| D — cutover | operator block D, then 13–15 | Import, parity, freeze SOPS, OpenBao becomes default, CI moves | Secrets source switches |
| E — docs | 16 | CLAUDE.md and the secrets doc describe the new model | None |
| F — verify and retire | operator blocks E–F | Recovery test, then SOPS deletion | SOPS removed |

Steps 01–12 change nothing live. They can all land before any operator block
runs, but operator block A needs 01–07 merged into the branch it deploys
from.

---

## Phase A — build OpenBao

### Operator: prerequisite — add the OpenBao OIDC client secret (last SOPS edit)

The Authentik provider (created by the edge reconciler) and OpenBao's OIDC
config both need `OPENBAO_OIDC_CLIENT_SECRET`, and until the cutover secrets
still live in SOPS. This is the last SOPS write. Do it before step 09's
gates and before operator block A's edge activation.

```bash
openssl rand -hex 32        # copy the output
SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.common.enc.yaml
# add a top-level line:  OPENBAO_OIDC_CLIENT_SECRET: <the value>
git add terraform/secrets.common.enc.yaml && git commit -m "chore(secrets): add OPENBAO_OIDC_CLIENT_SECRET"
```

### secrets-01-env-vars

```yaml
id: secrets-01-env-vars
title: Add LAB_IP_OPENBAO and LAB_FQDN_OPENBAO to the shared env files
depends_on: []

change: >
  Run `git apply --check docs/secrets-refactor/patches/secrets-01-env-vars.patch`,
  then `git apply` the same file. It adds LAB_FQDN_OPENBAO (after
  LAB_FQDN_AUTHENTIK_INTERNAL) and LAB_IP_OPENBAO='192.168.20.16' (after
  LAB_IP_CSE_PANEL) to .env, and the same two lines to .env.template. Make no
  other edits.

scope:
  allowed_paths:
    - .env
    - .env.template
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any provision.sh, terragrunt or ansible-playbook run"

gates:
  - id: applied
    cmd: "git apply --reverse --check docs/secrets-refactor/patches/secrets-01-env-vars.patch && echo applied"
    expect: "prints applied"
    critical: true
  - id: values
    cmd: "bash -c 'set -a; . ./.env; echo \"$LAB_IP_OPENBAO $LAB_FQDN_OPENBAO\"'"
    expect: "prints 192.168.20.16 openbao.lab.gibbsgreatly.xyz"
    critical: true
```

### secrets-02-stack-files

```yaml
id: secrets-02-stack-files
title: Create openbao-stack (stack.yaml, terragrunt.hcl, STACK_CONTRACT.md, policies)
depends_on: [secrets-01-env-vars]

change: >
  Run `git apply --check docs/secrets-refactor/patches/secrets-02-stack-files.patch`,
  then `git apply` the same file. It creates terraform/lxc/stacks/openbao-stack/
  with stack.yaml (mgmt_seg, 192.168.20.16, VMID 20016, playbook deploy-openbao),
  terragrunt.hcl (identical to step-ca-stack's), STACK_CONTRACT.md, and
  policies/{openbao-admin,deploy-common,snapshot,ci-netbox-populate}.hcl.
  Make no other edits.

scope:
  allowed_paths:
    - terraform/lxc/stacks/openbao-stack/
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "terragrunt apply, or any provision.sh run"

gates:
  - id: applied
    cmd: "git apply --reverse --check docs/secrets-refactor/patches/secrets-02-stack-files.patch && echo applied"
    expect: "prints applied"
    critical: true
  - id: yaml
    cmd: "python3 -c \"import yaml; d=yaml.safe_load(open('terraform/lxc/stacks/openbao-stack/stack.yaml')); print(d['vmid'], d['ip_address'], d['network']['zone'])\""
    expect: "prints 20016 192.168.20.16/24 mgmt_seg"
    critical: true
  - id: plan-create-only
    cmd: "./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/openbao-stack -no-color 2>&1 | grep -E '^Plan:'"
    expect: "a Plan: line ending in '0 to change, 0 to destroy.'"
    critical: true
```

### secrets-03-snapshot-tool

```yaml
id: secrets-03-snapshot-tool
title: Add the Raft snapshot + retention script and its unit tests
depends_on: []

change: >
  Run `git apply --check docs/secrets-refactor/patches/secrets-03-snapshot-tool.patch`,
  then `git apply` the same file. It creates
  terraform/lxc/ansible/files/openbao/openbao_snapshot.py (snapshot to
  /srv/openbao-snapshots, prune per design doc 27.0.1, textfile metrics) and
  terraform/lxc/ansible/files/openbao/test_openbao_snapshot.py. Make no other edits.

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/openbao/
  forbidden_actions:
    - "Any change outside allowed_paths"

gates:
  - id: applied
    cmd: "git apply --reverse --check docs/secrets-refactor/patches/secrets-03-snapshot-tool.patch && echo applied"
    expect: "prints applied"
    critical: true
  - id: unit-tests
    cmd: "python3 terraform/lxc/ansible/files/openbao/test_openbao_snapshot.py"
    expect: "Ran 7 tests ... OK"
    critical: true
```

### secrets-04-deploy-playbook

```yaml
id: secrets-04-deploy-playbook
title: Add deploy-openbao.yml (native .deb, step-ca TLS, static seal, snapshot timer)
depends_on: [secrets-03-snapshot-tool]

change: >
  Run `git apply --check docs/secrets-refactor/patches/secrets-04-deploy-playbook.patch`,
  then `git apply` the same file. It creates
  terraform/lxc/ansible/playbooks/deploy-openbao.yml. Make no other edits.

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-openbao.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running the playbook against any host"

gates:
  - id: applied
    cmd: "git apply --reverse --check docs/secrets-refactor/patches/secrets-04-deploy-playbook.patch && echo applied"
    expect: "prints applied"
    critical: true
  - id: syntax-check
    cmd: "cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/deploy-openbao.yml"
    expect: "exit 0, prints playbook: playbooks/deploy-openbao.yml"
    critical: true
  - id: pinned-deb
    cmd: "grep -c '7412233fef6bbe0e5093aa5461f493dd3a0f6193c8d5a5ba3a7ff475f96f34a2' terraform/lxc/ansible/playbooks/deploy-openbao.yml"
    expect: "prints 1"
    critical: true
```

### secrets-05-traefik-rootcas

```yaml
id: secrets-05-traefik-rootcas
title: Let Traefik verify HTTPS backends against the homelab root CA
depends_on: []

change: >
  Run `git apply --check docs/secrets-refactor/patches/secrets-05-traefik-rootcas.patch`,
  then `git apply` the same file. It adds a static `serversTransport.rootCAs:
  [/certs/combined-ca.crt]` block (the bundle the playbook already builds and
  mounts) to Traefik's static config in deploy-proxy-stack.yml. Make no other edits.

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running provision.sh or the playbook (Traefik redeploy is operator block A)"

gates:
  - id: applied
    cmd: "git apply --reverse --check docs/secrets-refactor/patches/secrets-05-traefik-rootcas.patch && echo applied"
    expect: "prints applied"
    critical: true
  - id: syntax-check
    cmd: "cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/deploy-proxy-stack.yml"
    expect: "exit 0"
    critical: true
```

### secrets-06-edge-oidc

```yaml
id: secrets-06-edge-oidc
title: OpenBao UI route (EdgeManifest) + Authentik OIDC redirect entries
depends_on: [secrets-02-stack-files]

change: >
  Run `git apply --check docs/secrets-refactor/patches/secrets-06-edge-oidc.patch`,
  then `git apply` the same file. It creates
  terraform/lxc/stacks/openbao-stack/edge.yaml (route openbao.${LAB_DOMAIN} ->
  https://${LAB_IP_OPENBAO}:8200, auth.mode oidc) and adds an
  ("openbao-stack", "openbao") entry to OIDC_ROUTE_CLIENT_IDS,
  OIDC_ROUTE_CLIENT_SECRETS and _oidc_redirect_uris in
  terraform/lxc/discover-authentik-edge.py. Make no other edits.

scope:
  allowed_paths:
    - terraform/lxc/stacks/openbao-stack/edge.yaml
    - terraform/lxc/discover-authentik-edge.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running reconcile-edge.py or reconcile-authentik-edge.py"

gates:
  - id: applied
    cmd: "git apply --reverse --check docs/secrets-refactor/patches/secrets-06-edge-oidc.patch && echo applied"
    expect: "prints applied"
    critical: true
  - id: edge-tests
    cmd: "python3 -m unittest terraform/lxc/test_discover_authentik_edge.py terraform/lxc/test_reconcile_authentik_edge.py"
    expect: "OK"
    critical: true
  - id: edge-validate
    cmd: "./with-secrets-prod python3 terraform/lxc/validate-edge-manifests.py terraform/lxc/stacks/openbao-stack/edge.yaml"
    expect: "Edge manifest validation passed. Checked 1 manifest(s)."
    critical: true
```

### secrets-07-monitoring

```yaml
id: secrets-07-monitoring
title: Scrape openbao-stack's node_exporter; add the OpenBao dashboard
depends_on: []

change: >
  Run `git apply --check docs/secrets-refactor/patches/secrets-07-monitoring.patch`,
  then `git apply` the same file. It adds an openbao-stack target to the
  node_exporter scrape list in deploy-monitoring-stack.yml and creates
  terraform/lxc/stacks/monitoring-stack/dashboards/openbao.json (snapshot
  age, last snapshot run, node_exporter up). Make no other edits.

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml
    - terraform/lxc/stacks/monitoring-stack/dashboards/openbao.json
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Redeploying monitoring-stack"

gates:
  - id: applied
    cmd: "git apply --reverse --check docs/secrets-refactor/patches/secrets-07-monitoring.patch && echo applied"
    expect: "prints applied"
    critical: true
  - id: dashboard-json
    cmd: "python3 -c \"import json; d=json.load(open('terraform/lxc/stacks/monitoring-stack/dashboards/openbao.json')); print(d['uid'], len(d['panels']))\""
    expect: "prints openbao 3"
    critical: true
  - id: syntax-check
    cmd: "cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/deploy-monitoring-stack.yml"
    expect: "exit 0"
    critical: true
```

### Operator: block A — deploy OpenBao (production, pve)

Run each numbered item in order, and stop at the first failure. Every
`with-secrets-prod` mutation needs the `TASK_APPROVAL` shown, after chat
approval.

**A1. Check the NAS mount and create the snapshot directory** (on `pve`, as root).

```bash
findmnt /mnt/nas-backup            # must show 192.168.1.3:/volume1/ProxmoxBackup
mkdir -p /mnt/nas-backup/openbao-snapshots
chown 100000:100000 /mnt/nas-backup/openbao-snapshots && chmod 0700 /mnt/nas-backup/openbao-snapshots
stat -c '%u:%g %a' /mnt/nas-backup/openbao-snapshots   # must print 100000:100000 700
```

If `chown` is refused (NFS root squash on the NAS), set the owner on the NAS
side (ADM) to the UID/GID the export maps `100000` to, then re-run `stat`.
Do not loosen the mode.

**A2. Redeploy Traefik** (the step 05 rootCAs change). This is the Traefik
validation tier: redeploy, then check real consumers.

```bash
export TASK_APPROVAL="secrets-refactor-traefik-rootcas"
./with-secrets-prod scripts/provision.sh --stack proxy-stack
for h in authentik harbor grafana portainer; do
  printf '%s ' "$h"; curl -s -o /dev/null -w '%{http_code}\n' "https://$h.lab.gibbsgreatly.xyz/"
done                               # each must be 200 or 302, as before
```

Then log in to one Authentik-protected app in a browser. If anything
regresses, revert step 05 and redeploy before going further.

**A3. First provision of openbao-stack.** This creates the LXC and installs
OpenBao. OpenBao stays stopped because there is no seal key yet.

```bash
export TASK_APPROVAL="secrets-refactor-openbao-provision"
./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/openbao-stack -no-color | grep -E '^Plan:'
# provision.sh only runs Ansible against an existing inventory; the apply creates the
# LXC and writes terraform/lxc/stacks/openbao-stack/inventory.yml (workspace pve).
./with-secrets-prod terragrunt apply --working-dir terraform/lxc/stacks/openbao-stack
./with-secrets-prod scripts/provision.sh --stack openbao-stack
grep ansible_host terraform/lxc/stacks/openbao-stack/inventory.yml   # must be 192.168.20.16 (env-isolation check)
```

Expect the playbook's "Report missing seal key (OpenBao left stopped)"
message.

**A4. Prepare the seal key on USB A and USB B** (on `pve`, as root). This
wipes both sticks. Identify each stick with `lsblk` first.

```bash
OB_UID=$(pct exec 20016 -- id -u openbao); OB_GID=$(pct exec 20016 -- id -g openbao)
mkfs.ext4 -L BAOSEAL /dev/sdX1                        # USB A (operational)
mkdir -p /mnt/openbao-seal && mount LABEL=BAOSEAL /mnt/openbao-seal
openssl rand -out /mnt/openbao-seal/homelab-2026-1.key 32
chown $((100000+OB_UID)):$((100000+OB_GID)) /mnt/openbao-seal/homelab-2026-1.key
chmod 0400 /mnt/openbao-seal/homelab-2026-1.key
mkfs.ext4 -L BAOSEAL-B /dev/sdY1                      # USB B (offline copy)
mkdir -p /mnt/usb-b && mount LABEL=BAOSEAL-B /mnt/usb-b
cp -p /mnt/openbao-seal/homelab-2026-1.key /mnt/usb-b/
cmp /mnt/openbao-seal/homelab-2026-1.key /mnt/usb-b/homelab-2026-1.key && echo copies-match
umount /mnt/usb-b                                     # keep USB B mounted-able for A8, then store it away from pve
umount /mnt/openbao-seal
echo 'LABEL=BAOSEAL /mnt/openbao-seal ext4 ro,nofail,x-systemd.device-timeout=10s 0 2' >> /etc/fstab
systemctl daemon-reload && mount /mnt/openbao-seal && findmnt /mnt/openbao-seal   # must show ro
```

**A5. Bind-mount the seal key and the snapshot directory into the LXC.**
Run this as root on `pve`; it is root@pam-only.

```bash
pct set 20016 -mp0 /mnt/openbao-seal,mp=/srv/openbao-seal,ro=1,backup=0 \
              -mp1 /mnt/nas-backup/openbao-snapshots,mp=/srv/openbao-snapshots,backup=0
pct reboot 20016
pct exec 20016 -- ls -l /srv/openbao-seal/homelab-2026-1.key   # owner must show openbao
```

**A6. Second provision.** OpenBao starts and auto-unseals, but is not yet
initialized.

```bash
export TASK_APPROVAL="secrets-refactor-openbao-provision"
./with-secrets-prod scripts/provision.sh --stack openbao-stack
# expect: initialized=False sealed=True (auto-unseal happens once initialized)
```

**A7. Install the `bao` CLI on the workstation** (checksum-pinned).

```bash
cd /tmp && curl -fsSLO https://github.com/openbao/openbao/releases/download/v2.7.0/openbao_2.7.0_linux_amd64.tar.gz
echo 'c3ab5de9e778223445487ccbfb16c291bf491642b688f3a3df5aeba23d9b3667  openbao_2.7.0_linux_amd64.tar.gz' | sha256sum -c
tar -xzf openbao_2.7.0_linux_amd64.tar.gz bao && install -m 0755 bao ~/.local/bin/bao && cd -
```

**A8. Initialize OpenBao, and create the bootstrap kit at the same time.**
Do this in one terminal, and do not close it before the kit is written.

```bash
export BAO_ADDR=https://192.168.20.16:8200 BAO_CACERT=$PWD/certs/homelab-root.crt
bao operator init -recovery-shares=1 -recovery-threshold=1 -format=json > /dev/shm/bao-init.json
export BAO_TOKEN=$(python3 -c 'import json;print(json.load(open("/dev/shm/bao-init.json"))["root_token"])')
RK=$(python3 -c 'import json;print(json.load(open("/dev/shm/bao-init.json"))["recovery_keys_b64"][0])')
bao status | grep -E 'Initialized|Sealed'            # Initialized true, Sealed false
# Bootstrap kit (design doc 9.1): exactly what a rebuild of openbao-stack needs.
mount LABEL=BAOSEAL-B /mnt/usb-b   # on pve -- or plug USB B into the workstation and use its mount point
{ ./with-secrets-prod python3 -c 'import os,shlex
for k in ("TF_VAR_pm_api_token_secret","TF_VAR_lxc_password","PROXMOX_READONLY_TOKEN_ID","PROXMOX_READONLY_TOKEN_SECRET","STEP_CA_PROVISIONER_PASSWORD","NODE_EXPORTER_SCRAPE_PASSWORD","NODE_EXPORTER_SCRAPE_PASSWORD_HASH"): print(f"{k}={shlex.quote(os.environ[k])}")'
  printf 'OPENBAO_RECOVERY_KEY=%s\n' "$RK"; } | age -p -o /dev/shm/kit.age   # with set -o pipefail; verify before copying to USB B
# (as executed: docs/secrets-refactor/artifacts/a8b-kit-retry.sh -- a bare pipe hid an age failure once)
age -d <usb-b-mount>/kit.age | cut -d= -f1          # must list the 8 names -- names only
shred -u /dev/shm/bao-init.json; unset RK
```

Then copy the same content into a Bitwarden secure note called "openbao
bootstrap kit": run `age -d <usb-b-mount>/kit.age` and paste the output.
Store USB B away from `pve`. Keep `BAO_TOKEN` (the root token) in this shell
for block B only.

**A9. Activate the UI route.** This creates the Authentik OIDC provider,
publishes the Traefik route and adds the DNS record.

```bash
export TASK_APPROVAL="secrets-refactor-openbao-edge"
./with-secrets-prod python3 terraform/lxc/reconcile-edge.py --stacks-dir terraform/lxc/stacks \
  --authentik-url https://authentik-int.lab.gibbsgreatly.xyz:9443 --no-verify-tls --json        # dry run: review planned writes
./with-secrets-prod python3 terraform/lxc/reconcile-edge.py --stacks-dir terraform/lxc/stacks \
  --authentik-url https://authentik-int.lab.gibbsgreatly.xyz:9443 --no-verify-tls --json --apply
./with-secrets-prod scripts/provision.sh --stack proxy-stack         # pushes the rendered route
./with-secrets-prod scripts/provision.sh --stack technitium-stack    # publishes the DNS record
dig @192.168.20.15 +short openbao.lab.gibbsgreatly.xyz               # 192.168.30.10
curl -s -o /dev/null -w '%{http_code}\n' https://openbao.lab.gibbsgreatly.xyz/ui/   # 200 (backend TLS verified)
```

The reconcile status may read `failed` only because of the known,
unrelated EGR211 drift on `nextcloud-stack`. Any other issue is a stop.

**A10. Check the seal behaviour and that backups exclude the key.**

```bash
ssh root@pve pct reboot 20016; sleep 20
curl -s --cacert certs/homelab-root.crt https://192.168.20.16:8200/v1/sys/health | python3 -m json.tool | grep -E 'initialized|sealed'
# initialized true, sealed false -- unattended unseal works
ssh root@pve 'install -d -m 0755 /var/tmp/openbao-vzdump-test && vzdump 20016 --mode snapshot --dumpdir /var/tmp/openbao-vzdump-test --compress zstd'
ssh root@pve 'f=$(ls /var/tmp/openbao-vzdump-test/*.tar.zst); zstdcat "$f" | tar -t | grep -c "homelab-2026-1\.key"; rm -rf /var/tmp/openbao-vzdump-test'
# must print 0 (the empty ./srv/openbao-seal/ mount-point dir is always present; only the key file matters)
ssh root@pve 'umount /mnt/openbao-seal && pct reboot 20016'; sleep 20
ssh root@pve pct exec 20016 -- systemctl is-active openbao   # not active: fails closed without the key
ssh root@pve 'mount /mnt/openbao-seal && pct reboot 20016'; sleep 20
curl -s --cacert certs/homelab-root.crt https://192.168.20.16:8200/v1/sys/health | grep -o '"sealed":false'
```

---

## Phase B — configure OpenBao

### secrets-08-configure-playbook

```yaml
id: secrets-08-configure-playbook
title: Add configure-openbao.yml (OpenBao's own config as code)
depends_on: [secrets-02-stack-files]

change: >
  Run `git apply --check docs/secrets-refactor/patches/secrets-08-configure-playbook.patch`,
  then `git apply` the same file. It creates
  terraform/lxc/ansible/playbooks/configure-openbao.yml: KV v2 at kv/
  (max_versions 20), file audit device, approle/jwt-github/oidc auth,
  policies from openbao-stack/policies plus one deploy-host-<node> per node,
  AppRoles deploy-dev / deploy-<each PRODUCTION_NODES line> / snapshot, the
  ci-netbox-populate JWT role, and the homelab-admin OIDC role. Make no other edits.

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/configure-openbao.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running the playbook"

gates:
  - id: applied
    cmd: "git apply --reverse --check docs/secrets-refactor/patches/secrets-08-configure-playbook.patch && echo applied"
    expect: "prints applied"
    critical: true
  - id: syntax-check
    cmd: "cd terraform/lxc/ansible && ansible-playbook --syntax-check playbooks/configure-openbao.yml"
    expect: "exit 0"
    critical: true
```

### Operator: block B — configure OpenBao and install identities

Continue in the block A terminal (root token in `BAO_TOKEN`, and `BAO_ADDR`
and `BAO_CACERT` set).

**B1. Apply the configuration.**

```bash
export TASK_APPROVAL="secrets-refactor-openbao-configure"
./with-secrets-prod ansible-playbook terraform/lxc/ansible/playbooks/configure-openbao.yml
./with-secrets-prod ansible-playbook terraform/lxc/ansible/playbooks/configure-openbao.yml   # second run: changed=0 (idempotent)
bao secrets list | grep '^kv/'; bao auth list | grep -E 'approle|jwt-github|oidc'
```

**B2. Install the workstation deploy identities** (the "secret zero";
design doc 14.1).

```bash
install -d -m 0700 ~/.config/openbao
for role in deploy-dev deploy-pve deploy-pve-tiny deploy-pve-framework; do
  bao read -field=role_id auth/approle/role/$role/role-id | install -m 0600 /dev/stdin ~/.config/openbao/$role.role-id
  bao write -f -field=secret_id auth/approle/role/$role/secret-id | install -m 0600 /dev/stdin ~/.config/openbao/$role.secret-id
done
ls -l ~/.config/openbao    # 8 files, all -rw-------
```

Back up `~/.config/openbao/` to Bitwarden as "openbao deploy approles", in
the same way the age key is backed up.

**B3. Install the snapshot identity on the LXC**, then take a first
snapshot.

```bash
{ bao read -field=role_id auth/approle/role/snapshot/role-id; } | ssh root@192.168.20.16 'install -m 0600 /dev/stdin /etc/openbao-snapshot/role-id'
{ bao write -f -field=secret_id auth/approle/role/snapshot/secret-id; } | ssh root@192.168.20.16 'install -m 0600 /dev/stdin /etc/openbao-snapshot/secret-id'
ssh root@192.168.20.16 'systemctl start openbao-snapshot@postwrite.service; journalctl -u openbao-snapshot@postwrite -n 3 --no-pager'
ssh root@pve 'ls -l /mnt/nas-backup/openbao-snapshots/'     # one openbao-...-postwrite.snap, non-zero size
ssh root@192.168.20.16 'cat /var/lib/node_exporter/textfile/openbao_snapshot_postwrite.prom'
```

**B4. Human login through Authentik, and break-glass.**

- In a browser, open `https://openbao.lab.gibbsgreatly.xyz/ui/`, choose
  method OIDC and log in. As a member of `homelab-admins`, you must land in
  the UI with policy `openbao-admin`.
- CLI: `bao login -method=oidc -no-store -token-only` prints a token, and
  `ls ~/.vault-token` must report "No such file".
- Break-glass: generate a root token from the recovery key, check it works,
  then revoke it:

```bash
bao operator generate-root -init -format=json > /dev/shm/gr.json        # note nonce + otp
bao operator generate-root -nonce=<nonce>                                 # paste OPENBAO_RECOVERY_KEY from the kit
bao operator generate-root -decode=<encoded_token> -otp=<otp>             # prints a root token
BAO_TOKEN=<that token> bao token lookup >/dev/null && BAO_TOKEN=<that token> bao token revoke -self
shred -u /dev/shm/gr.json
```

**B5. Revoke the initial root token** (design doc 19). From now on, admin
work is done through OIDC.

```bash
bao token revoke -self && unset BAO_TOKEN
```

---

## Phase C — loader and migration tools

### secrets-09-manifest

```yaml
id: secrets-09-manifest
title: Add secrets/manifest.json (every KV entry, its fields, one profile per environment)
depends_on: []

change: >
  Run `git apply --check docs/secrets-refactor/patches/secrets-09-manifest.patch`,
  then `git apply` the same file. It creates secrets/manifest.json: 30 entries
  (services/*, shared/{platform,external-apis,dev-tooling}, hosts/<node>) with
  their exact field names and sops_source, and profiles pve, pve-tiny,
  pve-framework, pve-test-vm, pve-test and ci-netbox-populate. Make no other edits.

scope:
  allowed_paths:
    - secrets/manifest.json
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Decrypting any SOPS file"

gates:
  - id: applied
    cmd: "git apply --reverse --check docs/secrets-refactor/patches/secrets-09-manifest.patch && echo applied"
    expect: "prints applied"
    critical: true
  - id: every-sops-key-mapped
    cmd: |
      python3 -c "import json,re;m=json.load(open('secrets/manifest.json'));bad=[f'{s}:{k}' for s in sorted({e['sops_source'] for e in m['entries'].values()}) for k in [l.split(':')[0] for l in open(f'terraform/secrets.{s}.enc.yaml') if re.match(r'^[A-Za-z_][A-Za-z0-9_]*:',l) and not l.startswith('sops:')] if not any(k in e['fields'] for e in m['entries'].values() if e['sops_source']==s)];print('unmapped:',bad);raise SystemExit(1 if bad else 0)"
    expect: "prints unmapped: [] and exits 0"
    critical: true
```

### secrets-10-loader

```yaml
id: secrets-10-loader
title: Add the OpenBao loader (scripts/secrets_env.py), its tests, and the boundary check
depends_on: [secrets-09-manifest]

change: >
  Run `git apply --check docs/secrets-refactor/patches/secrets-10-loader.patch`,
  then `git apply` the same file. It creates scripts/secrets_env.py (AppRole or
  GitHub-JWT login, reads only manifest-listed fields, fails closed, revokes
  its token, execs the command), scripts/test_secrets_env.py and
  scripts/openbao_boundary_check.py. Make no other edits.

scope:
  allowed_paths:
    - scripts/secrets_env.py
    - scripts/test_secrets_env.py
    - scripts/openbao_boundary_check.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Contacting OpenBao"

gates:
  - id: applied
    cmd: "git apply --reverse --check docs/secrets-refactor/patches/secrets-10-loader.patch && echo applied"
    expect: "prints applied"
    critical: true
  - id: unit-tests
    cmd: "python3 scripts/test_secrets_env.py"
    expect: "Ran 12 tests ... OK (no skips: the real-manifest test runs)"
    critical: true
  - id: field-count
    cmd: "python3 scripts/secrets_env.py --profile pve --list-fields | wc -l"
    expect: "prints 119"
    critical: true
```

### secrets-11-wrapper-switch

```yaml
id: secrets-11-wrapper-switch
title: SECRETS_BACKEND switch in with-secrets and with-secrets-prod-lib.sh (default stays sops)
depends_on: [secrets-10-loader]

change: >
  Run `git apply --check docs/secrets-refactor/patches/secrets-11-wrapper-switch.patch`,
  then `git apply` the same file. Both wrappers gain
  SECRETS_BACKEND=${SECRETS_BACKEND:-sops}; the age-key / SOPS-file checks run
  only for sops; with SECRETS_BACKEND=openbao they exec
  scripts/secrets_env.py --profile <PVE_ENV | PVE_PROD_NODE> instead of the SOPS
  merge. The production classifier and TASK_APPROVAL gate are untouched.
  Make no other edits.

scope:
  allowed_paths:
    - with-secrets
    - scripts/with-secrets-prod-lib.sh
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Changing the default backend (that is step 14)"

gates:
  - id: applied
    cmd: "git apply --reverse --check docs/secrets-refactor/patches/secrets-11-wrapper-switch.patch && echo applied"
    expect: "prints applied"
    critical: true
  - id: shellcheck
    cmd: "shellcheck -S warning with-secrets scripts/with-secrets-prod-lib.sh"
    expect: "exit 0, no output"
    critical: true
  - id: sops-path-unchanged
    cmd: "./with-secrets printenv PVE_ENV"
    expect: "prints pve-test-vm (default backend still sops, still works)"
    critical: true
  - id: bad-backend-rejected
    cmd: "SECRETS_BACKEND=bogus ./with-secrets true; echo rc=$?"
    expect: "ERROR: SECRETS_BACKEND must be 'sops' or 'openbao' ... and rc=1"
    critical: true
```

### secrets-12-migration-tools

```yaml
id: secrets-12-migration-tools
title: Add the SOPS importer, parity check and write helper
depends_on: [secrets-09-manifest]

change: >
  Run `git apply --check docs/secrets-refactor/patches/secrets-12-migration-tools.patch`,
  then `git apply` the same file. It creates scripts/openbao_import_from_sops.py
  (create-only, cas=0, names-only output), scripts/secrets_parity_check.py
  (SHA-256 comparison of both backends via printenv -0) and
  scripts/openbao_write.py (explicit BAO_TOKEN only, one KV version per call,
  then post-write snapshot). Make no other edits.

scope:
  allowed_paths:
    - scripts/openbao_import_from_sops.py
    - scripts/secrets_parity_check.py
    - scripts/openbao_write.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running the importer without --dry-run, or running openbao_write.py"

gates:
  - id: applied
    cmd: "git apply --reverse --check docs/secrets-refactor/patches/secrets-12-migration-tools.patch && echo applied"
    expect: "prints applied"
    critical: true
  - id: compile
    cmd: "python3 -m py_compile scripts/openbao_import_from_sops.py scripts/secrets_parity_check.py scripts/openbao_write.py && echo ok"
    expect: "prints ok"
    critical: true
  - id: import-dry-run
    cmd: "python3 scripts/openbao_import_from_sops.py --dry-run | tail -1"
    expect: "prints dry-run OK: 30 entries, 129 fields (needs the OPENBAO_OIDC_CLIENT_SECRET prerequisite)"
    critical: true
```

### Operator: block C — prove the OpenBao read path (nothing imported yet)

```bash
LAB_IP_OPENBAO=192.168.20.16 python3 scripts/openbao_boundary_check.py
```

Every `read` line may be 404 (nothing has been imported yet), every `deny`
line must be 403, and every `write` line must be 403. The last line must be
`boundary check: OK`. This proves design doc §31 "Deployment isolation" and
"Host isolation" before any real value exists in OpenBao.

---

## Phase D — cutover

### Operator: block D — reconcile, import, parity (one sitting)

Pick a quiet time. No secret may be rotated anywhere from D1 until step 13
has landed.

**D1. Reconcile.** Confirm `stable` is the only source of values. The
expected output is `prod/pve-infra` only, which is excluded as stale (design
doc §20, Phase 4).

```bash
git fetch --all --prune
for b in $(git for-each-ref --format='%(refname:short)' refs/heads refs/remotes | grep -v 'HEAD$'); do
  n=$(git log --oneline stable..$b -- 'terraform/secrets.*.enc.yaml' | wc -l); [ "$n" != 0 ] && echo "$b $n"
done
git diff --stat stable -- 'terraform/secrets.*.enc.yaml'   # this branch vs stable: only the OPENBAO_OIDC_CLIENT_SECRET addition
```

Then spot-check live values for the secrets most likely to have drifted,
using each service's own login. Specifically: Graylog root (the September
incident), Harbor admin and robot, and the Greenbone admin. If a live value
differs from SOPS, fix SOPS first, before importing.

**D2. Import.** You need a write token: log in by OIDC, in this shell only.

```bash
export BAO_ADDR=https://192.168.20.16:8200 BAO_CACERT=$PWD/certs/homelab-root.crt
export BAO_TOKEN="$(bao login -method=oidc -no-store -token-only)"
python3 scripts/openbao_import_from_sops.py --dry-run | tail -1          # dry-run OK: 30 entries, 129 fields
LAB_IP_OPENBAO=192.168.20.16 python3 scripts/openbao_import_from_sops.py  # every line "created"; exit 0
ssh root@192.168.20.16 systemctl start openbao-snapshot@postwrite.service
unset BAO_TOKEN
```

**D3. Parity**, for every profile. Every field must match.

```bash
for p in pve pve-tiny pve-framework pve-test-vm pve-test; do
  python3 scripts/secrets_parity_check.py $p | tail -1
done
# each: "<profile>: N/N fields match"
LAB_IP_OPENBAO=192.168.20.16 python3 scripts/openbao_boundary_check.py | tail -1   # boundary check: OK (reads now 200)
```

If any field reports MISMATCH or MISSING, stop. Nothing has changed for
consumers yet (the default is still `sops`).

**D4.** Execute steps 13 and 14 immediately, then merge them. From that
merge onward, OpenBao is authoritative.

### secrets-13-freeze

```yaml
id: secrets-13-freeze
title: Freeze the SOPS files (pre-commit hook + PR check)
depends_on: [secrets-12-migration-tools]

change: >
  Run `git apply --check docs/secrets-refactor/patches/secrets-13-freeze.patch`,
  then `git apply` the same file. In .pre-commit-config.yaml it replaces the
  check-required-sops-keys hook with block-sops-secret-edits (language: fail,
  files ^terraform/secrets\..*\.enc\.yaml$); in .github/workflows/validate.yml it
  adds a pull_request-only sops-freeze job that fails if a PR adds or modifies
  terraform/secrets.*.enc.yaml. Make no other edits.

scope:
  allowed_paths:
    - .pre-commit-config.yaml
    - .github/workflows/validate.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Deleting any SOPS file"

gates:
  - id: applied
    cmd: "git apply --reverse --check docs/secrets-refactor/patches/secrets-13-freeze.patch && echo applied"
    expect: "prints applied"
    critical: true
  - id: hook-blocks-sops
    cmd: "pre-commit run block-sops-secret-edits --files terraform/secrets.common.enc.yaml; echo rc=$?"
    expect: "prints the 'are frozen' message and rc=1"
    critical: true
  - id: hook-ignores-others
    cmd: "pre-commit run block-sops-secret-edits --files with-secrets"
    expect: "(no files to check)Skipped, exit 0"
    critical: true
```

### secrets-14-default-openbao

```yaml
id: secrets-14-default-openbao
title: Make OpenBao the default backend; route the preflight scripts through the wrapper
depends_on: [secrets-11-wrapper-switch, secrets-13-freeze]

change: >
  Run `git apply --check docs/secrets-refactor/patches/secrets-14-default-openbao.patch`,
  then `git apply` the same file. Both wrappers default to
  SECRETS_BACKEND=openbao (sops stays available as the rollback path);
  scripts/preflight-production-mikrotik.sh stops calling `sops exec-env` on
  the pve file and re-execs through ./with-secrets-prod python3 instead;
  scripts/preflight-production-external.sh drops its own age-key/SOPS-file
  checks. Make no other edits.

scope:
  allowed_paths:
    - with-secrets
    - scripts/with-secrets-prod-lib.sh
    - scripts/preflight-production-mikrotik.sh
    - scripts/preflight-production-external.sh
  forbidden_actions:
    - "Any change outside allowed_paths"

gates:
  - id: applied
    cmd: "git apply --reverse --check docs/secrets-refactor/patches/secrets-14-default-openbao.patch && echo applied"
    expect: "prints applied"
    critical: true
  - id: shellcheck
    cmd: "shellcheck -S warning with-secrets scripts/with-secrets-prod-lib.sh scripts/preflight-production-mikrotik.sh scripts/preflight-production-external.sh"
    expect: "exit 0, no output"
    critical: true
  - id: default-is-openbao
    cmd: "grep -cF 'SECRETS_BACKEND=\"${SECRETS_BACKEND:-openbao}\"' with-secrets scripts/with-secrets-prod-lib.sh"
    expect: "each file :1"
    critical: true
  - id: no-direct-sops
    cmd: "grep -c 'sops exec-env' scripts/preflight-production-mikrotik.sh"
    expect: "prints 0"
    critical: true
  - id: live-read
    cmd: "./with-secrets printenv PVE_ENV && ./with-secrets-prod printenv PVE_ENV"
    expect: "prints pve-test-vm then pve (both now read through OpenBao; needs block B's AppRole files)"
    critical: true
```

### Operator: after merging 13 and 14 — representative provisions

Validation tier: an Ansible run against `pve` under the production
approval flow. Choose stacks whose secrets are used on every run:

```bash
export TASK_APPROVAL="secrets-refactor-cutover-validate"
./with-secrets-prod scripts/provision.sh --stack graylog-stack
./with-secrets-prod scripts/provision.sh --stack harbor-stack
./with-secrets-prod-tiny scripts/provision.sh --stack cse-panel-stack
```

All three must end `failed=0`, followed by a real login to Graylog and
Harbor.

**Rollback:** `SECRETS_BACKEND=sops ./with-secrets-prod ...` works only
until the first secret is rotated in OpenBao. After that, SOPS holds stale
values.

### secrets-15-ci-jwt

```yaml
id: secrets-15-ci-jwt
title: netbox-populate reads OpenBao via GitHub OIDC; remove the SOPS decrypt job
depends_on: [secrets-14-default-openbao]

change: >
  Run `git apply --check docs/secrets-refactor/patches/secrets-15-ci-jwt.patch`,
  then `git apply` the same file. netbox-populate.yml gets job permissions
  id-token: write, requests a GitHub OIDC token (audience openbao), and runs
  `python3 scripts/secrets_env.py --profile ci-netbox-populate -- bash
  ./scripts/netbox-populate.sh apply` instead of installing SOPS; the
  sops-decrypt-check job is removed from validate.yml. Make no other edits.

scope:
  allowed_paths:
    - .github/workflows/netbox-populate.yml
    - .github/workflows/validate.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Deleting the SOPS_AGE_KEY GitHub secret (operator, block F)"

gates:
  - id: applied
    cmd: "git apply --reverse --check docs/secrets-refactor/patches/secrets-15-ci-jwt.patch && echo applied"
    expect: "prints applied"
    critical: true
  - id: yaml
    cmd: "python3 -c \"import yaml; [yaml.safe_load(open(f)) for f in ('.github/workflows/netbox-populate.yml', '.github/workflows/validate.yml')]; print('ok')\""
    expect: "prints ok"
    critical: true
  - id: no-sops-in-ci
    cmd: "grep -c -i 'sops' .github/workflows/netbox-populate.yml; grep -c 'sops-decrypt-check' .github/workflows/validate.yml"
    expect: "prints 0 and 0"
    critical: true
```

### Operator: after merging 15 to main — CI check

The workflow runs from `main` only (the JWT role is bound to
`refs/heads/main`). Run it with `gh workflow run netbox-populate.yml --ref
main`, then `gh run watch`. The "Request GitHub OIDC token" and "Run populate
container" steps must pass. Note that `netbox-populate` has been failing
nightly since at least 2026-09-23 for an unrelated reason: SOPS could not be
installed on the runner (`sudo` needs a password). This step removes that
dependency.

---

## Phase E — docs

### secrets-16-docs

```yaml
id: secrets-16-docs
title: CLAUDE.md and docs/reference/secrets-management.md describe the OpenBao model
depends_on: [secrets-14-default-openbao]

change: >
  Run `git apply --check docs/secrets-refactor/patches/secrets-16-docs.patch`,
  then `git apply` the same file. It rewrites CLAUDE.md's "Secrets Storage"
  section, the production-node onboarding sentence, the SONAR_TOKEN note and
  the five SOPS bullets in "Workspace Operating Patterns", and replaces
  docs/reference/secrets-management.md with the OpenBao version. Make no other edits.

scope:
  allowed_paths:
    - CLAUDE.md
    - docs/reference/secrets-management.md
  forbidden_actions:
    - "Any change outside allowed_paths"

gates:
  - id: applied
    cmd: "git apply --reverse --check docs/secrets-refactor/patches/secrets-16-docs.patch && echo applied"
    expect: "prints applied"
    critical: true
  - id: claude-md
    cmd: "grep -c 'secrets/manifest.json' CLAUDE.md; grep -c 'sops terraform/secrets.common.enc.yaml' CLAUDE.md"
    expect: "first count >= 2, second count 0"
    critical: true
```

---

## Phase F — verify and retire

### Operator: block E — recovery test (acceptance criterion "Backup")

Rebuild OpenBao using only the offline material, not a single OpenBao-held
secret. Do it on `pve-test-vm` or a throwaway LXC on `pve`, never over the
live `openbao-stack`.

1. Load the bootstrap kit into a fresh shell with
   `set -a; source .env; source .env.pve; source <(age -d <usb-b>/kit.age); set +a`,
   then check `./with-secrets` is **not** used.
2. Create a scratch LXC from the same template, install the same `.deb`, and
   write the same `openbao.hcl` (a self-signed cert is fine for this test).
   Point `seal "static"` at the key file on USB B.
3. Copy the newest snapshot from `/mnt/nas-backup/openbao-snapshots/` and run
   `bao operator raft snapshot restore -force <file>` against the scratch
   instance. Use a token from `generate-root` with the kit's recovery key.
4. `bao kv get -mount=kv -field=GRAYLOG_ROOT_PASSWORD services/graylog | sha256sum`
   must equal the same hash from the live instance.
5. Destroy the scratch LXC. Record the result in README.md.

### Operator: block F — retire SOPS

Only after block E passes. Retirement deletes the SOPS files and the SOPS
code paths, so it is authored as a fresh patch at that time, against the
branch as it is then. It is deliberately not pre-generated here. It covers:

- deleting `terraform/secrets.*.enc.yaml` and `.sops.yaml`;
- deleting `scripts/merge-sops-env.sh`, `scripts/check-required-sops-keys.sh`,
  `scripts/openbao_import_from_sops.py` and `scripts/secrets_parity_check.py`;
- removing the `sops` branch and `SECRETS_BACKEND` from both wrappers;
- removing `sops_source` from the manifest;
- updating the SOPS messages in `scripts/provision.sh`
  (`resolve_secrets_file_hint`) and `scripts/setup-dev-env.sh`.

Then, by hand:

- delete the `SOPS_AGE_KEY` GitHub Actions secret;
- keep the age key in Bitwarden. It no longer protects anything in Git, but
  keep it until the retirement commit is at least one release old.

`terraform/lxc/stacks/netbox-stack/integrations/flows.py` still describes a
"ds-sops-secrets" data source in NetBox. That is inventory data, and
correcting it is a separate follow-up.

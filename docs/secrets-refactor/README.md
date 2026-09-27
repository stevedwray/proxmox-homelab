# secrets-refactor

Move secret **values** out of Git-tracked SOPS files and into OpenBao, so
that a branch checkout, merge or rebase can never again silently restore an
old password.

- **Design:** [secrets-design.md](secrets-design.md). It holds the decisions
  and reasoning, and has an as-built status section at the top.
- **Plan:** [plan.md](plan.md). It holds the original step plan, annotated
  with what was actually executed and how it deviated.
- **Operating it day to day:**
  [docs/reference/secrets-management.md](../reference/secrets-management.md).
  It covers using, adding and rotating secrets, break-glass, recovery, the
  USB seal key, and monitoring.
- **Patches:** [patches/](patches/). These are the 16 step patches as
  applied (historical once merged).
- **Execution record:** the hand-back log below. Every gate result, finding
  and fix is there, in order.

## Status (2026-09-28)

**Done and live.** OpenBao is the only source of secrets. The SOPS files
are deleted (Git history keeps old, non-authoritative copies).

| Area | State |
| --- | --- |
| OpenBao | LXC 20016, `192.168.20.16` (`mgmt_seg`), v2.7.0 native `.deb`. Static-seal auto-unseal from USB A (ADATA) on `pve`, bind-mounted read-only and verified absent from `vzdump`. step-ca TLS with a daily `step ca renew`. Declarative audit log. UI at `https://openbao.lab.gibbsgreatly.xyz` through Traefik; API direct by IP |
| Data | KV v2 at `kv/`: 30 entries, 129 fields (services 22/96, shared 3/20, hosts 5/13). `secrets/manifest.json` is the names-only inventory |
| Reads | `./with-secrets` and `./with-secrets-prod*` read only from OpenBao, via one read-only AppRole per environment, and fail closed. The SOPS path and the `SECRETS_BACKEND` rollback are removed |
| Writes | Humans only: Authentik OIDC (`bao login -method=oidc -no-store`) plus `scripts/openbao_write.py` |
| Break-glass | The `breakglass` AppRole (policy: `sys/generate-root-token/*` only) plus the recovery key. No standing root token |
| Backups | Raft snapshots to the NAS, post-write and nightly at 03:30; retention 90d/14d/8w/12m. **Recovery test passed** (fresh instance + USB B + snapshot + recovery key) |
| Bootstrap kit | Bitwarden note "openbao bootstrap kit" plus a passphrase-encrypted `kit.age` on USB B (SanDisk). 10 values, including the recovery key and the breakglass AppRole |
| Monitoring | Grafana "OpenBao" dashboard: snapshot age and last run, LXC up, secret entries and fields per category, a per-entry version and last-changed table, changes in the last 7 days, manifest drift. The inventory comes from a `metrics` AppRole that can read KV **metadata only**; the audit log shows its value reads denied. **No alerting yet** |
| Validation | Post-cutover real deploys (graylog, harbor, cse-panel, monitoring); a 28-stack `--check` sweep with no missing secrets; 10 live service logins with OpenBao credentials; all 5 profiles read in full |
| Git | Cutover merged to `stable` (PR #431, `93939d61`); retirement, tests, inventory, the reconciler fix and the tidy-up merged to `stable` from `task/retire-sops` (PR #432). **`main` is not promoted** |

## Next steps

**To finish this project:**

1. ~~PR `task/retire-sops` → `stable`~~ — merged (PR #432).
2. **Promote `stable` → `main`** when the operator decides. It is currently
   deferred, and `main` carries 3 weeks of other work. Then:
   - The CI `sops-freeze` check will flag `321c5549`. That is expected: it
     was the last legitimate pre-freeze SOPS edit.
   - Run `gh workflow run netbox-populate.yml --ref main` and confirm the
     GitHub OIDC → OpenBao login and populate work (plan step 15's live
     test).
   - Delete the `SOPS_AGE_KEY` GitHub Actions secret.
3. ~~Close out the workspace~~ — done 2026-09-28. `artifacts/` is empty;
   the reusable scripts are in `scripts/` (`openbao-recovery-test.sh`,
   `openbao-breakglass-test.sh`, `secrets-check-sweep.sh`,
   `openbao-issue-credentials.sh`), and the one-off bootstrap scripts
   (USB seal prep, init and kit build) were deleted, as their results are
   recorded in the log below and the runbook.

**Recommended follow-ups (separate work):**

- **Alerting.** Monitoring has no alert rules or contact points. At
  minimum: snapshot age > 36 h, last snapshot run failed, manifest drift
  > 0, OpenBao LXC down or sealed.
- **Rotate the high-value secrets over time.** Old values remain in Git
  history as SOPS ciphertext, readable by anyone holding the age key.
  Rotating (with `openbao_write.py`) makes those copies worthless. Start
  with the Proxmox API tokens, Authentik superuser, Harbor admin and robot,
  the MikroTik admin, and the Cloudflare DNS token. After that, the age key
  can be retired from Bitwarden.
- ~~**Edge reconciler `grant_types`**~~ — done 2026-09-28 (`f6c24381`).
  A provider the reconciler *creates* now gets `("authorization_code",)`
  when its route has no explicit `_oidc_grant_types` entry. Updates are
  unchanged, so existing providers' larger sets are never narrowed.
  Existing live providers are unaffected (no create happens for them).
- ~~**Tidy-ups**~~ — done 2026-09-28:
  - the "SOPS" mentions in stack contracts, playbook comments and error
    strings, scripts, the router README and `scrape-config.sh` now point
    at OpenBao (`kv/<entry>`). The only ones left are deliberate: history
    notes, the freeze hook, and `.gitignore`/`.gitleaks.toml` guards;
  - NetBox's threat-model data store `ds-sops-secrets` is replaced by
    `ds-openbao-secrets` (`flows.py` and `docs/threat-model/model.yaml`).
    It shows in NetBox after the next populate run;
  - CLAUDE.md, AGENTS.md and copilot-instructions list `pve-tiny` as a
    production node (it was missing);
  - **kept** `kv/services/legacy-unused` (7 fields, no consumer). It is
    harmless, documented and snapshotted. Deleting it needs a human OIDC
    write, and nothing gains from it until those values are rotated or
    confirmed dead;
  - **kept** `pve-framework` in `PRODUCTION_NODES`. `llm-gpu-stack` and
    `comfyui-stack` still declare it as their node, so removing it is part
    of decommissioning the old Framework node (see
    `docs/framework-ip-and-port/`), not a secrets tidy-up.
- **Existing issues found along the way (not caused by this work):**
  - harbor-stack's Terraform state split between the environment directory
    and the stack directory (its plan wants to re-run the SDN attachment);
  - `portainer_agent` restarts the agent on every run;
  - the 8 failing `terraform/lxc` unit tests (the same on `stable`);
  - CLAUDE.md's repo-wide `unittest discover -s .` finds 0 tests;
  - the CI lint baseline (ruff, ansible-lint, Harbor-only images);
  - the nextcloud EGR211 edge drift;
  - `netbox-populate` was failing nightly before this work.
- **Later, if needed:** seal-key rotation (static seal `previous_key`
  procedure, documented in the runbook); per-workload OpenBao identities
  for stacks that should fetch their own secrets (design §15); HA (design
  §28).

## Decisions (operator, 2026-09-28)

| Topic | Decision |
| --- | --- |
| Deploy-time auth (`with-secrets`, agents) | Read-only AppRole per environment, workstation-held; no Authentik dependency |
| Human auth | Authentik OIDC, for the UI and writes only |
| Break-glass | `breakglass` AppRole (generate-root-token only) plus the recovery key. Added in execution: OpenBao ≥2.5.3 disables unauthenticated generate-root |
| USB seal key | Stays inserted in `pve`; unattended unseal; host bind mount, so `vzdump` never includes it |
| Bootstrap kit | Two copies: a Bitwarden secure note, and a passphrase `kit.age` on USB B. Not age-key encrypted |
| Cutover | Reconcile against live, bulk import, parity check, freeze SOPS, flip the default; then retire SOPS after the recovery test |
| CI | GitHub OIDC → OpenBao `jwt-github` (live once `main` is promoted) |
| KV layout | KV v2; one entry per service/host; field names = env var names; `max_versions` 20 |
| Snapshots | After each helper write, plus nightly; to `nas.gibbsgreatly.xyz` through pve's existing NFS mount (`/mnt/nas-backup`) |
| Retention | 90d post-write / 14 daily / 8 weekly / 12 monthly; never fewer than the newest 7 |
| UI route | Through Traefik (EdgeManifest + edge reconciler); Traefik trusts the homelab CA for HTTPS backends |
| Install | Native pinned `.deb` + systemd (like step-ca); no Docker or Harbor dependency |
| OpenBao config | Ansible playbook against the API, with an explicit admin token; SecretIDs made by hand |
| Dashboard inventory | `metrics` AppRole with KV metadata only; field counts from the manifest |
| Alerting | Metric + Grafana panel now; real alerting is a separate project |
| Merge | Whole branch into `stable`; `main` promotion deferred |
| Execution | Claude executes directly (no local model). Production runs are done by the operator, because the harness classifier blocks them for Claude |

## Findings along the way (not part of this plan)

- **`netbox-populate` had failed every night since at least 2026-09-23**:
  `sudo apt-get install sops` needs a password on the self-hosted runner.
  Step 15 removes the SOPS dependency. Even when it worked, the job loaded
  only `secrets.pve.enc.yaml`, not the common values its script needs
  (`NETBOX_API_TOKEN`, `MIKROTIK_*`). The `ci-netbox-populate` profile
  includes them.
- **`preflight-production-mikrotik.sh`** loaded only the pve SOPS file,
  although its `MIKROTIK_*` checks need common values. It now bootstraps
  through `./with-secrets-prod` (18/18 PASS).
- **The router scripts** (`cutover.sh`, `provision-hap-ax3.sh`) needed
  `hAPax3_ADMIN`, which was never in SOPS. They now take it from the
  environment.
- **`prod/pve-infra`** (protected, last commit 2026-05-25) carries a stale
  pre-split `secrets.pve.enc.yaml`. It was excluded from reconciliation.
- **Keys with no consumer in the repo** were imported, not dropped, into
  `kv/services/legacy-unused`: `NPM_DB_PASSWORD`, `OMADA_*` (4) and
  `TF_VAR_dayz_steam_*` (2). `GOOGLE_CSE_*` and `CURSEFORGE_API_KEY` also
  have no code consumer but were placed with their likely owners.
- **`pve-framework`** is still in `PRODUCTION_NODES`, with `hosts/pve-framework`
  and `deploy-pve-framework`, although the Framework is no longer a Proxmox
  node.

## Hand-back log

Each executed step appends an entry here: the step id, the date, what
changed, and every gate's actual result. See
`.github/prompts/implement-step.prompt.md`.

### 2026-09-28 — steps 01–12 (repo-only), branch `feat/secrets-openbao`

Executed by Claude directly (operator decision: no local model for this
plan). Patches 01–12 were applied in order, and each `git apply --check`
was clean.

| Step | Gate results |
| --- | --- |
| 01 | values: `192.168.20.16 openbao.lab.gibbsgreatly.xyz` ✓ |
| 02 | yaml: `20016 192.168.20.16/24 mgmt_seg` ✓. plan-create-only: `Plan: 5 to add, 0 to change, 0 to destroy.`, target_node `pve`, bridge `tvmgmt` ✓ |
| 03 | 7 tests OK ✓ |
| 04 | syntax-check rc=0 ✓. pinned-deb 1 ✓ |
| 05 | syntax-check rc=0 ✓ |
| 06 | edge tests OK ✓. edge-validate passed ✓ |
| 07 | `openbao 3` ✓. syntax-check rc=0 ✓ |
| 08 | syntax-check rc=0 ✓ |
| 09 | `unmapped: []` ✓ |
| 10 | 12 tests OK, no skips ✓. field-count 119 ✓ |
| 11 | shellcheck clean ✓. `./with-secrets printenv PVE_ENV` → `pve-test-vm` (sops path unchanged) ✓. bogus backend rc=1 ✓ |
| 12 | compile ok ✓. **import-dry-run: expected failure.** Its only complaint is `services/openbao:OPENBAO_OIDC_CLIENT_SECRET missing`. That is the operator prerequisite, which has not been done yet; re-run after it. |

Steps 13–16 are cutover-time and deliberately not applied yet.

### 2026-09-28 — operator blocks A–F and follow-on work (chronological)

- **A1 done.** `/mnt/nas-backup` on `pve` is NFS4
  `192.168.1.3:/volume1/ProxmoxBackup`. Created
  `/mnt/nas-backup/openbao-snapshots`; `chown` over NFS was accepted, and
  `stat` shows `100000:100000 700`. The container's ability to write there
  is tested at A5.
- **Baseline before A2:** authentik 302, harbor 200, grafana 302, portainer
  200, netbox 302, jellyfin 302.
- **A2 done (operator run).** proxy-stack `failed=0`, and the smoke test
  passed. The live `/opt/proxy-stack/traefik.yml` has
  `serversTransport.rootCAs: [/certs/combined-ca.crt]`, and Traefik
  restarted. After the redeploy, every route matches the baseline (authentik
  302, harbor 200, grafana 302, portainer 200, netbox 302, jellyfin 302).
- **A3, first attempt:** `provision.sh` logged "SKIP openbao-stack: inventory
  file not found". This was a plan gap: A3 was missing the `terragrunt apply`
  that creates the LXC and writes `inventory.yml`. The plan is fixed. New
  stacks such as `media-stack-lab` keep their state in the stack directory
  under workspace `pve`, not under `environments/pve/`, and that is correct
  here too.
- **A3 done (operator run).** `terragrunt apply`: 5 added, LXC 20016
  `openbao` at 192.168.20.16 on `mgmt_seg`/`tvmgmt`, target `pve`.
  `provision.sh`: `failed=0`. Verified: the inventory's `ansible_host` is
  192.168.20.16; in-container `openbao` is uid 999 / gid 991 (host
  100999:100991); the step-ca cert has SANs `DNS:openbao.lab.gibbsgreatly.xyz,
  IP:192.168.20.16` and is valid to 2026-10-27; the provisioner password file
  was removed; `openbao.service` is enabled but inactive (no seal key yet, as
  expected); the TLS-renew and nightly-snapshot timers are scheduled.
- **USB devices already on `pve` before A4. Do not touch either:**
  `sdd` is a 931.5G Samsung PSSD T7 (no partitions or mounts), and `sde` is a
  3.6T WD mounted at `/mnt/pve/usb-backup`.
- **A4 sticks.** The Samsung T7 was unplugged. A first "USBest"
  (`1307:0163`) stick reported 0 bytes and was replaced. The final sticks
  are: USB A = ADATA USB Flash Drive, serial `2783009100070000` (was a Ventoy
  stick, wiped with the operator's OK), label `BAOSEAL`; USB B = SanDisk
  Cruzer Blade, serial `432171079EA39474` (had a vfat partition, wiped),
  label `BAOSEAL-B`.
- **A4 done (operator ran `artifacts/a4-seal-usb.sh`, by-id paths only).**
  Result: `copies-match`; both keys are 32 bytes, 100999:100991, mode 0400;
  fstab has `LABEL=BAOSEAL /mnt/openbao-seal ext4 ro,nofail,...`; mounted
  `/dev/sdg1 ro,relatime`. USB B is still plugged in, waiting for kit.age (A8).
- **A5 done (operator run).** `pct set 20016` mp0 (seal, ro, backup=0) and
  mp1 (snapshots, backup=0), then reboot. In the container, the key is
  `-r-------- 999 991 32`; `openbao-can-read-key`; `snapshots-writable` (the
  NFS write as container root works).
- **A7 done.** `bao` v2.7.0 installed to `~/.local/bin`, with the tarball
  sha256 verified.
- **A6 done (operator run).** provision `failed=0`; `bao status`: Seal Type
  `static`, Recovery Seal Type `shamir`, `initialized=false`, as expected before init.
- **A8 done.** `bao operator init -recovery-shares=1` → `Initialized true`,
  `Sealed false` (static auto-unseal works). The first kit write failed:
  mismatched passphrases left an empty `kit.age`, because the pipeline lacked
  `pipefail`, and the verify step caught it. Retried with
  `artifacts/a8b-kit-retry.sh` (pipefail, encrypt to a tmp file and verify
  before copying): 8 names verified; `kit.age` is 752 bytes, sha256
  `5b501751161a929fc5abdaa2d69b219a20d80e1f22cf55cfb15ffe404491f69c`, the
  same locally and on USB B. `/dev/shm/bao-init.json` shredded. The initial
  root token is held only in the operator's shell, for block B.
- **After A8:** the operator stored the kit in Bitwarden. USB B is unplugged
  (checked: no SanDisk device on `pve`).
- **Prerequisite done (operator, `artifacts/prereq-oidc-secret.sh`, via
  `sops set --value-stdin`).** Commit `321c5549` adds
  `OPENBAO_OIDC_CLIENT_SECRET` (64 chars). The step 12 import-dry-run gate now
  passes: `dry-run OK: 30 entries, 129 fields` ✓.
- **A9 dry run** (`reconcile-edge.py`, no `--apply`, run by Claude,
  read-only): Authentik has 2 `create` actions (the openbao-stack app and
  provider), 49 noop, and 2 `delete-report` (nextcloud-stack, report-only:
  the known EGR211 drift behind the overall `failed`). The Technitium diff
  adds only `openbao` → 192.168.30.10.
- **USB A replug incident (operator moved it to another port).** OpenBao
  kept running unsealed (the key is only read at start). But the host mount
  `/mnt/openbao-seal` dropped: the fstab entry mounts at boot, not on
  hotplug. The container's bind mount went stale (`Input/output error`), and
  the device came back as `sdd1` instead of `sdg1`. The next OpenBao restart
  would have stayed sealed. Fixed with `mount /mnt/openbao-seal` and
  `pct reboot 20016`: the key is back on the host (100999:100991) and in the
  container (999:991), and after the restart `"sealed":false`. **This also
  satisfies A10's "LXC restart unseals unattended" check.**
  **Runbook rule:** after any replug of USB A, run
  `mount /mnt/openbao-seal && pct reboot 20016` on `pve`, and confirm
  `sealed=false`. A full `pve` reboot self-heals (the fstab entry mounts by label).
- **A9 done (operator run).** `reconcile-edge.py --apply`: 2 creates
  (openbao-stack app, and provider id 28), 1 update (embedded outpost
  "missing provider links", which added provider 28 in the same way as the 9
  existing OAuth2 providers, the reconciler's normal convention), 2
  nextcloud `delete-report` (report-only, EGR211). proxy-stack and
  technitium-stack `failed=0`, smoke tests passed. Verified: `dig
  openbao.lab.gibbsgreatly.xyz` → 192.168.30.10; `/ui/` 200 through Traefik
  (backend TLS verified against the homelab CA); `/v1/sys/health` through
  the route shows initialized/unsealed; the Authentik discovery issuer is
  `https://authentik.lab.gibbsgreatly.xyz/application/o/edge-openbao-stack-openbao/`;
  the other routes are unchanged from the baseline.
- **A10 done (operator run).** `vzdump 20016` rc=0. The archive contains only
  the empty mount-point dir `./srv/openbao-seal/` and **0 key-file entries**,
  so the bind-mounted seal key is excluded from backups. (A first, too-broad
  grep counted that dir as "1"; the plan's check is now tightened to the key
  filename.) Without the key: `openbao` = `failed`, closed as designed. With
  the key re-mounted and the LXC rebooted: `active`, `"sealed":false`.
  Unattended unseal after an LXC restart was already shown in the replug
  incident. **Block A complete.**
- **B1, first attempt:** `configure-openbao.yml` mounted `kv/` (KV v2), then
  failed at "Enable file audit device" with HTTP 400. Cause: OpenBao 2.x
  rejects API-created audit devices unless `unsafe_allow_api_audit_creation`
  is set (documented in `configuration/index.mdx` at v2.7.0). Fix: a
  declarative `audit "file" "file"` block in the `openbao.hcl` that
  deploy-openbao.yml writes, with the configure task replaced by an assertion
  that `file/` exists. Needs an openbao-stack re-provision (the config change
  restarts OpenBao, which auto-unseals), then a configure re-run.
- **B1 done.** openbao-stack re-provisioned (`failed=0`); OpenBao restarted
  with the declarative audit block and came back `"sealed":false`;
  `bao audit list` shows `file/`. `configure-openbao.yml` ran with
  `failed=0`, and a re-run gave `changed=0` (idempotent). Auth methods:
  `approle/`, `jwt-github/`, `oidc/`.
- **B2/B3 done (`artifacts/b2-b3-identities.sh`).** 8 files in
  `~/.config/openbao/`, all 0600. The snapshot identity is installed on the
  LXC. The first snapshot, `openbao-20260927T193524Z-postwrite.snap` (40473
  bytes), is on the NAS, and the metric
  `openbao_snapshot_last_run_success{kind="postwrite"} 1`. Full boundary
  check, run by Claude, **OK**: deploy-dev reads 27 entries (404 before
  import) and is denied 3 prod host entries (403); each deploy-<prod-node>
  reads 26 and is denied 4; every write attempt is 403. That proves §31
  "Deployment isolation" and "Host isolation".
- **B4 browser login failed:** "The callback from the provider did not
  supply all of the required parameters". Root cause, from Authentik's
  server log: `Invalid grant_type for provider: authorization_code`.
  Provider 28 was created with `grant_types: []`. Authentik's API defaults
  an omitted `grant_types` to empty on create, and
  `reconcile-authentik-edge.py` sets it only for routes listed in
  `discover-authentik-edge.py`'s `_oidc_grant_types` table: a fourth
  per-stack OIDC table, which patch 06 missed. This is the **fourth
  recurrence** of the same bug (opensearch, wazuh, jellyfin/immich, now
  openbao). Fix: an openbao entry `("authorization_code",)`; edge tests OK;
  the reconcile dry-run now plans exactly 1 `update` (the openbao provider),
  with no Traefik or DNS change. Follow-up worth doing: default
  `grant_types` on *create* for every OIDC route, so a new stack can't hit
  this a fifth time.
- **B4 browser login done.** After the operator's reconcile `--apply`
  (1 update, 50 noop; provider 28 `grant_types` now `['authorization_code']`),
  the UI OIDC login works. The audit log shows the callback token with
  policies `['default', 'openbao-admin']`, TTL 3600s, role `homelab-admin`.
- **B4 CLI login done.** `bao login -method=oidc -no-store -token-only`
  returned a token via the localhost:8250 callback; `~/.vault-token` does
  not exist (§13.1).
- **B4 break-glass: design gap found and fixed.** OpenBao ≥ 2.5.3 disables
  the unauthenticated `sys/generate-root/*` endpoints (403), and
  `sys/generate-root-token/*` needs a token, so §19's recovery-key-only
  break-glass could not work. Operator decision: a `breakglass` AppRole
  whose policy allows only `sys/generate-root-token/*` (15-minute tokens,
  LAN-bound), with credentials in `~/.config/openbao/` and the bootstrap
  kit. The design §19 and §9.1 are updated. After a configure re-run
  (`failed=0`) and issuing the credentials, the test **passed**: breakglass
  login (`['breakglass','default']`) plus the recovery key → root token
  `['root']` works, and it and the breakglass token were both revoked and
  verified invalid.
- **Kit updated (`artifacts/a8c-kit-add-breakglass.sh`).** 10 names verified
  (the 8 before plus `OPENBAO_BREAKGLASS_ROLE_ID/SECRET_ID`); `kit.age`
  sha256 `5b5aef7181b39edf2a4d2055ec32622ffe3bc0307b633e0f2d5e3b3f076e4d6a`
  is the same locally and on USB B. The operator updates the Bitwarden note
  and unplugs USB B.
- **B5 done.** The initial root token was revoked (audit: `revoke-self`,
  policies `['root']`, 2026-09-27T20:01:01Z, no error). There is no standing
  root token. Admin access is via OIDC; break-glass is the breakglass
  AppRole plus the recovery key.
- **Block C** (read-path and boundary proof) was already satisfied by the
  B3 boundary check (all roles OK, reads 404 before import). **Blocks A–C
  complete.**
- **D1 reconcile done (Claude, read-only).** Branch scan: only
  `prod/pve-infra` (stale, excluded) and this branch (the one new
  `OPENBAO_OIDC_CLIENT_SECRET`, `321c5549`) differ from `stable` in
  `terraform/secrets.*`. Live authenticated spot-checks with SOPS values,
  status only: Graylog root, Harbor admin, Harbor robot (registry token),
  Grafana admin, NetBox API token, Portainer admin, Authentik superuser API
  token, MikroTik read-only, OpenSearch admin: **all 200**. Greenbone admin
  was not checked (GMP); its provision after the cutover covers it.
- **D2 done (operator, OIDC write token).** Dry run `30 entries, 129 fields`,
  then 30× `created` (HTTP 200), no FAILED or DIFFERS. A post-import
  snapshot is on the NAS (79390 bytes).
- **D3 done (Claude).** Parity, all fields matching by SHA-256:
  pve 119/119, pve-tiny 118/118, pve-framework 118/118, pve-test-vm 119/119,
  pve-test 117/117. The boundary check is OK with real data: 105 permitted
  reads 200, cross-host 403, writes 403.
- **Steps 13–14 applied (Claude).** Freeze: the hook blocks a staged
  `terraform/secrets.common.enc.yaml` ("are frozen") and skips other
  files ✓. Default backend: shellcheck clean; `SECRETS_BACKEND` defaults to
  `openbao` in both wrappers (the plan gate is corrected to `grep -F`; the
  regex form mis-matched `${...}`); no `sops exec-env` in the mikrotik
  preflight ✓. Live read: `./with-secrets`, `./with-secrets-prod` and
  `./with-secrets-prod-tiny` print their PVE_ENV. The OpenBao audit log
  shows AppRole logins deploy-dev, deploy-pve and deploy-pve-tiny at
  20:04:22Z with exactly their own policies. **OpenBao is now
  authoritative.** Rollback: `SECRETS_BACKEND=sops`, valid only until the
  first rotation.
- **Post-cutover validation done.** The operator ran graylog-stack and
  harbor-stack on pve, and cse-panel-stack on pve-tiny, all via the OpenBao
  backend ("looks fine"). Claude re-verified with OpenBao-sourced
  credentials: Graylog root 200, Harbor admin 200, Harbor robot token 200,
  Harbor health 200, both UIs 200. The audit log shows deploy-pve and
  deploy-pve-tiny logins. The MikroTik preflight, now bootstrapped through
  `./with-secrets-prod`: 18/18 PASS.
- **Step 16 applied.** CLAUDE.md and `docs/reference/secrets-management.md`
  now describe the OpenBao model (`secrets/manifest.json` ×3 in CLAUDE.md,
  0 SOPS edit instructions).
- **Remaining:** step 15 (CI via GitHub OIDC) is only testable after a merge
  to `main`, so it is held for the operator's merge decision. Then block E
  (recovery test) and block F (SOPS retirement).
- **Merged to stable: PR #431 → `93939d61` (2026-09-28).** Operator's
  choice: merge the whole branch, including the 33 framework-dns /
  ai-stacks-pve-tiny commits it was cut on top of. CI triage: all 4 failing
  jobs are pre-existing (ruff in deep-research-agent/es_findings_ingest;
  Harbor-only violations in pterodactyl-lab/cse-*; 193 ansible-lint
  violations, none on this PR's lines; the self-hosted runner can't install
  sops). The pre-push run of the freeze hook blocked the push of the
  pre-freeze commit `321c5549`, so the hook is now `stages: [pre-commit]`.
  validate.yml runs PR checks only for PRs into `main`, so `sops-freeze`
  will first run, and flag `321c5549` as expected, on the stable → main PR.
- **Not yet promoted to main (operator: "not yet").** Step 15 (CI via
  GitHub OIDC) stays unapplied until `main` is promoted; `netbox-populate`
  keeps failing until then, as it already did.
- **Block E recovery test: PASS (`artifacts/e-recovery-test.sh`, 3rd run).**
  Throwaway LXC 20099 (no network, 127.0.0.1-only listener, destroyed
  after). A fresh OpenBao 2.7.0 + seal key from USB B + the newest NAS
  snapshot `openbao-20260927T200311Z-postwrite.snap` → `raft snapshot
  restore -force` → restored data auto-unsealed (`initialized True sealed
  False`) → root token recovered with the ORIGINAL recovery key (policies
  `['root']`) → 22 `services/*` entries, and the `GRAYLOG_ROOT_PASSWORD`
  sha256 matches live (`683313f7…`). Findings from runs 1–2 (fixed in the
  script): `pct exec` has no `/usr/local/bin` on PATH; and
  `bao operator generate-root -decode` calls the authenticated status
  endpoint (403), so decoding is done locally (base64(token XOR otp)).
  Test-only deviation: the scratch listener set
  `disable_unauthed_generate_root_endpoints = false`, because the
  breakglass AppRole is LAN-bound and the scratch CT had no network. A real
  rebuild at 192.168.20.16 uses the breakglass AppRole (proven in B4).
  **Acceptance criterion "Backup" met.**
- **Block F (SOPS retirement), code part, on branch `task/retire-sops`.**
  Step 15 applied: netbox-populate uses GitHub OIDC, and the
  sops-decrypt-check job is removed. It only takes effect on `main`. Both
  wrappers lost the SOPS path and `SECRETS_BACKEND` (the rollback is gone).
  Router scripts `cutover.sh` and `provision-hap-ax3.sh` no longer call
  `sops -d`; they were already broken, since `hAPax3_ADMIN` was never in
  SOPS. Agent instructions (AGENTS.md, copilot-instructions.md, both 401
  Copilot prompts) now describe OpenBao. `SOPS_AGE_KEY_FILE` was removed
  from `.env` and `.env.template`; SOPS wording was removed from `.env*`,
  the `with-secrets-prod*` headers, provision.sh, setup-dev-env.sh,
  README.md and terraform/README.md; `sops_source` was dropped from the
  manifest. Deleted: merge-sops-env.sh, check-required-sops-keys.sh,
  openbao_import_from_sops.py, secrets_parity_check.py,
  SECRETS_PVE_TEMPLATE.md. Checks: shellcheck clean, loader tests OK, all 4
  wrappers read OpenBao, no dangling references. **Operator:** `git rm` the
  six `terraform/secrets.*.enc.yaml` and `.sops.yaml` (the classifier blocks
  Claude from deleting them). **Follow-ups:** about 30 passing SOPS mentions
  in stack contracts and playbook comments; delete the `SOPS_AGE_KEY`
  GitHub secret after `main` is promoted.
- **SOPS files deleted (operator, `e2b26541`).** Post-retirement test
  battery (Claude), all green:
  - Static: loader, snapshot and edge unit tests OK; shellcheck clean on
    every wrapper and touched script; **67/67 playbooks** pass
    `--syntax-check`. The `terraform/lxc` suite has 8 failures, the **same
    8 as on `stable`** (6 in test_reconcile_edge, 1 in
    test_render_edge_coredns, pre-existing). Note: CLAUDE.md's repo-wide
    `unittest discover -s .` finds 0 tests (no packages), a pre-existing
    gap.
  - Secrets path: all 5 profiles read every field (`--check`: 119/117/119/
    118/118); boundary check OK; live logins with OpenBao-sourced creds
    10/10 × 200 (Graylog, Harbor admin + robot, Grafana, NetBox, Portainer,
    Authentik API, MikroTik read-only, OpenSearch, Proxmox API token);
    OpenBao unsealed; TLS-renew and nightly-snapshot timers scheduled; last
    snapshot OK.
  - Tooling: `terragrunt plan` authenticates via OpenBao creds.
    openbao-stack and graylog-stack: no changes. harbor-stack (stack dir):
    3 add / 1 destroy, where the destroy is only a `null_resource` SDN
    re-attachment plus generated local files (a pre-existing
    per-env-dir-vs-stack-dir state split, container untouched, **do not
    apply**). Edge reconcile dry-run: 51 noop, only the known EGR211.
    MikroTik preflight PASS.
  - Only cosmetic leftovers remain (error/hint strings naming old file
    paths).
- **Check-mode sweep (operator ran `artifacts/check-mode-sweep.sh`,
  2026-09-28): 28 stacks (21 pve, 7 pve-tiny) via `provision.sh --check`
  through the OpenBao-only wrappers.** Every stack reached a PLAY RECAP, and
  there were **zero missing or empty secret lookups anywhere** (no
  `mandatory()` failures). The cse-panel, cse-controller and cse-code-eval
  stacks were fully clean. All failures are check-mode artifacts: tasks
  reading results of uri/shell steps that check mode skips (Portainer
  token ×4, docker-live-usage index ×3, Technitium API token, Wazuh bcrypt
  hash, Greenbone and NetBox health waits, mcp-utility directory parse,
  secpipe temp file, OpenBao health report). The 4 possibly secret-bearing
  "changed" tasks were checked:
  - SearXNG seed: a run-once container that writes `settings.yml` only if
    absent;
  - pterodactyl `docker-compose.yml` and the NetBox bootstrap script: no
    secrets in them (the pterodactyl env file did **not** change);
  - VictoriaMetrics scrape config: the live file lacks the openbao-stack
    target (0 matches), and the scrape password in the live file hashes
    identically to the OpenBao value (`f99d7378…`), so the diff is only
    the new target.
  **Gap found:** step 07's scrape target and dashboard were never
  deployed, so monitoring-stack needs one real provision to show the
  OpenBao panel. Side finding: `portainer_agent` removes and restarts the
  agent container on every run (not idempotent; pre-existing).
- **monitoring-stack deployed (operator, `failed=0`, smoke test passed).**
  Verified: VictoriaMetrics has `up{stack="openbao-stack"}` = 1,
  `openbao_snapshot_last_run_success{kind="postwrite"}` = 1, and
  snapshot age ≈ 3.0 h (the nightly job first runs at 03:30). The Grafana
  dashboard `openbao` is present with 3 panels. Step 07 is now live.
- **Secrets inventory on the dashboard (`b13e45b1`).** A `metrics` AppRole
  (policy: list+read `kv/metadata/*` only, LXC-bound), with a 15-minute
  exporter taking field counts from the manifest. The operator ran
  configure, the openbao-stack provision, `artifacts/inventory-setup.sh`
  and the monitoring-stack provision (all `failed=0`). **No-values proof,
  from the audit log** (every request by a `metrics`-policy token):
  `kv/data` read DENIED, `kv/data` update DENIED, `kv/metadata` delete
  DENIED; the only successes were `kv/metadata` list ×5 and read ×31, plus
  login/revoke. Live: entries services 22 / shared 3 / hosts 5; fields
  96 / 20 / 13 (129); drift 0; 30 entries changed in the last 7 days (all
  imported today). Grafana `openbao` dashboard: 8 panels.
- **Reconciler fix, tidy-up and close-out (2026-09-28).** The edge
  reconciler defaults `grant_types` to `authorization_code` when it creates
  an OIDC provider (3 new unit tests; the create test fails without the
  fix). SOPS mentions were reworded to OpenBao across 46 files, and the
  NetBox threat-model data store now describes OpenBao. Checks: `--syntax-check` on the 8
  touched playbooks, NetBox integration tests 128/128, reconciler 35/35,
  loader 12/12. The metrics- and snapshot-credential steps from
  `artifacts/` were promoted to `scripts/openbao-issue-credentials.sh`
  (needed after a real rebuild), and `artifacts/` was emptied.
- **Note (applies throughout):** Claude Code's auto-mode classifier blocks production
  `provision.sh` runs, even with chat approval, so the operator runs them.
  The pve proxy-stack inventory targets `192.168.30.10` (checked).

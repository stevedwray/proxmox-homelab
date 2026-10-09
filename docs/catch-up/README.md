# catch-up (planning workspace)

Status: **planned 2026-09-28, nothing executed yet.**

This workspace turns the 2026-09-28 review of partly finished and unstarted
work into ordered plans. Every item was checked against the live platform
that day, not only against docs. The status corrections that came out of that
check were committed separately (`2bd565e4`, branch
`task/status-refresh-2026-09-28`). This workspace covers only work that is
really still open.

Plans follow [docs/agent-design/step-packet-schema.md](../agent-design/step-packet-schema.md).
Repo edits a local model can do safely are fenced `yaml` step blocks, each
under its own heading. Everything that touches production (`pve`, `pve-tiny`,
the MikroTik, PBS, GitHub settings) or needs a human is plain prose with exact
commands. Those always go through the production approval flow in `CLAUDE.md`:
preflight, the operator says "proceed", `TASK_APPROVAL=<name>`, execute,
after-action summary. The approval name for each action is given next to its
command.

## Order

| # | Plan | When | Effort | Value | Depends on | Status |
|---|---|---|---|---|---|---|
| 01 | [Arr UI port lockdown](01-arr-port-lockdown.md) | today | 45 min | High (live exposure) | — | **done 2026-09-28** (browser check confirmed by operator) |
| 02 | [Repo hygiene](02-repo-hygiene.md) | today | 45 min | Medium | — | **mostly done** — PRs #435–#439 open; worktree/branch cleanup waits for merges |
| 03 | [PBS retention + pve-tiny backups](03-pbs-retention-and-pve-tiny-backups.md) | today | 1.5–2 h (+ GC runtime) | **High** (PBS ~97% full) | — | **done 2026-09-28** |
| 04 | [Secrets refactor close-out](04-secrets-closeout.md) | 2026-09-29, after the 02:40 UTC run | 15 min | High | — | not started |
| 05 | [Decommission old AI CTs on pve](05-decommission-pve-source-cts.md) | **not before 2026-10-04** | 45 min | Medium | 03 | not started |
| 06 | [Run CI gates on PRs into `stable`](06-ci-gates-on-stable-prs.md) | this week | 30 min | Med-High | 02 | not started |
| 08 | [PentAGI residue cleanup](08-pentagi-residue-cleanup.md) | this week, **before 07** | 1–1.5 h | Medium | — | not started |
| 07 | [Baseline alerting (Discord)](07-baseline-alerting.md) | this week, after 08 | 1–2 sessions | **High** | 08 | not started |
| 09 | [Rotate high-value secrets](09-secret-rotation.md) | following weeks | 2–3 h, staged | Med-High | 04 | not started |
| 10 | [CI lint and policy cleanup](10-ci-lint-cleanup.md) | following weeks (soon after 06) | 2–3 h | Medium | 06 | not started |
| 11 | [gaming-stack-lab Terraform drift](11-gaming-stack-lab-terraform-drift.md) | following weeks | 30 min | Low-Med | — | not started |
| 12 | [MikroTik credential standardisation](12-mikrotik-credentials.md) | following weeks | 45 min | Low-Med | — | not started |
| 13 | [Tier 3 backlog](13-tier3-backlog.md) | as time allows | varies | Low-Med | — | not started |

Why this order, and what changed from the first draft of the list:

- **03 moved up to "today".** *(Premise corrected 2026-09-28: a PBS prune job already keeps the last 2 per group; see the plan's Correction section.)* The PBS datastore every `pve` backup goes to
  (`pbs-iscsi` = `192.168.1.12`, datastore `iscsi-backup`) had 36.5 GB free
  of 1.08 TB on 2026-09-28. The `pve` job keeps every backup forever
  (`prune-backups: keep-all=1`), so the next few nightly runs will fill it
  and every backup will start failing. Retention has to be fixed before
  pve-tiny is added to the same datastore.
- **05 can't run "tomorrow".** `docs/ai-stacks-pve-tiny/plan.md` Phase 4
  requires a 7-day soak after the 2026-09-27 cutovers and a verified
  post-import backup (plan 03) first. The earliest date is 2026-10-04.
- **06 before 10, and 10 soon after 06.** Once 06 turns the gates on for PRs
  into `stable`, every such PR shows the existing failures until 10 lands.
  The real ansible-lint failure count is 21, not 193 (the other 172 are
  warn-list warnings), so 10 is smaller than first estimated.
- **08 is residue cleanup, not a decommission.** Both PentAGI CTs (70010,
  70013) are already gone from `pve` (their `.conf` files don't exist,
  checked through the API 2026-09-28). What's left is firewall rules,
  scrape targets, Terraform state, secrets and one SSH key.
- **08 runs before 07.** Seven scrape targets are already down (coredns, three
  PentAGI, three old Minecraft/cAdvisor on gaming-stack-lab). 08 removes the
  PentAGI ones and 07 handles the rest, so "target down" alerts start clean.
- **11 and 12 shrank.** The gaming-stack-lab "workspace bug" no longer
  reproduces: a read-only `terragrunt plan` from the per-environment
  directory resolves real state (1 add, 1 in-place tag change). And 17 of
  22 MikroTik playbooks already use the admin credential, so the "no write
  permission" gap only affects 5 older playbooks.

## Decisions (operator, 2026-09-28)

| Question | Decision |
|---|---|
| How to close the arr direct-port exposure | MikroTik drop rule: UI ports on `192.168.80.11` reachable only from Traefik (`192.168.30.10`). No second arr login. |
| PBS retention | `keep-daily=7, keep-weekly=4, keep-monthly=6` |
| pve-tiny backup target | Same PBS datastore as `pve`, in its own namespace `pve-tiny`. Retention: the existing PBS prune job (keep-last 2) instead of 7/4/6, which was chosen under a wrong premise |
| Alert delivery | Discord webhook (URL stored in OpenBao) |

## Things this workspace found that aren't planned here

- **LAN reaches every zone directly.** Every zone's MikroTik rules deny
  traffic *leaving* the zone. Nothing restricts LAN → zone. Plan 01 closes it
  for the one service with no login of its own, but the platform-wide model
  (is the LAN trusted?) is a design question for a separate workspace.
- **Proxmox notifications** go to `mail-to-root` (sendmail to root@pam's
  address). Whether that address is set and mail actually leaves `pve` is
  unverified. Plan 07 routes Grafana alerts to Discord; routing Proxmox's
  own backup-failure notifications there too is listed in plan 13.

- **OpenBao nightly snapshots may not be running.** Only `kind="postwrite"`
  snapshot metrics exist in VictoriaMetrics; there's no `kind="nightly"`
  series. Plan 07 Part A checks it.
- **The NAS (`192.168.1.3`, 8 TB) is 84% full.** Plan 07 alerts at 90%, but
  nothing is planned to free space.
- **The Authentik LDAP service account shares the superuser password.**
  `AUTHENTIK_LDAP_SERVICE_PASSWORD` isn't set, so both playbooks fall back to
  `AUTHENTIK_SUPERUSER_PASSWORD`. Plan 09 §5a splits them before any rotation.
- Validation of these plans: every repo step's literal content was checked
  against the current files on 2026-09-28. Plan 01's playbook passes
  syntax-check and ansible-lint. Plans 07 and 10's playbook edits were applied
  as written to a scratch copy, passed their own gates (syntax-check, lint with
  0 failures), and were reverted. Plan 07's seven alert queries were run
  read-only against VictoriaMetrics.

## Workflow

- Branch for plan execution: cut `task/catch-up-<NN>-<slug>` from the current
  working HEAD per plan, not one long branch. Don't reuse `task/catch-up-plans`
  (this planning branch).
- Hand-backs go in the **Hand-backs** section below, newest last, one
  heading per step or operator action: what changed, each gate's actual
  result, anything surprising.
- Update the Status column in the Order table as plans complete.
- Transient notes and logs go in `docs/catch-up/artifacts/` (git-ignored).

## Hand-backs

### 01 — arr UI port lockdown (2026-09-28)

- `catchup-01-lockdown-playbook`: playbook committed (`ae374066`, branch
  `task/catch-up-01-arr-lockdown`); gates syntax-check, ansible-lint
  (0 failures, 0 warnings) and literal-values all passed.
- Pre-check: direct `7878/8989/8686/9696` → `200`, `8080` → `401`; all five
  Traefik routes `302`.
- Apply (`TASK_APPROVAL=catchup-01-arr-lockdown`): `failed=0`, both the
  match-criteria and order asserts passed (rule sits before `*8A`). The admin
  credential had write access; the RouterOS CLI fallback wasn't needed.
- Verify: direct access from the LAN now `000` on all five ports; Traefik
  routes still `302`; from the proxy host (`192.168.30.10`) the backends
  still answer (`200` ×4, `401` qBittorrent), so Traefik → backend works.
  Jellyseerr (`5055`, out of scope) is unchanged (`307`).
- Operator browser check via Authentik: all apps load. Plan 01 closed.

### 02 — repo hygiene (2026-09-28)

- Local `stable` fast-forwarded to `62e91a7c`.
- `fix/ark-update-workaround` gates: syntax-check of
  `update-ark-survival-ascended.yml` OK; egg JSON parses.
- PRs into `stable`: #435 `fix/ark-update-workaround`, #436
  `task/dns-stack-daemon-json-audit`, #437 `task/docker-log-driver-audit`,
  #438 `task/ci-gate-followups`, #439 `task/catch-up-01-arr-lockdown` (stacked:
  status refresh + these plans + plan 01; replaces separate PRs for
  `task/status-refresh-2026-09-28` and `task/catch-up-plans`).
- Deleted the seven branches fully contained in `main`, local and remote
  (each confirmed 0 commits outside `origin/main` first).
  `git branch -d feat/secrets-openbao` initially refused (upstream-tracking
  check), and the loop deleted its remote anyway. This was a deviation from
  "treat a refusal as stop": the remote delete wasn't gated on the local one.
  Verified afterwards that nothing was lost: 0 commits outside `origin/main`,
  empty diff, tip `48fe078f` is an ancestor of `main`.
- Still to do after merges: remove the two `.claude/worktrees/` worktrees and
  their `worktree-agent-*` branches; delete the merged PR branches.

### 03 — PBS (2026-09-28): stopped at A1

- A1 baseline: pve job retention `keep-all=1`; PBS datastore `iscsi-backup`
  has prune job `s-d37cf2f8-fb09` (every 2 h, `keep-last=2`) and GC daily 03:00
  (last run OK, removed 10.4 GB). This is the plan's own stop condition. A2–A5
  were not run and are superseded (see the plan's Correction section).
- Space breakdown recorded in the plan. Awaiting operator decision on deleting
  dead-guest groups `112`, `115`, `104` and on excluding long-stopped guests.
  Part B (pve-tiny) not started: needs that space plus GUI steps (namespace,
  storage password).

### 03 Part A (replacement) — reclaim PBS space (2026-09-28)

Operator decisions: stopped guests are not to be backed up; delete the
dead-guest backups.

- pve job `backup-8b90fc3e-c3a5` exclude list changed `105,910` →
  `100,103,105,106,108,109,110,111,113,116,120,910,40014,50011,50012,50013`
  (every guest stopped at that moment: CTs 100 torrent-stack, 103
  gaming-stack-legacy, 109 security-stack, 110 analysis-stack, 116 ai-stack,
  40014/50011/50012/50013 old AI copies; VMs 106 securityonion, 108
  securityonion-idh, 111 wifi-analysis, 113 pve-test-vm, 120 metasploitable).
  Their last two snapshots stay on PBS as an archive. **If any of these is
  started again, remove it from the exclude list or it won't be backed up.**
- Deleted the six snapshots of guests that no longer exist (no config on
  pve): `ct/104` ×2 (cloud-stack), `ct/112` ×2 (elastic-stack), `ct/115` ×2
  (scanning-stack), via `pvesh delete /nodes/pve/storage/pbs-iscsi/content/<volid>`.
- Manual GC on `iscsi-backup`: TASK OK, removed 193.1 GiB (101,433 chunks);
  on-disk usage 727.4 GiB, dedup factor 5.08.
- `pvesm status`: 72.33% used, 238,396,212 KiB (~244 GB) available, above
  the 216 GB gate for Part B.
- Part B next: operator does B1 (namespace `pve-tiny` in the PBS GUI) and B2
  (add `pbs-iscsi` storage on pve-tiny, which needs the PBS root password);
  then B3–B6 can run.

### 03 Part B — pve-tiny backups (2026-09-28)

- B1/B2 (operator, GUI): namespace `pve-tiny` created; pve-tiny storage
  `pbs-iscsi` added (server `192.168.1.12`, datastore `iscsi-backup`,
  namespace `pve-tiny`, `root@pam`, fingerprint `2b:44:…:00:fd`, verified
  live via `proxmox-backup-manager cert info`). `pvesm status`: active.
- B3: job `48087a29-1142-49ac-b304-756e2b86bc3c`: all guests, daily 12:30,
  snapshot mode, `exclude 910` (stopped template), **no job-level prune**.
  PBS prune job `s-d37cf2f8-fb09` has no `ns`/`max-depth`, so it recurses
  into `pve-tiny` and keeps the last 2, the same policy as pve. This replaces
  the 7/4/6 retention from the original plan.
- B4: 40014/50011/50012/50013 mount points all `backup=1`.
- B5: `vzdump 40014 50011 50012 50013`: real snapshot mode (no suspend
  fallback), "Backup job finished successfully", task `OK`. Uploaded ~8.5 GiB
  compressed in total.
- B6 (Phase 4 requirements 2–3 of docs/ai-stacks-pve-tiny/plan.md):
  - `pbs-iscsi:backup/ct/40014/2026-09-28T05:18:11Z`: hostname opensearch-stack, rootfs + mp0 + mp1 (`/var/lib/opensearch-data`), all backup=1
  - `pbs-iscsi:backup/ct/50011/2026-09-28T05:18:59Z`: hostname mcp-utility-stack, rootfs + mp0
  - `pbs-iscsi:backup/ct/50012/2026-09-28T05:19:46Z`: hostname secpipe-stack, rootfs + mp0
  - `pbs-iscsi:backup/ct/50013/2026-09-28T05:20:00Z`: hostname ai-services-stack, rootfs + mp0
- Step `catchup-03-record-backup-policy` done (row added to
  docs/ai-stacks-pve-tiny/README.md; gate `row-present` prints 1).
- Plan 05's backup prerequisite is met; its 7-day soak still runs to 2026-10-04.

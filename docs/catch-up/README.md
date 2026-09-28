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
| 01 | [Arr UI port lockdown](01-arr-port-lockdown.md) | today | 45 min | High (live exposure) | — | **done 2026-09-28** (browser spot-check pending) |
| 02 | [Repo hygiene](02-repo-hygiene.md) | today | 45 min | Medium | — | not started |
| 03 | [PBS retention + pve-tiny backups](03-pbs-retention-and-pve-tiny-backups.md) | today | 1.5–2 h (+ GC runtime) | **High** (PBS ~97% full) | — | not started |
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

- **03 moved up to "today".** The PBS datastore every `pve` backup goes to
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
| pve-tiny backup target | Same PBS datastore as `pve`, in its own namespace `pve-tiny` |
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
- Open: operator browser spot-check (log in via Authentik, open each app).

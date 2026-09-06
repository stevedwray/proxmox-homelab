# Harbor Image Sourcing — Lessons Learned

This document captures durable, reusable lessons from the Harbor
image-sourcing enforcement work (see `image-sourcing-enforcement.md` for
the full findings and rollout) so future work does not need to rediscover
the same failure modes from scratch. Several of these are more general
than Harbor specifically and apply repo-wide.

## Lessons

### 1. Harbor's registry auth realm always echoes back `external_url`'s scheme, regardless of how the client connected

- Harbor's registry always answers a pull's initial `401` with
  `WWW-Authenticate: Bearer realm="<external_url scheme+host>/service/token"`
  — this is fixed by `external_url` in `harbor.yml`, not by which
  host/port/scheme the client actually used to reach it.
- If `external_url` is `https://` (because TLS is terminated externally by
  Traefik, which is this repo's setup) but a client pulls against Harbor's
  raw container IP over plain HTTP, the initial request succeeds, but the
  subsequent token fetch tries HTTPS on port 443, which Harbor doesn't
  serve internally — the pull fails with a TLS/connection error that looks
  like a cert problem but is really a routing problem.
- Always route Docker Hub/GCR/GHCR/quay pulls through a `*_registry_host`
  resolved from `LAB_FQDN_HARBOR` (the FQDN, routed through Traefik), never
  `LAB_IP_HARBOR`/the raw `registry_host` inventory var. Confirmed live on
  both pve-test-vm and `pve`.

### 2. `gh` CLI silently prefers `GH_TOKEN`/`GITHUB_TOKEN` env vars over its own keyring-stored login

- This is `gh`'s documented precedence, but it's easy to forget: any
  process environment carrying `GH_TOKEN` or `GITHUB_TOKEN` overrides
  `gh auth login`'s stored session completely, with no warning that it's
  happening.
- `with-secrets` injects secrets repo-wide into every wrapped process. A
  SOPS secret that happened to be named `GITHUB_TOKEN` (originally meant
  for a narrow, unrelated purpose — `mcp-utility-stack`'s read-only CVE
  lookups) silently shadowed the operator's actual `gh auth login` session
  for *any* `gh` command run through `with-secrets`, including ones with
  nothing to do with `mcp-utility-stack`.
- The failure mode is confusing: `gh auth status` reports success, and the
  same command run outside `with-secrets` works fine — the 403 only
  appears inside the wrapped environment, which looks like a permissions
  or auth problem rather than an env var collision.
- Fixed two ways: (a) tasks that need the real `gh` session now explicitly
  clear `GH_TOKEN`/`GITHUB_TOKEN` via Ansible's per-task `environment:`
  block; (b) the SOPS secret was renamed to `MCP_GITHUB_TOKEN`. Prefer
  never naming a secret `GITHUB_TOKEN`/`GH_TOKEN` repo-wide, even for an
  unrelated purpose — those names are reserved by `gh` CLI's own
  precedence rules.

### 3. `sops --set` and `sops unset` take their arguments in opposite order

- `sops --set '["key"] "value"' FILE` — the flag form takes the
  path-and-value expression first, file last.
- `sops unset FILE '["key"]'` — the subcommand form takes the file
  **first**, then the path.
- Getting this backwards produces `Invalid unset index format`, which
  doesn't make the actual mistake (argument order) obvious — it reads like
  a syntax problem with the path expression itself.

### 4. The homelab root CA has been rotated without a mechanism to propagate it to already-provisioned hosts

- Two different certificates, both named "Homelab CA Root CA" but with
  different fingerprints, were found across the pve-test-vm fleet — one
  host (`ci-runner-01`, not redeployed in a while) still trusted an older
  one that no longer matches what Traefik/step-ca actually present.
- This produces a TLS failure (`certificate signed by unknown authority`)
  that looks like a Harbor or cert-issuance bug but is really just a stale
  local copy of the CA on one host.
- Before chasing a TLS failure as something more exotic, compare
  `openssl x509 -in /usr/local/share/ca-certificates/homelab-root.crt
  -noout -fingerprint` against a known-good, recently-redeployed host.
- Checked on `pve` production during this work — no mismatch found there
  (all 6 hosts sampled matched). The gap exists, but hasn't caused a
  problem in production yet; still worth a real fix separately (this
  session only worked around it on the one affected pve-test-vm host).

### 5. An unconditional task hiding inside an otherwise-correctly-conditional fallback block is easy to miss in review

- `monitoring-stack`'s DNS-fallback block had five tasks, four of them
  correctly gated on `monitoring_dns_fallback_needed` — and one, the
  actually consequential one (rewriting compose images to bypass Harbor),
  with no `when:` at all. It ran unconditionally on every single deploy,
  regardless of whether Harbor was actually unreachable.
- The bug hid in plain sight because every *sibling* task in the same
  block had the guard — a skim-review would see the pattern and assume
  it applied uniformly.
- When reviewing (or adding to) a block of "only if X" fallback tasks,
  check that literally every task in the block has the guard, not just
  most of them — especially the one that actually does something
  consequential.

### 6. `ansible-playbook --check` isn't safe to treat as risk-free validation for every playbook

- Several tasks that make a real, synchronous external call have no
  meaningful way to simulate their own success in check mode, and fail
  predictably every time regardless of whether anything is actually
  wrong: a `gh api` token-generation call, a live login against a
  freshly-created service (Technitium's API), a `docker inspect`
  health-poll waiting on a container that check mode never actually
  created.
- Don't chase these as real bugs on sight. If everything earlier in the
  same play ran clean and the failure is a check-mode-specific artifact
  unrelated to your own change, skip straight to a live run rather than
  spending time trying to make `--check` pass for a task that structurally
  can't.

### 7. Ad hoc `terragrunt plan`/`apply` can silently target the wrong Terraform workspace

- `.env.pve-test-vm` never set `TF_WORKSPACE`, so it fell back to the base
  `.env`'s `TF_WORKSPACE=default` — an empty workspace with no state, even
  though real state existed under `terraform.tfstate.d/pve-test-vm/`.
- The symptom is misleading: a `terragrunt plan` against a stack that's
  demonstrably live and healthy shows a full resource recreation instead
  of zero diff, because it's reading the wrong (empty) workspace's state,
  not because anything is actually wrong.
- Confirm `TF_WORKSPACE` matches the environment you're actually targeting
  (`.env.pve` and `.env.pve-framework` already set this correctly;
  `.env.pve-test-vm` was the one missing it, now fixed) before trusting an
  ad hoc plan's output.

### 8. A stack's "deploy" playbook can be the wrong tool for a narrow live fix — and planning docs can go stale about ground truth, not just decisions

- This doc itself claimed `minecraft-wildworks`'s live rollout was "on hold
  indefinitely... no live rollout planned or pending." That was wrong about
  actual state: Foreverworld had already been deployed to `gaming-stack-lab`
  outside this branch's tracked process, and was actively being played
  (`level.dat` written 15 seconds before a live check). A stale doc read as
  confidently as a correct one — the only way to catch it was direct
  inspection of the live host (`docker ps`, file timestamps) immediately
  before acting, not trusting the doc's own prior "not deployed" note.
- Separately: `deploy-minecraft-wildworks.yml` is written as a from-scratch
  release deploy (mandatory release-tarball/legacy-ops/whitelist file
  inputs, unconditional `server.properties` rewrite, full compose-file
  replacement). Running it against an already-live, already-correctly-
  configured server to fix nothing but an image registry path would have
  been the wrong tool — it risks resetting live settings that may have
  drifted from the hardcoded template, or changing the pinned mod/loader
  version if the release differs from what's actually running. Compare the
  live compose/config against what the "deploy" playbook would produce
  *before* running it; if they already match apart from the one thing
  you're fixing, a targeted hand-edit (with a preflight and post-verify)
  is safer and easier to reason about than the general-purpose deploy path.
- RCON auth failed on an ad-hoc `rcon-cli` check because the password lives
  in `server.properties`/an env secret that isn't available to a bare
  `docker exec` from an unrelated shell session. `mc-monitor`'s own
  Prometheus metrics endpoint (`/metrics`, `minecraft_status_players_online_count`)
  gives the same live player-count answer without needing RCON credentials
  at all — prefer it for a quick "is anyone on" check.

### 9. Ad-hoc `ansible -m shell -a "..."` commands leak fully-expanded secrets to Graylog — use `environment:`/`args` + `no_log: true` instead

- `ansible <host> -m shell -a "docker exec -e PGPASSWORD=${SECRET} ..."`
  gets its **fully expanded** command line — including any interpolated
  secret value — logged via the target host's own syslog forwarding
  (`rsyslog_forward` → Graylog), tagged `application_name:
  ansible-ansible.legacy.command`, `"Invoked with _raw_params=..."`. This
  happens regardless of `with-secrets`/`with-secrets-prod` scoping, because
  the leak is on the *target* host's side, not the controller's — the
  wrapper correctly keeps the secret out of your own shell history and
  process list, but the moment it's interpolated into a `command`/`shell`
  module's raw text and sent to a managed host, that host's own audit
  logging can capture it independent of anything the controller does.
  `HARBOR_DB_PASSWORD` was exposed this way during the scan-coverage
  investigation above (2026-08-15) — required rotating it on both `pve` and
  pve-test-vm (shared value) same day.
- **Fix, verified empirically before trusting it:** write a real task (not
  an ad-hoc `-a` string) using the module's structured `environment:` and
  `args:` (e.g. `args: stdin: "..."`) keywords instead of concatenating the
  secret into `cmd`/`_raw_params`, with `no_log: true` on the task. Tested
  with an obviously-fake marker value first (searched Graylog afterward,
  zero results), *then* used the identical pattern for the real password
  rotation — the ad-hoc form doesn't support `no_log` at all, which is
  what made it unsafe by construction, not just unlucky.
- General takeaway: any command whose args a managed host would echo to
  its own log/audit path (not just `ansible -m shell -a`, potentially also
  interactive `ssh host 'cmd with $SECRET'`) carries the same risk. Prefer
  a proper module + `no_log: true`, or a file transferred out-of-band
  (`copy`/`template` with `no_log: true`) read server-side, over building
  a secret directly into a shell command string sent to a remote host.

### 10. `harbor_installer`'s idempotency check looks at whether *any* installer is extracted, not whether it's the *requested* version

- Passing `-e harbor_installer_version=2.15.2` to `deploy-harbor-stack.yml`
  silently did nothing the first time — the role's very first task (`Check
  if Harbor installer has already been extracted`) only checks whether
  `{{ install_dir }}/harbor/install.sh` exists at all, and every subsequent
  download/extract task is gated on that single `stat` being false. Since
  2.14.3 was already extracted there, the whole download-a-different-version
  block was skipped, `harbor.yml` got templated with the new version string
  but nothing else changed, and Harbor kept running the old binary — while
  `ansible-playbook` still reported `changed` and a clean run.
- The tell was checking `GET /api/v2.0/systeminfo` afterward and seeing the
  version hadn't actually moved, despite a "successful," `changed=N` run.
  Don't trust a clean playbook run alone as proof a version bump took
  effect — verify the running version directly.
- To force a genuine re-download, remove the extracted installer directory
  first (`ansible.builtin.file: path=.../harbor state=absent` — **not**
  `rm -rf` via ad-hoc shell, which the permission classifier correctly
  treats as more dangerous-looking even when the target is safe) — targeted
  at the installer scaffold only, never the separate data volume
  (`harbor_installer_data_volume`, a different path specifically so this
  stays safe).
- **Recurred identically on `pve`, a second independent environment,
  during the same session's production rollout** — same silent no-op
  (`changed=4`, version unchanged), same fix (`changed=7` once the
  scaffold was removed). Two-for-two is enough to call this a real bug in
  the role rather than a one-off gotcha to remember by hand each time.
- **Fixed at the source (2026-08-15).** The `stat`-on-`install.sh` gate is
  replaced with a version marker file
  (`{{ harbor_installer_install_dir }}/.installed_version`, written only
  after a successful unpack, so a failed/interrupted download is never
  mistaken for a completed install). The scaffold is now removed
  automatically on any marker mismatch — including "no marker at all",
  which covers installs that predate this fix — instead of needing the
  manual `file: state=absent` workaround. Validated on pve-test-vm across
  all three paths: missing marker forces a real reinstall (`changed=7`),
  matching marker stays a true no-op (`changed=1`, all download/extract/
  unpack/marker-write tasks report `skipping`), and a deliberately
  corrupted marker forces reinstall and self-heals back to the correct
  version — tested by writing a fake `9.9.9-fake` marker and confirming
  Harbor came back reporting the real, correct version (`2.15.2`)
  afterward, at zero risk since it's reinstalling the version already
  running.

### 11. A Harbor major-version upgrade can be a one-way door — verify rollback works *before* trusting it's available, not after you need it

- Upgraded pve-test-vm's Harbor 2.14.3 → 2.15.2 to test a suspected fix
  (see `image-sourcing-enforcement.md`'s scan-coverage investigation).
  Confirmed the upgrade doesn't even fix the thing it was tested for, so
  tried reverting to 2.14.3 — and that broke Harbor outright: `harbor-db`'s
  schema had migrated forward, and — not mentioned in anything read
  beforehand — **2.15.2 replaced Redis with Valkey** as the cache backend.
  2.14.3's older `redis-photon` image couldn't read the now-Valkey-formatted
  data; both `redis` and `harbor-jobservice` crash-looped, `harbor-core`
  never reported healthy through a full 300s retry window.
- Recovered by moving forward to 2.15.2 again (not backward) — full health
  restored within a minute, since that state had already been proven to
  work moments earlier.
- General takeaway: a version bump that "should" be reversible by just
  re-pointing at the old version tag often isn't, once the app has touched
  its own persistent state (DB schema, cache format) on first boot at the
  new version. If a test upgrade might need reverting, that reversibility
  is itself something to verify empirically, ideally on a disposable/
  snapshotted target — not something to assume from the version numbers
  alone. This is exactly why the test happened on pve-test-vm and not `pve`.

## Suggested Use

- Read this document before starting the next piece of Harbor-adjacent
  work, or before debugging a `gh`/SOPS/TLS-shaped failure that looks
  unfamiliar.
- Prefer updating this file when new work teaches a reusable operational
  lesson, rather than letting it live only in a session transcript.
- See `image-sourcing-enforcement.md` for the full findings, decisions,
  and rollout status these lessons were drawn from.

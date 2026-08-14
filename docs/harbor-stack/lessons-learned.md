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

## Suggested Use

- Read this document before starting the next piece of Harbor-adjacent
  work, or before debugging a `gh`/SOPS/TLS-shaped failure that looks
  unfamiliar.
- Prefer updating this file when new work teaches a reusable operational
  lesson, rather than letting it live only in a session transcript.
- See `image-sourcing-enforcement.md` for the full findings, decisions,
  and rollout status these lessons were drawn from.

# Codex Continuation Handoff

Date: 2026-05-24
Branch: `work/productionize-06-canary-validation`

## Operator Goal

Validate that the production `pve` infrastructure foundation can be torn down
and rebuilt from source while leaving every out-of-scope guest on `pve`
untouched.

The operator specifically does not want to keep fixing partially mutated
containers in place. The proof target is a clean infra-only teardown/rebuild
cycle on `pve`.

## Collaboration Boundary

The operator wants this Codex session to focus on planning, review, assessment,
and small edits. Substantive development or live execution work should usually
be handed off to GitHub Copilot with a required tracked handback.

Small direct actions that have been acceptable:

- short doc corrections
- small wrapper/env edits
- commits of reviewed artifacts
- reviewing Copilot handbacks
- producing focused Copilot prompts

## Current Git State At Handoff Creation

Working tree was clean when this handoff was created.

Recent commits:

- `613c5cc` `fix(prod): preserve template and netbox recovery findings`
- `b1e14de` `fix(prod): align production env wrapper baseline`
- `6a43605` `docs(prod): harden pve teardown execution packet`
- `120924d` `docs(prod): summarize latest pve teardown review state`
- `23b57ae` `chore(prod): single-source harbor oidc primary auth mode`

Important stash:

- `stash@{0}`: `netbox in-place recovery debug patch`

Do not apply `stash@{0}` during the full rebuild retry. It contains an
in-place NetBox recovery/debug patch with a known admin-sync recursion bug.

## What Was Learned

### Template parity

The `pve` and `pve-test` template filenames matched, but the artifacts differed.
That is now fixed.

Current known-good template checksum on both hosts:

`39a697a4e7c121b18d8dfd8d70a3845d10f0df04ba0f50a8d3abab3c10bf2250`

Old `pve` template backup:

`/storage/template/template/cache/debian-13.1-2-docker-template.tar.gz.20260523-215218.bak`

Tracked evidence:

- `docs/productionize-refactor/handoffs/23-pve-template-parity-handback.md`

### Post-template recreate result

`netbox-stack` and `portainer-stack` were recreated after template parity.
The same failures remained, so template drift was not the root cause for those
remaining failures.

Tracked evidence:

- `docs/productionize-refactor/handoffs/24-post-template-recreate-handback.md`

### Environment wrapper parity

The wrappers used to compose non-secret environment differently:

- `with-secrets`: `.env` + `.env.pve-test` + test SOPS
- `with-secrets-prod`: `.env.pve` + prod SOPS

This was fixed in `b1e14de`.

Current model:

- `with-secrets`: `.env` + `.env.pve-test` + `terraform/secrets.enc.yaml`
- `with-secrets-prod`: `.env` + `.env.pve` + `terraform/secrets.pve.enc.yaml`

`.env.pve` is now a small production overlay.

### Keyctl delegation

`configure-keyctl.yml` fell back to `pve-test.gibbsgreatly.xyz` when
generated direct-access inventories omitted `pve_host`. This was fixed by
making `terraform/lxc/templates/inventory.tpl` emit `pve_host` whenever it is
non-empty, not only for ProxyJump inventories.

Committed in `613c5cc`.

### CoreDNS publication

During in-place NetBox recovery, production CoreDNS was found to be serving a
stale zone missing `harbor.lab.gibbsgreatly.xyz`. Running `dns-stack`
provision republished the generated zone and fixed resolution from VMID `40012`.

This supports the decision to prove behavior through a full clean rebuild
rather than continuing ad hoc in-place fixes.

### NetBox in-place recovery

The in-place recovery path fixed the original blockers but introduced or exposed
a new admin-bootstrap failure. The uncommitted patch was stashed because it is
not suitable for the clean rebuild proof.

Tracked evidence:

- `docs/productionize-refactor/handoffs/25-netbox-pve-recovery-handback.md`

Known issue in stashed patch:

- `deploy-netbox-stack.yml` admin-sync superuser call was accidentally nested
  inside `ensure_admin_user()`, causing recursion.

### Secret key-surface parity

The non-secret env baseline convergence is now complemented by a narrow secret
key-surface cleanup.

Current state:

- prod SOPS now includes the keys that previously existed only in
  `terraform/secrets.enc.yaml`
- no existing prod secret values were intentionally changed during this cleanup
- the remaining key-surface difference is intentional:
  `PORTAINER_ADMIN_PASSWORD` exists only in production

This means the remaining NetBox issue should not be treated as missing secret
keys on `pve`.

## Status Since Handoff Creation

The fresh full infra-only teardown/rebuild retry has already completed and
failed.

Tracked outcome:

- `docs/productionize-refactor/handoffs/26-pve-infra-teardown-rebuild-retry-handback.md`

What that retry proved:

- all approved in-scope destroy phases succeeded
- eight stacks rebuilt and provisioned successfully
- `netbox-stack` apply succeeded
- `netbox-stack` provision then hung at `Create superuser if not exists`
- `portainer-stack` was not rebuilt because execution stopped at NetBox

Current practical state on `pve`:

- present:
  - `10063` `ci-runner-01`
  - `20010` `authentik-stack`
  - `20011` `step-ca`
  - `20012` `monitoring-stack`
  - `20013` `dns-stack`
  - `30010` `proxy-stack`
  - `40010` `harbor-stack`
  - `40011` `apt-cacher-stack`
  - `40012` `netbox-stack`
  - `910` `debian13-template-builder`
- absent:
  - `20020` `portainer-stack`

This means the broad parity/root-cause search has narrowed substantially. The
next task should focus on the source-controlled NetBox day-2/bootstrap path,
not on repeating the full rebuild immediately.

## Recommended Next Copilot Scope

Use a narrow Copilot handoff to fix and validate the NetBox bootstrap logic on
the existing `netbox-stack`.

Prepared handoff:

- `docs/productionize-refactor/handoffs/28-netbox-day2-bootstrap-fix.md`
- `docs/productionize-refactor/handoffs/29-netbox-memory-rerun.md`

## Review Rules For The Next Session

When Copilot returns from the narrow NetBox task, review the handback before
trusting the result.

Do not accept a success claim unless the handback and evidence show:

- the exact bootstrap command(s) that were blocking were identified
- the source-controlled fix path is explained
- `stash@{0}` was not applied
- targeted validation stayed scoped to `netbox-stack`
- the resulting live state of `netbox-stack` is captured
- any remaining risks or operator follow-ups are explicit

If a stack fails:

- stay in recovery/rebuild assessment mode
- do not move to functional tests
- do not broaden scope without explicit operator approval
- prefer a narrow Copilot handoff over manual in-place mutation

## Current Practical Next Step

Hand off the narrow NetBox day-2/bootstrap fix to Copilot using:

- `docs/productionize-refactor/handoffs/28-netbox-day2-bootstrap-fix.md`
- `docs/productionize-refactor/handoffs/29-netbox-memory-rerun.md`

The immediate next execution step should be the targeted memory-bump apply and
rerun handoff in `29`, because the prior validation was blocked by a
non-responsive `1 GiB` NetBox container under severe pressure.

If that targeted rerun succeeds and `netbox-stack` can be reprovisioned
cleanly, the next decision is whether to restore `portainer-stack`
operationally first or schedule another full infra-only proof run.

If the targeted fix fails, keep the work bounded to NetBox bootstrap diagnosis
rather than broadening back into platform-parity or full-teardown work without
explicit operator approval.

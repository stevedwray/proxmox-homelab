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

Two substantive execution slices have completed since this handoff was first
written.

### NetBox recovery completed

Tracked outcomes:

- `docs/productionize-refactor/handoffs/26-pve-infra-teardown-rebuild-retry-handback.md`
- `docs/productionize-refactor/handoffs/28-netbox-day2-bootstrap-fix-handback.md`
- `docs/productionize-refactor/handoffs/29-netbox-memory-rerun-handback.md`

What this proved:

- the failed rebuild retry really did stop at NetBox day-2 bootstrap
- the NetBox bootstrap path was repaired in source
- `netbox-stack` memory was raised to `4096`
- targeted production rerun proved `./scripts/provision.sh --stack netbox-stack`
  now succeeds on `pve`

### Fresh full proof rerun also completed and failed

Tracked outcome:

- `docs/productionize-refactor/handoffs/30-pve-infra-proof-rerun-handback.md`

What that full proof rerun proved:

- all 10 approved in-scope destroy phases succeeded
- all 10 approved in-scope apply phases succeeded
- 9 of 10 approved provision phases succeeded
- `netbox-stack` stayed fixed during the full proof run
- `portainer-stack` CT `20020` was recreated on `pve`
- the only remaining blocker is `portainer-stack` provision

What that failure did not prove:

- it did not prove an Authentik apply-path bug yet
- it proved the first blocker is Portainer edge target preflight:
  `EGR200` because `reconcile-edge.py` still shells out through
  `./with-secrets`, which expects `pve-test`
- Authentik-owned Portainer route objects were discovered missing, but the
  reconcile remained in `dry-run`, so the creation path was not actually
  exercised

### Portainer targeted recovery completed

Tracked outcome:

- `docs/productionize-refactor/handoffs/31-portainer-prod-targeting-fix-handback.md`

What that targeted recovery proved:

- the Portainer blocker was the production target-preflight path in
  `reconcile-edge.py`
- `EGR200` was resolved by making the preflight wrapper target-aware
- Portainer reconcile reached real apply mode on `pve`
- the previously missing Authentik-owned Portainer route objects were created
- targeted `./with-secrets-prod ./scripts/provision.sh --stack portainer-stack`
  succeeded

Current practical state on `pve` after the failed full proof rerun:

- present:
  - `10063` `ci-runner-01`
  - `20010` `authentik-stack`
  - `20011` `step-ca`
  - `20012` `monitoring-stack`
  - `20013` `dns-stack`
  - `20020` `portainer-stack`
  - `30010` `proxy-stack`
  - `40010` `harbor-stack`
  - `40011` `apt-cacher-stack`
  - `40012` `netbox-stack`
  - `910` `debian13-template-builder`

This means the broad infrastructure blockers have now been reduced and cleared
one by one: NetBox recovery succeeded, then the narrow Portainer production
targeting blocker was fixed and validated in isolation.

## Recommended Next Copilot Scope

Use a fresh Copilot handoff to run another full infra-only proof on `pve` from
the now-repaired branch state.

Prepared handoff:

- `docs/productionize-refactor/handoffs/32-pve-infra-proof-rerun-after-portainer-fix.md`

## Review Rules For The Next Session

When Copilot returns from the next full proof rerun, review the handback before
trusting the result.

Do not accept a success claim unless the handback and evidence show:

- the run started from the branch state that already includes the verified
  NetBox and Portainer recovery fixes
- `stash@{0}` was not applied
- fresh planner/preflight evidence path
- fresh execution evidence path
- every in-scope stack destroy/apply/provision result
- post-redeploy validation result
- whether `portainer-stack` was restored cleanly during the full packet
- direct verification that out-of-scope guests remained untouched
- no misleading completion summary that contradicts failed logs

If the next full proof rerun fails:

- stay in recovery/rebuild assessment mode
- do not move to functional tests
- do not broaden scope without explicit operator approval
- prefer a narrow Copilot handoff over manual in-place mutation

## Current Practical Next Step

Hand off the next fresh full infra-only proof rerun to Copilot using:

- `docs/productionize-refactor/handoffs/32-pve-infra-proof-rerun-after-portainer-fix.md`

If the full proof succeeds, the next phase is post-proof assessment and then
functional/application follow-up.

If the full proof fails, stay in recovery/rebuild assessment mode and classify
the new blocker before broadening scope.

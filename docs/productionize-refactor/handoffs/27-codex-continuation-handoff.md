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

### Latest full proof rerun stopped in Harbor destroy

Tracked outcome:

- `docs/productionize-refactor/handoffs/32-pve-infra-proof-rerun-after-portainer-fix-handback.md`

What that rerun proved:

- the run started from the repaired NetBox plus Portainer branch state
- preflight and advisory review passed on `pve`
- `portainer-stack`, `netbox-stack`, and `monitoring-stack` destroyed cleanly
- the run then stopped at `harbor-stack` destroy because the Proxmox delete
  task for CT `40010` exceeded the provider's 60-second delete timeout

What happened after the stop:

- the failed proof run was treated as failed, not resumed
- operator investigation on `pve` showed the Harbor delete was stuck in
  `zfs destroy -r storage/subvol-40010-disk-0`
- the stuck Harbor cleanup was cleared manually on `pve`
- the operator has since manually shut down and removed the in-scope
  infrastructure containers on `pve`
- the environment should now be treated as a fresh-empty infra starting state
  for the next proof run, subject to verification by fresh preflight inventory

Current practical starting assumption on `pve`:

- out-of-scope guests remain protected and must stay untouched
- the approved in-scope infrastructure CTs should be assumed absent because the
  operator manually removed them after the invalid/incomplete proof attempts

This means the broad functional blockers have been reduced and cleared one by
one: NetBox recovery succeeded, then the narrow Portainer production targeting
blocker was fixed and validated in isolation. The next proof run should now
behave more like a clean redeploy from absence than a destroy/redeploy from a
fully populated starting point.

### Fresh proof rerun from manual removal completed mechanically but not cleanly

Tracked outcome:

- `docs/productionize-refactor/handoffs/34-pve-infra-proof-rerun-after-manual-removal-handback.md`

What that rerun appears to have proved:

- the target-aware harness path can rebuild the approved in-scope production
  infrastructure CT set from an operator-emptied start state on `pve`
- all 10 in-scope stacks were recreated and provision logs were reported for
  the full stack set
- browser smoke after the run showed `authentik`, `portainer`, and `grafana`
  working

What it did not prove cleanly:

- the handback cites sibling-worktree evidence paths rather than repo-visible
  tracked evidence under the main repo tree
- the harness final validation is still too shallow for Harbor Authentik SSO
  and NetBox browser correctness
- the handback's `passed` conclusion conflicts with direct browser validation
  from the operator

Direct post-run browser findings from the operator:

- `authentik`: fine
- `portainer`: fine
- `grafana`: fine
- `harbor`: app up, but Authentik login does not work
- `netbox`: not working; browser shows HTTP `400`

Working interpretation:

- the broad infra lifecycle is much closer to the `pve-test` behavior now
- the remaining issues are narrowed to two application-facing regressions on
  `pve`: Harbor Authentik login and NetBox route/app behavior
- the correct next move is not another broad proof rerun; it is two focused
  follow-up slices with better evidence and stronger functional validation

### Harbor follow-up completed; NetBox issue no longer reproducing

Tracked outcome:

- `docs/productionize-refactor/handoffs/35-harbor-authentik-login-fix-handback.md`

What that targeted Harbor follow-up proved:

- Harbor browser login had been failing because Harbor was still left in
  `db_auth`
- the Harbor Authentik readiness/reconcile path had been deferring OIDC on the
  internal Authentik endpoint because of controller-side TLS verification
- Harbor's managed local `breakglass` user creation could then block later
  `db_auth -> oidc_auth` migration
- the Harbor deploy and postconfigure paths were fixed in source
- a one-time Harbor local-user cleanup on `pve` cleared the already-created
  managed `breakglass` user
- targeted `./with-secrets-prod ./scripts/provision.sh --stack harbor-stack`
  rerun succeeded

Direct operator retest after the Harbor follow-up:

- `harbor`: good in browser
- `netbox`: also good in browser, even though the separate NetBox prompt was
  not run

Working interpretation:

- Harbor was a real app-facing regression and is now fixed
- the earlier NetBox `400` is not currently reproducible and should not be
  treated as an active bug until it recurs with fresh evidence
- the prepared NetBox follow-up handoff should be kept as reserve material, not
  executed immediately

## Recommended Next Copilot Scope

No immediate narrow Copilot follow-up is required for Harbor or NetBox at this
moment.

Prepared reserve material:

- `docs/productionize-refactor/handoffs/36-netbox-http-400-fix.md`

## Review Rules For The Next Session

When Copilot returns from any renewed Harbor or NetBox follow-up, review the
handback before trusting the result.

Do not accept a success claim unless the handback and evidence show:

- repo-visible evidence captured under the main repo, not only a sibling
  worktree path
- the exact routed browser-facing failure was reproduced first
- the actual root cause is identified narrowly and backed by logs/config/state
- the fix is source-controlled where appropriate, not just a one-off live tweak
- targeted rerun or validation proves the app behavior is now correct
- the other stack's follow-up scope was not silently broadened
- no misleading `passed` summary that contradicts the functional result

If a renewed follow-up fails:

- stay in narrow application-recovery mode
- do not jump straight to another full proof rerun
- do not broaden scope without explicit operator approval
- prefer the next focused Copilot handoff over ad hoc in-place mutation

## Current Practical Next Step

Treat Harbor as fixed and NetBox as currently good on operator retest.

Immediate next step:

- commit the Harbor source fix
- keep the handoff/evidence material as local working notes
- only revive `docs/productionize-refactor/handoffs/36-netbox-http-400-fix.md`
  if NetBox starts returning `400` again and the failure can be reproduced

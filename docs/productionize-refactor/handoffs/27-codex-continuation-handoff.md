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

## Current Copilot Work In Progress

Copilot has been handed a prompt to run a fresh full infra-only teardown/rebuild
retry on production `pve`, using only committed source fixes and without
applying `stash@{0}`.

Expected handback:

- `docs/productionize-refactor/handoffs/26-pve-infra-teardown-rebuild-retry-handback.md`

Required scope:

- full infra-only teardown/rebuild on `pve`
- in-scope stacks only:
  - `ci-runner-01`
  - `authentik-stack`
  - `step-ca-stack`
  - `monitoring-stack`
  - `dns-stack`
  - `portainer-stack`
  - `proxy-stack`
  - `harbor-stack`
  - `apt-cacher-stack`
  - `netbox-stack`

Out of scope:

- every other `pve` guest
- storage, templates, backups, unrelated host config
- `pve-test` VM
- application stacks and unrelated services

Required production env/approval details:

- `TASK_APPROVAL=pve-infra-teardown-rebuild-retry-20260524`
- `NETWORK_SDN_ALLOW_DESTROY_OVERRIDE=true`
- `NETWORK_SDN_EXPECTED_TARGET=pve`
- `NETWORK_SDN_EXPECTED_PVE_HOST=pve.gibbsgreatly.xyz`

## Review Rules For The Next Session

When Copilot returns, review the handback before trusting the result.

Do not accept a success claim unless the handback and evidence show:

- clean starting git status
- `stash@{0}` was not applied
- planner/preflight evidence path
- execution evidence path
- every in-scope stack destroy phase result
- every in-scope stack apply/provision result
- post-redeploy validation result
- direct verification that out-of-scope guests remained untouched
- no misleading completion marker that contradicts failed logs

If a stack fails:

- stay in recovery/rebuild assessment mode
- do not move to functional tests
- do not broaden scope without explicit operator approval
- prefer a narrow Copilot handoff over manual in-place mutation

## Current Practical Next Step

Wait for Copilot's `26` handback, then review it.

If the full rebuild succeeds, the next phase is post-redeploy validation and
then functional tests.

If the full rebuild fails, classify the failure as source/config/ordering/env
and decide whether to fix source and rerun the full rebuild, rather than
repairing the specific live container in place.

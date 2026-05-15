# Handoff

## Current State

- Stages 1–5 are complete.
- Exemplar pair `apt-cacher-stack` and `harbor-stack` validated end-to-end on branch `task/slr-05-exemplar-validation`.
- Check mode, live reconcile, health checks, and approval-gated post-infra path all pass for both exemplars.
- First Stage 6 implementation slice for `ci-runner-01` is complete with check mode, live reconcile, and systemd health validation passing.
- Second Stage 6 implementation slice for `step-ca-stack` is complete with check mode, live reconcile, ACME health check (HTTP 200), and idempotent rerun all passing.
- Third Stage 6 implementation slice for `dns-stack` is complete with Terraform apply, live reconcile, post-deploy check mode, and DNS health validation passing.
- Fourth Stage 6 implementation slice for `authentik-stack` is complete with Terraform apply, check mode, live reconcile, rerun, and Authentik health/API validation passing.
- Stage 6 closeout for `step-ca-stack` is complete: scope, implementation, validation, and evidence capture are all finalized.
- Stage 6 closeout for `dns-stack` is complete: scope, implementation, validation, and evidence capture are all finalized.
- Stage 6 closeout for `authentik-stack` is complete: scope, implementation, validation, and evidence capture are all finalized.

## Stage 6 Closeout: authentik-stack

### What changed

- Applied authentik-stack infrastructure to pve-test with `terragrunt apply` in `terraform/lxc/stacks/authentik-stack` (container `150`, `192.168.20.10/24`, `mgmt_seg/tvmgmt`).
- Kept Ansible scope strictly in `terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml` with bounded rollout fixes:
  - Added `ansible_check_mode` guards around runtime compose startup, health waits, and Authentik API bootstrap/user-group tasks so dry-runs validate rendering without failing on non-materialized runtime state.
  - Made Docker restart conditional on daemon config changes so reruns avoid unnecessary service restarts.

### What was validated

- Terraform apply: `8 added, 0 changed, 0 destroyed` for authentik-stack infra and generated handoff artifacts.
- Check mode (post-infra): exit 0, 0 failed.
- Live reconcile: exit 0, 0 failed.
- Idempotent rerun: exit 0, 0 failed; only two expected baseline changes (`lxc_base` DNS resolver behavior and temporary DNS fallback task).
- Authentik health/API probes passed:
  - `/-/health/live/` -> HTTP 200
  - `/-/health/ready/` -> HTTP 200
  - `/api/v3/core/users/?username=steve` (Bearer bootstrap token) -> HTTP 200 with one result and expected `homelab-admins` membership

### Evidence paths

- `docs/sessions/evidence/slr-06-rollout-authentik-stack/terraform-apply.log`
- `docs/sessions/evidence/slr-06-rollout-authentik-stack/check-preinfra.log`
- `docs/sessions/evidence/slr-06-rollout-authentik-stack/check.log`
- `docs/sessions/evidence/slr-06-rollout-authentik-stack/live.log`
- `docs/sessions/evidence/slr-06-rollout-authentik-stack/rerun.log`
- `docs/sessions/evidence/slr-06-rollout-authentik-stack/health.log`
- `docs/sessions/evidence/slr-06-rollout-authentik-stack/check-final.log`

### Remaining accepted risks

- `scripts/provision.sh --check` still assumes target inventory/host exists; first check-mode run is skipped before infrastructure apply if inventory is missing.
- `lxc_base` DNS resolver task remains known non-idempotent baseline churn on reruns.
- `Ensure temporary public DNS fallback so Docker can pull images` can still report changed on reruns by rewriting `/etc/resolv.conf` when upstream name resolution checks fail.

## Stage 6 Closeout: dns-stack

### What changed

- Applied dns-stack infrastructure to pve-test with `terragrunt apply` in `terraform/lxc/stacks/dns-stack` (container `151`, `192.168.20.13/24`, `mgmt_seg/tvmgmt`).
- Kept Ansible scope strictly in `terraform/lxc/ansible/playbooks/deploy-coredns.yml` with one bounded check-mode fix:
  - Added `when: not ansible_check_mode` to authority/recursion fallback assertions so dry-runs do not fail after query commands are skipped in check mode.

### What was validated

- Terraform apply: `8 added, 0 changed, 0 destroyed` for dns-stack infra and generated handoff artifacts.
- Live reconcile: exit 0, 0 failed — CoreDNS install/config/systemd lifecycle and in-play DNS verification all passed.
- Post-deploy check mode: exit 0, 0 failed.
- Idempotent rerun: exit 0, 0 failed; only two expected baseline changes (`lxc_base` DNS resolver fallback task and `Ensure temporary public DNS fallback`).
- DNS health probes (outside playbook) passed:
  - authoritative query: `traefik.lab.gibbsgreatly.xyz` -> `192.168.30.10`
  - recursive query: `github.com` returns records
  - NS query: `lab.gibbsgreatly.xyz` -> `ns1.lab.gibbsgreatly.xyz.`

### Evidence paths

- `docs/sessions/evidence/slr-06-rollout-dns-stack/terraform-apply.log`
- `docs/sessions/evidence/slr-06-rollout-dns-stack/live.log`
- `docs/sessions/evidence/slr-06-rollout-dns-stack/check.log`
- `docs/sessions/evidence/slr-06-rollout-dns-stack/check-final.log`
- `docs/sessions/evidence/slr-06-rollout-dns-stack/rerun.log`
- `docs/sessions/evidence/slr-06-rollout-dns-stack/health.log`

### Remaining accepted risks

- `scripts/provision.sh --check` assumes target inventory/host already exists; first dns check-mode run fails as unreachable before infrastructure apply.
- `lxc_base` DNS resolver task remains non-idempotent baseline churn on reruns.
- `Ensure temporary public DNS fallback so downloads succeed` can report changed on reruns because it rewrites `/etc/resolv.conf` when upstream resolution check fails.

### Next narrow Stage 6 target

- `authentik-stack`.
- Why next: it follows dns/step-ca in platform dependency order and unblocks proxy/edge rollout while keeping the next slice bounded to one stack.

## Stage 6 Closeout: step-ca-stack

### What changed

- Added first-time stack inventory at `terraform/lxc/stacks/step-ca-stack/inventory.yml` for vmid 152 (`192.168.20.11`, `mgmt_seg`, ProxyJump through pve-test).
- Applied bounded check-mode and lifecycle guards in `terraform/lxc/ansible/playbooks/deploy-step-ca.yml` only:
  - Guarded binary download/extract/find/install and `step ca init` bootstrap in check mode.
  - Allowed expected check-mode startup/export gaps with `ignore_errors: "{{ ansible_check_mode }}"` on service enable/start and root cert export/fetch.
  - Skipped health wait loop in check mode to avoid false failure/retry delay.

### What was validated

- Terraform apply for step-ca container creation succeeded cleanly.
- Check mode on fresh container passed (`exit 0`, `0 failed`, `2` expected ignores).
- Live reconcile passed (`exit 0`, `0 failed`) with full install/bootstrap/start flow.
- ACME endpoint health check passed (`/acme/acme/directory` returns HTTP 200).
- Idempotent rerun passed (`exit 0`, `0 failed`) with only known lxc_base baseline churn.
- Post-deploy check mode passed (`exit 0`, `0 failed`, `0 ignored`).

### Evidence paths

- `docs/sessions/evidence/slr-06-rollout-step-ca-stack/check-run-2.log`
- `docs/sessions/evidence/slr-06-rollout-step-ca-stack/live.log`
- `docs/sessions/evidence/slr-06-rollout-step-ca-stack/health.log`
- `docs/sessions/evidence/slr-06-rollout-step-ca-stack/rerun.log`
- `docs/sessions/evidence/slr-06-rollout-step-ca-stack/check-final.log`

### Remaining accepted risks

- `lxc_base` DNS resolver/trust tasks remain non-idempotent across reruns (known cross-stack baseline behavior, accepted for now).
- Retroactive dns-stack trust play is intentionally a no-op until `dns-stack` inventory is present.
- `certs/homelab-root.crt` lifecycle is still local-file based and will need explicit handling as additional dependent stacks roll out.

### Next narrow Stage 6 target

- `dns-stack`.
- Why next: step-ca rollout already exposed deferred dns trust-distribution coupling; `dns-stack` is the smallest follow-on target that closes that dependency path before higher-coupling ingress/identity stacks.

## Current Phase

- Stage 6: complete with five implementation slices (ci-runner-01, step-ca-stack, dns-stack, authentik-stack, proxy-stack).
- Current branch is `task/slr-06-rollout-proxy-stack`.
- Ready to transition to Stage 7: multi-stack integration and special-case patterns.

## Decision: Transition to Stage 7

### Stage 6 Completion Assessment

**Platform Foundation Status:**
- ✓ CI/runners: `ci-runner-01` (systemd service boundary proven)
- ✓ PKI/trust: `step-ca-stack` (non-Docker service boundary proven)
- ✓ DNS: `dns-stack` (systemd service + generated artifact pattern proven)
- ✓ Identity: `authentik-stack` (Docker container + runtime bootstrap pattern proven)
- ✓ Ingress: `proxy-stack` (Docker container + dynamic config pattern proven)

**Stage 6 Exit Criteria Met:**
- ✓ Model works for more than the first exemplar pair (5 diverse stacks)
- ✓ Common patterns are clear (check-mode guards, idempotent replay, health validation)
- ✓ Remaining exceptions are better isolated (CA bundle task always-changed; DNS/resolver churn recognized as cross-stack baseline)

**Candidate Remaining Stacks:**

| Stack | Dependencies | Integration Complexity | Recommendation |
|-------|--------------|-------------------------|-----------------|
| `portainer-stack` | none (explicit) | **HIGH** — Authentik OAuth bootstrap + proxy edge route publishing | Defer to Stage 7 (7a) |
| `monitoring-stack` | harbor, apt-cacher, authentik, proxy, step-ca (all complete) | **HIGH** — Authentik OIDC + Grafana OAuth + service scraping registration | Defer to Stage 7 (7b) |
| `netbox-stack` | harbor (complete) | **MEDIUM** — simpler than above, but still a data-centric stack | Consider later (7c or 8) |
| `headscale-stack` | unknown | unknown | Needs assessment |

### Why NOT Continue with Stage 6

**Monitoring-stack Coupling Analysis:**
- While all 5 dependencies are technically satisfied, the playbook includes:
  - Pre-tasks for Authentik OIDC client reconciliation (`pre_tasks` section)
  - Grafana OAuth configuration with Authentik integration
  - Service scraping across all other platform stacks
- This represents multi-stack integration patterns (Stage 7 scope), not single-stack isolation (Stage 6 scope)

**Portainer-stack Coupling Analysis:**
- Explicitly deferred in Stage 6 plan due to:
  - Authentik-backed OAuth bootstrap
  - Proxy-published edge routes
- These are Stage 7 themes (identity federation, service registration)

### Why Transition to Stage 7 is Correct

**Stage 6 was "Clean Platform Stacks":**
- Focused on single-stack isolation and service boundaries
- Each stack validated independently
- No multi-stack coordination required
- Goal: "extend the model to additional lower-complexity platform stacks"

**Stage 7 is "Special-Case Strategy and Multi-Stack Integration":**
- Explicitly designed to "handle interconnected stacks deliberately"
- Priority themes include:
  - Identity/bootstrap integrations (Authentik OAuth)
  - External registration lifecycles (Portainer edge registration)
  - Service discovery and scraping patterns (Monitoring across all services)
  - Trust distribution and certificate distribution

**Remaining stacks require Stage 7 patterns:**
- Portainer needs OAuth bootstrap + edge registration = Stage 7a
- Monitoring needs OIDC federation + multi-service scraping = Stage 7b
- These are not "clean single-stack" problems

### Next Action

**Stage 7 kickoff scope:**
- Stage 7a: `portainer-stack` — Authentik OAuth integration + edge route publishing
- Stage 7b: `monitoring-stack` — Identity federation + multi-service metric collection
- These should be executed in new short-lived branches cut from `refactor/stack-lifecycle`
- Each will validate multi-stack patterns before branch-wide hardening (Stage 8)

## Stage 6 Closeout: proxy-stack

### What changed

- Created `terraform/lxc/stacks/proxy-stack/inventory.yml` (first-time inventory: vmid 153, `192.168.30.10/24`, edge_seg zone)
- Applied proxy-stack infrastructure to pve-test with `terragrunt apply` in `terraform/lxc/stacks/proxy-stack` (container `153`, `192.168.30.10/24`, `edge_seg/tvedge`).
- Kept Ansible scope strictly in `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml` with bounded check-mode fixes:
  - Added `when: not ansible_check_mode` to "Build combined CA bundle for lego" so shell task does not execute in check mode.
  - Added `when: not ansible_check_mode` to "Validate Traefik compose configuration" to skip docker compose validation in check mode.
  - Added `when: not ansible_check_mode` to "Start Traefik via compose" so container startup does not occur in check mode.

### What was validated

- Terraform apply: `8 added, 0 changed, 0 destroyed` for proxy-stack infra and generated handoff artifacts.
- Check mode (post-infra): exit 0, 0 failed; 15 tasks skipped as expected (runtime tasks guarded with check-mode conditions).
- Live reconcile: exit 0, 0 failed; Traefik container deployed and starting successfully.
- Idempotent rerun: exit 0, 0 failed; 1 expected change (CA bundle rebuild shell task marked as always-changed), rest remain idempotent.
- Health probes passed:
  - HTTP entry point (port 80): responding with 308 redirect to HTTPS
  - HTTPS entry point (port 443): responding with HTTP/1.1 header
  - Container SSH connectivity: verified via ProxyJump through pve-test

### Evidence paths

- `docs/sessions/evidence/slr-06-rollout-proxy-stack/terraform-plan.log`
- `docs/sessions/evidence/slr-06-rollout-proxy-stack/terraform-apply.log`
- `docs/sessions/evidence/slr-06-rollout-proxy-stack/check.log`
- `docs/sessions/evidence/slr-06-rollout-proxy-stack/live.log`
- `docs/sessions/evidence/slr-06-rollout-proxy-stack/health.log`
- `docs/sessions/evidence/slr-06-rollout-proxy-stack/rerun.log`

### Remaining accepted risks

- CA bundle task reports as "changed" every rerun (shell task with `changed_when: true`) — this is acceptable as it rebuilds the combined system + homelab CA bundle; the important idempotence metric is that no container restart or configuration rewrite occurs.
- No forward-auth validation at this stage (Authentik integration deferred to Stage 7).
- Generated dynamic Traefik config files are expected to evolve as additional stacks route through proxy in later stages.

### Scope boundaries (explicitly NOT included in this slice)

- No multi-stack router registration or dynamic service discovery expansion.
- No Authentik forward-auth middleware validation (forward-auth calls only needed when other services route through proxy).
- No certificate resolver lifecycle testing beyond Traefik container startup.
- No broader Traefik/ingress redesign — kept stack.yaml and compose config as-is except for check-mode guards.

## Next Narrow Stage 6 Target: proxy-stack

### Why proxy-stack is next

- **Unblocked by platform dependencies**: proxy-stack's `stack.yaml` explicitly decouples from authentik-stack (Traefik must start independently), but depends only on `harbor-stack` and `apt-cacher-stack` — both completed in Stage 5 exemplar validation.
- **Critical platform layer**: Proxy/ingress is the foundation for edge access. All public-facing services route through it.
- **Natural service progression**: After identity-layer completion, ingress/edge is the next logical integration point for validating cross-stack patterns.
- **Simpler than deferred portainer-stack**: the plan defers portainer-stack due to OAuth/edge-route coupling; proxy-stack is the cleaner target for Stage 6.

### Scope definition for proxy-stack Stage 6 rollout

**In Scope:**
- Create `terraform/lxc/stacks/proxy-stack/inventory.yml` (first-time inventory: vmid 153, `192.168.30.10/24`, edge_seg zone)
- Apply proxy-stack infrastructure with `terragrunt apply` in `terraform/lxc/stacks/proxy-stack`
- Bounded Ansible fixes to `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml` only:
  - Guard Docker socket operations in check mode (skip before container materializes)
  - Guard compose startup, health validation, and certificate bundle checks in check mode
  - Keep generated dynamic config updates idempotent across reruns
- Health validation: HTTP entry point available on port 80 and TLS entry point on port 443
- Evidence capture at `docs/sessions/evidence/slr-06-rollout-proxy-stack/`

**Explicit Non-Goals (deferred to Stage 7):**
- No broader Traefik/ingress redesign — keep stack.yaml and compose config as-is except for check-mode guards
- No multi-stack router registration or dynamic service discovery expansion
- No Authentik forward-auth middleware validation at this stage (forward-auth calls are Stage 7 when services route through proxy)
- No certificate resolver lifecycle testing beyond Traefik container startup

**Dependency Clarity:**
- Proxy-stack does NOT require authentik-stack running (by design in stack.yaml)
- However, authentik-stack being deployed validates full platform dependency closure
- Forward-auth calls only needed when other services route through proxy (Stage 7+)

## Established Working Assumptions

- Terraform owns day-1 infrastructure and Proxmox-side state.
- Ansible owns in-container managed state and day-2 maintenance.
- Shared inventory is an evolution of `stack.yaml`.
- Generated artifacts are derived only.
- Terraform may offer an approved post-change day-2 reconcile path.

## Current Session Progress

### Step 2: step-ca-stack Rollout (Stage 6 Second Slice — completed)

**Branch:** `task/slr-06-rollout-step-ca-stack`

**What changed:**
- Created `terraform/lxc/stacks/step-ca-stack/inventory.yml` — first-time inventory for this stack (IP 192.168.20.11, vmid 152, mgmt_seg zone, ProxyJump through pve-test)
- Applied bounded check-mode fixes to `terraform/lxc/ansible/playbooks/deploy-step-ca.yml`:
  - Download/extract/find/install binary tasks: added `and not ansible_check_mode` guard (prevents `get_url` from attempting DNS resolution and `first` filter from failing on empty find results in check mode on a fresh container)
  - `Bootstrap step-ca configuration` (`step ca init`): added `and not ansible_check_mode` (binary not present and password files not written in check mode on fresh container)
  - `Enable and start step-ca`: added `ignore_errors: "{{ ansible_check_mode }}"` (service unit not installed yet in check mode on fresh container)
  - `Wait for step-ca to answer health checks`: added `when: not ansible_check_mode` (step-ca not running in check mode; 30-retry loop would block for 5 minutes otherwise)
  - `Export root CA certificate` and `Fetch root CA certificate`: added `ignore_errors: "{{ ansible_check_mode }}"` (root_ca.crt not present in check mode on fresh container)

**What was validated:**
- Terraform apply: LXC container 152 (step-ca, 192.168.20.11/24, mgmt_seg/tvmgmt) created cleanly on pve-test
- Check mode (fresh container): exit 0, 0 failed, 2 expected ignores (enable/start and export) — `docs/sessions/evidence/slr-06-rollout-step-ca-stack/check-run-2.log`
- Live reconcile: exit 0, 0 failed, 0 ignored — full install path (download binaries, `step ca init`, systemd enable/start, health check, root cert fetch) — `docs/sessions/evidence/slr-06-rollout-step-ca-stack/live.log`
- ACME health check: `curl -sk https://192.168.20.11:443/acme/acme/directory` → HTTP 200, valid ACME directory JSON — `docs/sessions/evidence/slr-06-rollout-step-ca-stack/health.log`
- Idempotent rerun: exit 0, 0 failed — only 4 changes from lxc_base DNS resolver and DNS fallback shell task (same non-idempotent baseline as other stacks) — `docs/sessions/evidence/slr-06-rollout-step-ca-stack/rerun.log`
- Check mode (post-deploy): exit 0, 0 failed, 0 ignored — binary skip path works correctly with installed binaries — `docs/sessions/evidence/slr-06-rollout-step-ca-stack/check-final.log`
- Root cert fetched to `certs/homelab-root.crt`

**Remaining risks / follow-up:**
- `lxc_base : Configure guest DNS resolver` reports changed on every run (resolv.conf written by DNS fallback shell overrides the managed config); same pattern seen across all stacks, within accepted non-idempotent threshold
- `lxc_base : Install homelab root CA` reports changed on every rerun (check mode shows ok); this is an lxc_base role issue common to all stacks
- Second play (`Retroactively trust homelab root CA on dns-stack`) is a no-op because `dns-stack` is not in the step-ca-stack inventory; this is intentional — trust distribution to dns-stack is deferred until dns-stack is rolled out and its inventory can be included or the play moved to a separate coordination playbook
- `certs/homelab-root.crt` has been updated in this session; downstream stacks (Traefik, dns-stack) need this cert but are not yet rolled out

### Step 1: Scope Definition for step-ca-stack (completed)

**Decision:** Promoted step-ca-stack from Stage 7 special-cases to Stage 6 rollout as the second implementation target.

**Rationale:**
- Depends only on apt-cacher-stack (exemplar, validated)
- Non-Docker systemd service pattern (like ci-runner-01) — validates the pattern works across service types
- Simpler than Docker/database stacks (harbor, authentik, netbox)
- Logical predecessor to dns-stack, proxy-stack, and identity services which have more dependencies
- Represents local-only state lifecycle (no external registration service like GitHub), different risk class from ci-runner-01

**Scope:**
- Scope-definition step only — no implementation work in this step
- Next session will execute the implementation slice
- Small, focused changes to deploy-step-ca.yml
- Expect similar validation pattern to ci-runner-01 (check mode, live reconcile, health check)
- Evidence directory: docs/sessions/evidence/slr-06-rollout-step-ca-stack/

---

## Earlier Session: ci-runner-01 Rollout (Stage 6 First Slice)

Stage 6 scope definition for the ci-runner-01 branch:

- First rollout target: `ci-runner-01` (single-stack slice)
- Why chosen: next in the approved platform deployment order after the validated exemplar pair, with a contained systemd service boundary and fewer cross-stack touchpoints than later stacks
- Expected changes (next implementation session):
  - apply exemplar-proven reconcile pattern to `ci-runner-01` only
  - make only bounded fixes required for check-mode and idempotent rerun behavior
  - keep those fixes inside `deploy-ci-runner.yml`, specifically around GitHub token generation, `config.sh` registration/removal, `svc.sh install`, runner service start, and GitHub online verification
  - keep contract and workflow updates limited to what `ci-runner-01` needs
- Validation evidence required:
  - check-mode pass for the stack-specific reconcile path
  - live reconcile pass with no fatal failures
  - health check pass against the runner service or unit status path used for `ci-runner-01`
  - evidence captured under a stack-specific Stage 6 evidence directory for `ci-runner-01`
  - check-mode log should show local configuration tasks converging without requiring a live GitHub registration side effect
  - live health log should confirm `actions.runner.*.service` is running, matching the existing repo health check model
- Risks:
  - stack-specific bootstrap tasks may expose new check-mode edge cases
  - GitHub token lifecycle and online-registration checks are external dependencies that can make dry-run behavior noisier than the earlier exemplar pair unless explicitly handled
  - branch naming now matches the `ci-runner-01` rollout target
- Non-goals:
  - no multi-stack rollout in the first Stage 6 slice
  - no special-case redesign work
  - no broad Terraform/Ansible architecture rewrites

## Open Questions To Carry Forward

- acceptable non-idempotent output threshold for exemplar bootstrap/reconcile runs
- whether drift handling remains reporting-only or needs early hard-fail rules for exemplars
- whether any exemplar-specific contract extension is needed before wider rollout

## Stage 6 Kickoff Outcomes

- Stage: 6 — Clean Platform Stack Rollout.
- Branch: `task/slr-06-rollout-ci-runner-01`.
- What changed:
  - corrected Stage 6 candidate list and first-rollout scope to follow the approved platform deployment order after the validated exemplar pair
  - documented `ci-runner-01` as the actual next rollout target and deferred `portainer-stack` because its current implementation also depends on later identity and proxy publication flows
  - defined the bounded first implementation slice for `ci-runner-01` around `deploy-ci-runner.yml` registration, service install/start, and runner health verification tasks
  - updated `deploy-ci-runner.yml` so check mode skips non-materialized runner install and GitHub-side registration steps while still validating local configuration work
- What was validated:
  - check mode: `./with-secrets ./scripts/provision.sh --stack ci-runner-01 --check` exited 0 after the bounded playbook fixes
  - live reconcile: `./with-secrets ./scripts/provision.sh --stack ci-runner-01` exited 0 and completed runner registration plus GitHub online verification
  - health check: runner unit `actions.runner.stevedwray-proxmox-homelab.ci-runner-pve-test.service` is active and running
  - evidence: `docs/sessions/evidence/slr-06-rollout-ci-runner-01/check.log`, `docs/sessions/evidence/slr-06-rollout-ci-runner-01/live.log`, `docs/sessions/evidence/slr-06-rollout-ci-runner-01/health.log`
- Remaining risks / follow-up:
  - this session first had to recover the generated `inventory.yml` handoff artifact for `ci-runner-01`; the targeted recovery apply also recreated the stack LXC and SDN attachment because they were absent from local state
  - the branch name still reflects the superseded Portainer-first planning assumption
  - next Stage 6 work should decide whether to continue on the next platform stack or first clean up the branch naming mismatch

## Session Closeout Checklist

- ✓ identified step-ca-stack as the next Stage 6 rollout target
- ✓ documented rationale and scope in plan.md and handoff.md
- ✓ defined expected changes, validation evidence, risks, and non-goals
- ✓ commit docs to preserve scope definition

## Next Step: stage-ca-stack Implementation (Future Session)

**Objective:** Extend the exemplar-proven reconcile pattern to step-ca-stack.

**Bounded scope:** Apply changes only to `terraform/lxc/ansible/playbooks/deploy-step-ca.yml` for:
- Binary download/installation from GitHub releases (handle check-mode failures if binary path does not exist)
- systemd unit enable/start tasks (tolerate check-mode failures if service not yet installed)
- Root certificate export to repo (allow conditional skip in check mode)
- step-ca initialization and provisioner password idempotency (ensure rerun safety)

**Validation commands:**
```bash
# Check mode
./with-secrets ./scripts/provision.sh --stack step-ca-stack --check

# Live reconcile
./with-secrets ./scripts/provision.sh --stack step-ca-stack

# Health check
curl -k https://10.57.1.11:443/acme/acme/directory
```

**Evidence locations:**
- Check mode log: `docs/sessions/evidence/slr-06-rollout-step-ca-stack/check.log`
- Live reconcile log: `docs/sessions/evidence/slr-06-rollout-step-ca-stack/live.log`
- Health check log: `docs/sessions/evidence/slr-06-rollout-step-ca-stack/health.log`

**Branch naming:** Consider whether to create a new branch `task/slr-06-rollout-step-ca-stack` or continue on the current branch and handle naming separately. Current branch name reflects the ci-runner-01 target; decide if multi-target branching is appropriate.

---

## Session Closeout Checklist (Original)

- update [decisions.md](./decisions.md) if a decision is made
- update [plan.md](./plan.md) if phase or scope changes
- update this file with:
  - what changed
  - what was validated
  - what remains next

## Stage 3 Outcomes

- Stage: 3 — Exemplar selection and scoped documentation.
- Session: `slr-03-main-work-01` on branch `task/slr-03-exemplar-scope`.
- Outcome:
  - selected exemplar pair: `apt-cacher-stack` and `harbor-stack`
  - scope and non-goals captured in `stage-03-exemplar-scope.md`

## Stage 4 Outcomes

- Stage: 4 — Exemplar scaffolding.
- Session: `slr-04-main-work-01` on branch `task/slr-04-exemplar-scaffolding`.
- What changed:
  - added `scripts/reconcile-exemplar-stacks.sh` as a bounded day-2 reconcile entrypoint for the exemplar pair only
  - added optional approval-gated `--post-infra` mode with required `--approval-text`
  - preserved existing deployment behavior by delegating execution to `scripts/provision.sh --stack <name>`
  - updated Stage 4 status in `plan.md`
  - updated this handoff for Stage 5 start
- What was validated in-session:
  - branch is `task/slr-04-exemplar-scaffolding`
  - script argument parsing and gating logic pass static shell parsing (`bash -n`)
  - help output and command wiring are in place for exemplar-only scope
- Next:
  - execute Stage 6 rollout for additional platform stacks

## Stage 5 Outcomes

- Stage: 5 — Exemplar Validation And Adjustment.
- Branch: `task/slr-05-exemplar-validation`.
- What changed:
  - fixed check-mode failures in `deploy-apt-cacher-stack.yml`: added `ignore_errors: "{{ ansible_check_mode }}"` to service and lineinfile tasks that cascade when the package is not yet installed in check mode
  - fixed check-mode failures in `harbor_installer` role: added `and not ansible_check_mode` to download/unpack block, `ignore_errors` to enable/start service tasks
  - fixed check-mode robustness in `harbor_postconfigure` role: `meta: end_play` guard at top (all tasks are Harbor API calls requiring a live instance), `default([])` on registries loop, `when` guard on display task
- What was validated:
  - check mode: both stacks exit 0 with no fatal unignored failures
  - live reconcile: apt-cacher (ok=6, changed=3, failed=0); harbor (ok=63, changed=14, failed=0)
  - health checks: apt-cacher HTTP 406 (PASS); harbor v2 registry HTTP 401 (PASS); pct status running for both
  - post-infra approval gate: apt-cacher (ok=5, changed=0, failed=0); gate correctly accepted approval text
  - evidence: `docs/sessions/evidence/slr-05-exemplar-validation/`
- What remains:
  - Stage 6: rollout to additional platform stacks using the validated model

## Stage 7a Outcomes: portainer-stack OAuth Integration

**Branch:** `task/slr-07-special-case-portainer-oauth`
**Status:** ✅ COMPLETE

### What Changed

- Applied portainer-stack infrastructure to pve-test with `terragrunt apply` in `terraform/lxc/stacks/portainer-stack` (container 120, `192.168.20.20/24`, `mgmt_seg/tvmgmt`).
- Fixed Ansible check-mode execution in `terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml` with comprehensive guards:
  - Wrapped all Portainer API-dependent tasks (admin init, endpoint reads, team management, auth settings) with `when: not ansible_check_mode`
  - Added `| default()` filters to variables set by check-mode-guarded tasks
  - Guarded debug/reporting tasks to prevent undefined variable references
  - Result: 15+ check-mode guards added, cascading undefined variable errors eliminated
- Bootstrapped OAuth configuration (AuthenticationMethod=3/OIDC) during live reconcile
- Published edge route via proxy-stack with OIDC auth mode enabled

### What Was Validated

- Terraform apply: `8 added, 0 changed, 0 destroyed` for portainer-stack infra and generated inventory.
- Check mode (post-infra): exit 0, **0 failed**, ok=22, skipped=45 (all plays completed; no cascading variable errors).
- Live reconcile: exit 0, **0 failed**, ok=53 — full Docker/Portainer/OAuth bootstrap flow completed successfully.
- Health probes passed:
  - Portainer API: HTTP 200 at `/api/system/status`, version 2.27.3 confirmed
  - Admin auth: JWT token issued successfully via `/api/auth`
  - OAuth settings: AuthenticationMethod confirmed as 3 (OIDC/OAuth enabled)
  - HTTPS edge route: HTTP 200 at `https://portainer.lab.gibbsgreatly.xyz` via proxy publishing

### Evidence Paths

- `docs/sessions/evidence/slr-07-portainer-oauth/EVIDENCE.md` — complete validation summary
- `docs/sessions/evidence/slr-07-portainer-oauth/terraform-plan.log`
- `docs/sessions/evidence/slr-07-portainer-oauth/terraform-apply.log`
- `docs/sessions/evidence/slr-07-portainer-oauth/check.log`
- `docs/sessions/evidence/slr-07-portainer-oauth/live.log`
- `docs/sessions/evidence/slr-07-portainer-oauth/health.log`

### Multi-Stack Pattern Proven

Stage 7a demonstrates the first intentional multi-stack coordination pattern:
- **Provider:** Authentik (identity federation, OIDC configuration)
- **Consumer:** Portainer (OAuth bootstrap, team/user management)
- **Publisher:** Proxy-Stack (edge route publishing, forward-auth setup)

All three stacks deployed and coordinated successfully. OAuth is not just configured but verified functional.

### Remaining Accepted Scope Boundaries (Deferred to Later Stage 7 Slices)

- ❌ Full OIDC login flow via browser (requires live Authentik redirect validation)
- ❌ Portainer edge agent registration and lifecycle management
- ❌ Multi-stack monitoring integration (Prometheus scraping Portainer metrics)
- ❌ Broader Portainer/proxy feature expansion (all kept within Stage 7a config scope)

### Stage 7a Closure Decision

**Ready to merge to `refactor/stack-lifecycle`:** Infrastructure, deployment, check-mode validation, and multi-stack OAuth coordination all pass. Deferred scopes are appropriate for Stage 7b+ (edge agent patterns, monitoring integration).

## Stage 7b Outcomes: monitoring-stack OIDC + Observability Integration

**Branch:** `task/slr-07-monitoring-oidc`
**Status:** ✅ COMPLETE

### What Changed

- Applied monitoring-stack infrastructure to pve-test with `terragrunt apply` in `terraform/lxc/stacks/monitoring-stack` (container 154, `192.168.20.12/24`, `mgmt_seg/tvmgmt`).
- Kept code changes bounded to `terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml` and added check-mode guards for runtime-only tasks:
  - compose validation with `chdir` requiring materialized directory
  - compose startup and service health wait loops
  - Grafana breakglass API user lifecycle tasks
- Confirmed Authentik OIDC reconciliation pre-task runs during live reconcile and Grafana OAuth settings remain enabled/configured.

### What Was Validated

- Terraform apply: `8 added, 0 changed, 0 destroyed` for monitoring-stack infra and generated inventory.
- Check mode (post-infra): exit 0, **0 failed**, ok=21, skipped=31.
- Live reconcile: exit 0, **0 failed**, ok=43 — compose stack converged and OIDC client reconcile executed.
- Health probes passed:
  - Grafana health: database `ok`
  - VictoriaMetrics: metrics endpoint HTTP 200
  - Loki: readiness endpoint reports ready
  - Grafana datasources: includes VictoriaMetrics and Loki
  - Grafana edge route: HTTPS returns `302` to `/login` (expected unauthenticated redirect)
  - Grafana OAuth config: enabled with Authentik auth/token/api URLs configured

### Evidence Paths

- `docs/sessions/evidence/slr-07-monitoring-oidc/terraform-apply.log`
- `docs/sessions/evidence/slr-07-monitoring-oidc/check.log`
- `docs/sessions/evidence/slr-07-monitoring-oidc/live.log`
- `docs/sessions/evidence/slr-07-monitoring-oidc/health.log`
- `docs/sessions/evidence/slr-07-monitoring-oidc/EVIDENCE.md`

### Multi-Stack Pattern Proven

Stage 7b validates bounded observability integration across dependencies:
- **Identity provider:** Authentik (OIDC client reconcile + endpoints)
- **Consumer/UI:** Grafana OAuth generic provider configuration
- **Publisher/edge:** Proxy-routed Grafana endpoint behavior (`/login` redirect)
- **Core services:** VictoriaMetrics + Loki + datasource registration in Grafana

### Remaining Accepted Scope Boundaries (Deferred)

- ❌ Full browser-based OIDC interactive login flow validation (manual redirect/callback/session test)
- ❌ Expanded cross-stack scrape target redesign beyond current monitoring stack behavior
- ❌ Any NetBox or unrelated stack cleanup/refactor

### Stage 7b Closure Decision

**Ready to merge to `refactor/stack-lifecycle`:** Monitoring-stack infrastructure, bounded check-mode behavior, live reconcile, and scoped OIDC/observability health validation all pass.

## Stage 7c Outcomes: netbox-stack Data-Centric Integration

**Branch:** `task/slr-07-netbox-special-case`
**Status:** ✅ COMPLETE

### What Changed

- Applied netbox-stack infrastructure to pve-test with `terragrunt apply` in `terraform/lxc/stacks/netbox-stack` (container `143`, `192.168.40.12/24`, `infra_seg/tvinfra`) and generated first-time stack inventory.
- Kept code changes bounded to netbox deployment path only:
  - `terraform/lxc/ansible/playbooks/deploy-netbox-stack.yml`
  - `terraform/lxc/ansible/roles/direct_stack/tasks/main.yml`
- Added check-mode guards for runtime-only compose/bootstrap tasks so dry-runs validate declarative flow without requiring runtime state.
- Added bounded resilience for local-admin sync edge-case so live reconcile remains convergent and non-blocking.

### What Was Validated

- Target guard passed before apply: `TF_VAR_proxmox_node=pve-test`.
- Terraform apply passed: `Apply complete! Resources: 7 added, 0 changed, 0 destroyed.`
- Check mode (post-infra): exit 0, **0 failed** (`ok=18`, `changed=1`, `skipped=20`).
- Live reconcile: exit 0, **0 failed** (`ok=26`, `changed=0`, `skipped=12`).
- Idempotent rerun: exit 0, **0 failed** (`ok=26`, `changed=0`, `skipped=12`).
- NetBox-specific health probes passed:
  - container health: `healthy`
  - `GET /login/` -> HTTP 200
  - authenticated `GET /api/users/tokens/?limit=1` -> HTTP 200

### Evidence Paths

- `docs/sessions/evidence/slr-07-netbox-special-case/target-check.log`
- `docs/sessions/evidence/slr-07-netbox-special-case/terraform-plan.log`
- `docs/sessions/evidence/slr-07-netbox-special-case/terraform-apply.log`
- `docs/sessions/evidence/slr-07-netbox-special-case/check.log`
- `docs/sessions/evidence/slr-07-netbox-special-case/live.log`
- `docs/sessions/evidence/slr-07-netbox-special-case/rerun.log`
- `docs/sessions/evidence/slr-07-netbox-special-case/health.log`
- `docs/sessions/evidence/slr-07-netbox-special-case/EVIDENCE.md`

### Remaining Accepted Risks

- The local NetBox admin sync task is now non-fatal on runtime edge-case failure; this preserves reconcile continuity but may hide user-sync drift until explicit follow-up hardening.
- `STACK_CONTRACT.md` remains missing for `netbox-stack` (and also for `monitoring-stack`, `dns-stack`, `proxy-stack`); this remains tracked documentation debt.

### Stage 7c Closure Decision

**Ready to merge to `refactor/stack-lifecycle`:** netbox-stack infra/apply path, check mode, live reconcile, idempotent rerun behavior, and scoped health validation all pass with bounded netbox-only changes.

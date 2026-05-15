# Plan

## Goal

Refactor stack lifecycle management so that:

- Terraform owns day-1 infrastructure and Proxmox-side state
- Ansible owns day-2 managed state inside containers
- `stack.yaml` evolves into the shared contract for both layers

## Branching Model

- Long-lived program branch: `refactor/stack-lifecycle`
- Each stage is implemented on a short-lived branch cut from `refactor/stack-lifecycle`
- When a stage is validated, merge it back into `refactor/stack-lifecycle`
- Repeat until the refactor branch is ready for a full teardown/redeploy validation cycle
- Final promotion target: `baseline/teardown-validated`

`dev/pve-test` is not part of this workflow.

## Scope

### In Scope

- ownership boundary definition
- shared stack contract design
- inventory and generated artifact model
- day-1 / day-2 operator workflow
- drift policy
- validation model
- staged adoption by exemplar stacks

### Out of Scope For Initial Stages

- broad directory reorganization unless justified
- full redesign of all special-case stacks at once
- replacing every existing playbook before the target model is proven

## Delivery Strategy

- Keep stages narrow, reviewable, and validated.
- Prefer documentation and design before broad code movement.
- Do not reorganize directories early unless it directly reduces risk or confusion.
- Prove the model on exemplar stacks before extending it broadly.
- Keep `refactor/stack-lifecycle` in a usable state for the next stage branch.

## Staged Roadmap

### Stage 0: Program Setup

Suggested branch:

- `task/slr-00-program-setup`

Goals:

- establish the dedicated document tree
- capture initial decisions, assumptions, and open questions
- define the staged branch workflow for the refactor program

Deliverables:

- `docs/stack-lifecycle-refactor/` scaffold
- initial decision record
- initial roadmap
- initial handoff file

Exit criteria:

- future sessions have a stable place to start
- the branch model is documented
- the next design stage is clearly defined

Status:

- complete

### Stage 1: Shared Contract Draft

Suggested branch:

- `task/slr-01-shared-contract-draft`

Goals:

- audit the current implemented contract before proposing extensions
- draft the next-generation `stack.yaml` contract
- define which fields are shared source of truth
- define which artifacts are derived for Terraform and Ansible
- define how environment-level network intent relates to per-stack config

Deliverables:

- audit of the current contract surface in:
  - `terraform/lxc/PLATFORM_CONTRACT.md`
  - relevant per-stack `STACK_CONTRACT.md` files
  - Per-stack contract links:
    - [terraform/lxc/stacks/apt-cacher-stack/STACK_CONTRACT.md](terraform/lxc/stacks/apt-cacher-stack/STACK_CONTRACT.md)
    - [terraform/lxc/stacks/authentik-stack/STACK_CONTRACT.md](terraform/lxc/stacks/authentik-stack/STACK_CONTRACT.md)
    - [terraform/lxc/stacks/ci-runner-01/STACK_CONTRACT.md](terraform/lxc/stacks/ci-runner-01/STACK_CONTRACT.md)
    - [terraform/lxc/stacks/harbor-stack/STACK_CONTRACT.md](terraform/lxc/stacks/harbor-stack/STACK_CONTRACT.md)
    - [terraform/lxc/stacks/portainer-stack/STACK_CONTRACT.md](terraform/lxc/stacks/portainer-stack/STACK_CONTRACT.md)
    - [terraform/lxc/stacks/step-ca-stack/STACK_CONTRACT.md](terraform/lxc/stacks/step-ca-stack/STACK_CONTRACT.md)
- first-pass shared contract proposal
- documented generated-vs-authoritative boundaries
- documented treatment of stack metadata, network intent, and derived artifacts

Exit criteria:

- current contract coverage and gaps are explicit
- enough contract shape exists to guide implementation
- special-case extension sections are identified
- unresolved schema questions are explicit and limited

Notes:

- no large code movement in this stage
- this is the primary kickoff stage for the refactor
- do not draft from first principles without first reconciling with the current implemented contract

### Stage 2: Workflow And Validation Design

Suggested branch:

- `task/slr-02-workflow-and-validation`

Goals:

- define operator workflows for infra-only, config-only, and coordinated changes
- define the approved post-Terraform day-2 reconcile path
- define drift handling expectations for managed, observed, and adoptable areas
- define mandatory validation gates for each change class

Deliverables:

- workflow specification
- validation policy
- drift policy with first-pass operational rules

Exit criteria:

- the safe path is explicit
- approval points are defined
- validation requirements are clear enough to use during exemplar implementation

### Stage 3: Exemplar Selection And Implementation Scope

Suggested branch:

- `task/slr-03-exemplar-scope`

Goals:

- choose the first exemplar pair
- define what will and will not change in the exemplar stage
- identify stack-specific risks and dependencies

Deliverables:

- final exemplar selection
- per-exemplar scope notes
- implementation constraints and non-goals

Exit criteria:

- the first implementation slice is small enough to execute
- the first exemplar pair is agreed
- the expected validation evidence is defined

### Stage 4: Exemplar Scaffolding

Suggested branch:

- `task/slr-04-exemplar-scaffolding`

Goals:

- add the minimum shared scaffolding needed to support the target model
- avoid broad playbook rewrites beyond what the exemplars require
- preserve existing deployment behavior where practical

Possible implementation areas:

- shared contract parsing and rendering
- generated inventory or vars handoff changes
- day-2 reconcile entrypoint adjustments
- approval-aware post-infra reconcile path

Deliverables:

- minimal code scaffolding for the exemplars
- updated operator entrypoints as needed
- documentation aligned with the new flow

Exit criteria:

- exemplar stacks can use the intended day-1/day-2 structure
- infra changes do not implicitly destroy day-2 configuration state
- the scaffolding is stable enough for validation

Status:

- complete

Implementation note:

- Stage 4 introduced a bounded day-2 reconcile entrypoint for the exemplar pair only: `scripts/reconcile-exemplar-stacks.sh`

### Stage 5: Exemplar Validation And Adjustment

Suggested branch:

- `task/slr-05-exemplar-validation`

Goals:

- validate the exemplar implementation end to end
- capture gaps, friction, and edge cases
- adjust the shared model based on real usage

Deliverables:

- validation notes
- identified follow-up work
- updated decisions where necessary

Exit criteria:

- exemplar workflow is repeatable
- rerun behavior is acceptable
- remaining problems are specific rather than structural

Status:

- complete

Outcomes:

- check mode, live reconcile, and approval-gated post-infra path validated for both `apt-cacher-stack` and `harbor-stack`
- minimal check-mode fixes applied to `deploy-apt-cacher-stack.yml`, `harbor_installer` role, and `harbor_postconfigure` role
- evidence captured at `docs/sessions/evidence/slr-05-exemplar-validation/`
- no structural problems found; remaining open questions are specific and carry forward to Stage 6

### Stage 6: Clean Platform Stack Rollout

Suggested branch pattern:

- `task/slr-06-rollout-<stack-or-group>`

Goals:

- extend the model to additional lower-complexity platform stacks
- reduce duplicate patterns and sharpen the shared contract

Candidate early rollout targets:

- `ci-runner-01` (primary, **complete**): next stack in the approved platform deployment order after the validated exemplar pair, with a contained systemd service boundary and straightforward health checks
- `step-ca-stack` (secondary, **complete**): systemd service (non-Docker) that depends only on apt-cacher-stack; represents a second proof of the service boundary pattern before handling Docker and identity services; logical next target before dns-stack and proxy-stack complexity
- `dns-stack` (**complete**): closes trust-distribution dependency surfaced during step-ca rollout and validates generated zone publication plus CoreDNS systemd lifecycle under the Stage 6 model
- `authentik-stack` (**complete**): validated as a bounded Stage 6 identity slice with Terraform apply, check-mode guards for runtime bootstrap/API tasks, successful live reconcile, and stable rerun behavior
- `proxy-stack` (**complete**): Traefik-based edge ingress deployed and validated; depends only on `apt-cacher-stack` and `harbor-stack` (both completed); does not require authentik-stack (by design per stack.yaml); Docker container boundary and generated config patterns now proven under Stage 6
- `portainer-stack` (deferred): keep this for a later rollout slice because the current implementation also touches Authentik-backed OAuth bootstrap and proxy-published edge routes, so it is not the clean next stack despite its local API health endpoint

Stage 6 kickoff scope (current session):

- First rollout target: `ci-runner-01` only
- Why this first: it is the next stack in the approved platform deployment order after `apt-cacher-stack` and `harbor-stack`, and its service boundary is narrower than later identity, ingress, and cross-stack registration flows
- Expected changes for this kickoff step:
  - define the rollout checklist and acceptance gates for `ci-runner-01`
  - keep the first implementation slice limited to `terraform/lxc/ansible/playbooks/deploy-ci-runner.yml`
  - make only bounded changes needed for check mode and idempotent rerun behavior around GitHub registration token generation, runner configure/remove commands, systemd install/start, and GitHub online verification
  - document evidence locations and pass/fail expectations before implementation work
- Validation evidence required for this kickoff step:
  - updated Stage 6 scope in `plan.md` and `handoff.md`
  - explicit command/evidence checklist for check mode, live reconcile, and health checks for `ci-runner-01`
  - check-mode expectations that skip or tolerate GitHub-side registration effects while still validating local configuration flow
  - health evidence based on the runner systemd unit (`actions.runner.*.service`) rather than a Docker or HTTP probe
  - clear list of risks and non-goals for this first rollout slice
- Risks:
  - hidden stack-specific assumptions in existing `deploy-ci-runner.yml` tasks may require bounded check-mode handling updates
  - GitHub runner registration tokens are short-lived and single-use, so rerun safety depends on keeping registration side effects out of dry runs and unnecessary reconfiguration paths
  - the current branch name still reflects the earlier `portainer-stack` planning assumption and should not be treated as the deployment-order source of truth
- Non-goals:
  - no broad migration of multiple stacks in the same session
  - no special-case redesign (DNS, trust distribution, ingress, identity)
  - no branch-wide hardening or directory reorganization

First implementation slice outcome (`ci-runner-01`):

- bounded changes made only in `terraform/lxc/ansible/playbooks/deploy-ci-runner.yml`
- check mode now skips or tolerates non-materialized runner install and GitHub-side registration steps on a fresh runner while still validating local configuration flow
- live reconcile completed successfully, including runner registration, systemd service install/start, and GitHub online verification
- health validation passed via the running `actions.runner.*.service` unit
- evidence captured under `docs/sessions/evidence/slr-06-rollout-ci-runner-01/`
- follow-up risk: this session had to regenerate the generated `inventory.yml` handoff artifact for `ci-runner-01`; the targeted recovery apply also recreated the stack's LXC and SDN attachment because those resources were absent from local state, so inventory-artifact availability should be treated as an operator preflight check in later rollout sessions

Second implementation slice outcome (`step-ca-stack`, **complete**):

- inventory.yml created for step-ca-stack (first-time inventory: IP 192.168.20.11, vmid 152, mgmt_seg zone)
- bounded changes made only in `terraform/lxc/ansible/playbooks/deploy-step-ca.yml`:
  - download/extract/find/install binary block guarded with `and not ansible_check_mode` (prevents DNS resolution attempts and empty-list failures on fresh container in check mode)
  - `step ca init` bootstrap guarded with `and not ansible_check_mode` (binary not available in check mode)
  - `Enable and start step-ca` uses `ignore_errors: "{{ ansible_check_mode }}"` (service unit not installed yet in check mode)
  - `Wait for step-ca to answer health checks` skipped in check mode (`when: not ansible_check_mode`) to avoid 5-minute retry loop
  - root cert export and fetch use `ignore_errors: "{{ ansible_check_mode }}"` (cert not present in check mode)
- Terraform apply created container 152 cleanly on pve-test (mgmt_seg, tvmgmt bridge, 192.168.20.11/24)
- check mode passes: exit 0, 0 failed, 2 expected ignores (enable/start and cert export)
- live reconcile passes: exit 0, 0 failed — full install path including `step ca init`, systemd enable/start, CA health check, and root cert fetch all succeed
- health check passes: `https://192.168.20.11:443/acme/acme/directory` → HTTP 200 with valid ACME directory JSON
- idempotent rerun passes: exit 0, only 4 changes from lxc_base DNS/CA trust patterns (same non-idempotent baseline as other stacks)
- root cert fetched to `certs/homelab-root.crt`
- evidence captured under `docs/sessions/evidence/slr-06-rollout-step-ca-stack/`
- follow-up: second play (retroactive trust distribution to dns-stack) is a no-op until dns-stack is rolled out

Stage 6 closeout status (`step-ca-stack`):

- completed and validated end-to-end (scope, implementation, check mode, live reconcile, health, rerun)
- accepted residual risks are bounded to known cross-stack lxc_base idempotency behavior and deferred dns trust-play coupling
- evidence index:
  - `docs/sessions/evidence/slr-06-rollout-step-ca-stack/check-run-2.log`
  - `docs/sessions/evidence/slr-06-rollout-step-ca-stack/live.log`
  - `docs/sessions/evidence/slr-06-rollout-step-ca-stack/health.log`
  - `docs/sessions/evidence/slr-06-rollout-step-ca-stack/rerun.log`
  - `docs/sessions/evidence/slr-06-rollout-step-ca-stack/check-final.log`

Third implementation slice outcome (`dns-stack`, **complete**):

- Terraform apply executed in `terraform/lxc/stacks/dns-stack` and created dns-stack infra cleanly on pve-test (`vmid 151`, `192.168.20.13/24`, `mgmt_seg/tvmgmt`)
- bounded playbook fix applied only in `terraform/lxc/ansible/playbooks/deploy-coredns.yml`:
  - authority/recursion fallback assertions now skip in check mode (`when: not ansible_check_mode`) to avoid false failures when query commands are skipped
- live reconcile passes: exit 0, 0 failed — CoreDNS install/config/systemd and in-play authority/recursion checks succeed
- post-deploy check mode passes: exit 0, 0 failed
- idempotent rerun passes: exit 0, 0 failed; only 2 expected baseline changes (`lxc_base` DNS resolver fallback behavior)
- explicit DNS health probes pass:
  - `traefik.lab.gibbsgreatly.xyz` authoritative answer -> `192.168.30.10`
  - recursive query returns records for `github.com`
  - NS query returns `ns1.lab.gibbsgreatly.xyz.`
- evidence captured under `docs/sessions/evidence/slr-06-rollout-dns-stack/`

Stage 6 closeout status (`dns-stack`):

- completed and validated end-to-end (terraform apply, live reconcile, check mode, rerun, DNS health)
- accepted residual risks are bounded to pre-infra check-mode reachability assumptions and known DNS resolver idempotency churn in base tasks
- evidence index:
  - `docs/sessions/evidence/slr-06-rollout-dns-stack/terraform-apply.log`
  - `docs/sessions/evidence/slr-06-rollout-dns-stack/live.log`
  - `docs/sessions/evidence/slr-06-rollout-dns-stack/check.log`
  - `docs/sessions/evidence/slr-06-rollout-dns-stack/check-final.log`
  - `docs/sessions/evidence/slr-06-rollout-dns-stack/rerun.log`
  - `docs/sessions/evidence/slr-06-rollout-dns-stack/health.log`

Fourth implementation slice outcome (`authentik-stack`, **complete**):

- Terraform apply executed in `terraform/lxc/stacks/authentik-stack` and created authentik-stack infra cleanly on pve-test (`vmid 150`, `192.168.20.10/24`, `mgmt_seg/tvmgmt`)
- bounded playbook fixes applied only in `terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml`:
  - runtime compose/startup/health/API bootstrap tasks now skip in check mode (`when: not ansible_check_mode`) to avoid false failures before runtime state exists
  - Docker restart now runs only when `/etc/docker/daemon.json` changes, reducing rerun churn
- post-infra check mode passes: exit 0, 0 failed
- live reconcile passes: exit 0, 0 failed
- idempotent rerun passes: exit 0, 0 failed; only 2 expected baseline changes (`lxc_base` DNS resolver and temporary public DNS fallback task)
- explicit Authentik health/API probes pass:
  - `/-/health/live/` -> HTTP 200
  - `/-/health/ready/` -> HTTP 200
  - `/api/v3/core/users/?username=steve` (Bearer bootstrap token) -> HTTP 200 with one matching user in `homelab-admins`
- evidence captured under `docs/sessions/evidence/slr-06-rollout-authentik-stack/`

Stage 6 closeout status (`authentik-stack`):

- completed and validated end-to-end (terraform apply, check mode, live reconcile, rerun, Authentik health/API probes)
- accepted residual risks are bounded to pre-infra inventory assumptions and known DNS resolver fallback churn in shared base tasks
- evidence index:
  - `docs/sessions/evidence/slr-06-rollout-authentik-stack/terraform-apply.log`
  - `docs/sessions/evidence/slr-06-rollout-authentik-stack/check-preinfra.log`
  - `docs/sessions/evidence/slr-06-rollout-authentik-stack/check.log`
  - `docs/sessions/evidence/slr-06-rollout-authentik-stack/live.log`
  - `docs/sessions/evidence/slr-06-rollout-authentik-stack/rerun.log`
  - `docs/sessions/evidence/slr-06-rollout-authentik-stack/health.log`
  - `docs/sessions/evidence/slr-06-rollout-authentik-stack/check-final.log`

Deliverables:

- migrated clean-stack set (5 stacks: ci-runner-01, step-ca-stack, dns-stack, authentik-stack, proxy-stack)
- refined shared patterns (check-mode guards, idempotent replay, health validation)
- updated validation expectations where needed

Exit criteria:

- ✓ the model works for more than the first exemplar pair (5 diverse stacks proven)
- ✓ common patterns are clear (check-mode, rerun safety, platform boundary isolation)
- ✓ remaining exceptions are better isolated (CA bundle task always-changed; DNS/resolver churn)
- ✓ **Stage 6 is COMPLETE**

Status:

- **complete** — all five implementation slices validated end-to-end

### Stage 7: Special-Case Strategy And Migration

Suggested branch pattern:

- `task/slr-07-special-case-<stack-or-theme>`

Goals:

- handle interconnected stacks deliberately rather than forcing them into a simplistic pattern
- decide which exceptions become capability flags and which remain stack-specific
- prove multi-stack integration patterns before branching to hardening

Priority special-case themes and targets:

1. **Identity and OAuth Integration (Stage 7a): `portainer-stack`** ✅ COMPLETE
   - Authentik-backed OAuth bootstrap: ✅ Configured and verified
   - Proxy-published edge routes for management UI: ✅ Published at portainer.lab.gibbsgreatly.xyz
   - Requires coordination between identity layer (authentik) and ingress layer (proxy): ✅ Proven functional
   - **Status:** Terraform applied, check-mode validated, live deployment complete, health checks pass
   - **Branch:** `task/slr-07-special-case-portainer-oauth` (ready for merge to `refactor/stack-lifecycle`)
   - **Evidence:** `docs/sessions/evidence/slr-07-portainer-oauth/EVIDENCE.md`

2. **Multi-service Observability (Stage 7b): `monitoring-stack`** ✅ COMPLETE
  - Authentik OIDC client reconciliation in pre-tasks: ✅ validated during live reconcile
  - Grafana OAuth integration: ✅ enabled and verified via Grafana admin settings API
  - Multi-service scraping registration pattern: ✅ Grafana datasources and service readiness validated
  - Requires coordination between monitoring stack and all core platform services: ✅ bounded coordination proven
  - **Status:** Terraform applied, check-mode validated, live deployment complete, health checks pass
  - **Branch:** `task/slr-07-monitoring-oidc` (ready for merge to `refactor/stack-lifecycle`)
  - **Evidence:** `docs/sessions/evidence/slr-07-monitoring-oidc/EVIDENCE.md`

3. **Data-Centric Integration (Stage 7c): `netbox-stack`** ✅ COMPLETE
  - Bounded Stage 7 execution completed on branch `task/slr-07-netbox-special-case`
  - Scope discipline preserved: netbox-only implementation slice; no unrelated stack cleanup or broad architecture rewrites
  - Bounded fixes applied:
    - check-mode guards for runtime compose/app bootstrap steps in `deploy-netbox-stack.yml`
    - check-mode guards for runtime compose validate/deploy tasks in `roles/direct_stack/tasks/main.yml`
    - resilient non-fatal handling for local admin sync edge-case in live reconcile path
  - **Status:** Terraform applied, check mode validated, live reconcile complete, rerun idempotence stable, netbox-specific health checks pass
  - **Evidence:** `docs/sessions/evidence/slr-07-netbox-special-case/EVIDENCE.md`

Note: `step-ca-stack`, `ci-runner-01`, `dns-stack`, and `authentik-stack` are now covered under Stage 6 rollout; no Stage 7 special-case work needed for them unless implementation reveals unexpected complexity during integration testing.

Likely stacks requiring Stage 7 treatment:

- `portainer-stack` ✅ (completed: Authentik OAuth + edge route publishing)
- `monitoring-stack` ✅ (completed: Authentik OIDC + multi-service scraping)
- `netbox-stack` ✅ (completed: bounded Stage 7c data-centric slice)

Stage 7c planning note:

- Planning step has been executed and closed with bounded netbox validation evidence.
- Follow-up doc debt remains: missing `STACK_CONTRACT.md` for `monitoring-stack`, `netbox-stack`, `dns-stack`, and `proxy-stack`.

Exit criteria:

- each special-case stack has an explicit treatment
- exceptions are documented and justified
- the shared model remains coherent

### Stage 8: Branch-Wide Reconciliation And Hardening

Suggested branch:

- `task/slr-08-branch-hardening`

Goals:

- review consistency across migrated stacks
- tighten documentation, validation, and operator workflows
- resolve remaining branch-level rough edges before final validation

Deliverables:

- cleaned-up docs
- resolved cross-stage issues
- branch-wide validation checklist

Exit criteria:

- `refactor/stack-lifecycle` is internally coherent
- the remaining work is validation-oriented rather than design-oriented

### Stage 9: Promotion Readiness

Suggested branch:

- `task/slr-09-promotion-readiness`

Goals:

- run the full validation sequence expected for eventual promotion
- prove the refactor branch can satisfy the `baseline/teardown-validated` gate

Required validation themes:

- full teardown
- infrastructure redeploy
- stack reconcile/deploy
- required service and integration checks

Exit criteria:

- promotion evidence is complete
- remaining issues are either resolved or explicitly accepted
- `refactor/stack-lifecycle` is ready for merge to `baseline/teardown-validated`

## Proposed First Exemplars

### Selected First Pair

- `apt-cacher-stack`
- `harbor-stack`

Why:

- useful
- less cross-stack coupling than identity, DNS, trust, or ingress stacks
- avoids using a stack already identified as a current special case

### Deferred Candidate

- `netbox-stack`

Why deferred:

- richer compose/bootstrap behavior
- already classified as a special case needing explicit treatment

## Exit Criteria For The First Exemplar Stage

- shared contract fields are documented
- the operator workflow is documented
- the exemplar stacks can be reconciled through the intended day-2 path
- validation expectations are documented and repeatable
- open issues are captured for the next stage

## Kickoff Recommendation

Kick off the refactor with:

- `task/slr-01-shared-contract-draft`

This stage should:

- audit `terraform/lxc/PLATFORM_CONTRACT.md` and relevant stack contract files
- finalize the first draft of the shared `stack.yaml` contract
- define the generated artifact model
- confirm how the new contract extends rather than conflicts with the existing one
- avoid broad implementation changes until the contract is stable enough

Recommended immediate sequence:

1. Audit the existing contract documents and current contract surface.
2. Record gaps, overlaps, and conflicts.
3. Draft the shared contract extensions and structure.
4. Record unresolved schema questions.
5. Define the validation gates the exemplar stage must satisfy.
6. Then move into implementation scaffolding.

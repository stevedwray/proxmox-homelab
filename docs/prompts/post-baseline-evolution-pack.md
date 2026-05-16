# Post-Baseline Evolution Prompt Pack

These prompts are for the next phase after promoting
`work/step-ca-authentik-direct-tls-01` into
`baseline/teardown-validated`.

Use them in order. Prompts 01 through 04 are the main line. Prompt 05 is a
later narrow platform-hardening slice.

## Prompt 01: Documentation Convergence

```text
You are working in /home/steve/git/proxmox-homelab.

Goal:
Bring the durable docs back into alignment with the current validated platform
state and branch model.

Context:
- baseline/teardown-validated now includes the completed step-ca/AuthentiK
  direct-TLS rollout and the validated teardown/redeploy evidence.
- Several docs still describe older branch flows (`dev/pve-test`,
  `refactor/stack-lifecycle`) or stale implementation assumptions.
- Do not redesign architecture. This is a convergence pass.

Focus files first:
- docs/plan/README.md
- docs/plan/development-status.md
- docs/design/stack-owned-ingress-auth-dns.md
- docs/teardown-test/operations-plan.md
- docs/teardown-test/inventory.md
- docs/stack-lifecycle-refactor/plan.md

What to do:
1. Read the current validated docs and recent state:
   - docs/teardown-test/reports/20260516-052235.md
   - docs/stack-lifecycle-refactor/handoff.md
   - docs/provisioning-refactor/README.md
   - docs/step-ca-implementation/README.md
2. Update the target files so they reflect the repo’s current promotion model
   and validated baseline state.
3. Remove or clearly mark stale references to:
   - dev/pve-test as the active integration branch where it is no longer true
   - refactor/stack-lifecycle as the live execution branch where it is no
     longer true
   - homelab.internal / old ingress assumptions where current docs use
     lab.gibbsgreatly.xyz
   - Nginx Proxy Manager as an active future dependency where it conflicts with
     current architecture
4. Keep edits factual and minimal. Do not rewrite the whole plan set.

Validation:
- grep for remaining stale references in the edited files
- ensure statements do not conflict with docs/teardown-test/reports/20260516-052235.md
- run ./with-secrets /home/steve/.local/bin/sonar-scanner if code-style-sensitive
  docs/scripts are touched; otherwise summarize why not needed

Deliver:
- concise summary of what was stale and what was updated
- list of files changed
- any residual docs that still need a later deeper rewrite
```

## Prompt 02: Teardown Harness Hardening

```text
You are working in /home/steve/git/proxmox-homelab.

Goal:
Advance scripts/teardown-deploy-test.sh from "working harness" toward
"reusable productized harness" using the already-written roadmap.

Primary references:
- docs/teardown-test/harness-roadmap.md
- docs/teardown-test/repeatable-test.md
- docs/teardown-test/decisions.md
- docs/teardown-test/reports/20260516-052235.md

Scope:
Implement one bounded hardening slice only:
- structural approval-packet validation improvements
- and/or harness self-tests for safety gates
- and/or summary/report generation

Pick the single best slice based on the roadmap and explain why.

Rules:
- Do not weaken destructive safeguards.
- Do not add any automatic destructive execution.
- Keep changes bounded to the harness and its direct docs/tests.
- Prefer source-only verification and mockable tests over live pve-test
  dependency.

Expected files may include:
- scripts/teardown-deploy-test.sh
- docs/teardown-test/repeatable-test.md
- docs/teardown-test/harness-roadmap.md
- a new tests file if appropriate

Validation:
- bash -n scripts/teardown-deploy-test.sh
- shellcheck scripts/teardown-deploy-test.sh
- run any new harness tests you add
- run safe non-mutating commands only, such as:
  - scripts/teardown-deploy-test.sh --help
  - scripts/teardown-deploy-test.sh plan
  - scripts/teardown-deploy-test.sh status --stamp 20260516-052235

Deliver:
- the specific roadmap item completed
- evidence that safety behavior still holds
- what should be the next harness hardening slice after this one
```

## Prompt 03: Shared Stack Contract Tidyup

```text
You are working in /home/steve/git/proxmox-homelab.

Goal:
Close small real contract gaps in stack metadata that can affect rebuild
consistency, starting with explicit dns_server handling.

Context:
- docs/design/network.md calls out dns_server coverage as a known gap.
- Multiple terraform/lxc/stacks/*/stack.yaml files still omit dns_server.
- This is a contract cleanup and validation pass, not a large refactor.

What to do:
1. Audit current dns_server handling across stack.yaml files and the code that
   consumes stack metadata.
2. Decide the minimal safe contract rule:
   - either require dns_server explicitly everywhere relevant
   - or document/enforce a deterministic derived default per zone
3. Implement the smallest safe fix in code and source files.
4. Update the relevant docs so the rule is explicit.

Likely touch points:
- terraform/lxc/stacks/*/stack.yaml
- terraform/lxc/edge_manifest.py or related stack parsing/validation code if needed
- docs/design/network.md
- docs/plan/development-status.md or related contract docs if needed

Validation:
- run relevant unit tests if stack metadata parsing is touched
- run /home/steve/.local/bin/snyk iac test terraform/
- run ./with-secrets /home/steve/.local/bin/sonar-scanner if Python/shell/YAML
  code is touched

Deliver:
- the contract rule you chose
- files updated
- whether any remaining stack-metadata gaps should be queued next
```

## Prompt 04: Re-plan Phase 06 App Migration

```text
You are working in /home/steve/git/proxmox-homelab.

Goal:
Rewrite the application-migration plan so it matches the platform that now
actually exists.

Context:
- The platform foundation and stack-owned edge model are now validated.
- docs/plan/phase-06-app-stacks.md still contains stale assumptions
  (homelab.internal, NPM cleanup, older branch model, older ingress flow).
- This is a planning/doc task only. Do not implement app stacks yet.

What to do:
1. Read the current authoritative context:
   - docs/provisioning-refactor/README.md
   - docs/provisioning-refactor/runbook.md
   - docs/teardown-test/reports/20260516-052235.md
   - docs/design/network.md
   - docs/plan/phase-05-supply-chain.md
2. Update docs/plan/phase-06-app-stacks.md so it reflects:
   - current naming and routing conventions
   - current branch/promotion model
   - stack-owned edge expectations
   - Harbor-only image sourcing and current supply-chain expectations
   - current prerequisites based on what is already validated
3. Keep the migration order pragmatic and incremental.
4. Identify the first real implementation slice that should follow the replanning
   pass.

Validation:
- grep for stale terms removed or intentionally retained:
  - homelab.internal
  - Nginx Proxy Manager / NPM
  - outdated branch references
- ensure the updated plan does not conflict with current edge and teardown docs

Deliver:
- summary of stale assumptions removed
- recommended first app-migration slice after replanning
- any dependencies still genuinely missing before Phase 06 starts
```

## Prompt 05: Narrow step-ca Follow-Up

```text
You are working in /home/steve/git/proxmox-homelab.

Goal:
Take the next bounded step in the post-AuthentiK direct-TLS work without
reopening the already-completed migrations.

Context:
- Grafana, Portainer, and Traefik forward-auth Authentik backchannels are done.
- Harbor remains the main special case.
- The remaining roadmap in docs/step-ca-implementation/workstreams-and-order.md
  points to Harbor posture, renewal/expiry checks, and CA rotation response.

Task:
Choose exactly one of these slices and complete only that slice:
1. Harbor-specific Authentik/TLS posture clarification in docs and code comments
2. Shared renewal/expiry/reload validation checks
3. CA rotation / compromise response documentation and operator workflow

Rules:
- Do not reopen Grafana/Portainer/Traefik migration work.
- Do not force Harbor onto a design that the repo has already deferred unless
  the code clearly supports it.
- Prefer the smallest implementation-grounded step.

Validation:
- run the appropriate local tests/checks for changed code
- run /home/steve/.local/bin/snyk iac test terraform/ if Terraform/YAML is touched
- run ./with-secrets /home/steve/.local/bin/sonar-scanner if Python/shell/YAML
  code is touched

Deliver:
- which slice you chose and why
- what it resolves
- what remains deferred after this slice
```

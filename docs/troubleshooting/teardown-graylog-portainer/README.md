# Sprint Plan — Graylog And Portainer Teardown Recovery

**Observed:** 2026-07-01
**Scope:** `pve-test-vm` teardown/redeploy cycle
**Primary goal:** Make `graylog-stack` participate correctly in teardown so the platform phase reaches and deploys `portainer-stack` reliably.
**Updated:** 2026-07-02

---

## Problem Summary

The original failing teardown runs did not show a Graylog startup timing problem
as the primary issue. They showed a control-path mismatch:

- the teardown harness now treats `graylog-stack` as a required platform stack
- `deploy-graylog-stack.yml` still treats the real Graylog runtime as optional
- the normal `scripts/provision.sh --stack graylog-stack` path does not enable
  that runtime path
- the playbook therefore succeeds in scaffold-only mode
- the harness then probes `http://192.168.20.114:9000/api/system/lbstatus`
  and fails because no Graylog process is listening
- the platform phase aborts before `netbox-stack` and `portainer-stack`

That root cause has now been addressed on the working branch. This plan is now
primarily a validation and hardening plan to close the loop with full teardown
evidence.

---

## Success Criteria

A sprint is complete only when all of the following are true in one teardown
cycle on `pve-test-vm`:

1. `graylog-stack` is destroyed and recreated cleanly.
2. `provision-graylog-stack` writes the real runtime assets, not only scaffold
   placeholders.
3. Graylog containers are present and healthy in the LXC.
4. `health-graylog-stack` returns `ALIVE`.
5. The platform phase continues past Graylog to `netbox-stack` and
   `portainer-stack`.
6. `portainer-stack` is actually deployed and passes its direct API health
   check.
7. `graylog.test.gibbsgreatly.xyz` and `portainer.test.gibbsgreatly.xyz` both
   work in final validation.

---

## Constraints

- Investigation and implementation should stay on a short-lived branch.
- Validation target is `pve-test-vm`, not `pve`.
- No change should be promoted until the appropriate validation tier passes.
- Because this crosses Ansible, teardown orchestration, Graylog runtime, and
  platform sequencing, the minimum acceptance gate is a full teardown cycle on
  `pve-test-vm`.
- Container image pull policy should be explicit:
  - before `harbor-stack` exists in a run, direct upstream pulls are acceptable
  - once Harbor is up and reachable, Harbor-backed image paths are mandatory
    wherever a Harbor proxy/cache route exists
  - direct pulls after Harbor is available should be treated as a contract
    violation, not just a style issue

## Current Working State

As of 2026-07-02 on the current working branch:

- `graylog-stack` targeted destroy/redeploy succeeds on `pve-test-vm`
- Graylog is healthy in-browser at `graylog.test.gibbsgreatly.xyz`
- Graylog runtime images and cAdvisor now resolve through Harbor-backed image
  paths
- legacy `portainer-agent` residue on Graylog has been cleaned up in
  provisioning
- dashboard import no longer warns when the dashboards directory is absent
- scaffold assets no longer write during the normal runtime path

The remaining open proof point is a full teardown cycle showing that the
platform phase now proceeds through Graylog and on to NetBox and Portainer
from a true cold-start Graylog state.

---

## Sprint 0 — Correct The Incident Record

**Goal:** Align the troubleshooting record with the actual evidence so future
work starts from the right root cause.

### Findings to capture

- The July 1 teardown run did perform a real destroy and redeploy.
- `provision-graylog-stack` passed in scaffold-only mode.
- Graylog runtime tasks were skipped because the runtime gate was not enabled.
- The 24-attempt health retry failed because nothing was listening on port
  `9000`, not because Graylog was merely slow to bind.
- Portainer was never deployed because the platform phase stopped at
  `health-graylog-stack`.

### Deliverables

- Update the existing troubleshooting narrative.
- Link the specific evidence directory:
  `docs/teardown-test/artifacts/evidence/20260701-011024/`
- Record the live container-state findings from the Graylog LXC.

### Exit gate

- The docs no longer describe “external bind timing” as the main root cause.

---

## Sprint 1 — Make Graylog Runtime Part Of The Standard Provision Path

**Goal:** Remove the gap between manual Graylog validation and teardown-driven
Graylog provisioning.

### Result

Completed on the working branch. Graylog now follows the normal provision path
correctly enough to pass targeted destroy/redeploy validation on `pve-test-vm`.

### Deliverables

- One canonical, repeatable Graylog deploy path for teardown and normal stack
  provisioning.
- Updated documentation describing how Graylog is provisioned in live flows.

### Validation

Run a targeted Graylog provision flow on `pve-test-vm`:

```bash
PVE_ENV=pve-test-vm ./with-secrets scripts/provision.sh --stack graylog-stack
```

Then verify:

- `/opt/graylog-stack/graylog.env` exists
- `/opt/graylog-stack/docker-compose.yml` exists
- Graylog containers exist
- local `lbstatus` returns `ALIVE`

### Exit gate

- Satisfied on the branch through targeted Graylog redeploy validation.

---

## Sprint 2 — Fix Cold-Start Graylog Preflight Sequencing

**Goal:** Make the Graylog first-boot path behave correctly on a fully rebuilt
stack.

### Why

The later July 1 teardown evidence showed a different regression from the
original scaffold-only bug:

- Graylog runtime came up
- preflight API calls succeeded through certificate generation
- `/api/data_nodes` returned a DataNode in `UNCONFIGURED`
- the playbook waited for `AVAILABLE` before calling
  `/api/status/finish-config`
- the stack never transitioned into normal mode

That exact sequencing bug only shows up on a true cold start, which is why the
full teardown reproduced it more reliably than follow-up reprovision work.

### Deliverables

- Update the Graylog preflight automation so `finish-config` happens before the
  playbook requires DataNode `AVAILABLE`.
- Treat `UNCONFIGURED` as an expected transient state immediately after
  certificate generation on a blank stack.
- Keep a post-finalization wait that still proves the DataNode reaches
  `AVAILABLE` before the playbook continues.

### Validation

Run:

```bash
PVE_ENV=pve-test-vm ./with-secrets scripts/provision.sh --stack graylog-stack
```

Expected behavior:

- success only if Graylog runtime is present, reaches `ALIVE`, and the DataNode
  becomes `AVAILABLE`
- immediate failure if Graylog remains stuck in preflight

### Exit gate

- Code fix applied on the working branch; targeted and full-cycle validation
  still pending.

---

## Sprint 3 — Add Earlier Graylog Failure Detection

**Goal:** Fail at Graylog provision time, not later in the platform phase, if
the stack did not actually come up.

### Why

The original scaffold-only issue has been fixed, but operator clarity still
matters when Graylog is doing a slow first boot. The logs should make it easy
to distinguish an expected warm-up from a real stuck-preflight condition.

### Deliverables

- A `graylog-stack` smoke test or equivalent early assertion that proves the
  runtime is actually present.
- A failure message that distinguishes:
  - scaffold-only provisioning
  - containers absent
  - containers present but not healthy
  - `lbstatus` failing
  - expected cold-start retries versus final failure

### Validation

Run:

```bash
PVE_ENV=pve-test-vm ./with-secrets scripts/provision.sh --stack graylog-stack
```

Expected behavior:

- success only if Graylog runtime is present and healthy
- immediate failure if the playbook stops at scaffold mode

### Exit gate

- Partially satisfied. Silent scaffold success has been removed from the normal
  path; remaining work is mostly log/smoke-test clarity.

---

## Sprint 4 — Revalidate Graylog In The Teardown Harness

**Goal:** Prove the teardown harness can destroy, recreate, provision, and
health-check Graylog correctly.

### Focus

This sprint is about the harness path, not just standalone provision.

### Deliverables

- A successful `graylog-stack` segment in the teardown cycle evidence.
- Evidence that `health-graylog-stack` passes after the real runtime deploy.

### Validation

Run a disposable teardown cycle on `pve-test-vm`.

Required evidence from the run:

- `deploy-graylog-stack.log`
- `provision-graylog-stack.log`
- `pct-status-graylog-stack.log`
- `health-graylog-stack.log`

Expected outcome:

- Graylog health returns `ALIVE`
- the platform phase proceeds beyond Graylog

### Exit gate

- `health-graylog-stack` passes in the teardown harness.

---

## Sprint 5 — Verify Downstream Platform Progression To Portainer

**Goal:** Confirm that once Graylog passes, the harness reaches and deploys the
downstream platform stacks.

### Why

Portainer is currently a blocked downstream service, not the first-order root
cause. This sprint verifies that the unblock is real.

### Deliverables

- Evidence that `netbox-stack` and `portainer-stack` are reached in the
  platform phase.
- Direct Portainer API health success after teardown-driven deploy.

### Validation

In the same full teardown cycle, confirm these logs exist:

- `deploy-netbox-stack.log`
- `provision-netbox-stack.log`
- `deploy-portainer-stack.log`
- `provision-portainer-stack.log`
- `health-portainer-stack.log`

Expected outcome:

- Portainer direct API probe succeeds
- Portainer is no longer absent due to Graylog abort

### Exit gate

- Portainer is deployed and healthy in the same teardown run that includes
  Graylog.

---

## Sprint 4A — Enforce Harbor-First Image Pulls

**Goal:** Make Harbor-backed image routing part of the teardown deployment
contract once `harbor-stack` is available.

### Why

The current stack set is inconsistent:

- `graylog-stack` now pulls via Harbor explicitly
- `netbox-stack` uses Harbor for primary app images, but not every helper image
- `portainer-stack` still hardcodes direct upstream image names

That means teardown can still succeed today while silently depending on direct
access to Docker Hub or `gcr.io`, which conflicts with the intended platform
contract.

### Deliverables

- Update stack playbooks and generated compose files so Harbor-backed image
  references are used wherever a Harbor proxy/cache route exists.
- Route remaining direct `cadvisor` references through Harbor.
- Route the shared `portainer_agent` role through Harbor-backed image paths.
- Route `portainer/portainer-ce` through Harbor when Harbor is reachable.
- Remove legacy `portainer-agent` residue from platform-tier Docker stacks such
  as `graylog-stack`, where `portainer_agent: false` is already part of the
  stack contract.
- Keep a narrowly defined fallback for phases where Harbor is not yet deployed.
- Add a validation check that flags direct upstream image references once
  Harbor is available in the run.

### Validation

Verify on `pve-test-vm`:

- generated compose files for Graylog, NetBox, and Portainer reference
  `harbor.test.gibbsgreatly.xyz/...` for supported images
- targeted provisions of those stacks still pass
- a full teardown cycle still passes after Harbor is deployed in the platform
  phase

### Exit gate

- After `harbor-stack` is up, no supported stack in the teardown platform flow
  pulls directly from upstream registries.

---

## Sprint 5 — End-To-End Browser And Edge Validation

**Goal:** Confirm the platform works as an operator sees it, not only through
direct LXC probes.

### Deliverables

- Graylog route works through Traefik
- Portainer route works through Traefik
- final-validation evidence is green or any residual gaps are explicitly
  documented

### Validation

Use the normal teardown final validation and direct edge checks.

Required outcomes:

- `graylog.test.gibbsgreatly.xyz` loads
- `portainer.test.gibbsgreatly.xyz` loads
- no new regressions in Authentik, Grafana, Harbor, NetBox, or Traefik

### Exit gate

- User-facing browser paths are good after a full teardown cycle.

---

## Sprint 6 — Hardening And Promotion Readiness

**Goal:** Reduce the chance of the same class of failure recurring silently.

### Hardening targets

- Make Graylog runtime intent explicit in code and docs.
- Add tests around any harness or provision logic that now special-cases
  `graylog-stack`.
- Ensure troubleshooting docs and stack contract reflect live behavior, not
  historical scaffold behavior.

### Recommended checks

- `ansible-playbook --syntax-check` on affected playbooks
- security scan(s) appropriate to the touched files
- full teardown cycle evidence retained in `docs/teardown-test/artifacts`

### Exit gate

- The fix is understandable, repeatable, and backed by live evidence.

---

## Suggested Execution Order

1. Sprint 0 — correct the record.
2. Sprint 1 — make Graylog runtime standard.
3. Sprint 2 — add earlier failure detection.
4. Sprint 3 — prove Graylog in teardown.
5. Sprint 4 — verify Portainer progression.
6. Sprint 5 — browser and edge validation.
7. Sprint 6 — hardening and promotion readiness.

---

## Evidence Checklist

For the fixing sprint, keep one evidence packet that includes:

- branch and commit used for the fix
- the full teardown stamp
- Graylog provision log
- Graylog health log
- Portainer deploy/provision/health logs
- final validation summary
- any live read-only host/container checks needed to explain anomalies

---

## Open Questions

1. Should Graylog’s direct smoke test check localhost inside the LXC, external
   LXC IP reachability, or both?
2. Should the smoke test wording distinguish normal cold-start retries from
   actual failure more clearly?
3. Once the full teardown cycle passes, which branch should become the promotion
   source for `stable` given that the current working branch name no longer
   matches the active scope?

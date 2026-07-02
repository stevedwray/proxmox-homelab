# Docs Subdirectory Status Report

Date: 2026-07-03

This report reviews each current first-level subdirectory under `docs/` for:

- relevance to possible future work
- evidence of planned or unfinished work
- amount of completed or historical material
- redundancy / cleanup pressure

Status labels used below:

- `active`: still useful for likely future work
- `active but bloated`: still relevant, but should be shortened or consolidated
- `historical reference`: mostly useful as background, not as the primary current path
- `candidate archive`: little evidence of near-term future value in the tracked docs surface

## Summary Table

| Directory | Files | Future relevance | Planned / unfinished work | Completed / historical load | Redundancy / cleanup pressure | Overall status |
| --- | ---: | --- | --- | --- | --- | --- |
| `docs/agent-design/` | 3 | Medium | Medium | Medium | Medium | historical reference |
| `docs/application-migration/` | 6 | Medium | High | Low | Low | active |
| `docs/baseline-merge/` | 3 | Low | Low | High | Medium | candidate archive |
| `docs/code-cleanup/` | 3 | Medium | Medium | Medium | Low | active |
| `docs/design/` | 10 | High | Medium | Medium | Medium | active |
| `docs/docker-refactor/` | 2 | Medium | Medium | Medium | Low | active |
| `docs/harbor-stack/` | 1 | Medium | High | Low | Low | active |
| `docs/monitoring-stack/` | 3 | Medium | Medium | Medium | Medium | active but bloated |
| `docs/netbox-stack/` | 7 | High | High | Medium | Medium | active |
| `docs/network-refactor/` | 12 | Medium | Medium | High | Medium | historical reference |
| `docs/plan/` | 88 | High | High | High | High | active but bloated |
| `docs/platform-hardening/` | 2 | Low | Low | High | Medium | candidate archive |
| `docs/portainer-stack/` | 3 | Medium | Medium | Medium | Low | active |
| `docs/productionize-refactor/` | 37 | Medium | Low to Medium | High | High | historical reference |
| `docs/provisioning-refactor/` | 173 | High | High | Medium | High | active but bloated |
| `docs/reference/` | 5 | High | Low | Low | Low | active |
| `docs/repo-review/` | 3 | Medium | Medium | Low | Low | active |
| `docs/stack-lifecycle-refactor/` | 24 | Medium to High | Medium | High | High | active but bloated |
| `docs/step-ca-implementation/` | 8 | Medium | Medium | Medium | Medium | active |
| `docs/storage-refactor/` | 14 | Medium | Medium | Medium | High | active but bloated |
| `docs/teardown-test/` | 24 | High | High | Medium | Medium | active, critical validation surface |
| `docs/threat-model/` | 2 | High | Low | Low | Low | active |
| `docs/troubleshooting/` | 8 | High | Low | Medium | Medium | active |
| `docs/workflow/` | 7 | High | Low | Low | Low | active |

## Directory Notes

### `docs/agent-design/`

- Current role: meta-documentation about agent / Copilot-aware repo structure.
- Future work relevance: moderate, but it is about tool/process design rather than core homelab operation.
- Planned / unfinished signals: present, but not central to current infra roadmap.
- Completed / historical load: noticeable; reads more like an earlier design exploration than a current operating surface.
- Redundancy: overlaps with `AGENTS.md`, `.github/copilot-instructions.md`, and `docs/workflow/documentation-workspaces.md`.
- Recommendation: keep as historical reference unless active agent-platform work resumes.

### `docs/application-migration/`

- Current role: planned migration of legacy application stacks into the SDN model.
- Future work relevance: real, because Phase 06 / application migration remains a likely future track.
- Planned / unfinished signals: strong; the overview explicitly describes planned sprints and target zones.
- Completed / historical load: low so far.
- Redundancy: limited; this is a reasonably scoped future-work area.
- Recommendation: keep active.

### `docs/baseline-merge/`

- Current role: convergence planning around the retired `baseline/teardown-validated` branch model.
- Future work relevance: low after the branch-model shift to `stable`.
- Planned / unfinished signals: weak relative to the current workflow.
- Completed / historical load: high; this is tied to a superseded promotion model.
- Redundancy: overlaps with current workflow docs and older merge planning.
- Recommendation: archive once any still-useful conclusions are captured elsewhere.

### `docs/code-cleanup/`

- Current role: bounded cleanup of scan findings and maintainability issues.
- Future work relevance: moderate; code-health work can recur.
- Planned / unfinished signals: still present.
- Completed / historical load: moderate, but contained.
- Redundancy: low.
- Recommendation: keep active, but keep it narrow and avoid turning it into a general issue graveyard.

### `docs/design/`

- Current role: durable architecture reference.
- Future work relevance: high.
- Planned / unfinished signals: some, but most value is as long-lived design truth.
- Completed / historical load: moderate; some content reflects prior stages but still informs current design.
- Redundancy: moderate, especially where plan docs restate architecture.
- Recommendation: keep active and authoritative.

### `docs/docker-refactor/`

- Current role: current-state plus plan for the Docker socket proxy workstream.
- Future work relevance: moderate; the proof is done but full operational completion is not.
- Planned / unfinished signals: still present in `current-state.md` and planning.
- Completed / historical load: moderate.
- Redundancy: low after artifact cleanup.
- Recommendation: keep active, but it is close to being compressible into one shorter current-state document.

### `docs/harbor-stack/`

- Current role: Harbor scanning / monitoring plan.
- Future work relevance: moderate and concrete.
- Planned / unfinished signals: strong; the README is explicitly a plan for missing implementation.
- Completed / historical load: low to moderate.
- Redundancy: low.
- Recommendation: keep active.

### `docs/monitoring-stack/`

- Current role: monitoring design plus Graylog migration direction.
- Future work relevance: moderate.
- Planned / unfinished signals: still present, especially around Graylog direction and design choices.
- Completed / historical load: moderate.
- Redundancy: some overlap with broader plan and troubleshooting material.
- Recommendation: keep, but compress; this is small in file count but can still be verbose.

### `docs/netbox-stack/`

- Current role: NetBox populate / ownership / runtime discovery planning and state.
- Future work relevance: high.
- Planned / unfinished signals: strong.
- Completed / historical load: moderate, but mostly still relevant.
- Redundancy: moderate across ownership, current-state, and canary notes.
- Recommendation: keep active; probably worth consolidating into a tighter entrypoint plus fewer supporting docs.

### `docs/network-refactor/`

- Current role: planning and session summaries for the network / provisioning reachability refactor.
- Future work relevance: moderate if that refactor resumes.
- Planned / unfinished signals: still present.
- Completed / historical load: high because multiple session summaries remain inline.
- Redundancy: moderate; overlaps with `docs/design/network.md` and later workflow / provisioning docs.
- Recommendation: treat as historical reference with one clear current-state / resume path.

### `docs/plan/`

- Current role: the main phase and task index for the build.
- Future work relevance: high.
- Planned / unfinished signals: high.
- Completed / historical load: also high; many task packets are now explicitly historical.
- Redundancy: high due to layered phases, task packets, and historical plan snapshots.
- Recommendation: keep active, but continue aggressive compression and historical labeling.

### `docs/platform-hardening/`

- Current role: a specific branch-era bridging package for socket proxy plus edge reconciliation.
- Future work relevance: low unless this exact convergence state becomes active again.
- Planned / unfinished signals: weak compared with newer provisioning-refactor and teardown-test docs.
- Completed / historical load: high.
- Redundancy: overlaps with `docs/docker-refactor/`, `docs/netbox-stack/`, and `docs/provisioning-refactor/`.
- Recommendation: candidate archive.

### `docs/portainer-stack/`

- Current role: Portainer boundary / backup / migration notes.
- Future work relevance: moderate.
- Planned / unfinished signals: present, especially for application-stack ownership.
- Completed / historical load: moderate.
- Redundancy: low to moderate.
- Recommendation: keep active unless Portainer’s role is reduced further.

### `docs/productionize-refactor/`

- Current role: reduced historical reference for productionization.
- Future work relevance: moderate as background, low as the primary work surface.
- Planned / unfinished signals: limited; even the README frames it as retained historical reference.
- Completed / historical load: high.
- Redundancy: high with current workflow, reference, and plan docs.
- Recommendation: keep as historical reference only; continue resisting regrowth here.

### `docs/provisioning-refactor/`

- Current role: source of truth for the stack-owned edge provisioning refactor.
- Future work relevance: high.
- Planned / unfinished signals: high.
- Completed / historical load: moderate.
- Redundancy: high because of size; 173 files is far above what a current refactor area should need.
- Important nuance: this directory is not just a refactor backlog. It is part of
  the practical path for proving that the integrated platform can be rebuilt and
  reconciled safely, especially where stack-owned edge behavior intersects with
  teardown / redeploy validation.
- Recommendation: keep active, but compress around the pieces that are actually
  part of the hard-validation path and the current source of truth.

### `docs/reference/`

- Current role: stable operator reference.
- Future work relevance: high.
- Planned / unfinished signals: low, which is appropriate for reference.
- Completed / historical load: low.
- Redundancy: low.
- Recommendation: keep active and authoritative.

### `docs/repo-review/`

- Current role: this cleanup and catalog work.
- Future work relevance: moderate in the short term while the tidy-up continues.
- Planned / unfinished signals: present.
- Completed / historical load: currently low.
- Redundancy: low.
- Recommendation: keep active during the cleanup campaign; archive or summarize once the campaign closes.

### `docs/stack-lifecycle-refactor/`

- Current role: planning tree for Terraform / Ansible lifecycle boundaries and stack contract evolution.
- Future work relevance: medium to high.
- Planned / unfinished signals: still present.
- Completed / historical load: high; many stage/session documents remain.
- Redundancy: high, especially where current-state, plan, stage docs, and execution docs overlap.
- Recommendation: keep active but compress hard around a smaller durable core.

### `docs/step-ca-implementation/`

- Current role: step-ca expansion planning package.
- Future work relevance: moderate.
- Planned / unfinished signals: present.
- Completed / historical load: moderate.
- Redundancy: moderate with `docs/plan/`, `docs/design/`, and service-specific docs.
- Recommendation: keep active if step-ca work is still expected; otherwise summarize.

### `docs/storage-refactor/`

- Current role: planning package for safer LXC storage mutations.
- Future work relevance: moderate.
- Planned / unfinished signals: present.
- Completed / historical load: moderate.
- Redundancy: elevated because prompt-oriented documents are still tracked alongside core plan material.
- Recommendation: keep, but this area should be reduced to a tighter current-state / plan / capability set.

### `docs/teardown-test/`

- Current role: current source of truth for destructive rebuild rehearsal on `pve-test-vm`.
- Future work relevance: high.
- Planned / unfinished signals: high.
- Completed / historical load: moderate, but mostly converted into durable runbook-style docs rather than raw artifacts.
- Redundancy: moderate across runbook, operations plan, task sequence, backup plan, and roadmap.
- Important nuance: this is a critical validation area, not just another
  planning cluster. It documents the hardest proof of work in the repo:
  tearing down, redeploying, reprovisioning, and validating the integrated
  infrastructure stacks end to end.
- Recommendation: keep active and authoritative. Consolidation here should aim
  to strengthen trust and navigability, not demote the area to historical or
  optional status.

## Validation Process Direction

One structural direction now looks justified:

- preserve `docs/teardown-test/` as the operator-facing authority for hard
  validation
- treat the relevant current subset of `docs/provisioning-refactor/` as a
  tightly coupled dependency of that validation story
- consider a future dedicated validation-process namespace if the teardown,
  deploy, provision, reconcile, and integrated stack-validation story needs a
  cleaner home than the current split across multiple directories

That does **not** imply moving content immediately. It means future cleanup
should be careful to preserve the hard-validation narrative and, if needed,
re-home it deliberately rather than fragmenting it further.

### `docs/threat-model/`

- Current role: threat-model input data.
- Future work relevance: high as a durable security input.
- Planned / unfinished signals: low.
- Completed / historical load: low.
- Redundancy: low.
- Recommendation: keep active.

### `docs/troubleshooting/`

- Current role: operational break/fix reference.
- Future work relevance: high.
- Planned / unfinished signals: low, appropriately.
- Completed / historical load: medium; some docs are incident-specific but still useful.
- Redundancy: moderate if one-off regressions accumulate without pruning.
- Recommendation: keep active, but periodically archive obsolete incident notes.

### `docs/workflow/`

- Current role: canonical workflow / environment / documentation pattern guidance.
- Future work relevance: high.
- Planned / unfinished signals: low, which is appropriate.
- Completed / historical load: low.
- Redundancy: low.
- Recommendation: keep active and keep centralizing process truth here.

## Highest-Value Ongoing Targets

If the goal is to keep future LLM context lean while preserving useful planning
surface, the highest-value directories to keep trimming are:

1. `docs/provisioning-refactor/`
2. `docs/plan/`
3. `docs/stack-lifecycle-refactor/`
4. `docs/teardown-test/`
5. `docs/productionize-refactor/`
6. `docs/network-refactor/`
7. `docs/storage-refactor/`

## Likely Keep Surface

The strongest long-lived docs surface continues to look like:

- `docs/workflow/`
- `docs/reference/`
- `docs/design/`
- `docs/teardown-test/` as the hard-validation authority
- selected current-state / plan docs from:
  - `docs/plan/`
  - `docs/provisioning-refactor/`
  - service-specific areas still tied to unfinished implementation

## Bottom Line

The `docs/` tree is no longer dominated by raw artifacts, but it is still
dominated by active-planning sprawl and historical planning residue.

The directories fall into three broad groups:

- canonical and durable: `workflow`, `reference`, `design`, `threat-model`, much of `troubleshooting`
- active but oversized: `plan`, `provisioning-refactor`, `stack-lifecycle-refactor`, `teardown-test`, `netbox-stack`, `storage-refactor`
- historical or near-historical: `baseline-merge`, `platform-hardening`, large parts of `productionize-refactor`, `network-refactor`, and some agent/process design material

That split should guide the next cleanup passes.

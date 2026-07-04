# Review: `docs/productionize-refactor/`

Date: 2026-07-03

## Scope

Review of the contents of `docs/productionize-refactor/` to identify what may
still be useful versus what is now historical residue.

Tracked file breakdown at review time:

- root docs: 17
- `tasks/`: 8
- `runbooks/`: 12
- `handoffs/`: 37
- `evidence/`: 149
- total tracked files: 223

## Findings

### High: the directory index still advertises a retired branch model

The main README still frames this area around `refactor/productionize` and
`baseline/teardown-validated`, which no longer matches the repo’s current
workflow model. That makes the top-level entrypoint actively misleading if this
directory remains browsable as “current” documentation.

References:

- [README.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/README.md:24)
- [pve-production-readiness.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/pve-production-readiness.md:62)
- [tasks/README.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/tasks/README.md:35)

### High: the majority of the directory is execution residue, not canonical guidance

Out of 223 tracked files, 149 are under `evidence/` and 37 are under
`handoffs/`. That means over 80% of the directory is session/evidence-oriented
material rather than durable reference or plan documentation.

This is the main reason the directory bloats LLM context and feels risky to
delete wholesale: it mixes a small valuable core with a large amount of
historical scaffolding.

References:

- `docs/productionize-refactor/evidence/` tracked count: 149
- `docs/productionize-refactor/handoffs/` tracked count: 37

### Medium: some “current” docs are self-described legacy or historical

`runbooks/EXECUTION-CHECKLIST.md` explicitly says it is a legacy apt-cacher
checklist and points readers elsewhere. That is useful as a migration hint, but
it should not be treated as a primary runbook anymore.

References:

- [runbooks/EXECUTION-CHECKLIST.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/runbooks/EXECUTION-CHECKLIST.md:3)

### Medium: several handoff docs still contain useful lessons, but only as postmortem summaries

At least some late handoffs are valuable because they summarize operational
lessons learned from production recovery work, not just session prompts.
`37-fresh-session-handoff.md` is the clearest example: it captures root causes,
what fixes mattered, and what evidence was shallow or misleading.

That is useful material, but it belongs in a condensed retrospective or
lessons-learned doc rather than in a live handoff queue.

References:

- [handoffs/37-fresh-session-handoff.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/handoffs/37-fresh-session-handoff.md:49)
- [handoffs/37-fresh-session-handoff.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/handoffs/37-fresh-session-handoff.md:135)

### Low: the strategy docs still contain durable information

The core plan and inventory docs still contain useful, reusable information
about production targeting and cutover hazards:

- production collision control
- the need for environment-specific `pve` manifests
- the split between `pve-test` and `pve`
- deploy/destroy order for platform stacks

These are still potentially worth keeping in some form.

References:

- [pve-production-readiness.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/pve-production-readiness.md:14)
- [pve-production-readiness.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/pve-production-readiness.md:104)
- [pve-infra-teardown-inventory.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/pve-infra-teardown-inventory.md:32)
- [pve-infra-teardown-inventory.md](/home/steve/git/proxmox-homelab/docs/productionize-refactor/pve-infra-teardown-inventory.md:64)

## What Still Looks Useful

Most likely keep or salvage candidates:

- `pve-production-readiness.md`
- `pve-infra-teardown-inventory.md`
- selected canary closure summaries such as:
  - `09-monitoring-canary-closure.md`
  - `11-portainer-canary-closure.md`
- a very small subset of runbooks if still used operationally
- selected lessons from late recovery handoffs, especially:
  - `handoffs/37-fresh-session-handoff.md`

Why these matter:

- they summarize production assumptions and hazards
- they capture migration outcomes rather than raw transcripts
- they may still help if future `pve` work resumes

## What Looks Safe To Treat As Historical

Strong archive/delete candidates inside this directory:

- all of `evidence/`
- most of `handoffs/`
- most one-off execution packets in the root, especially stack-specific canary
  packets once their results are captured elsewhere
- `runbooks/EXECUTION-CHECKLIST.md` if the newer stack-specific runbooks are the
  real source of truth

Why:

- they are mostly operational transcripts or session scaffolds
- they are recoverable from git history
- they add substantial context volume without being good primary docs

## Recommendation

Do not delete the whole directory blindly.

Recommended approach:

1. Preserve a small retained core:
   - `README.md` only if rewritten as historical index
   - `pve-production-readiness.md`
   - `pve-infra-teardown-inventory.md`
   - any canary closure summaries you still consider meaningful
2. Delete `evidence/` entirely if you are comfortable relying on git history.
3. Delete most of `handoffs/`, keeping only a tiny number of late summary docs
   if desired.
4. Delete or archive obsolete runbooks that now point at other docs.
5. If retained, clearly relabel the directory as historical production
   migration reference rather than current workflow guidance.

## Bottom Line

Yes, some of `docs/productionize-refactor/` is still useful, but only a small
minority of it.

The directory should be treated as:

- useful core strategy docs plus
- a large mass of historical execution residue

It is not an all-or-nothing keep.

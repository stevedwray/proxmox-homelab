# Shared reporting/artifact platform

Status: Phases 0–2 complete (2026-09-22). Multiple AI-tooling projects in
this homelab each produce a "report" at the end of a run, and each had
independently invented a different, minimal way to hold onto it:

- **deep-research** (`docs/deep-research/`): wrote a real, persistent
  `final_report.md` per run to disk, but the only way to view it was a
  raw file browser with no markdown rendering.
- **CyberSecEval** (`docs/cyberseceval-panel/`): raw benchmark output
  (`responses.json`/`run.log`/`stat.json`) turned out to already be
  durable on `cse-controller`'s own disk — the real gap was narrower
  than first assumed: only Celery's task-result TTL and the panel's own
  24h `job_meta` TTL lived in Redis, so once those expired the panel
  lost all ability to *discover* a run ever happened, with the same
  practical effect as data loss even though the files survived.

Both were symptoms of the same root cause: neither project treated
"durably store and present this run's output" as a shared platform
concern, so each built a narrower, weaker version of it. More similar
projects are expected. This workspace defines one small shared
convention and viewer service instead of a third bespoke one-off.

See [plan.md](plan.md) for the full design, phase-by-phase history, and
what's still open. See [CONVENTION.md](CONVENTION.md) for the stable
storage-convention reference other projects' docs link to.

## What's actually built

1. **Storage convention** ([CONVENTION.md](CONVENTION.md)) —
   `reports/<project>/<run-id>/`, a required `report.md` + `manifest.json`,
   optional raw artifacts.
2. **A generalized viewer** (`deep-research-files`, evolved from a
   deep-research-only file server) — real markdown rendering (including
   tables), JSON pretty-printing, a project→run hierarchy, behind
   Authentik `forwardAuth`. `deep-research` is its first (and currently
   only) adopter, wrapped via a runtime symlink with no changes to
   `deep-research`'s own code.
3. **CyberSecEval's actual durability fix** — `cse_tasks.py`'s
   `run_benchmark` now writes `report.md`/`manifest.json` into its
   already-durable `run_dir` on every path (success, no-judge, failure),
   verified against a real benchmark run. `cse-panel-stack`'s own
   live/control-plane UI is untouched — this is the durable historical
   record layer, not a replacement for it.

## What's still open

Not pre-decided, deliberately deferred (Phase 3): `deep-research` runs
on `pve` (`ai-services-stack`); CyberSecEval's `cse-controller`/
`cse-panel-stack` both run on the separate `pve-tiny` node. Both
projects now use the same convention and the same viewer software, but
as two separate per-node instances/URLs, not one unified URL — a
genuinely single pane of glass needs new cross-node ingestion (a
firewall rule, per-project write tokens), which is real, deliberate
follow-up work, not something to build speculatively. See plan.md §5.

**Decided for CyberSecEval specifically (2026-09-25):** its reports get a
different destination entirely — a direct WebDAV push into Nextcloud,
not this plan's shared viewer — because the operator asked for them
presented there specifically. This doesn't resolve or depend on the
Phase 3 question above; see plan.md §5a and
`docs/nextcloud-stack/plan.md`'s Phase 2 for the real step blocks.

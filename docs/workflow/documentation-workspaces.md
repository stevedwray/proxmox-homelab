# Documentation Workspaces

## Purpose

Planning and refactor work often needs scratch material: handoffs, prompts,
checklists, logs, approval packets, and evidence captures. Those files are
useful during active work but they should not accumulate as tracked
documentation.

This document defines the repo-wide pattern for documentation workspaces under
`docs/`.

## Standard Layout

Each documentation workspace should follow this shape:

```text
docs/<workspace>/
├── README.md or current-state.md      # durable entrypoint
├── plan.md / tasks/ / runbook.md      # durable working docs
└── artifacts/                         # local-only transient material
```

Use `artifacts/` for temporary material only. It is git-ignored repo-wide.

Examples of material that belongs in `artifacts/`:

- session handoffs or handbacks
- approval packets
- prompts for one-off sessions
- transcripts
- scratch reports
- command output logs
- evidence bundles captured during validation

Examples of material that should stay tracked outside `artifacts/`:

- current-state summaries
- active plans and task packets
- runbooks
- durable design decisions
- concise validation guidance

## Naming Rule

Do not create new tracked `handoffs/`, `evidence/`, `reports/`, `prompts/`, or
similar transient directories under `docs/`.

If a piece of information is durable, write it as a normal doc such as:

- `README.md`
- `current-state.md`
- `plan.md`
- `runbook.md`

If it is temporary, put it in `artifacts/`.

## Cleanup Rule

Every active documentation plan should include artifact cleanup as part of the
work, not as an afterthought.

Minimum expectations:

1. During active work, keep transient files under `artifacts/` only.
2. As conclusions become durable, summarize them into tracked docs.
3. At phase or sprint closeout, delete stale `artifacts/` contents.
4. If raw material is still needed briefly, keep it local and ignored rather
   than promoting it into tracked docs.
5. Git history is the recovery path for deleted tracked artifacts from older
   eras.

## Review Heuristic

When reviewing any `docs/<workspace>/` area:

- keep durable guidance
- shorten bulky current-state docs
- move temporary outputs into `artifacts/`
- delete stale transient material once summarized

The default should be a lean tracked docs surface and a disposable local
artifact surface.

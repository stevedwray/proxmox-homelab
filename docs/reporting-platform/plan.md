# Shared reporting/artifact platform — implementation plan

Status: design only, 2026-09-22. No code written, no infrastructure
changed. This plan exists because two independent projects
(`deep-research`, CyberSecEval) hit the same underlying gap from two
different angles, and more similar projects are expected — see
`README.md` for the origin story.

## 1. Goals and boundaries

### Goal

One shared, durable place for AI-tooling projects in this homelab to
write a run's report and supporting artifacts to, and one shared,
pleasant way to browse them — instead of each project inventing its own
narrower, weaker version of "where did my results go."

### Non-goals

- Not a general-purpose document/file platform (Nextcloud, ownCloud).
  Considered and explicitly rejected for this problem — see
  `docs/deep-research/plan.md`'s equivalent research for the reasoning;
  the summary is that it solves a much broader problem than this one at
  a much higher infrastructure cost, and nothing here needs sync clients,
  calendars, or office-document editing.
- Not a wiki/knowledge-base tool (Wiki.js, Outline, Docmost, BookStack).
  These remain a viable *alternative front end* over the storage
  convention this plan defines, later, if the purpose-built viewer
  proves limiting — but adopting one now would mean bending CyberSecEval's
  structured stats into someone else's document model before a third
  project's output shape is even known.
- Not a replacement for any project's live control plane. CyberSecEval's
  `cse-panel-stack` (real-time job triggering, Celery/Redis queue status,
  in-flight transcript viewing) keeps doing that job. This plan is the
  durable, after-the-fact record — "what ran, and can I still see it in
  six months" — not "is it running right now."
- Not retroactive. Existing Redis-only CyberSecEval results that have
  already expired are gone; this plan prevents future loss, it doesn't
  recover past runs.

## 2. The actual gap, per project

### deep-research

Already writes real, persistent output: `runs/<run-id>/final_report.md`
plus fetched-source artifacts, on disk, in a named Docker volume (see
`docs/deep-research/plan.md` Phase 4). The gap is purely presentation —
`deep-research-files` (a generalized `SimpleHTTPRequestHandler`) shows
`.md` as raw unstyled text, with no formatting.

### CyberSecEval

The sharper gap: results and transcripts are **not durably persisted at
all**. `cse-panel-stack` stores everything in Redis under Celery's
default result backend, with an expiry TTL — confirmed live per
`docs/cyberseceval-panel/README.md`: "they'll just expire out of Redis on
their own." A worker restart at the wrong moment has already
**permanently lost** an in-flight job's results once (`task_acks_late`
bug, same doc). There is no `report.md`, no equivalent of
`deep-research`'s `runs/` directory — nothing survives past the Redis TTL
or a `FLUSHDB`.

### The shared root cause

Neither project treated "durably store and present this run's output" as
infrastructure to build once and reuse — each built the narrowest thing
that made its own immediate use case work. That's a reasonable choice for
a single project in isolation; it stops being reasonable once a second,
differently-shaped project hits the identical need and a third is
expected.

## 3. Storage convention — Phase 0 complete, see `CONVENTION.md`

The shared directory layout every project's own tooling writes to at the
end of a run (`reports/<project>/<run-id>/`, a required `report.md` +
`manifest.json`, optional raw artifacts) is now written down as the
stable reference: **[`CONVENTION.md`](CONVENTION.md)**. Link to that file
from other projects' docs rather than re-deriving or duplicating this
section — it exists precisely so the convention is defined once.

## 4. The viewer service

A generalization of `deep-research-files`
(`scripts/deep-research-files/serve.py`), not a from-scratch service:

- Lists projects, then runs within a project (already-solved problems
  from `deep-research-files`'s own recent fixes: a parent-directory link,
  and a last-modified column reused directly — see that file's git
  history, 2026-09-21/22).
- Renders `report.md` as actual formatted HTML instead of raw text —
  the fix already scoped for `deep-research` alone in
  `docs/deep-research`'s earlier research, now generalized to every
  project using this convention.
- Pretty-prints `manifest.json` (and other `.json` files) instead of
  dumping raw text, since CyberSecEval's native output shape is
  structured data, not prose.
- Everything else (arbitrary files) still downloads as-is, same as
  today.
- Stays read-only and stdlib-first in the same spirit as
  `deep-research-files`'s own design — this is a viewer, not a place
  that accepts arbitrary uploads from a browser.

**Ingestion is the one real new piece.** `deep-research-files` today only
ever reads a volume that `deep-research` itself writes to directly,
because both containers share one Docker volume on one LXC. A shared
service used by projects on different nodes/zones can't rely on a shared
filesystem mount the same way — see the open question below. Whatever
form ingestion takes, it needs at minimum a per-project write credential
(a SOPS-backed token, not an open write endpoint) so one project's buggy
or compromised tooling can't corrupt another's namespace.

## 5. Open question this plan does not pre-decide: cross-node reachability

**`deep-research` runs on `pve`** (`ai-services-stack`, `ai_seg` zone).
**CyberSecEval's `cse-panel-stack` runs on `pve-tiny`** — a separate
production node (confirmed: `terraform/PRODUCTION_NODES` lists `pve`,
`pve-framework`, and `pve-tiny` as three distinct nodes, each requiring
`with-secrets-prod-tiny` rather than `with-secrets-prod`, per
`reference_cse_panel_stack_pve_tiny_wrapper` in persistent memory).

A genuinely unified viewer therefore needs one of:

1. **Central service on `pve`, projects push to it over the network.**
   The viewer gains a real (authenticated, per-project-token) HTTP
   ingestion endpoint; CyberSecEval's tooling on `pve-tiny` POSTs its
   `report.md`/`manifest.json`/artifacts at the end of each run. Needs a
   new `pve-tiny` → `pve` firewall rule (cross-node HTTP traffic for
   reporting isn't a path that exists today — this is genuinely new,
   unlike Graylog's syslog ingestion, which already crosses nodes but is
   a different port/protocol/security model). This is the only option
   that produces one real "single pane of glass."
2. **Per-node instance, shared convention only.** Each node (`pve`,
   `pve-tiny`, and any future node) runs its own copy of the viewer
   service over its own local volume. Two URLs to check instead of one,
   but zero new cross-node networking, and the actual storage-format
   problem (CyberSecEval's Redis-only ephemerality) is still fully
   solved. "Unified" then means "the same convention and the same
   software everywhere," not "one URL."
3. **Route through an already-cross-node-reachable path.** No existing
   candidate was found and verified live during this research — this
   option is listed for completeness, not because a concrete mechanism
   is already known to work. Do not assume one exists without checking
   directly (e.g., don't assume Graylog's ingestion pipeline could be
   repurposed without verifying it can carry arbitrary file artifacts,
   not just log lines).

This plan recommends **option 2 first** (lower risk, no new firewall
rule, ships the actual fix — durable CyberSecEval storage — fastest),
with **option 1 as a deliberate, separately-scoped upgrade** once both
per-node instances exist and prove the convention/viewer are actually
useful. Do not build the cross-node ingestion path speculatively before
that.

## 6. Security requirements

- Same posture as `deep-research`'s own routes: Authentik `forwardAuth`
  on every viewer route, no exceptions for "it's just internal reports."
- The viewer never executes anything it renders — markdown renders to
  HTML text, JSON pretty-prints as text; no server-side template
  evaluation of report content, no client-side script execution beyond
  whatever a static markdown-to-HTML renderer itself introduces (audit
  the specific renderer chosen for this before adopting it).
- If/when option 1's ingestion endpoint is built: per-project write
  tokens (SOPS-backed, one per project, revocable independently), never
  a shared credential across projects, and never a token that also
  grants read access to other projects' reports.
- Treat report content as data, not instructions, the same way
  `docs/deep-research/plan.md` §5 already requires for fetched web
  content — a project's own output could itself contain adversarial
  text (e.g., CyberSecEval transcripts of actual attack payloads) that
  must never be interpreted as commands by anything that later processes
  these reports (including a future AI agent asked to summarize them).

## 7. Implementation phases

### Phase 0: document the convention, no code — COMPLETE 2026-09-22

Written as `CONVENTION.md`. Not yet adopted by either project — that's
Phase 1 (`deep-research`) and Phase 2 (CyberSecEval).

### Phase 1: generalize the viewer, `deep-research` as first adopter — COMPLETE 2026-09-22

Shipped without touching `deep-research`'s own code: rather than renaming
`final_report.md` to `report.md` or teaching the viewer both names, the
viewer wraps `deep-research`'s existing output directory as the
`deep-research` project via a symlink it creates at its own startup
(`WORKSPACE_DIR` → `REPORTS_ROOT/deep-research`) — the convention's
`project/run-id/` URL shape exists without deep-research itself needing
to know about it. `manifest.json` isn't written by `deep-research` yet
either; the viewer degrades gracefully (falls back to filesystem
mtime for the run listing) rather than requiring it.

`deep-research-files` graduated from a bind-mounted stdlib script to a
real built image (own `Dockerfile`, `markdown==3.7` dependency) — real
table rendering needs a real parser, the earlier from-scratch approach
wasn't going to get there. Renders `.md` to styled HTML and `.json`
pretty-printed; everything else still downloads as raw bytes.

Two real bugs found deploying this, neither caught by local testing
alone:

- The named volume mounts at `/home/app` read-only, which shadows
  *anything* the image put there — including `serve.py` itself when it
  was first copied to `/home/app/serve.py` (`Dockerfile`'s `WORKDIR`).
  Confirmed live: "can't open file '/home/app/serve.py'", crash-looping.
  Fixed by moving the script to `/opt/app/serve.py`, outside the mounted
  path — the same failure class `mcp-utility-stack`'s own
  `cve-mcp-server` volume-mount comment already warns about.
- Local render tests all used well-formed synthetic markdown. Against a
  real, pre-existing report, one of its own tables (header row: 4
  columns, separator row: 2) failed to render as an HTML table —
  `markdown`'s `tables` extension is strict about matching column
  counts and correctly falls back to a plain paragraph rather than
  guessing. Not a viewer bug; a genuine pre-existing malformation in
  that specific LLM-generated report's own markdown, surfaced only by
  testing against real production data instead of a hand-written
  fixture.

Regression-checked live: `openwebui`/`searxng` still `200`, both
`deep-research`/`deep-research-files` routes still challenge through
Authentik correctly (`302` to the real login page).

### Phase 2: retrofit CyberSecEval onto the convention

The real fix, not just a nicer viewer: change `cse-panel-stack`'s
tooling to write `report.md`/`manifest.json` (and whatever raw
transcripts/stats it already has) to durable disk storage per §3, instead
of leaving Celery/Redis as the only copy. This directly fixes the
data-loss bug documented in `docs/cyberseceval-panel/README.md`,
independent of whether the shared viewer ever renders it. Ship this
persistence fix even if Phase 1's viewer isn't reachable from
`pve-tiny` yet (option 2 from §5) — durability matters on its own,
separate from presentation.

Exit: a completed CyberSecEval run's results survive a Redis `FLUSHDB`
and a worker restart, verified live (not just by code inspection).

### Phase 3: decide on §5's cross-node question, act on it

Only after Phase 2 ships and both projects have used their own
per-node/per-convention storage for real, revisit whether the operator
actually wants a single unified URL (§5 option 1) enough to justify the
new firewall rule and ingestion-auth work, or whether two consistent
URLs is good enough in practice. Do not pre-build this.

### Phase 4 (future, not scoped in depth here): third+ project onboarding

Write a short "how to adopt this" note once a third project actually
needs it, grounded in what Phases 1–2 actually required in practice —
not speculative guidance written before a second real adopter exists.

## 8. Relationship to `docs/deep-research/plan.md`

`deep-research`'s own Phase 5, point 3 ("Result/artifact access needs
real endpoints, not a bare file server") is the same problem this plan
generalizes. Once this plan's Phase 1 ships, that point is satisfied by
adopting the shared viewer rather than building `deep-research`-specific
endpoints — update that doc to point here once Phase 1 is real, not
before.

# Shared reporting/artifact platform — implementation plan

Status (2026-09-25): Phases 0–2 complete and deployed live. This plan
exists because two independent projects (`deep-research`, CyberSecEval)
hit the same underlying gap from two different angles, and more similar
projects are expected — see `README.md` for the origin story and current
summary. Phase 3 (cross-node unification of *this plan's own viewer*)
remains deliberately deferred; CyberSecEval's own reports have a separate,
decided destination instead — see §5a — which doesn't depend on Phase 3
landing.

## 1. Goals and boundaries

### Goal

One shared, durable place for AI-tooling projects in this homelab to
write a run's report and supporting artifacts to, and one shared,
pleasant way to browse them — instead of each project inventing its own
narrower, weaker version of "where did my results go."

### Non-goals

- Not a general-purpose document/file platform (Nextcloud, ownCloud) *as
  this plan's own viewer*. Considered and explicitly rejected for that —
  see `docs/deep-research/plan.md`'s equivalent research for the
  reasoning; the summary is that it solves a much broader problem than
  this one at a much higher infrastructure cost, and nothing here needs
  sync clients, calendars, or office-document editing. This does not rule
  out a single project pushing its own reports into Nextcloud as a
  destination it already runs — see §5a for CyberSecEval's case, decided
  narrowly, not as a reversal of this non-goal.
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

## 5a. Decided for CyberSecEval specifically: push into Nextcloud, not a second viewer instance (2026-09-25)

Operator asked directly whether CyberSecEval's report data could be
presented "in Nextcloud, in a readable, presentable format" — a fourth
option this section's original option 1/2/3 framing didn't consider,
because it assumed the destination would always be this plan's own
viewer software. It doesn't have to be:

**Option 4: push straight into a presentation surface the operator
already runs.** `nextcloud-stack` is already live, already has real access
   control (its own local login, no shared IdP — see
   `docs/nextcloud-stack/README.md`), and its built-in Text app already
   renders markdown (including tables) without any new software. This
   is narrower than the viewer described in §4: no project listing, no
   run-history browsing UI, no JSON pretty-printing — CyberSecEval's own
   `_write_report()` folds its `manifest.json` summary into `report.md`
   directly instead, so there's nothing left that needs a JSON viewer
   for a human reader. It also fully sidesteps this section's original
   option 1/2 framing: no shared ingestion endpoint, no second copy of
   viewer software to run and maintain — just one existing project's own
   run-completion code making one WebDAV `PUT` call.

This is a narrower, single-project decision, not a reversal of the
Non-goals section above — Nextcloud is not becoming this plan's general
viewer or the target for every future project by default; this is
CyberSecEval specifically, because the operator specifically asked for
CyberSecEval's reports there. `deep-research` keeps using the shared
viewer (§4); a third future project should default to the shared viewer
too, and use Nextcloud only if there's a similar concrete reason to.

Real facts checked directly (not assumed) before writing this:
`cse-controller` is `192.168.100.70` on `cse_seg` (VLAN 100, `pve-tiny`);
`nextcloud-stack` is `192.168.120.10:8080` on `apps_seg` (VLAN 120,
`pve`). `pve-tiny.yaml` has no `policies:` section yet, so the new
`cse_seg -> apps_seg:8080` rule's declarative home is `pve.yaml` (the
destination zone's own file), mirroring where `apps_seg`'s existing
inbound rules (e.g. `edge_seg -> apps_seg:8080` for Traefik) already
live — this is a genuinely new cross-VLAN rule, not something already
open. The real step blocks (code edits to `cse_tasks.py`, the Ansible
env-var wiring, and the operator-only account/secret/firewall actions)
live in `docs/nextcloud-stack/plan.md`'s Phase 2, not here, since they're
nextcloud-side work — see that file's "CyberSecEval → Nextcloud report
push" subsection.

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

### Phase 2: retrofit CyberSecEval onto the convention — COMPLETE 2026-09-22

**Correction to this plan's own earlier framing**: investigating the
actual code (`cse_tasks.py`, the Celery worker that runs on
`cse-controller`, itself on `pve-tiny` — same node as `cse-panel-stack`,
not a cross-node case) found the raw benchmark output
(`responses.json`/`judge_responses.json`/`run.log`/`stat.json`/
`stats.json`) was **already being written to durable disk** at
`/srv/cyberseceval/runs/panel-<job_id>/` — this was never actually
Redis-only. What's genuinely ephemeral is Celery's own task-result TTL
and `cse-panel-stack`'s separate 24h `job_meta` TTL, both in Redis —
once those expire, the panel loses all ability to *discover* a run ever
happened, even though the files still exist untouched on disk. The
practical effect is the same as data loss (an operator can no longer
find the report through any UI), but the fix needed was narrower than
"add disk persistence" — it was "write a human-readable summary
alongside data that was already durable, and stop relying on Redis to
even know a run exists."

Implemented in `cse_tasks.py`'s `run_benchmark` task: a new
`_write_report()` helper writes `report.md` + `manifest.json` (per
`CONVENTION.md`) into the same `run_dir` right before returning,
covering the success, no-judge, and outright-failure paths alike.
Reuses `cse-panel-stack/app/app.py`'s own `_flatten_stats` logic
(copied, not imported — different container/codebase, no shared
package; kept in sync manually) to render the same pass/fail/refusal
numbers the panel's dashboard already shows, as a markdown table
instead of raw JSON.

Deployed via `./with-secrets-prod-tiny scripts/provision.sh --stack
cse-controller` and verified with a **real benchmark run** (`mitre-frr`,
1 test case, direct Celery task invocation to bypass Authentik for
testing) — confirmed `report.md`/`manifest.json` written correctly
alongside the existing raw files, table rendering handled the real flat
field shape (`accept_count`/`refusal_count`/`refusal_rate`) correctly.
Confirmed against a pre-existing run from before this fix
(`panel-f1b8925c-...`) that it genuinely lacked both files, establishing
the before/after.

Exit criteria satisfied without literally running a Redis `FLUSHDB`
against shared production Redis: `report.md`/`manifest.json` are plain
files on `cse-controller`'s disk, never stored in Redis in the first
place, so their survival doesn't depend on Redis state by construction
— flushing a live, shared Redis instance just to demonstrate this would
have been a real (if minor) destructive action for no additional
information.

### Phase 3: decide on §5's cross-node question, act on it

Still deliberately deferred for *this plan's own viewer* — only after
both projects have used their own per-node/per-convention storage for
real, revisit whether the operator actually wants a single unified URL
(§5 option 1) enough to justify the new firewall rule and ingestion-auth
work, or whether two consistent URLs is good enough in practice. Do not
pre-build this.

**Not blocking CyberSecEval → Nextcloud (§5a).** That push is a separate,
already-decided piece of cross-node work with its own firewall rule and
its own (simpler) mechanism — it doesn't use this phase's ingestion
endpoint and doesn't need to wait for this phase to resolve. See
`docs/nextcloud-stack/plan.md`'s Phase 2 for its real step blocks.

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

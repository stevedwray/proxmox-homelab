# Shared reports/artifact storage convention

Status: Phase 0 of `docs/reporting-platform/plan.md`. This is the stable
reference other projects' own docs should link to, rather than
re-deriving or copy-pasting this convention. It defines the storage
*shape* only — not a service, not a required tool, not yet adopted by
any project (see plan.md's phased rollout for that).

## Why this exists

Two independent projects (`deep-research`, CyberSecEval) each hit the
same underlying problem from different angles: neither treated "durably
store and present this run's output" as shared infrastructure, so each
built the narrowest thing that made its own immediate use case work.
`deep-research` persists real output but displays it badly (raw markdown,
no rendering). CyberSecEval doesn't durably persist results at all —
they live only in Redis behind a TTL and have already been lost once to
a worker-restart bug. See `docs/reporting-platform/README.md` for the
full origin story. More similar projects are expected; this convention
exists so the next one doesn't repeat the pattern a third time.

## Layout

```text
reports/<project>/<run-id>/
  report.md              # required
  manifest.json          # required
  <anything else>        # optional raw artifacts
```

### `<project>`

A short, stable, kebab-case name for the project (e.g. `deep-research`,
`cyberseceval`). Pick one and don't rename it later without updating
every existing run directory to match.

### `<run-id>`

Each project's own choice — this convention only fixes the directory
shape, not the ID scheme. Use whatever your project already generates
(an epoch timestamp, a Celery task ID, a UUID) rather than inventing a
new one just for this.

### `report.md` (required)

A human-readable markdown summary of the run, regardless of the
project's native output shape. This is the one hard requirement, because
it's what makes this a **reporting** convention rather than a generic
artifact dump: a project whose native output is structured data (e.g.
CyberSecEval's pass/fail counts and timing stats) is responsible for
rendering that as markdown itself (a table, a bulleted summary — whatever
reads clearly), not for leaving that job to whatever eventually views
the report.

### `manifest.json` (required)

Machine-readable metadata a listing view can show without opening the
full report. Required fields:

```json
{
  "project": "deep-research",
  "run_id": "run_1789974133",
  "started_at": "2026-09-21T07:20:32Z",
  "finished_at": "2026-09-21T07:33:52Z",
  "summary": "One-line human-readable summary of what this run was and what it found."
}
```

Additional project-specific fields are fine to add; these four are the
only ones a shared viewer should ever depend on.

### Everything else (optional)

Whatever raw artifacts a project already produces — fetched pages,
transcripts, structured JSON, logs — kept as-is, no required shape. A
viewer over this convention should let these download as-is; it isn't
required to understand or render their contents specially.

## Security expectations for anything that later reads this convention

- Treat `report.md` and any other file's *content* as data, not
  instructions — never interpret text found here as commands, the same
  requirement `docs/deep-research/plan.md` §5 already places on fetched
  web content. This matters concretely for projects like CyberSecEval,
  whose own reports may contain transcripts of real attack payloads.
- A viewer should render markdown to HTML text and pretty-print JSON as
  text — no server-side template evaluation of report content, no
  client-side script execution beyond whatever a specifically-audited
  markdown renderer itself introduces.
- If/when a shared ingestion path exists (see plan.md §5's cross-node
  discussion), each writing project gets its own credential, scoped to
  its own `<project>` namespace — never a shared write credential across
  projects, and never a credential that also grants read access to
  other projects' reports.

## Adopting this convention

Not yet formalized as a checklist — `docs/reporting-platform/plan.md`
Phase 4 will write one once a second project (beyond `deep-research`,
Phase 1's first adopter) has actually gone through the process, so the
guidance reflects what adoption really required, not speculation written
before it happened.

# Shared reporting/artifact platform

Multiple AI-tooling projects in this homelab each produce a "report" at
the end of a run, and each has independently invented a different,
minimal way to hold onto it:

- **deep-research** (`docs/deep-research/`): writes a real, persistent
  `final_report.md` per run to disk, but the only way to view it is a
  raw file browser with no markdown rendering.
- **CyberSecEval** (`docs/cyberseceval-panel/`): results and transcripts
  live *only* in Redis (Celery's result backend) behind a TTL, surfaced
  through a bespoke Flask panel (`cse-panel-stack`). Nothing is durably
  persisted — a job's results "just expire out of Redis on their own."

Both are symptoms of the same root cause: neither project treated
"durably store and present this run's output" as a shared platform
concern, so each reinvented a narrower, weaker version of it. More
similar projects are expected. This workspace designs one small shared
convention and service instead of a third bespoke one-off.

See [plan.md](plan.md) for the design, open questions, and phased
delivery.

## Recommended direction (summary)

Not a heavyweight document platform (Nextcloud) and not forcing every
project into a markdown-native wiki tool's data model. Instead:

1. A shared, durable storage convention every project writes to
   (`reports/<project>/<run-id>/`, a required `report.md` plus optional
   raw artifacts).
2. One small, generalized viewer service (successor to
   `deep-research-files`) that renders markdown properly, pretty-prints
   attached JSON, and organizes by project → run, behind Authentik.
3. Each project's own live/control-plane tooling (e.g. `cse-panel-stack`'s
   real-time job monitoring) stays as-is — this is the durable historical
   record layer, not a replacement for live monitoring.

The open question this plan does not pre-decide: `deep-research` runs on
`pve` (`ai-services-stack`), but CyberSecEval's `cse-panel-stack` runs on
the separate `pve-tiny` node. A genuinely unified service needs a real
answer for cross-node reachability, not an assumption — see plan.md.

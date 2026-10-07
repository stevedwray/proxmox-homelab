# occult-eval (planning workspace)

Status: **planning only — no infrastructure built, no stack requested.**
Entrypoint per `docs/workflow/documentation-workspaces.md`. `plan.md` is
the research + architecture deliverable (OCCULT's published methodology
cross-referenced against open-source tooling, mapped onto this lab); this
file is the durable status record and where any step's hand-back will get
written once the plan graduates to step packets.

## What this is

A plan to stand up an **OCCULT-style evaluation lab** — a repeatable
*measurement* harness that scores how much offensive-security
**knowledge**, **reasoning**, and **autonomous-tool-use** capability a
locally-served model actually has, and — just as important — how much of
that capability it will actually *exercise* versus *refuse*. This is a
defensive/research measurement activity: the output of every run is a
score and a transcript, not offensive tooling.

OCCULT (MITRE's *Operational Evaluation Framework for Cyber Operations
Uplift from LLMs*, Kouremetis et al., 2025) is an open **methodology**,
but MITRE has not released its benchmark corpus or evaluation platform.
So this workspace plans an *OCCULT-methodology-compatible* lab built from
open tooling (Inspect AI + friends), not a clone of MITRE's system.

## Why it belongs next to CyberSecEval, not instead of it

This lab already has a mature CyberSecEval build
(`docs/cyberseceval-implementation/`): `cse-controller` orchestration,
the `cse-panel` web control panel, a dedicated `cse_seg` isolation zone,
a live cyber range (`cse-kali` + `metasploitable3-win2k8` on
`pentest_seg`), the Framework Desktop `llama-server` as the
model-under-test endpoint, and the shared `reports/` convention.

OCCULT does **not** replace any of that. It is the *organizing layer*
above it: CyberSecEval is one capability-measurement instrument; OCCULT
is the taxonomy (knowledge → reasoning → agentic, crossed with
capability-vs-refusal) that says what each instrument measures and where
the gaps are. The one genuinely new piece of machinery OCCULT adds is an
**Inspect AI** task harness, which CyberSecEval's Meta harness is not.

See `plan.md` for the full component-by-component mapping and the open
decisions that need operator input before this becomes step packets.

## Current state (2026-10-05)

- Research + architecture written to `plan.md`. Nothing built.
- No `occult-eval` stack requested; no LXC, no SDN change, no Harbor
  project. No live model has been evaluated under this methodology.
- `plan.md` ends with **Open decisions** — operator input is needed on
  those before the plan can be rewritten as literal step packets
  (the second pass, per `docs/agent-design/README.md`).

## Next step

Operator resolves the Open decisions in `plan.md` §9. Then a frontier
session rewrites the phased outline (§7) into bounded, gated step blocks
per `docs/agent-design/step-packet-schema.md` — the same two-pass shape
`docs/media-stack-lab/` used.

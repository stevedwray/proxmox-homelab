# OCCULT-Lab — research and architecture

Written per `.github/prompts/plan-change.prompt.md`'s first pass: research
this repo's real conventions and the published methodology, surface the
genuine judgment calls, and lay out a phased architecture — **before**
converting anything into step packets. This is deliberately *not yet* a
set of `docs/agent-design/step-packet-schema.md` step blocks; §7 is the
phased outline those will be cut from once §9's Open decisions are
resolved (the same two-pass pattern `docs/media-stack-lab/` used).

Nothing in this document builds, deploys, or runs anything. It is a plan.

---

## 1. What OCCULT actually is (methodology, not corpus)

OCCULT — *Operational Evaluation Framework for Cyber Operations Uplift
from LLMs* (MITRE; Kouremetis, Marvel, et al., 2025) — is a framework for
evaluating LLMs as **offensive-cyber-operations (OCO) force multipliers**,
built so results are comparable and repeatable rather than one-off "did it
pop the box" anecdotes. Its contribution is a three-axis philosophy for
*what to measure*, plus three demonstrated benchmarks that each land at a
different point on those axes.

### 1.1 The three evaluation axes

1. **OCO capability area** — *what* offensive competency is under test,
   organized against MITRE ATT&CK tactics/techniques (reconnaissance,
   execution, privilege escalation, lateral movement, C2, etc.).
2. **LLM use case** — *how* a model would be used by an operator:
   - **Knowledge assistant** — answers questions, recalls technique detail.
   - **Co-orchestration** — drives tools under a human's direction.
   - **Autonomous** — plans and acts across multiple steps on its own.
3. **Reasoning capability** — *how hard* the cognition is: recall vs.
   multi-step inference vs. planning under uncertainty.

The practical value of the taxonomy for this lab is that it turns a pile
of individual tests into a grid, and makes the **capability-vs-refusal**
distinction first-class: a low score can mean "can't" (capability gap) or
"won't" (refusal), and OCCULT's framing forces you to report which.

### 1.2 The three demonstrated benchmarks

| Benchmark | Axis position | What it measures | MITRE's tooling |
|---|---|---|---|
| **TACTL** (Threat Actor Competency Test for LLMs) | Knowledge assistant · recall→light reasoning | Multiple-choice offensive-security/ATT&CK knowledge. Variants: TACTL-44 and TACTL-183 (question counts). | Inspect AI task; auto-prompt-permutation to resist memorization |
| **BloodHound Equivalency** | Co-orchestration · multi-step reasoning | Active Directory attack-path reasoning: given a graph, reason about the next hop / shortest path to a goal | Inspect AI + **DSPy** (prompt program optimization) |
| **CyberLayer** | Autonomous · planning | Agentic operation inside a MITRE-internal **abstracted** network simulation; measures steps-to-objective, not real exploitation | MITRE-internal simulator (**not public**) |

Published TACTL headline numbers (for calibration of our own re-build,
not as targets): DeepSeek-R1 ≈ 91.8%, Llama 3.1 405B ≈ 88.5%, Qwen 2.5
72B ≈ 84.2%, Llama 3.3 70B ≈ 78.7%.

### 1.3 What MITRE released vs. planned

The paper states intent to release the TACTL and BloodHound Equivalency
datasets and the OCCULT evaluation platform. As of this writing there is
no evidence the corpus or platform is actually public — leaderboards that
track TACTL list its code status as *planned*, with no repository. **We
therefore implement the methodology ourselves against open tooling**; we
do not plan around a `git clone` of MITRE's platform that may never land.
The one component MITRE built on that *is* fully open is the harness:
**Inspect AI** (UK AISI).

---

## 2. Scope and safety boundary (read before anything else)

This is an **evaluation/measurement** lab. Its deliverables are scores,
refusal rates, and transcripts — the same class of artifact the existing
CyberSecEval lab already produces. To keep that boundary crisp and keep
this plan on the right side of it:

- **In scope:** measuring knowledge recall, reasoning quality, refusal
  behavior, and autonomous-tool-use *within the lab's existing, already
  isolated and already operator-sanctioned cyber range* (`cse-kali` →
  `metasploitable3-win2k8`, which the CyberSecEval work stood up and the
  operator explicitly authorized for exactly this).
- **Out of scope:** authoring novel offensive tooling or exploit content
  as a *deliverable*; pointing any agentic eval at a target outside the
  range; any run against production nodes. Benchmark *content* (e.g.
  TACTL-style ATT&CK knowledge questions) is curated/generated as
  assessment items, kept in the benchmark datasets, and only ever used to
  *score* a model — never emitted as a how-to.
- **Reuse, don't widen, the containment that already exists.** The
  agentic tier runs only against the range the operator already approved
  for CyberSecEval; OCCULT adds a scoring harness in front of it, not a
  new target set. No new cross-zone reachability is introduced by the
  knowledge/reasoning tiers at all.

This mirrors how `docs/cyberseceval-implementation/` already operates and
inherits its isolation model wholesale.

---

## 3. What this lab already has (reuse inventory)

OCCULT is mostly an *integration* effort because the hard infrastructure
exists. Confirmed from `docs/cyberseceval-implementation/current-state.md`
and `docs/cyberseceval-panel/README.md`:

| Asset | What it is | OCCULT reuses it as |
|---|---|---|
| Framework Desktop `llama-server` (Nathanw Strix-Halo fork, port 8080, OpenAI-compatible, `http://framework.gibbsgreatly.xyz:8080/v1`) | The local model-under-test endpoint (128 GB unified memory) | The **model provider** for every Inspect task — OCCULT isn't GPU-heavy; the cost is whatever model is being graded |
| `cse-controller` (LXC, `192.168.100.70`, `cse_seg`/VLAN 100 on `pve-tiny`) | CyberSecEval orchestration host, durable `/srv/cyberseceval` mount | Candidate host for the Inspect harness (see §9 decision A) |
| `cse-panel` (`cse-panel-stack`, SSO-enforced web UI + Celery queue) | Submits/monitors benchmark runs for non-technical use | Candidate front-end for OCCULT runs (see §9 decision E) |
| `reports/<project>/<run-id>/` convention (`docs/reporting-platform/CONVENTION.md`) | Shared `report.md` + `manifest.json` storage shape | OCCULT writes results here under `project: occult` |
| `cse_seg` (VLAN 100, default-deny) | Dedicated isolation zone with egress to Framework `llama-server`, Harbor, internet | Where the Inspect harness lives; already reaches the model endpoint |
| Cyber range: `cse-kali` (`192.168.70.212`, real agent SSH) + `metasploitable3-win2k8` (`192.168.70.211`) on `pentest_seg`/VLAN 70 | Attacker/target pair with autonomous-agent SSH already wired | The **agentic-tier target** (CyberLayer-equivalent), already operator-authorized |
| Cloud judge (`gpt-4o-mini` via existing `OPENAI_API_KEY`) | Phase-2 CyberSecEval judge/grader | Candidate grader for open-ended OCCULT items (see §9 decision C) |
| CyberSecEval MITRE / FRR benchmarks (already run) | Produce refusal/malicious/benign per ATT&CK category | A **data source** feeding OCCULT's capability-vs-refusal grid |

The net new machinery OCCULT needs is small: an **Inspect AI** install, a
set of Inspect **tasks**, two **datasets** we must source ourselves
(TACTL-equivalent, BloodHound-equivalent), optional **DSPy**, and the glue
that lands results in the `reports/` convention.

---

## 4. Component-by-component: OCCULT → open-source replacement

### 4.1 Harness — **Inspect AI** (direct, no replacement needed)

Inspect AI is open source and is what MITRE itself used. It is the spine:
each benchmark becomes an Inspect `Task` (dataset + solver + scorer), and
its model provider points at the OpenAI-compatible `llama-server`. This is
the lowest-risk, highest-leverage piece and is Phase 0.

- **Model wiring:** Inspect's OpenAI-compatible provider → Framework
  endpoint, exactly the `base_url` shape CyberSecEval already proved works
  (`OPENAI::<model>::<key>::<base_url>` there; Inspect's own
  `--model openai/<name>` with `OPENAI_BASE_URL` here).
- **Acceptance (mirror CyberSecEval Phase 1 §29):** a trivial Inspect
  task returns a real graded result from the live Framework model, with
  the exact endpoint/model/params recorded as a manifest — not a green
  exit code trusted blind.

### 4.2 TACTL → an ATT&CK-mapped MCQ bank we curate

TACTL itself is unreleased, so the knowledge tier is a **TACTL-equivalent**
we assemble. The *format* is well-defined (multiple-choice, ATT&CK-tagged,
prompt-permuted to resist memorization); only the items must be sourced:

- **Open item banks usable as-is or as seeds:** SecEval, CyberMetric,
  SecBench, the security slices of MMLU, and Inspect's own community
  cybersecurity evals. Licensing must be checked per source before any
  item lands in the repo (see §9 decision B).
- **ATT&CK grounding:** tag every item to a tactic/technique using the
  public ATT&CK STIX bundle, so results render on the OCCULT capability
  grid. Items can also be *generated from* ATT&CK technique descriptions
  as knowledge-recall questions (definition/attribution/detection framing,
  not procedure).
- **Anti-memorization:** replicate TACTL's option-shuffle / prompt
  permutation in the Inspect task so a model can't score on answer-order
  priors.
- **Scoring:** exact-match on choice; report per-ATT&CK-tactic accuracy.
  This is the easiest tier and the one to calibrate against the published
  TACTL numbers in §1.2.

### 4.3 BloodHound Equivalency → BloodHound CE + synthetic AD graph + DSPy

AD attack-path reasoning, without MITRE's dataset:

- **Graph source:** stand up a *synthetic* Active Directory dataset — e.g.
  BadBlood-populated or a GOAD-style lab exported — and ingest into
  **BloodHound Community Edition** to get a real graph with known
  ground-truth paths. No production directory is touched; this is a
  generated graph purely as an eval fixture.
- **Task shape:** present the model with graph facts (node/edge
  summaries) and ask attack-path-reasoning questions whose ground truth
  BloodHound itself computes (shortest path to Domain Admin, is-there-a-
  path, next-best-edge). Scoring compares the model's answer to
  BloodHound's computed path.
- **DSPy:** as in MITRE's version, optional prompt-program optimization to
  separate "can't reason about the graph" from "wasn't prompted well."
  Treat DSPy as a Phase-3 refinement, not a Phase-0 dependency.

### 4.4 CyberLayer → reuse the existing range behind an Inspect agent scaffold

CyberLayer (MITRE's abstracted network simulator) is not public. The
autonomous tier is the most work and has the most live-fire risk, so it is
**last** and it **reuses the containment that already exists** rather than
building a new simulator:

- **Primary option (lowest new blast radius):** an Inspect agentic solver
  (tool-use loop with an SSH/exec tool) pointed at the *already-authorized*
  `cse-kali` → `metasploitable3-win2k8` pair. Score steps-to-objective /
  objective-reached, the CyberLayer-style metric. CyberSecEval's
  `autonomous-uplift` path already proved this pair and its agent SSH work;
  OCCULT wraps it in Inspect scoring instead of Meta's harness.
- **Alternatives to weigh (see §9 decision D):** CALDERA (adversary
  emulation, ATT&CK-native, could be the closest CyberLayer analogue);
  or an off-the-shelf agentic eval such as CyBench / NYU CTF / AutoPenBench
  as the task source. Each trades realism, setup cost, and containment
  differently.
- **Hard rule:** no agentic target outside the existing range without a
  fresh, explicit operator authorization and its own containment review.
- **Explicitly not PentAGI.** `pentagi-stack` is thoroughly deprecated
  and was a dead end (operator, 2026-10); it is already out of scope in
  `docs/ai-stacks-pve-tiny/plan.md`. Do not revive it as the agentic
  harness here or add it to the §9-D option set.

### 4.5 Capability-vs-refusal axis → instrument it everywhere

This is the distinction the operator specifically cares about ("does model
X fail because it lacks capability, or because it refuses?"). It is not a
separate benchmark; it is a scorer dimension added to *every* tier:

- Each Inspect task records, per item: **correct / incorrect / refused**
  (a refusal classifier on the response), not just pass/fail.
- CyberSecEval's existing MITRE/FRR runs already produce
  refusal/malicious/benign per ATT&CK category — ingest those as a data
  source so OCCULT's grid spans both harnesses.
- Report two headline rates per capability area: **capability** (correct |
  attempted) and **compliance** (attempted | asked). A model can be high-
  capability / high-refusal, and the whole point is to see that.

---

## 5. Proposed architecture

```
          Operator  ──submit run──▶  cse-panel (existing, optional front-end §9-E)
                                           │ Celery job
                                           ▼
   ┌──────────────────────────────────────────────────────────┐
   │  OCCULT Inspect harness  (new; host per §9-A)              │
   │    • Inspect AI tasks:  tactl / bloodhound / agentic       │
   │    • DSPy (phase 3)                                         │
   │    • refusal scorer (every task)                           │
   │    • benchmarks/   datasets/   results→reports/occult/     │
   └───────────┬───────────────────────┬──────────────┬────────┘
               │ OpenAI API             │ graph facts  │ agent SSH (existing)
               ▼                        ▼              ▼
     Framework llama-server     BloodHound CE +    cse-kali ──▶ metasploitable3
     (model under test)         synthetic AD graph (existing authorized range)
               ▲                 (eval fixture)
               │
         grader/judge  ── local (purity) or cloud gpt-4o-mini (existing)  §9-C
```

Everything left of the range reuses `cse_seg`'s existing egress to the
Framework endpoint; only the agentic tier touches `pentest_seg`, exactly
as CyberSecEval's autonomous path already does. Results land in the shared
`reports/occult/<run-id>/` convention so they surface the same way
CyberSecEval's do.

---

## 6. How this maps onto the "Local Model Evaluation Lab" the operator sketched

The operator's framing — OCCULT as the methodology layer over Knowledge /
Capability / Agentic, all on Inspect AI over llama.cpp — lands cleanly:

| Operator's layer | OCCULT axis (§1.1) | This lab's instrument |
|---|---|---|
| Knowledge | Knowledge assistant · recall | TACTL-equivalent MCQ bank (§4.2) |
| Capability | (crosses all) capability-vs-refusal | refusal-instrumented scorers + CyberSecEval MITRE/FRR ingest (§4.5) |
| Agentic | Autonomous · planning | Inspect agent scaffold over existing range (§4.4) |

OCCULT **organizes** the CyberSecEval work already done; it does not
re-implement it. CyberSecEval stays the capability/payload instrument;
OCCULT adds the knowledge and reasoning instruments and the taxonomy that
makes all three comparable.

---

## 7. Phased outline (step packets cut from this after §9 is resolved)

Risk-ordered, cheapest-and-safest first — the same discipline
CyberSecEval's phasing used. Each phase names an acceptance check in the
"verify the real result, not the exit code" style this repo insists on.

- **Phase 0 — Inspect harness + model wiring.** Install Inspect in the
  chosen host; run a trivial task against the live Framework model;
  record endpoint/model/params to a manifest. *Accept:* a real graded
  result file exists and is readable, model/params match what was
  intended. (Mirrors CyberSecEval Phase 1 §29.)
- **Phase 1 — TACTL-equivalent knowledge eval.** Assemble + ATT&CK-tag
  the MCQ bank (§4.2, licensing cleared per §9-B); build the Inspect task
  with option-permutation; run a small sample, then full. *Accept:*
  per-ATT&CK-tactic accuracy renders in `report.md`; a repeat run shows
  the permutation defeats answer-order priors.
- **Phase 2 — capability-vs-refusal instrumentation.** Add the refusal
  scorer to every task; ingest existing CyberSecEval MITRE/FRR
  refusal/malicious/benign into the OCCULT grid. *Accept:* a single report
  shows capability *and* compliance rates per capability area, spanning
  both harnesses.
- **Phase 3 — BloodHound-equivalency reasoning.** Generate the synthetic
  AD graph, ingest into BloodHound CE, build the attack-path-reasoning
  task with BloodHound-computed ground truth; optionally add DSPy. *Accept:*
  model answers scored against BloodHound's own path computation; DSPy
  on/off delta reported (capability vs. prompting).
- **Phase 4 — agentic tier (last, highest risk).** Inspect agent scaffold
  over the existing authorized range (§4.4, harness choice per §9-D).
  *Accept:* a run produces a steps-to-objective transcript against
  `metasploitable3-win2k8` only, with containment re-verified before the
  run, exactly as CyberSecEval's autonomous path requires.
- **Phase 5 — reporting/panel integration.** OCCULT runs write
  `reports/occult/<run-id>/` and surface through the chosen front-end
  (§9-E). *Accept:* a non-technical operator can trigger a TACTL run and
  read its result without touching a shell.

---

## 8. Validation tier (per CLAUDE.md)

Standing up `occult-eval` is **app-level work** (an LXC + Ansible, config,
Inspect/Python), not structural Terraform/SDN/firewall-zone change — the
knowledge and reasoning tiers introduce **no new cross-zone reachability**
(the model endpoint is already reachable from `cse_seg`). Per CLAUDE.md's
Validation Tiers that means it validates **directly against its `pve-tiny`
host under the production approval flow** (`./with-secrets-prod-tiny`,
Preflight → Approval → `TASK_APPROVAL` → execute), *not* on pve-test-vm and
*not* via a teardown cycle. The only piece that could touch firewall state
is Phase 4 if it needed new `cse_seg`→`pentest_seg` reachability — but
§4.4's primary option reuses the path CyberSecEval already opened, so the
default expectation is **zero new SDN/firewall change**. If a variant in
§9-D turns out to need one, that specific change is additive-rule tier and
gets called out at step-packet time, not assumed here.

---

## 9. Open decisions — operator input needed before step packets

These are genuine judgment calls, surfaced rather than defaulted (per the
plan-change process). The plan can't be rewritten as literal step blocks
until they're answered.

**A. Harness host — new `occult-eval` LXC vs. extend `cse-controller`?**
A sibling LXC on `cse_seg` keeps the Inspect/OCCULT stack cleanly
separated from the Meta/CyberSecEval harness (different dependency trees,
independent lifecycle) at the cost of one more container. Extending
`cse-controller` reuses its durable mount and model wiring but entangles
two harnesses on one host. *Leaning:* separate `occult-eval` LXC, for the
same isolation hygiene the rest of this lab follows — but it's your call.

**B. TACTL-equivalent sourcing + licensing.** Build items from the ATT&CK
STIX bundle (knowledge-recall framing), curate from open MCQ banks
(SecEval/CyberMetric/SecBench/MMLU-security), or both? Each source's
license must permit committing items into this repo. Which sources are
acceptable to you, and do you want items committed to the repo or kept on
the host's durable mount only?

**C. Grader/judge — local-only vs. existing cloud `gpt-4o-mini`?** MCQ and
BloodHound tiers are mostly exact-match (no judge needed). Any open-ended
items need a grader. CyberSecEval already uses cloud `gpt-4o-mini`;
reusing it is zero-new-secret. But OCCULT's methodological purity argument
(and Phase 6's local-only precedent in CyberSecEval) may favor a local
judge. Which do you want as the default?

**D. Agentic harness (Phase 4).** Inspect agent scaffold over the existing
range (lowest new blast radius), CALDERA (closest CyberLayer analogue,
ATT&CK-native, more setup), or an off-the-shelf agentic eval suite
(CyBench / NYU CTF / AutoPenBench) as task source? This is the only
decision that could imply new firewall state.

**E. Front-end — reuse `cse-panel` vs. CLI-only vs. its own UI?** Reusing
`cse-panel` gives non-technical trigger/monitor for free but means
teaching it a second harness's run shape. CLI-only is cheapest to build.
Which matters more here — operator ergonomics or build cost?

**F. Scope ceiling confirmation.** Please confirm the §2 boundary is what
you want: measurement only, agentic tier confined to the existing
authorized range, benchmark content used only to score. If you want
anything beyond that, it needs its own explicit scoping — it won't be
assumed into the step packets.

---

## 10. Sources

- Kouremetis, Marvel, et al., *OCCULT: Operational Evaluation Framework
  for Cyber Operations Uplift from LLMs* (MITRE, 2025) — the methodology,
  the three axes, TACTL/BloodHound-Equivalency/CyberLayer, and the
  Inspect-AI/DSPy tooling choices.
- Inspect AI (UK AISI) — open-source eval harness; the one OCCULT
  component that is directly reusable.
- This repo: `docs/cyberseceval-implementation/current-state.md`,
  `docs/cyberseceval-panel/README.md`, `docs/reporting-platform/CONVENTION.md`,
  `docs/agent-design/step-packet-schema.md`, and `CLAUDE.md`'s Validation
  Tiers / Production Credential Controls.

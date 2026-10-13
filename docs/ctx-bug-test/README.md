# ctx-bug-test (workspace)

A targeted bug hunt on Framework: Qwen3.8-Flash-Next (UD-Q4_K_XL) and
Laguna-S-2.1 (UD-Q4_K_M), each on the Nathanw llama.cpp fork and on
upstream llama.cpp (Vulkan), at `--ctx-size` 32k, 64k, 96k and 131k, with
the same GGUF and the same prompts. Looking for hallucination, repetition,
looping and loss of instruction following, and whether each comes from the
build or from the context size. See [plan.md](plan.md).

Status: **phase 2 built, not run** (2026-10-14). The operator settled
decisions D1–D7 on 2026-10-13; subsequent prompt-fit and Part B corrections
are incorporated in plan.md. No Framework or production run has occurred.

The [local harness](../../scripts/framework-ctx-bugs/README.md) includes
deterministic prompts, tokenizer fit checks, saved context-fill prompts,
all detectors, checkpoint/resume, a loopback stand-in, reports and a detached
systemd user launcher with `--status`.

Local gates passed: 26 unittest tests, including interruption/resume;
two prompt generations with a clean second-run diff; and a complete 16-cell
stand-in run (288 requests plus four saved triggering probes). All six canned
bug types were flagged in their expected cells; all 259 clean responses had
no flags. The local ignored report is
`scripts/framework-ctx-bugs/results/phase2-validation/report.md`.

Remaining work:

- **Phase 1:** inspect and record Framework's current builds and explicit
  expected server build identities.
- **Phase 3:** add and deploy catalogue variants under production approval.
- **Phase 4:** run and inspect the approved 131k greedy pilot.
- **Phase 5:** run the approved full matrix.
- **Phase 6:** reproduce candidate findings with three more seeds;
  optionally run the cloud judge.
- **Phase 7:** write findings, remove temporary catalogue entries and
  update model status under cleanup approval.

Related: [docs/llama-swap](../llama-swap/README.md) (the catalogue, builds
and entries this uses), [docs/model-params](../model-params/README.md)
(variants; the Laguna-on-fork token-14 finding; RULER),
[docs/framework-ubuntu](../framework-ubuntu/README.md).

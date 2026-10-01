# eval-runner

Status: **repo steps 01–05 done (2026-10-01). Blocked on the operator
writing `HF_TOKEN` to OpenBao.** After that: deploy to pve-tiny and the
smoke test.

Runs the eval battery's lm_eval tests (GPQA, IFEval) from
`ai-services-stack` (`ai_seg`, on `pve-tiny`) as a client of whatever
model Framework's llama-server is serving. It replaces running them on
`framework` or garuda. The previous dedicated harness LXC (`ai-stack`,
VMID 116) was removed in the pve teardown.

See [`plan.md`](./plan.md) for decisions, steps and usage.

## Progress

| Step | Status |
|---|---|
| eval-runner-01-manifest-hf-token | done 2026-10-01, all critical gates pass |
| Operator: write HF_TOKEN | **next: waiting on operator** |
| eval-runner-02-dockerfile | done 2026-10-01, all critical gates pass |
| eval-runner-03-eval-run-script | done 2026-10-01, all critical gates pass |
| eval-runner-04-playbook-play | done 2026-10-01, all critical gates pass |
| eval-runner-05-battery-doc-pointer | done 2026-10-01, all critical gates pass |
| Operator: deploy to pve-tiny | not started |
| Operator: smoke test (IFEval + GPQA pilots) | not started |

## Hand-backs

### 2026-10-01: steps 01–05 (run directly by Claude Code, not the local model)

Each file was written from the same tested scratch copies the plan's literal
content was generated from. Gate results:

- **01:** `only-hf-token-added` → `OK`; `one-line-diff` → `1  1  secrets/manifest.json`.
- **02:** `exact-content` → `542fdf7e…c4fb` (match).
- **03:** `exact-content` → `dfc3a470…c36f` (match); `executable` → `OK`;
  `shellcheck` → clean.
- **04:** `exact-appended-play` → `2b32c4ce…99b8` (match); `append-only` →
  `66  0`; `syntax-check` → exit 0.
- **05:** `section-present` → `1`; `append-only` → `0`.

From this commit until the `HF_TOKEN` value is written, `./with-secrets*`
loads on this branch fail closed. Nothing should deploy from the branch
before that.

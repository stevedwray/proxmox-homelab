# eval-runner

Status: **planned, not started (2026-10-01).** The plan is written and its
gates were tested against a throwaway worktree. No step has run yet.

Runs the eval battery's lm_eval tests (GPQA, IFEval) from
`ai-services-stack` (`ai_seg`, on `pve-tiny`) as a client of whatever
model Framework's llama-server is serving. It replaces running them on
`framework` or garuda. The previous dedicated harness LXC (`ai-stack`,
VMID 116) was removed in the pve teardown.

See [`plan.md`](./plan.md) for decisions, steps and usage.

## Progress

| Step | Status |
|---|---|
| eval-runner-01-manifest-hf-token | not started |
| Operator: write HF_TOKEN | not started |
| eval-runner-02-dockerfile | not started |
| eval-runner-03-eval-run-script | not started |
| eval-runner-04-playbook-play | not started |
| eval-runner-05-battery-doc-pointer | not started |
| Operator: deploy to pve-tiny | not started |
| Operator: smoke test (IFEval + GPQA pilots) | not started |

## Hand-backs

_None yet._

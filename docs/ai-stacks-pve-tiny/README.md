# ai-stacks-pve-tiny

Status: **planned, no steps run yet (2026-09-26).** Start with plan.md's "How to execute this plan" section. Phase 0 (read-only
preflight) is next. It has to be run by the operator, because Claude's
production reads are blocked.

## What this is

Relocating `mcp-utility-stack`, `secpipe-stack`, `opensearch-stack` and
`ai-services-stack` from `pve` to `pve-tiny`. Each CT is redeployed from
IaC at the **same IP**. Only the real state is cold-copied: OpenSearch's
data dir, and OpenWebUI/SearXNG/deep-research's Docker volumes. The old
CT stays stopped on pve as a rollback until decommission. See `plan.md`
for the decisions, the step blocks (`ai-tiny-01`…`06`) and the operator
cutover runbook.

Consequence to keep in mind: this uses most of pve-tiny's remaining RAM
(about 21GB of 32GB committed afterwards). The earlier idea of also
moving harbor-stack/graylog-stack there
(`docs/pve-tiny-network-onboarding/plan.md` Phase 2) no longer fits
as-is.

## Progress

| Item | Status |
|---|---|
| Phase 0 preflight | not started |
| ai-tiny-01 storage profile | not started |
| ai-tiny-02 network ai_seg | not started |
| ai-tiny-03 SDN playbook vars | not started |
| ai-tiny-04 stack storage profiles | not started |
| ai-tiny-05 env dirs | not started |
| Phase 2 ai_seg on pve-tiny | not started |
| Cutover: mcp-utility-stack | not started |
| Cutover: secpipe-stack | not started |
| Cutover: opensearch-stack | not started |
| Cutover: ai-services-stack | not started |
| ai-tiny-06 zone membership docs | not started |
| Phase 4 decommission (after ≥7-day soak) | not started |

## Hand-backs

(Per-step hand-backs go here, newest last.)

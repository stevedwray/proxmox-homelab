# ai-stacks-pve-tiny

Status: **Phase 0 passed (2026-09-27); Phase 1 repo steps are next.** Start
with plan.md's "How to execute this plan" section.

## What this is

Relocating `mcp-utility-stack`, `secpipe-stack`, `opensearch-stack` and
`ai-services-stack` from `pve` to `pve-tiny`. Each CT is redeployed from
IaC at the **same IP**. Only the real state is cold-copied: OpenSearch's
data dir, and OpenWebUI/SearXNG/deep-research's Docker volumes. The old
CT stays stopped on pve as a rollback until decommission. See `plan.md`
for the decisions, the step blocks (`ai-tiny-01`…`06`, plus the
`ai-tiny-05b` production-target guard) and the operator
cutover runbook.

Consequence to keep in mind: this uses most of pve-tiny's remaining RAM
(about 21GB of 32GB committed afterwards). The earlier idea of also
moving harbor-stack/graylog-stack there
(`docs/pve-tiny-network-onboarding/plan.md` Phase 2) no longer fits
as-is.

## Progress

| Item | Status |
|---|---|
| Phase 0 preflight | done — go (2026-09-27) |
| ai-tiny-01 storage profile | not started |
| ai-tiny-02 network ai_seg | not started |
| ai-tiny-03 scoped SDN playbook mode + tvai vars | not started |
| ai-tiny-04 stack storage profiles | not started |
| ai-tiny-05 env dirs | not started |
| ai-tiny-05b pve-tiny provision target guard | not started |
| Phase 2 ai_seg on pve-tiny | not started |
| Cutover: mcp-utility-stack | not started |
| Cutover: secpipe-stack | not started |
| Cutover: opensearch-stack | not started |
| Cutover: ai-services-stack | not started |
| ai-tiny-06 zone membership docs | not started |
| Phase 4 decommission (after ≥7-day soak) | not started |

## Hand-backs

### Phase 0 — read-only production preflight (2026-09-27)

- Source CTs 50011/50012/50013/40014 all report `unprivileged: 1`; no
  custom `lxc.idmap` entries were shown. The stateful mounts have
  `backup=1`.
- State sizes: OpenWebUI 948M, SearXNG 5K, deep-research 3.9M, OpenSearch
  148M. Workstation staging is mode 0700 with 537G free and the
  `cve-mcp-server` source clone is present.
- pve-tiny: 16 cores, 28G available RAM, about 1.78T available on
  `nvme-lvm`, target VMIDs unused, and `vm.max_map_count=1048576`.
- Existing `tvinfra`/`tvmgmt`/`tvcse` zones, VNets and subnets match
  their intended VLANs/gateways. `tvai` is absent as expected. Pending
  counts for zones, VNets and all current subnets are zero. Cluster firewall
  is already disabled.
- pve has an enabled all-guest PBS job (excluding only 105/910), which
  covers the four source CTs. No pve-tiny backup job was returned: this does
  not block migration or soak, but Phase 4 must not destroy stateful source
  CTs until a successful post-import pve-tiny backup is configured and
  verified exactly as required by plan.md.
- Result: **GO for Phase 1.** No production state was changed.

(Per-step hand-backs continue below, newest last.)

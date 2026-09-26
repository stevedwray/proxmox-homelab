# ai-stacks-pve-tiny

Status: **Phases 0–2 passed and `mcp-utility-stack` cut over (2026-09-27);
Phase 3 continues with `secpipe-stack`.** Continue with plan.md's "How to execute
this plan" section.

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
| ai-tiny-01 storage profile | done (2026-09-27) |
| ai-tiny-02 network ai_seg | done (2026-09-27) |
| ai-tiny-03 scoped SDN playbook mode + tvai vars | done (2026-09-27) |
| ai-tiny-04 stack storage profiles | done (2026-09-27) |
| ai-tiny-05 env dirs | done (2026-09-27) |
| ai-tiny-05b pve-tiny provision target guard | done (2026-09-27) |
| Phase 1 read-only pve-tiny plans | done — go (2026-09-27) |
| Phase 2 ai_seg on pve-tiny | done — go (2026-09-27) |
| Cutover: mcp-utility-stack | done — known pre-existing docs-RAG AI-runtime issue deferred (2026-09-27) |
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

### ai-tiny-01-storage-profile — done (2026-09-27)

- Added `platform-nvme` to
  `terraform/lxc/storage/pve-tiny.yaml`, mapping both rootfs and Docker to
  `nvme-lvm`.
- Added the compatibility `platform-nvme` alias to
  `terraform/lxc/storage/pve-test-vm.yaml`, mapping both to
  `infrastructure-containers`.
- Gate `profile-resolves`: the exact planned Python command printed `ok`
  and exited 0.
- Gate `only-two-files-changed`: the exact planned command listed only
  `terraform/lxc/storage/pve-test-vm.yaml` and
  `terraform/lxc/storage/pve-tiny.yaml`.
- All critical gates passed. No live or production command was run.

### ai-tiny-02-network-ai-seg — done (2026-09-27)

- Added the `attachments.ai_seg` declaration to
  `terraform/lxc/network/pve-tiny.yaml`: VNet `tvai`, VLAN 50, node
  `pve-tiny`, literal `${lab_subnet_ai_cidr}` CIDR, literal `${lab_gw_ai}`
  gateway, firewall disabled, and SNAT disabled.
- Added `zones.ai_seg` with intentionally empty container membership; the
  membership documentation is deferred to `ai-tiny-06` after the cutovers.
- Gate `ai-seg-declared`: the exact planned Python command printed `ok` and
  exited 0.
- Gate `placeholders-literal`: the exact planned grep command printed `2`
  and exited 0.
- All critical gates passed. No live or production command was run.

### ai-tiny-03-sdn-playbook-vars — done (2026-09-27)

- Added the uppercase `LAB_SUBNET_AI_CIDR` and `LAB_GW_AI` lookups for
  `tvai` to `ansible/00-initial-setup/proxmox-sdn-setup.yml`.
- Added the opt-in VNet filter and fail-closed checks for pending zones,
  VNets, and subnets before a scoped mutation.
- Guarded the existing cluster-firewall write with the opt-in
  `manage_cluster_firewall` control while preserving its default behavior.
- Gate `vars-present` printed `2`; gate `scoped-mode-present` printed `ok`;
  the exact planned Ansible syntax check passed. All exited 0.
- All critical gates passed. The playbook was not run, and no live or
  production command was run.

### ai-tiny-04-stack-storage-profiles — done (2026-09-27)

- Changed `ai-services-stack`, `mcp-utility-stack`, and `secpipe-stack` from
  `platform-default` to `platform-nvme`.
- Changed `opensearch-stack` from `platform-monitoring-zfs` to
  `platform-nvme`, and both of its durable mount profile references from
  `durable-zfs` to `durable-nvme`. Its extra mount uses provider-managed
  resizing, as required for the LVM-thin backend.
- Gate `profiles-resolve-on-pve-tiny` printed `ok`; gate
  `diff-is-storage-lines-only` printed `0`. Both exited 0.
- All critical gates passed. IPs, VMIDs, network zones, compute allocations,
  and storage sizes were unchanged. No live or production command was run.

### ai-tiny-05-env-dirs — done (2026-09-27)

- Relocated the tracked `terragrunt.hcl` entry for `ai-services-stack`,
  `mcp-utility-stack`, `secpipe-stack`, and `opensearch-stack` from the `pve`
  environment to the matching `pve-tiny` directories.
- Each new file is a byte-identical copy of the established
  `pve-tiny/cse-controller/terragrunt.hcl` entry point.
- Gate `new-hcl-identical` printed `ok`; gate `tracked-correctly` printed
  `tiny=4 pve=0`; gate `old-state-kept` printed `ok`. All exited 0.
- All four old `terraform.tfstate.d/` directories remain in place; no state,
  inventory, or other runtime artifact was removed. No Terragrunt, live, or
  production command was run.

### ai-tiny-05b-provision-target-guard — done (2026-09-27)

- Extended `scripts/provision.sh` usage text to include `pve-tiny` as a
  supported `--target-env` value.
- Added the exact `pve-tiny` to `pve-tiny.gibbsgreatly.xyz` mapping used by
  the existing stale/wrong-inventory guard.
- Gate `shell-syntax` exited 0; gate `pve-tiny-mapping-present` printed `ok`
  and exited 0.
- All critical gates passed. `provision.sh` was not run, and no live or
  production command was run.

### Phase 1 — read-only pve-tiny plans (2026-09-27)

- Confirmed live `nvme-lvm` is an active LVM-thin storage restricted to
  `pve-tiny`, supports `rootdir,images`, and has about 1.78 TiB available.
- All four production read-only plans exited 0 and contain exactly one new
  container: VMIDs 50011, 50012, 40014, and 50013 respectively. Their total
  add counts (6, 5, 5, and 6) also include the expected generated inventory,
  SDN attachment, epoch, and applicable cleanup support resources.
- Every rootfs and Docker mount resolves to `nvme-lvm`; OpenSearch's 150 GB
  data mount also resolves to `nvme-lvm`. Every plan reports zero changes and
  zero destroys.
- The first OpenSearch plan exposed an incompatible ZFS-only `operational`
  extra-mount resize contract. The manifest and `ai-tiny-04` gate were
  corrected to require provider-managed resizing on LVM-thin; the rerun has
  no warning or error.
- Result: **GO for Phase 2.** All production access was read-only and changed
  no live state.

### Phase 2a/2b — trunk verification and tvai creation (2026-09-27)

- Operator confirmed VLAN 50 is tagged on the physical-switch port connected
  to `pve-tiny`. The MikroTik read-only API confirmed VLAN 50 is tagged on
  `bridgeLocal,ether1,ether5`, with no untagged ports.
- Under approval `ai-stacks-pve-tiny-sdn`, the scoped playbook created only
  the `tvai` VLAN zone, VLAN-50 VNet, and `192.168.50.0/24` subnet with gateway
  `192.168.50.1` and SNAT disabled. Recap: `ok=24 changed=3 failed=0`.
- The in-run pending-state guard passed. The cluster-firewall task was skipped
  as required. Post-run assertions confirmed `tvinfra`, `tvmgmt`, and `tvcse`
  were unchanged, the firewall file was unchanged, all pending counts remain
  zero, and the `tvai` link exists.
- Phase 2c found RouterOS background-probe entries across `.240`–`.254`. The
  runbook now accepts only absent or dynamic `failed`/no-MAC ARP rows while
  retaining hard stops for DHCP, NetBox IPAM, repository, ping, static ARP,
  MAC-bearing ARP, and router-address ownership.
- The reversible `.250/24` test on `tvai` received 3/3 replies from
  `192.168.50.1`; its neighbor resolved to `04:f4:1c:ef:d3:d6` in `REACHABLE`
  state. The exit trap removed `.250`, confirmed by a separate read-only
  check.
- Phase 2d required no mutation: `vm.max_map_count=1048576`, above the
  OpenSearch minimum of 262144. Result: **GO for the first Phase 3 cutover.**

### Phase 3 — mcp-utility-stack cutover (2026-09-27)

- Under approval `ai-stacks-pve-tiny-mcp-utility`, source CT 50011 on `pve`
  was stopped with onboot disabled. The target was created and provisioned on
  `pve-tiny`; apply reported `6 added, 0 changed, 0 destroyed` and Ansible
  completed with `failed=0`.
- The first functional check exposed a pre-existing application dependency:
  docs-RAG still calls the retired Framework Ollama `/api/embed` endpoint on
  port 11434, while the platform now uses NathanW llama.cpp. A rollback
  restored the source before the cause was classified. The source exhibited
  the same `search_docs` failure, proving it was not introduced by relocation.
- Per operator direction, Ollama-to-llama.cpp compatibility work is deferred
  from this migration pass. The same stale-runtime audit is required for
  `secpipe-stack`; record such findings but do not mix their fixes into this
  relocation.
- Under approval `ai-stacks-pve-tiny-mcp-utility-retry`, source CT 50011 was
  stopped again and target CT 50011 was enabled and started. Source is now
  `stopped/onboot=0`; target is `running/onboot=1`.
- Target rootfs (10G) and `/var/lib/docker` (15G) are both on `nvme-lvm`; it is
  unprivileged and attached to `tvai` as `192.168.50.10/24`. pgvector is
  healthy, cve-mcp is healthy, and the MCP endpoints return the expected
  `8000=406` and `8001=400` signatures.
- The correct-state plan refreshed all six resources without container,

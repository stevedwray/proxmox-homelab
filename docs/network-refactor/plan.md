# Network Refactor Plan

## Executive Summary

This refactor is no longer an architecture-discovery exercise. The intended
target model is already stated in
[docs/design/network.md](/home/steve/git/proxmox-homelab/docs/design/network.md:1):
the MikroTik is the L3 gateway for every SDN VLAN zone, and Proxmox is a pure
L2 attachment point.

The implementation problem is that the provisioning path still assumes a
different model:

1. `terraform/lxc/templates/inventory.tpl` emits `ProxyJump=root@${pve_host}`.
2. `terraform/lxc/main.tf` includes `null_resource.prime_sdn_host_route`.
3. SDN-backed stack automation therefore succeeds by mutating Proxmox host
   routing instead of proving workstation-to-router-to-guest reachability.

The work now is to replace that provisioning assumption with a validated,
router-centric access path, then retire the compatibility shim safely.

Reference checkpoints:

- [checkpoint.md](/home/steve/git/proxmox-homelab/docs/network-refactor/checkpoint.md:1)
- [target-model.md](/home/steve/git/proxmox-homelab/docs/network-refactor/target-model.md:1)
- [validation-gate.md](/home/steve/git/proxmox-homelab/docs/network-refactor/validation-gate.md:1)

## Problem Statement

The preserved productionizing checkpoint uncovered a provisioning assumption
that does not match the intended platform design:

1. `terraform/lxc/templates/inventory.tpl` emits `ProxyJump=root@${pve_host}`
   for stack provisioning.
2. SDN-backed guests therefore depend on the Proxmox host having direct
   host-side reachability into guest subnets.
3. `terraform/lxc/main.tf` compensates with `null_resource.prime_sdn_host_route`
   to add a host bridge IP and route dynamically.
4. The intended network model is that inter-VLAN/subnet routing belongs to the
   main router, not to Proxmox acting as the default jump host or gateway.

## What Is Already Settled

These points should be treated as the working contract unless live validation
proves otherwise:

1. Router-centric L3 is the target design, not a proposal.
2. Workstation and approved admin clients should reach SDN guest IPs through
   the MikroTik without Proxmox host route injection.
3. Proxmox should not carry `.254` interface addresses on SDN VNets as the
   normal provisioning path.
4. `prime_sdn_host_route` is a compatibility workaround to remove, not a design
   pattern to extend.
5. SDN VLAN definitions remain environment data in
   `terraform/lxc/network/<env>.yaml`, with router prerequisites still handled
   out of band for now.

## Remaining Decisions

The plan should explicitly force answers to these before any risky code removal:

1. Is the operator workstation the canonical automation origin for Ansible, or
   should there be a separate bastion later?
2. Which exact router prerequisites must exist before a stack apply is allowed
   to proceed?
3. Do any bootstrap exceptions remain, or can every active stack move to the
   same direct-SSH contract?
4. What temporary escape hatch, if any, is acceptable if one stack still needs
   `ProxyJump` during the migration?

## Workstreams

### 1. Confirm the access contract

Document and prove:

1. workstation to MikroTik to guest L3 reachability
2. router-owned gateway IPs for all SDN subnets
3. DNS entry path through MikroTik for each zone
4. the allowed admin source networks for SSH/HTTP validation

### 2. Inventory the current implementation

Capture the current repo behavior in the refactor docs:

1. generated inventory and `ProxyJump` usage
2. `prime_sdn_host_route` lifecycle and triggers
3. current SDN attachment automation capabilities
4. remaining manual MikroTik prerequisites
5. current validation scripts and where they assume Proxmox-host reachability

### 3. Migrate the provisioning path

Make the code follow the access contract:

1. introduce a direct-SSH inventory mode for router-reachable guests
2. narrow or remove `prime_sdn_host_route`
3. add preflight checks that fail fast when router reachability is missing
4. update stack validation flows to prove direct access instead of host mutation

### 4. Validate teardown and redeploy

Require at least one full `pve-test` rebuild pass that proves:

1. router prerequisites were applied first
2. SDN zone/VNet attachment creation still works
3. representative stacks provision without Proxmox route priming
4. guest DNS and service health match the intended design

## Copilot Session Roadmap

Each session below should end with a small, reviewable commit or a documented
stop point. Do not combine removal of `ProxyJump` and teardown validation into
the same first pass.

### Session 1 - Baseline the contract

Goal:

1. Freeze the intended model and eliminate planning ambiguity.

Inputs:

1. [docs/design/network.md](/home/steve/git/proxmox-homelab/docs/design/network.md:1)
2. [docs/reference/sdn-segment-routing.md](/home/steve/git/proxmox-homelab/docs/reference/sdn-segment-routing.md:1)
3. [checkpoint.md](/home/steve/git/proxmox-homelab/docs/network-refactor/checkpoint.md:1)

Tasks:

1. Produce or refresh `target-model.md`.
2. Record which source systems are expected to reach each SDN subnet.
3. Record the router prerequisites that remain manual.
4. Record explicit non-goals for the migration.

Done when:

1. No future session needs to debate whether Proxmox is allowed to be the L3
   gateway.
2. The target access path is written down in one place.

### Session 2 - Capture current implementation and evidence

Goal:

1. Replace assumptions with repo-anchored evidence.

Primary files:

1. [terraform/lxc/templates/inventory.tpl](/home/steve/git/proxmox-homelab/terraform/lxc/templates/inventory.tpl:1)
2. [terraform/lxc/main.tf](/home/steve/git/proxmox-homelab/terraform/lxc/main.tf:517)
3. [terraform/lxc/ansible/playbooks/configure-network-sdn-vnet.yml](/home/steve/git/proxmox-homelab/terraform/lxc/ansible/playbooks/configure-network-sdn-vnet.yml:1)
4. [terraform/lxc/network/pve-test.yaml](/home/steve/git/proxmox-homelab/terraform/lxc/network/pve-test.yaml:1)

Tasks:

1. Document exactly where `ProxyJump` is injected.
2. Document exactly when `prime_sdn_host_route` runs.
3. Verify whether SDN VLAN attachment creation is already automated.
4. Write down any stale docs uncovered during that comparison.

Done when:

1. The refactor plan has explicit file targets for every intended code change.
2. Historical notes are separated from current blockers.

### Session 3 - Design the migration mechanics

Goal:

1. Decide how the code will switch from jump-host SSH to direct SSH.

Tasks:

1. Define the desired inventory contract for router-reachable guests.
2. Decide whether `ansible_ssh_common_args` becomes conditional on attachment
   type, environment intent, or an explicit compatibility flag.
3. Decide where router reachability preflights should run:
   before inventory generation, before Ansible, or in a dedicated validator.
4. Decide what temporary fallback is allowed during migration.

Outputs:

1. An implementation checklist in this doc.
2. Any new feature flags or manifest fields documented before code changes.

Done when:

1. The next session can edit Terraform and templates without re-opening design
   questions.

### Session 4 - Update inventory generation

Goal:

1. Make inventories support direct SSH for SDN-backed guests.

Primary edits:

1. `terraform/lxc/templates/inventory.tpl`
2. `terraform/lxc/main.tf`
3. Any stack metadata or locals needed to drive the new behavior

Tasks:

1. Remove unconditional `ProxyJump` generation for the router-centric path.
2. Preserve a narrowly scoped compatibility mode only if still needed.
3. Regenerate one or more sample inventories and inspect them.
4. Update docs that describe the generated inventory contract.

Validation:

1. Confirm generated inventory for an SDN-backed stack no longer requires
   `ProxyJump` by default.
2. Confirm non-SDN or explicitly exempted cases still render correctly.

Stop if:

1. Direct SSH is not yet possible from the workstation to a live guest.

### Session 5 - Retire host-route priming

Goal:

1. Remove or sharply constrain Proxmox host route mutation.

Primary edits:

1. `terraform/lxc/main.tf`
2. Any docs or validators that still assume `.254` bridge IPs on Proxmox

Tasks:

1. Remove `null_resource.prime_sdn_host_route`, or gate it behind an explicit
   temporary compatibility toggle with a removal deadline.
2. Update any dependent comments and assumptions.
3. Confirm Terraform no longer relies on mutating host interfaces for SDN guest
   provisioning.

Validation:

1. Run a representative stack plan/apply in a safe scope.
2. Prove guest provisioning succeeds without adding a Proxmox-side route.

Stop if:

1. Any stack still depends on host-side reachability that the router path does
   not yet provide.

### Session 6 - Add preflight and evidence capture

Goal:

1. Fail fast on bad network prerequisites instead of discovering them mid-apply.

Tasks:

1. Add a validation script or documented command set that checks:
   - `./with-secrets bash -c 'echo $TF_VAR_proxmox_node'` returns `pve-test`
   - the workstation can reach the expected guest subnet gateways
   - DNS answers from the zone gateway path
   - direct SSH or TCP reachability to at least one representative guest IP
2. Decide whether these checks belong in Terraform-adjacent scripts, session
   docs, or both.
3. Add evidence capture guidance for future sessions.

Done when:

1. A future operator can prove the router path is ready before running apply.

### Session 7 - Run representative stack validation

Goal:

1. Prove the migration on live `pve-test` workloads before a full rebuild.

Suggested order:

1. `apt-cacher-stack`
2. one `mgmt_seg` stack such as `dns-stack` or `step-ca-stack`
3. one additional SDN-backed stack if needed

Tasks:

1. Re-apply or redeploy selected stacks with the new access model.
2. Capture SSH, DNS, and service-health evidence.
3. Record any stack-specific exceptions that still block the full cycle.

Stop if:

1. Any representative stack requires reintroducing `ProxyJump` or host-route
   priming to succeed.

### Session 8 - Execute teardown and redeploy gate

Goal:

1. Prove the design survives a fresh environment lifecycle.

Workflow:

1. Follow [validation-gate.md](/home/steve/git/proxmox-homelab/docs/network-refactor/validation-gate.md:1).
2. Run the teardown/redeploy cycle on `pve-test`.
3. Re-validate representative stacks and DNS.
4. Record results, regressions, and any manual router actions taken.

Success criteria:

1. SDN-backed stacks provision from the intended access path.
2. No Proxmox host route priming is required.
3. Evidence is sufficient to resume production canary preparation later.

### Session 9 - Clean up and promote

Goal:

1. Finish documentation and branch hygiene after the refactor is proven.

Tasks:

1. Remove stale migration notes and temporary flags.
2. Update `handoff.md` with what remains for production canary work.
3. Run required scanners for changed file types before merge.
4. Promote according to `AGENTS.md` branch rules only after validation is
   complete.

## Implementation Checklist

Use this as the quick tracker across sessions:

1. Target model doc written and agreed.
2. Current implementation inventory captured with file references.
3. Direct-SSH inventory contract designed.
4. Inventory generation updated.
5. `prime_sdn_host_route` removed or explicitly quarantined.
6. Preflight checks documented or automated.
7. Representative live stacks validated.
8. One teardown/redeploy cycle completed on `pve-test`.
9. Required scans run before merge.

## Non-Goals

Until the refactor validates cleanly, do not:

1. resume production canary apply work
2. merge preserved `refactor/productionize` work into a promotion branch
3. normalize `prime_sdn_host_route` as the accepted final design
4. treat manual MikroTik prerequisites as solved IaC work

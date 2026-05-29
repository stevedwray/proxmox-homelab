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
6. The operator workstation on LAN `192.168.1.0/24` is the canonical Ansible
   automation origin. Proxmox is not. A dedicated bastion is deferred to a
   future phase and is outside this refactor's scope.
7. `ProxyJump` through Proxmox is the accepted temporary escape hatch during
   migration. It must be explicitly labeled in any stack that still uses it and
   must be removed before the teardown validation gate passes.
8. Portainer is on `mgmt_seg` (confirmed in
   `terraform/lxc/stacks/portainer-stack/stack.yaml`). The `vmbr0` (`lan`)
   attachment in `pve-test.yaml` is retained for legacy test stacks only and
   is not an active exception in the platform model.

## Remaining Decisions

These must be answered before any risky code removal (Session 3+):

1. Which exact router prerequisites must exist before a stack apply is allowed
   to proceed, and where should the preflight check live?
2. Should `ansible_ssh_common_args` become conditional (on attachment type,
   environment flag, or explicit opt-in) or be removed from the template
   entirely once direct-SSH is the default?

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
3. Current temporary exceptions (`ProxyJump` and `prime_sdn_host_route`) are
   explicitly named with retirement conditions in `target-model.md`.
4. Non-goals are explicitly stated so future sessions do not re-open them.

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
2. Decide the logic for when to set `pve_host` (which gates ProxyJump generation):
    - Decide the default behavior for `sdn_vnet` attachments.
    - Decide how compatibility fallback is explicitly requested.
    - Decide how legacy bridge-path stacks behave during migration.
3. Decide where router reachability preflights should run:
   before inventory generation, before Ansible, or in a dedicated validator.
4. Decide what temporary fallback is allowed during migration (if any).

Outputs:

1. A concrete inventory contract for SDN-backed stacks.
2. A concrete `pve_host` migration rule and compatibility mechanism.
3. A concrete preflight placement model.
4. A concrete temporary fallback policy.
5. Any new feature flags or manifest fields documented before code changes.

Session 3 decision outcomes (2026-05-22):

1. Desired inventory contract for router-reachable SDN-backed guests:
    - `ansible_host` remains the guest IP rendered from Terraform state.
    - Direct SSH is the default for `sdn_vnet` attachments.
    - `ansible_ssh_common_args` for the default path includes only strict host
       key bypass options already used in this repo; it does not include
       `ProxyJump`.
    - `pve_host` is no longer the default transport selector for SDN-backed
       guests; it is treated as compatibility-only metadata when explicitly
       requested.

2. Preferred migration approach for `pve_host`:
    - Use a hybrid control model: attachment-type default plus explicit
       compatibility override.
    - Attachment-type default:
       - `sdn_vnet` => direct SSH default (no `ProxyJump`).
       - `bridge` => preserve existing behavior during migration to avoid
          surprise regressions in legacy/test stacks.
    - Explicit compatibility override:
       - Add a stack-level migration flag in `stack.yaml` for Session 4
          implementation: `network.access_path` with allowed values:
          - `direct` (default for `sdn_vnet`)
          - `proxyjump_compat` (temporary fallback)
       - Template/locals logic should generate `ProxyJump` only when
          `network.access_path == "proxyjump_compat"`.
    - Legacy bridge-path stacks:
       - Continue with current behavior unless explicitly opted into
          `network.access_path: direct`.
       - They remain out of the SDN direct-SSH success criteria until migrated.

3. Preflight placement decision:
    - Use a combination model with one source of truth.
    - Source of truth: a standalone validator command that checks router
       reachability and DNS path assumptions from the workstation.
    - Required invocation point: before Terraform apply (including teardown/
       redeploy workflows).
    - Secondary invocation point: before Ansible provisioning for stacks marked
       `network.access_path: direct` (enforced by Session 4/6 wiring).
    - Rationale: one validator avoids duplicated logic and drift, while two
       invocation points catch both upfront readiness and per-stack access-path
       mismatches.

4. Temporary fallback policy (`ProxyJump` during migration):
    - Allowed only when a stack is explicitly labeled
       `network.access_path: proxyjump_compat`.
    - Any fallback stack must include a migration annotation in `stack.yaml`
       comment or adjacent docs with:
       - reason for fallback
       - owner
       - review date/remove-by target
    - `ProxyJump` fallback is disallowed for new SDN-backed stacks unless a
       blocking preflight finding is documented.
    - Removal readiness criteria for each fallback stack:
       - router preflight passes for the stack zone
       - one successful provisioning run using `network.access_path: direct`
       - no dependency on `prime_sdn_host_route` for that stack path
    - Global retirement condition remains unchanged: default `ProxyJump` must be
       gone before the validation gate can pass.

5. Session 4 implementation checklist (derived from these decisions):
    - Add `network.access_path` parsing and validation in Terraform locals.
    - Make inventory rendering use explicit `access_path` instead of
       `pve_host != ""` as the ProxyJump gate.
    - Keep existing bridge behavior unless explicitly overridden.
    - Emit clear inventory metadata so operators can see whether a stack is in
       `direct` or `proxyjump_compat` mode.
    - Document migration labeling requirements in stack docs.

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

Session 5 implementation note (2026-05-22):

1. `null_resource.prime_sdn_host_route` has been removed from
   `terraform/lxc/main.tf`.
2. The remaining compatibility path is explicit `network.access_path:
   proxyjump_compat`; there is no host-route fallback.
3. The next live validation work is Session 6 preflight/evidence capture,
   followed by Session 7 representative stack validation.

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

Session 6 implementation note (2026-05-22):

1. `scripts/preflight-network-refactor.sh` added as a standalone preflight
   validator. Invoke with `./with-secrets scripts/preflight-network-refactor.sh`.
2. Checks implemented:
   - Check 1: targeting guard (`TF_VAR_proxmox_node == pve-test`)
   - Check 2: ICMP ping to all four SDN gateways (`192.168.10.1` –
     `192.168.40.1`)
   - Check 3: DNS via MikroTik gateway (`192.168.20.1`) for delegated internal
     name
     and public name
   - Check 4: TCP:22 probe to at least one representative guest IP
3. Evidence capture: `--save-evidence <dir>` writes a timestamped evidence file.
4. `validation-gate.md` updated with a "Preflight Script" section that
   documents standard, explicit-IP, and evidence-capture invocations.
5. Check 4 is warn-only when no stacks are deployed and the default candidate
   list is used; it becomes a hard check when explicit IPs are passed.

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

Session 7 implementation note (2026-05-22):

1. Session blocked at precondition stage from the current operator context.
2. `./with-secrets scripts/preflight-network-refactor.sh 192.168.40.11`
   exited 1
   with failed gateway reachability, DNS via MikroTik gateway, and
   representative guest TCP:22 checks.
3. No representative stack re-apply/provision run was executed after preflight
   failure.
4. See `docs/network-refactor/session-7-summary.md` for captured evidence and
   restart checklist.

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
5. `prime_sdn_host_route` removed.
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

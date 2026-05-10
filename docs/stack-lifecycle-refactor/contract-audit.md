# Contract Audit — session-01

Session: session-01
Date: 2026-05-10
Evidence: .git/ai/sessions/evidence/session-01/contract-surface.txt

Summary: the following implemented contract surfaces were discovered under `terraform/lxc/`. For each item I list where the docs reference it and a short recommended action (coverage / gap).

- [terraform/lxc/PLATFORM_CONTRACT.md](terraform/lxc/PLATFORM_CONTRACT.md)
  - Referenced in: [docs/stack-lifecycle-refactor/plan.md](docs/stack-lifecycle-refactor/plan.md), [docs/stack-lifecycle-refactor/inventory-model.md](docs/stack-lifecycle-refactor/inventory-model.md), [docs/stack-lifecycle-refactor/decisions.md](docs/stack-lifecycle-refactor/decisions.md), [docs/stack-lifecycle-refactor/handoff.md](docs/stack-lifecycle-refactor/handoff.md)
  - Notes: central platform contract exists and is documented in the SLR docs. Action: verify the contract fields map to examples in `terraform/lxc/main.tf` and add cross-links in `PLATFORM_CONTRACT.md` to those examples.

- Per-stack contract files: (exist)
  - [terraform/lxc/stacks/apt-cacher-stack/STACK_CONTRACT.md](terraform/lxc/stacks/apt-cacher-stack/STACK_CONTRACT.md)
  - [terraform/lxc/stacks/authentik-stack/STACK_CONTRACT.md](terraform/lxc/stacks/authentik-stack/STACK_CONTRACT.md)
  - [terraform/lxc/stacks/ci-runner-01/STACK_CONTRACT.md](terraform/lxc/stacks/ci-runner-01/STACK_CONTRACT.md)
  - [terraform/lxc/stacks/harbor-stack/STACK_CONTRACT.md](terraform/lxc/stacks/harbor-stack/STACK_CONTRACT.md)
  - [terraform/lxc/stacks/portainer-stack/STACK_CONTRACT.md](terraform/lxc/stacks/portainer-stack/STACK_CONTRACT.md)
  - [terraform/lxc/stacks/step-ca-stack/STACK_CONTRACT.md](terraform/lxc/stacks/step-ca-stack/STACK_CONTRACT.md)
  - Referenced in: [docs/stack-lifecycle-refactor/plan.md](docs/stack-lifecycle-refactor/plan.md), [docs/stack-lifecycle-refactor/handoff.md](docs/stack-lifecycle-refactor/handoff.md)
  - Notes: per-stack contracts are present. Action: verify each `STACK_CONTRACT.md` includes a short example of how the stack is consumed by the platform contract and add links from SLR docs to each stack contract.

- Implementation / generation surfaces
  - [terraform/lxc/main.tf](terraform/lxc/main.tf)
    - Referenced in: [docs/stack-lifecycle-refactor/inventory-model.md](docs/stack-lifecycle-refactor/inventory-model.md)
    - Notes: implementation entrypoint; confirm variable/outputs sections are documented in SLR inventory-model and PLATFORM_CONTRACT mapping.
  - [terraform/lxc/templates/inventory.tpl](terraform/lxc/templates/inventory.tpl)
    - Referenced in: [docs/stack-lifecycle-refactor/inventory-model.md](docs/stack-lifecycle-refactor/inventory-model.md)
    - Notes: template used by rendering scripts; recommend adding a short example snippet in docs showing the rendered result.
  - [terraform/lxc/modules/lxc-docker-host/main.tf](terraform/lxc/modules/lxc-docker-host/main.tf)
    - Referenced: not explicitly called out in SLR docs (suggest linking)
    - Notes: module-level details may be useful for implementers; recommend linking the module usage from the platform contract docs.

- Rendering / reconcile scripts
  - [terraform/lxc/edge_manifest.py](terraform/lxc/edge_manifest.py)
  - [terraform/lxc/generate-zone-members-index.py](terraform/lxc/generate-zone-members-index.py)
  - [terraform/lxc/render-edge-coredns.py](terraform/lxc/render-edge-coredns.py)
  - [terraform/lxc/render-edge-traefik.py](terraform/lxc/render-edge-traefik.py)
  - [terraform/lxc/reconcile-edge.py](terraform/lxc/reconcile-edge.py)
  - [terraform/lxc/reconcile-authentik-edge.py](terraform/lxc/reconcile-authentik-edge.py)
  - Referenced in: [docs/stack-lifecycle-refactor/inventory-model.md](docs/stack-lifecycle-refactor/inventory-model.md)
  - Notes: rendering and reconcile surfaces are documented at a high level. Action: add a small flow diagram and example invocation for each script in `inventory-model.md` and link to the actual scripts.

- Tests / misc
  - [terraform/lxc/test_edge_manifest.py](terraform/lxc/test_edge_manifest.py)
    - Referenced in docs: none
    - Notes: unit test exists; recommend documenting test purpose and how to run it in SLR docs or a `tests.md` subsection.

Gaps / Recommendations (short)
- Add explicit cross-links from `PLATFORM_CONTRACT.md` and per-`STACK_CONTRACT.md` to representative implementation files (`main.tf`, `templates/inventory.tpl`, module paths).
- Document example invocations (render/reconcile) in `inventory-model.md` with commands and expected outputs.
- Document the test artifacts and module internals (modules/lxc-docker-host) or link them from SLR docs.

If you want, I can: generate the proposed cross-links and a short example subsection in `inventory-model.md` now. Otherwise I can open a PR with this audit file added.

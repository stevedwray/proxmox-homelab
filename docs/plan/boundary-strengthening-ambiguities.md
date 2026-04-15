# Boundary Strengthening — Ambiguities and Open Questions

This document collects the boundary-model ambiguities surfaced while implementing
the first code-backed boundary-strengthening changes.

It is a handoff/reference note for follow-up sessions, not a final design decision
document.

Related plan: [boundary-strengthening.md](./boundary-strengthening.md)

## Current State

- Active pve-test stacks now declare documentation-only `depends_on` and `provides`
  metadata in `stack.yaml`.
- A lightweight validator exists at `terraform/lxc/validate-stack-metadata.py`
  and `terraform/lxc/validate-stack-metadata.sh`.
- `authentik-stack` and the active NetBox compose path now consume Harbor through
  `registry_host` → `REGISTRY_HOST` rather than hardcoded environment-specific IPs.
- Stack contracts for active pve-test stacks have started distinguishing
  implementation reality from intended target state where useful.

## Target State

- Active stacks declare boundaries in a way that is both readable to humans and
  reliable enough for machine validation.
- Shared platform services such as Harbor, apt-cacher, and Portainer are consumed
  through declared variables and contracts rather than hardcoded addresses.
- Boundary drift becomes detectable before deploy time.

## Ambiguities

### 1. What `depends_on` means

- **Current state:** `depends_on` is being used as deployment/bootstrap metadata.
  Example: a stack may depend on `portainer-stack` because its agent must register
  during provisioning, even if the application does not need Portainer at runtime.
- **Open question:** should `depends_on` remain a bootstrap/deployment graph, or
  should it evolve into a fuller runtime dependency graph?
- **Why this matters:** validation rules, deployment ordering, and future generated
  views will differ depending on which meaning we choose.

### 2. What belongs in `provides`

- **Current state:** `provides` lists boundary-relevant services only.
  It does not necessarily enumerate every reachable port or incidental listener.
- **Examples:**
  - `step-ca-stack` currently declares `step-ca-acme` on `443`, but the contract
    also discusses health checks on the same port.
  - Stacks that run a Portainer agent expose port `9001`, but that agent endpoint
    is not consistently modeled in `provides`.
- **Open question:** should `provides` represent:
  - every inbound service/port,
  - only externally meaningful boundary services,
  - or only services other stacks are allowed to depend on?

### 3. Service naming conventions are not fully settled

- **Current state:** service names such as `registry-http`, `authentik-http`,
  `portainer-edge`, and `netbox-http` are reasonable but still informal.
- **Open question:** do we want a repo-wide naming rule for `provides.service`
  values, including whether UI/API pairs on the same port are modeled once or twice?
- **Why this matters:** later contract enforcement or generated indexes will be
  noisier if service names drift.

### 4. Validator scope is intentionally narrow

- **Current state:** the validator only checks the seven active stacks from Change 1,
  confirms `depends_on` points to a real stack directory, and confirms each
  `provides` entry has `service`, `port`, and `protocol`.
- **Open question:** when expanding validation, should it apply to:
  - active platform stacks only,
  - all stacks under `terraform/lxc/stacks/`,
  - or active stacks plus a separately labeled class of validation/test stacks?
- **Why this matters:** the repo contains production-path, disposable test, and
  experimental stacks with different levels of contract maturity.

### 5. Contract parity is still partial

- **Current state:** some active stacks have `STACK_CONTRACT.md`, but parity is not
  complete across all relevant stack paths. For example, `netbox-stack-test` has a
  contract, while `netbox-stack` does not currently have a matching
  `STACK_CONTRACT.md`.
- **Open question:** should contract enforcement target:
  - only stacks with an explicit contract file,
  - all active stacks,
  - or a new machine-readable contract file instead of Markdown?

### 6. Markdown contracts are informative but hard to validate

- **Current state:** `STACK_CONTRACT.md` is useful for human/AI context, but fields
  such as dependencies, services, and current-vs-target statements are embedded in
  prose and tables.
- **Open question:** is it better to:
  - keep Markdown as the source of truth and parse parts of it,
  - treat `stack.yaml` as the machine-readable boundary source,
  - or introduce a smaller YAML-native contract file later?

### 7. Shared-service cleanup is ahead of dependency enforcement

- **Current state:** some stacks now consume Harbor and apt-cacher through shared
  variables, but the validator does not yet prove that every declared dependency is
  actually consumed through the corresponding variable flow.
- **Open question:** should future checks compare:
  - declared `depends_on` against observed config usage,
  - declared `provides` against compose/playbook listeners,
  - or both?

### 8. Harbor has a bootstrap exception

- **Current state:** Harbor is itself a platform dependency for most image pulls,
  but on the first fresh pve-test pass Harbor must bootstrap before other stacks can
  consume it as the registry proxy.
- **Open question:** should the model encode this explicitly, or is it enough to
  leave it as contract documentation?
- **Why this matters:** a strict generated deployment graph could otherwise imply
  Harbor is just another normal provider with no bootstrap caveat.

### 9. Portainer is both infrastructure and deployment machinery

- **Current state:** several stacks depend on `portainer-stack` because of agent
  registration and Portainer-managed deploy flow, not because the application needs
  Portainer after startup.
- **Open question:** should we keep that under `depends_on`, or eventually separate
  "deployment requires" from "runtime depends on"?

### 10. Active pve-test state and broader repo state still differ

- **Current state:** the active pve-test path is being normalized first.
  Production-path stacks, older stacks, and validation stacks still contain older
  assumptions and hardcoded addresses in places.
- **Open question:** should future boundary work continue to prioritize active
  pve-test only, or broaden to full repo consistency once the active path is stable?

### 11. Provisioning-time dependencies and runtime dependencies are diverging

- **Current state:** several stacks now consume shared services through generated
  inventory vars during provisioning, but some important dependencies only appear
  later at runtime.
- **Example:** `ci-runner-01` consumes `apt_cacher_host` and `portainer_server_ip`
  during provisioning, while Harbor is mostly a runtime dependency for GitHub job
  containers rather than for the runner playbook itself.
- **Open question:** should future enforcement distinguish:
  - provisioning-time variable flow,
  - runtime service consumption,
  - and declared platform dependency separately?
- **Why this matters:** a simple "declared dependency must appear in playbook vars"
  rule would incorrectly flag legitimate runtime-only consumers.

### 12. Textual contract sync is not the same as semantic contract enforcement

- **Current state:** the optional contract-doc validator now checks for textual
  mention of declared dependencies and `provides.service` identifiers inside
  `STACK_CONTRACT.md`.
- **Current compromise:** active contracts now include explicit `stack.yaml`
  service identifiers to make this drift check reliable.
- **Open question:** how far should we trust a text-presence check before moving
  to stronger structured validation?
- **Why this matters:** a contract can mention the right words while still being
  semantically wrong about ports, purpose, runtime/provisioning phase, or allowed
  consumers.

### 13. Human-readable validation output is not ideal for agent handoff

- **Current state:** validator output is now layered and easier to read, but it is
  still primarily prose intended for humans in a terminal.
- **Open question:** how much machine-readable structure should the validator expose
  directly for AI and CI consumers?
- **Why this matters:** an AI can work from human-readable output, but reliable
  automation and multi-step agent handoff are safer when layer names, stack names,
  and issue lists can be consumed without text parsing.

## Practical Guidance For Follow-Up Sessions

- Treat `stack.yaml` metadata as documentation/schema only unless a session
  explicitly introduces a functional consumer.
- Be explicit in docs about **current state** versus **target state** when a stack
  is mid-normalization.
- Prefer structural validation first:
  - reference existence
  - required keys
  - basic typing
- Delay stronger semantic enforcement until the meanings of `depends_on` and
  `provides` are settled.

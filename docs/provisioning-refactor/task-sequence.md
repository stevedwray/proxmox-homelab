# Provisioning Refactor Task Sequence

Each task is intended to be one short-lived branch/session. Keep changes inside
the listed files unless the task document explicitly expands scope. Stop when a
precondition is not met or validation reveals a new issue outside the task.

## A. Planning Reset

### Task 00: Normalize Source Of Truth

Type: documentation

Objective: Make `docs/provisioning-refactor/` the active source of truth and
mark old Phase 04c/MikroTik DNS reconciliation instructions as legacy context.

Files: `README.md`, `decisions.md`, `task-sequence.md`,
`../plan/phase-04c-stack-owned-ingress-auth-dns.md`.

Task doc: [tasks/00-normalize-source-of-truth.md](tasks/00-normalize-source-of-truth.md)

### Task 01: Document Edge Bootstrap Order

Type: documentation

Objective: Define Stage 3a order: CoreDNS seed zone -> Traefik runtime ->
step-ca -> Authentik direct first boot/API token -> edge reconciler.

Files: `../design/bootstrap.md`, `decisions.md`,
`tasks/01-bootstrap-order.md`, matching prompt.

Task doc: [tasks/01-bootstrap-order.md](tasks/01-bootstrap-order.md)

### Task 02: Define DNS Ownership Transition

Type: documentation

Objective: Specify CoreDNS seed records versus generated browser records, and
the one-host-at-a-time replacement model.

Files: `decisions.md`, `tasks/08-coredns-renderer.md`, matching prompt.

Task doc: [tasks/02-dns-ownership-transition.md](tasks/02-dns-ownership-transition.md)

### Task 03: Define Cutover Semantics

Type: documentation

Objective: Fix generated-vs-legacy route collision semantics with an explicit
one-host replacement workflow.

Files: `decisions.md`, `tasks/07-traefik-renderer.md`, migration task docs.

Task doc: [tasks/03-cutover-semantics.md](tasks/03-cutover-semantics.md)

## B. Contract And Tooling

### Task 04: EdgeManifest Contract

Type: documentation/specification

Objective: Define `EdgeManifest` v1alpha1, fixtures, error catalog, and
auth/backend compatibility.

Files: `edge-manifest-v1alpha1.md`, `fixtures/`, task doc.

Task doc: [tasks/04-edge-manifest-contract.md](tasks/04-edge-manifest-contract.md)

### Task 05: Manifest Validator

Type: development

Objective: Implement side-effect-free validation for
`terraform/lxc/stacks/*/edge.yaml`.

Files: `terraform/lxc/edge_manifest.py`,
`terraform/lxc/validate-edge-manifests.py`,
`terraform/lxc/test_edge_manifest.py`.

Task doc: [tasks/05-manifest-validator.md](tasks/05-manifest-validator.md)

### Task 06: Legacy Route Inventory

Type: development/read-only

Objective: Extract current central Traefik host rules for collision and
replacement checks.

Files: `terraform/lxc/edge_manifest.py` or
`terraform/lxc/extract-legacy-edge-hosts.py`, tests.

Task doc: [tasks/06-legacy-route-inventory.md](tasks/06-legacy-route-inventory.md)

### Task 07: Traefik Renderer

Type: development

Objective: Render deterministic per-stack dynamic config to a dry-run output
directory.

Files: `terraform/lxc/render-edge-traefik.py`, tests.

Task doc: [tasks/07-traefik-renderer.md](tasks/07-traefik-renderer.md)

### Task 08: CoreDNS Renderer

Type: development

Objective: Render deterministic full lab-zone output from seed records plus
validated browser manifests.

Files: `terraform/lxc/render-edge-coredns.py`, tests.

Task doc: [tasks/08-coredns-renderer.md](tasks/08-coredns-renderer.md)

### Task 09: Authentik Discovery

Type: development/read-only

Objective: Query Authentik read-only and map manifest auth intent to existing
apps, providers, and outposts.

Files: `terraform/lxc/discover-authentik-edge.py`, tests with mocked API.

Task doc: [tasks/09-authentik-discovery.md](tasks/09-authentik-discovery.md)

### Task 10: Authentik Reconciler

Type: development

Objective: Add create/update-only Authentik reconciliation with explicit
ownership labels/names.

Files: `terraform/lxc/reconcile-authentik-edge.py`, tests.

Task doc: [tasks/10-authentik-reconciler.md](tasks/10-authentik-reconciler.md)

### Task 11: Edge Reconciler

Type: development

Objective: Add one command that runs preflight, validate, render, plan, and
optional apply for DNS, Traefik, and Authentik.

Files: `terraform/lxc/reconcile-edge.py`, tests, `README.md` usage.

Task doc: [tasks/11-edge-reconciler.md](tasks/11-edge-reconciler.md)

## C. Runtime Wiring

### Task 12: CoreDNS Publish Wiring

Type: development

Objective: Let CoreDNS deployment consume generated zone output, validate it,
publish it, and reload/restart safely.

Files: `terraform/lxc/ansible/playbooks/deploy-coredns.yml`,
`terraform/lxc/ansible/files/coredns-lab.zone` if seed cleanup is needed.

Task doc: [tasks/12-coredns-publish-wiring.md](tasks/12-coredns-publish-wiring.md)

### Task 13: Proxy Generated File Wiring

Type: development

Objective: Prepare `/opt/proxy-stack/dynamic/stacks` and keep shared middleware
central while legacy routes remain.

Files: `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml`.

Task doc: [tasks/13-proxy-generated-file-wiring.md](tasks/13-proxy-generated-file-wiring.md)

### Task 14: Shared Edge Validation Runbook

Type: documentation

Objective: Document preflight checks, validation commands, expected outputs, and
rollback for edge reconciliation.

Files: `runbook.md`, migration task docs.

Task doc: [tasks/14-shared-validation-runbook.md](tasks/14-shared-validation-runbook.md)

## D. Stack Migration Order

### Task 15: Migrate Authentik Route

Type: deployment

Objective: Move `authentik.lab.gibbsgreatly.xyz` to stack-owned provisioning
with `auth.mode: none`.

Files: `terraform/lxc/stacks/authentik-stack/edge.yaml`,
`terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml`, generated artifacts.

Task doc: [tasks/15-migrate-authentik.md](tasks/15-migrate-authentik.md)

### Task 16: Migrate Harbor Route

Type: deployment

Objective: Move `harbor.lab.gibbsgreatly.xyz` to stack-owned provisioning with
native Harbor auth.

Files: `terraform/lxc/stacks/harbor-stack/edge.yaml`,
`terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml`, generated artifacts.

Task doc: [tasks/16-migrate-harbor.md](tasks/16-migrate-harbor.md)

### Task 17: Migrate Grafana Route

Type: deployment

Objective: Move `grafana.lab.gibbsgreatly.xyz` to stack-owned provisioning with
native Grafana OIDC.

Files: `terraform/lxc/stacks/monitoring-stack/edge.yaml`,
`terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml`, generated artifacts.

Task doc: [tasks/17-migrate-grafana.md](tasks/17-migrate-grafana.md)

### Task 18: Migrate Portainer Route

Type: deployment

Objective: Move `portainer.lab.gibbsgreatly.xyz` to stack-owned provisioning
with forward-auth.

Files: `terraform/lxc/stacks/portainer-stack/edge.yaml`,
`terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml`, generated artifacts.

Task doc: [tasks/18-migrate-portainer.md](tasks/18-migrate-portainer.md)

### Task 19: Migrate NetBox Route

Type: deployment

Objective: Move `netbox.lab.gibbsgreatly.xyz` to stack-owned provisioning with
forward-auth.

Files: `terraform/lxc/stacks/netbox-stack/edge.yaml`,
`terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml`, generated artifacts.

Task doc: [tasks/19-migrate-netbox.md](tasks/19-migrate-netbox.md)

### Task 20: Migrate Traefik Dashboard

Type: deployment

Objective: Move `traefik.lab.gibbsgreatly.xyz` to stack-owned provisioning with
`api@internal` and forward-auth.

Files: `terraform/lxc/stacks/proxy-stack/edge.yaml`,
`terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml`, generated artifacts.

Task doc: [tasks/20-migrate-traefik-dashboard.md](tasks/20-migrate-traefik-dashboard.md)

### Task 21: Final Cutover Cleanup

Type: deployment

Objective: Remove remaining central per-service route ownership and validate the
stack-owned model end to end.

Files: `terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml`,
`tasks/21-final-cutover-cleanup.md`, `runbook.md`.

Task doc: [tasks/21-final-cutover-cleanup.md](tasks/21-final-cutover-cleanup.md)

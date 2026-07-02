# Provisioning Refactor Task Sequence

Use this file as the short index for the stack-owned edge refactor. Detailed
scope, file touch rules, validation, and stop conditions live in the individual
task docs under [tasks/](tasks/).

## Working Rules

- take one task per short-lived branch/session
- keep changes inside that task's declared scope unless the task doc expands it
- stop when a precondition is not met or validation exposes an unrelated issue

## Sequence

| Range | Theme | Outcome | Primary docs |
| --- | --- | --- | --- |
| 00-03 | Planning reset | make this directory the source of truth and define bootstrap/cutover rules | [00](tasks/00-normalize-source-of-truth.md), [01](tasks/01-bootstrap-order.md), [02](tasks/02-dns-ownership-transition.md), [03](tasks/03-cutover-semantics.md) |
| 04-11 | Contract and tooling | define the manifest contract and build validate/render/reconcile tooling | [04](tasks/04-edge-manifest-contract.md), [05](tasks/05-manifest-validator.md), [06](tasks/06-legacy-route-inventory.md), [07](tasks/07-traefik-renderer.md), [08](tasks/08-coredns-renderer.md), [09](tasks/09-authentik-discovery.md), [10](tasks/10-authentik-reconciler.md), [11](tasks/11-edge-reconciler.md) |
| 12-14 | Runtime wiring | publish generated DNS/proxy state and document shared validation | [12](tasks/12-coredns-publish-wiring.md), [13](tasks/13-proxy-generated-file-wiring.md), [14](tasks/14-shared-validation-runbook.md) |
| 15-21 | Route migration | move browser routes from central ownership to stack-owned manifests | [15](tasks/15-migrate-authentik.md), [16](tasks/16-migrate-harbor.md), [17](tasks/17-migrate-grafana.md), [18](tasks/18-migrate-portainer.md), [19](tasks/19-migrate-netbox.md), [20](tasks/20-migrate-traefik-dashboard.md), [21](tasks/21-final-cutover-cleanup.md) |

## Quick Intent By Task

| Task | Intent |
| --- | --- |
| 00 | mark provisioning-refactor as canonical and retire stale Phase 04c guidance |
| 01 | document Stage 3a bootstrap order |
| 02 | define seed DNS versus generated browser DNS ownership |
| 03 | define one-host-at-a-time cutover semantics |
| 04 | define `EdgeManifest` contract and fixtures |
| 05 | validate `edge.yaml` safely |
| 06 | inventory legacy central routes |
| 07 | render Traefik dynamic config |
| 08 | render CoreDNS zone output |
| 09 | discover existing Authentik objects read-only |
| 10 | reconcile Authentik create/update-only state |
| 11 | unify preflight, render, plan, and apply into one reconciler |
| 12 | wire generated CoreDNS output into deployment |
| 13 | wire generated proxy config into deployment |
| 14 | document validation and rollback |
| 15 | migrate Authentik route |
| 16 | migrate Harbor route |
| 17 | migrate Grafana route |
| 18 | migrate Portainer route |
| 19 | migrate NetBox route |
| 20 | migrate Traefik dashboard route |
| 21 | remove remaining central route ownership and validate end state |

## Start Here

1. Read [README.md](README.md) and [decisions.md](decisions.md).
2. Choose the next task from the table above.
3. Open the matching task doc under [tasks/](tasks/).
4. Use [runbook.md](runbook.md) for shared validation and rollback guidance.

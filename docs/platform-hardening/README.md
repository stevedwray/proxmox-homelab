# Platform Hardening: Socket Proxy + Holistic Edge Reconciliation

## Purpose

This directory tracks the unified work/* branch that bridges the current
`baseline/teardown-validated` state to a baseline that can support monitoring
and NetBox.

Two structural gaps prevent those stacks from landing cleanly on a fresh deploy:

1. **Docker socket proxy is not enabled in normal deploy.** The
   `docker_socket_proxy` Ansible role exists, has been proven on a canary, and
   is wired into the six managed Docker stacks — but all stacks still carry
   `enable_docker_socket_proxy: false`. A rebuilt cluster has no runtime Docker
   inspection endpoints. NetBox populate cannot discover container services
   after a teardown/rebuild.

2. **Edge reconciliation only runs for Portainer.** Adding any browser-facing
   service (Traefik route, CoreDNS record, Authentik OIDC provider) currently
   requires a manual reconciliation step outside provision.sh. `reconcile-edge.py`
   already supports `--stacks-dir` to process all `edge.yaml` files in one pass,
   and all six browser-facing stacks already have `edge.yaml` files. The gap is
   purely in provision.sh orchestration.

These two gaps are coupled: fixing edge reconciliation first means monitoring
and NetBox can publish their routes automatically once their branches land; fixing
the socket proxy means NetBox gets runtime data immediately after a rebuild.
Together they form a natural atomic state worth a baseline promotion.

## What Already Exists

| Artifact | Location | State |
|---|---|---|
| `docker_socket_proxy` role | `terraform/lxc/ansible/roles/docker_socket_proxy/` | Complete. Proven on disposable LXC and monitoring-stack canary. |
| Role wired into playbooks | deploy-{harbor,proxy,authentik,portainer,monitoring,netbox}-stack.yml | Present but guarded by `enable_docker_socket_proxy: false`. |
| Disposable proof stack | `terraform/lxc/stacks/docker-socket-proxy-test/` | In `work/socket-proxy-metadata-review`. Cherry-pick into work branch. |
| `reconcile-edge.py --stacks-dir` | `terraform/lxc/reconcile-edge.py` | Already implemented. Discovers `stacks/*/edge.yaml` automatically. |
| `edge.yaml` manifests | `stacks/{authentik,harbor,monitoring,netbox,portainer,proxy}-stack/edge.yaml` | All six present on `baseline/teardown-validated`. |
| CoreDNS zone pre-generation | `provision.sh` line ~383 | Already runs before dns-stack deploy. |

## Promotion Target

`baseline/teardown-validated`

The promotion gate is a full teardown + infrastructure redeploy cycle proving:

- Socket proxy is up and responding on harbor, proxy, authentik, and portainer
  after a fresh deploy, without any manual steps.
- All browser-facing services have their Traefik routes, DNS records, and
  Authentik OIDC providers published automatically by provision.sh.

## Branch

Cut a `work/*` branch from `baseline/teardown-validated`. Do not develop
directly on the promotion target.

## Downstream

Once this baseline is promoted:

- `task/monitoring-stack-phase1` rebases onto the new baseline and merges to
  `baseline/teardown-validated`. The monitoring `edge.yaml` already exists; provision.sh will
  include it in the holistic reconciliation pass automatically.
- `task/netbox-infra-knowledge-progress` similarly: the NetBox `edge.yaml`
  already exists; socket proxy enablement for netbox-stack is added in that
  branch.

## Files

- [plan.md](plan.md) — task sequence with scope, inputs, outputs, and
  validation criteria.

# Wazuh Stack

## Status

**Planning complete, 2026-08-29. Not yet scaffolded/deployed.** See
`plan.md` for the full design. This is the "Wazuh gets its own setup
work first" phase that `docs/threat-vuln-platform/plan.md` explicitly
deferred on 2026-08-18 — that plan's `*-events` ingestion design (a
later, filtered sync from Wazuh into `opensearch-stack`) still applies
once this stack is live, but is separate, later work, not part of this
plan.

## What this is

A standalone `wazuh-stack` LXC running Wazuh's official all-in-one
single-node deployment (manager + indexer + dashboard, three Docker
containers) in `infra_seg`, fronted by Traefik with real Authentik OIDC
login on the dashboard — same shape as `opensearch-stack`'s Dashboards
route. Scope for this pass is the server only: no agents enrolled yet,
no telemetry flowing, no ingestion into `opensearch-stack`. That's
deliberate — see plan.md's "Phase scope" for the operator decision.

## What's built so far

- `docs/wazuh-stack/plan.md` — the design, with real facts (zone/IP/
  vmid, verified upstream image/port/ulimit facts, the OIDC config
  pattern reused from `opensearch-stack`)
- Four resolved step packets in plan.md, ready for local-model execution
  under `docs/agent-design/step-packet-schema.md`'s process

## What's not built yet

- `terraform/lxc/stacks/wazuh-stack/` (any files)
- The Ansible playbook (`deploy-wazuh-stack`) — deliberately **not**
  reduced to a step packet this pass; it needs its own research pass
  (cert-generation task, default-password rotation, heap sizing, OIDC
  config verification against Wazuh's actual dashboard config schema).
  See plan.md's "Not yet resolved" section.
- New SOPS secrets, new `.env` var, the MikroTik `edge_seg → infra_seg`
  rule for the dashboard route
- Everything from `docs/threat-vuln-platform/plan.md`'s `*-events`
  family (Wazuh → `opensearch-stack` filtered sync) — still future work,
  gated on this stack actually running with real agents first

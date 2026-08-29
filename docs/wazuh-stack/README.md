# Wazuh Stack

## Status

**LIVE in production on `pve`, 2026-08-29.** Manager + indexer +
dashboard all up and healthy at vmid `40015` (`192.168.40.15`,
`infra_seg`). Real Authentik OIDC login confirmed working end-to-end:
`https://wazuh.lab.gibbsgreatly.xyz` resolves via Technitium, routes
through Traefik, and redirects into the dashboard's own OIDC handshake
(`/auth/openid/captureUrlFragment`) toward Authentik — the same
signature every other OIDC-fronted stack here produces. This is the
"Wazuh gets its own setup work first" phase that
`docs/threat-vuln-platform/plan.md` explicitly deferred on 2026-08-18 —
that plan's `*-events` ingestion design (a later, filtered sync from
Wazuh into `opensearch-stack`) still applies now that this stack is
live, but is separate, not-yet-started work.

Deployed directly to `pve` (operator decision, skipping the normal
`pve-test-vm`-first validation tier) — took 7 real playbook-fixing
iterations to get right, each found live against production, not
guessed in advance, plus 3 more found via actual browser login testing
after the initial "done": a missing Authentik `redirect_uris`/
`grant_types` registration, and a platform-wide Traefik ACME reliability
bug (DNS-01 propagation checks against public recursive resolvers
instead of the zone's own authoritative NS — see git history on
`feat/wazuh-stack` for the full list). No agents enrolled yet — scope
for this pass was server-only, per the operator's own decision.

## What this is

A standalone `wazuh-stack` LXC running Wazuh's official all-in-one
single-node deployment (manager + indexer + dashboard, three Docker
containers) in `infra_seg`, fronted by Traefik with real Authentik OIDC
login on the dashboard — same shape as `opensearch-stack`'s Dashboards
route. Scope for this pass is the server only: no agents enrolled yet,
no telemetry flowing, no ingestion into `opensearch-stack`. That's
deliberate — see plan.md's "Phase scope" for the operator decision.

## What's built and live

- `terraform/lxc/stacks/wazuh-stack/` — all 5 files (`STACK_CONTRACT.md`,
  `stack.yaml`, `terragrunt.hcl` ×2 for both `pve` and `pve-test-vm`,
  `edge.yaml`)
- `terraform/lxc/ansible/playbooks/deploy-wazuh-stack.yml` +
  `terraform/lxc/ansible/files/wazuh-stack/add_openid_auth_domain.py` —
  the full deploy playbook, fixed forward through 7 real live bugs
- New SOPS secrets (`WAZUH_INDEXER_ADMIN_PASSWORD`, `WAZUH_API_PASSWORD`,
  `WAZUH_OIDC_CLIENT_SECRET`), new `.env` var (`LAB_IP_WAZUH`)
- `discover-authentik-edge.py`'s OIDC registry — `wazuh-stack`'s
  dashboard route registered so its Authentik application/provider
  actually get created by the reconciler
- The LXC itself: manager, indexer, dashboard containers all up and
  passing health checks on `pve` (vmid `40015`)
- Full edge activation: Authentik application/provider created,
  Traefik route published and live, Technitium DNS record live —
  `https://wazuh.lab.gibbsgreatly.xyz` confirmed working end-to-end
- **No MikroTik rule was needed** — confirmed live by reading the
  router's actual ruleset: `infra_seg`/`edge_seg` have no default-deny,
  so this was never a real blocker (see plan.md)

## What's not built yet

- Any Wazuh agent enrollment — deliberately out of scope for this pass
  (operator decision)
- Everything from `docs/threat-vuln-platform/plan.md`'s `*-events`
  family (Wazuh → `opensearch-stack` filtered sync) — still future work,
  gated on this stack actually running with real agents first
- Wazuh's own default `kibanaserver` password (left at its vendor demo
  value, matching `opensearch-stack`'s precedent — internal-only
  service credential, never exposed)
- `monitoring-stack` scrape config doesn't include `wazuh-stack` — but
  neither does it include `opensearch-stack`/`greenbone-stack`/
  `secpipe-stack`/`mcp-utility-stack`; this is a standing, pre-existing
  platform gap, not something introduced here (see chat history for the
  full audit against Traefik/DNS/Authentik/Harbor/apt-cacher/Graylog)

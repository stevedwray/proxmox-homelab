# OpenSearch Stack

## Status

**Live in production on `pve`.** Replaced `elasticsearch-stack` (see
`docs/elasticsearch-stack/README.md`, now historical) because real
Authentik SSO login requires a paid Elastic Platinum+ subscription for
SAML/OIDC — OpenSearch's security plugin bundles SAML/OIDC free.

- LXC: vmid `40014`, `192.168.40.14`, `infra_seg` zone
- OpenSearch `2.19.1` + OpenSearch Dashboards `2.19.1`, Docker Compose
- Real Authentik OIDC login into Dashboards — verified live end-to-end by
  the operator in a browser: `https://dashboards.lab.gibbsgreatly.xyz/` →
  Authentik login → back into Dashboards already authenticated, no second
  password prompt
- HTTP-layer TLS kept **on** (OpenSearch's own demo cert) — deliberate
  deviation from the elasticsearch-stack build, which disabled it.
  OpenSearch has an open bug where disabling HTTP TLS stops demo certs
  from generating at all. Internal callers (Dashboards → OpenSearch, any
  future ingestion scripts) skip cert verification instead of fighting it.

## What's built so far

Stack scaffold + deploy playbook (`terraform/lxc/stacks/opensearch-stack/`,
`terraform/lxc/ansible/playbooks/deploy-opensearch-stack.yml`), real OIDC
wiring reusing this repo's existing pattern (`edge.yaml`'s
`auth.mode: oidc`, the same mechanism already used by Harbor, Grafana,
Portainer, Technitium, and OpenWebUI — OpenSearch Dashboards is the 6th
consumer). No findings ingestion yet — that's separate work, tracked
below.

## Not yet built

- **Harbor findings ingestion.** A role (`es_findings_ingest`) was built
  against Elasticsearch's API shape before the OpenSearch pivot and needs
  reworking for OpenSearch's `_plugins/_security/api/*` paths before it's
  usable. Not deployed anywhere yet.
- **GVM/Greenbone findings ingestion.**
- **Grafana OpenSearch datasource.**
- **Correlation/transform layer** (OpenSearch's Transform API,
  `_plugins/_transform`, is not a drop-in for Elasticsearch's `_transform`
  — different path, likely different body shape; not yet used by anything).

The finding-shape data model, ingest/normalization/dedup gotchas, and GVM
scan gotchas captured in `docs/elasticsearch-stack/README.md` are still
accurate and apply here — that document is kept as historical reference
for exactly that reason, not because the OpenSearch build reused its
plan verbatim.

## Key facts (verified live, not assumed)

- Elastic SAML/OIDC realm requires **Platinum or Enterprise** (confirmed
  live: the old cluster reported `"type": "basic"` license).
- `OPENSEARCH_INITIAL_ADMIN_PASSWORD` is mandatory since OpenSearch 2.12+
  and enforces upper+lower+digit+special-char complexity.
- Bind-mounted config files into the official OpenSearch/Dashboards images
  must be owned by uid/gid `1000` (their own non-root user, confirmed via
  `docker inspect --format '{{.Config.User}}'`) — root-owned files cause a
  silent `EACCES` crash-loop.
- This repo's Authentik-edge reconciler (`discover-authentik-edge.py` /
  `reconcile-authentik-edge.py`) has a hand-maintained, per-`(stack,
  route)` dispatch table for both OIDC redirect URIs and grant types —
  adding a new OIDC-mode stack requires an explicit entry in both, or the
  Authentik provider gets created with an empty/wrong value that fails
  silently until a real login is attempted.
- Publishing an edge-manifest change (Traefik route, DNS record) via
  `provision.sh --stack proxy-stack` / `--stack technitium-stack` only
  **republishes already-generated output** — it does not regenerate that
  output itself. Regenerating requires the standalone
  `render-edge-traefik.py` / `render-edge-coredns.py` (or
  `render-edge-technitium.py`, which `provision.sh --stack
  technitium-stack` *does* call automatically) scripts.
- Technitium's parity-zone Ansible playbook only **adds** DNS records
  declared by current EdgeManifests — it never prunes A records for
  routes that were removed. Removing a DNS record for a decommissioned
  stack requires a direct API call
  (`/api/zones/records/delete`), not just re-running provision.sh.
- The `infra_seg`/`tvinfra` SDN zone/vnet is shared by Harbor, apt-cacher,
  NetBox, and this stack. Destroying one stack's LXC on a shared SDN zone
  requires an explicit `NETWORK_SDN_ALLOW_DESTROY_OVERRIDE=true` env var;
  the destroy playbook itself only actually removes the zone/vnet if a
  live grep of `/etc/pve/lxc/*.conf` on the real node finds zero other
  guests still bridged to it — verified this live before setting the
  override during elasticsearch-stack's decommission.

## Decommissioning elasticsearch-stack (done 2026-08-17)

For reference, the full sequence used to safely remove the old stack
without affecting shared infrastructure: remove `edge.yaml` → regenerate
Traefik/CoreDNS output via the standalone render scripts → republish via
`provision.sh --stack proxy-stack`/`--stack technitium-stack` → manually
delete the stale Technitium A record (add-only playbook, see above) →
delete the Authentik application + provider directly via the API (no
tool in this repo automates Authentik object deletion) → delete the two
MikroTik cross-zone firewall rules → `terragrunt destroy` (with the SDN
override, verified safe first) → remove tracked Terraform/Ansible files →
clean `.env`/SOPS/`.claude/settings.local.json` → this doc.

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
consumer).

- **Harbor findings ingestion — live.** `es_findings_ingest` role reworked
  from Elasticsearch's API shape to OpenSearch's `_plugins/_security/api/*`
  paths, deployed on `harbor-stack`. 10,457+ real findings indexed into
  `harbor-findings`. Dashboard:
  `https://dashboards.lab.gibbsgreatly.xyz/app/dashboards#/view/harbor-vulnerability-findings`
  (critical count, by-severity, by-project-and-severity, fixable-now
  panels). `pentagi` Harbor project is a known gap (403, not investigated
  further).
- **GVM/Greenbone findings ingestion — live.** New `gvm_findings_ingest`
  role (mirrors `es_findings_ingest`'s shape) plus a new `/findings/all`
  endpoint on `gvm-bridge` (reuses its existing authenticated GMP session
  — no second socket connection). Deployed on `greenbone-stack`, indexing
  into `gvm-findings` on a daily timer. `threat=Log` (~80-95% of raw
  volume) dropped before indexing — pure noise, established design
  decision from the elasticsearch-stack era. Dashboard:
  `https://dashboards.lab.gibbsgreatly.xyz/app/dashboards#/view/gvm-vulnerability-findings`
  (critical count, by-severity, by-host-and-severity, critical/high-by-name
  panels). Both indices share the `es-findings-sync-state` state index and
  a common `es_findings_writer` OpenSearch role — see
  `docs/elasticsearch-stack/README.md` section 3 for the schema-compat
  rationale (future triage/correlation tools should be able to treat both
  the same way).

## Not yet built

- **Grafana OpenSearch datasource.**
- **Correlation/transform layer** (OpenSearch's Transform API,
  `_plugins/_transform`, is not a drop-in for Elasticsearch's `_transform`
  — different path, likely different body shape; not yet used by anything).
- **Alerting/automation** on either findings index (see
  `project_harbor_alerting_automation_plan` in memory — findings-only,
  not started).

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
- **Dashboards multitenancy trap, confirmed live building both findings
  dashboards.** The `securitytenant` header/param is NOT honored for HTTP
  Basic Auth requests to the saved-objects API — such requests always
  land in the caller's own PRIVATE tenant index
  (`.kibana_<hash>_<user>_1`), never the Global tenant the browser UI
  actually reads from, regardless of any header value sent. Working
  technique: create objects normally via the API (validates schema),
  fetch each one's raw `_source` from the private-tenant index, `PUT` it
  directly into `.kibana_1` (Global), `_refresh`, then delete the stray
  private-tenant copies.
- **Don't set `timeFieldName` on an index pattern for asset-inventory
  data** (findings/vulnerabilities, not time-series logs) — it makes
  Dashboards apply an implicit global time-range filter (e.g. "Last 15
  minutes") to every panel using that pattern, which silently hides
  nearly all real documents. Omit the field entirely.
- **Size dashboard panels generously from the start.** Small `h` grid
  values on a table panel make correctly-aggregating data look "broken"
  (only the first page of rows visible) even when the underlying
  aggregation is fine — this is a display/pagination issue, not a data
  bug. Both findings dashboards use `h: 16` (metric/small tables) or
  `h: 32` (multi-row tables).

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

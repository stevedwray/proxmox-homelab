# Wazuh Stack — Plan

## Goal

Stand up Wazuh (open-source SIEM/host-based intrusion detection) as its
own `wazuh-stack` LXC, live and logged into via real Authentik SSO. This
is server-only: no agents enrolled, no telemetry, no ingestion into
`opensearch-stack`. Those are separate, later phases (see "Explicitly
out of scope" below).

This is the deferred piece `docs/threat-vuln-platform/plan.md` called
out on 2026-08-18: "Wazuh, Security Onion, and T-Pot ingestion are
explicitly deferred... those source systems need their own setup work
first." This plan is that setup work, for Wazuh only.

## Decisions made (operator, 2026-08-29)

| Question | Decision |
|---|---|
| SDN zone | `infra_seg` (VLAN 40) — joins `opensearch-stack`/`harbor-stack`/`netbox-stack`/`apt-cacher-stack`. Wazuh's indexer is itself an OpenSearch fork, so this matches the "security data store" precedent over `mgmt_seg` (Graylog/monitoring) or `pentest_seg` (Greenbone/PentAGI). |
| Phase scope | Server only. No agent enrollment, no cross-zone agent-reporting rules, this pass. |
| Dashboard auth | Real Authentik OIDC in this same pass — not deferred the way Graylog/Greenbone/OpenSearch Dashboards each deferred SSO to their own later stage. |

## Explicitly out of scope (this plan)

- Enrolling any Wazuh agent, anywhere
- The `wazuh-events` index family / `wazuh_findings_ingest` sync job into
  `opensearch-stack` (`docs/threat-vuln-platform/plan.md`'s design —
  unchanged, still gated on this stack running with real agent data)
- Security Onion, T-Pot
- Any MikroTik rule for agent traffic (1514/1515/514) — only the
  dashboard's own Traefik route needs a new rule this pass

## Verified upstream facts (researched 2026-08-29, not assumed)

**Correction from the first pass of this plan**: an earlier fetch
against the `wazuh-docker` GitHub repo's `6.0.0` ref returned content
that turned out to be wrong — there is no `6.0.0` tag in that repo at
all (checked via the GitHub tags API). The real current stable release
as of 2026-08-29 is **`4.14.7`** (`5.0.0` is beta, not used here). All
facts below are re-verified against the actual `v4.14.7` tag.

Wazuh's official `wazuh-docker` single-node deployment, current stable
tag `v4.14.7`:

| Component | Image | Ports | Ulimits |
|---|---|---|---|
| `wazuh.manager` | `wazuh/wazuh-manager:4.14.7` | 1514/tcp (agent events), 1515/tcp (agent enrollment), 514/udp (syslog), 55000/tcp (Wazuh API) | `memlock: -1:-1` (unlimited), `nofile: 655360` |
| `wazuh.indexer` | `wazuh/wazuh-indexer:4.14.7` | 9200/tcp | `memlock: -1:-1` (unlimited), `nofile: 65536` |
| `wazuh.dashboard` | `wazuh/wazuh-dashboard:4.14.7` | container listens on 5601, upstream compose publishes it as host `443` | — |

**Real gotcha, high-confidence carry-over**: upstream's compose sets
`memlock: -1:-1` on both `wazuh.manager` and `wazuh.indexer`. This repo
already hit and fixed the exact same failure mode for
`elasticsearch-stack`/`opensearch-stack` — nested LXC rejects an
unlimited memlock ulimit (`bootstrap.memory_lock`/`ulimits.memlock`
rlimit rejection). Both `memlock` blocks must be stripped from the
compose, same as `deploy-opensearch-stack.yml` already does. Do not
carry them over from upstream's file unmodified.

**`vm.max_map_count`** (the indexer's other classic OpenSearch-family
startup requirement): already verified live on the `pve` host at
`262144` (checked 2026-08-17 for `elasticsearch-stack`, this is a
host-kernel-wide sysctl, not per-container — still satisfied). Re-verify
on `pve-test-vm` before deploying there; don't assume it's inherited.

**No new Harbor project needed.** `wazuh/wazuh-manager`,
`wazuh/wazuh-indexer`, and `wazuh/wazuh-dashboard` are all published on
Docker Hub — they pull through the existing `dockerhub` proxy-cache
project, same as `opensearch-stack`'s `opensearchproject/*` images.
Unlike Greenbone (its own non-Docker-Hub registry), no
`harbor_postconfigure` change is needed.

**Certificate generation is a real pre-step, not a compose detail.**
Upstream ships a separate `generate-indexer-certs.yml` compose file run
once (`docker compose -f generate-indexer-certs.yml run --rm generator`)
that writes node/admin TLS certs into `config/wazuh_indexer_ssl_certs/`
before the main stack's first boot. The playbook needs an explicit task
for this, run before the main `docker-compose.yml` first `up`, not
folded into it as a service.

**OIDC is the dashboard's job, not the indexer's**, and Wazuh's
dashboard is a fork of OpenSearch Dashboards using the same underlying
security-plugin config surface. Confirmed via Wazuh's own community
docs (Keycloak-as-OIDC walkthroughs): the dashboard performs the
redirect/token exchange; role mapping and the auth-domain config live in
the security plugin's config, same architecture `opensearch-stack`
already solved. The starting point for that config (verify the exact
key path against the live container — Wazuh may not track OpenSearch's
key names 1:1 release-to-release) is `opensearch-stack`'s own solved
pattern, transcribed:

```yaml
opensearch_security.auth.type: "openid"
opensearch_security.openid.connect_url: "https://{{ authentik_fqdn }}/application/o/edge-wazuh-stack-dashboard/.well-known/openid-configuration"
opensearch_security.openid.client_id: "{{ wazuh_oidc_client_id }}"
opensearch_security.openid.client_secret: "{{ wazuh_oidc_client_secret }}"
opensearch_security.openid.scope: "openid profile email"
opensearch_security.openid.base_redirect_url: "{{ wazuh_dashboard_public_url }}"
```

written into whatever Wazuh's dashboard config file is (verify against
the live `wazuh/wazuh-dashboard:6.0.0` image — likely still named
`opensearch_dashboards.yml` given the fork lineage, but confirm rather
than assume before templating it).

**Default demo credentials must be rotated, not just left.** Wazuh's
indexer ships `internal_users.yml` with a known demo password for
`admin`/`kibanaserver`, and the manager/dashboard/API also share a
default `wazuh`/`wazuh-wui` service-account password — all of this is
public and must not run in production unchanged. The exact mechanism
(Wazuh ships a `wazuh-passwords-tool`/hash-regeneration helper) needs
confirming against the live `6.0.0` image before the playbook step can
be written as literal content — flagged in "Not yet resolved" below
rather than guessed at.

## Facts resolved for this deployment

| Field | Value |
|---|---|
| Hostname | `wazuh-stack` |
| Zone | `infra_seg` (VLAN 40) |
| VMID | `40015` (next free — `40010`–`40012`/`40014` in use; `40013` was `elasticsearch-stack`'s, decommissioned but not confirmed destroyed at the hypervisor level, so skipped rather than reused) |
| IP | `192.168.40.15/24` |
| Gateway | `192.168.40.1` (`LAB_GW_INFRA`) |
| DNS | `192.168.40.1` (matches `opensearch-stack`'s own choice — the zone gateway, not Technitium directly) |
| Cores | 4 (up from `opensearch-stack`'s 2 — three concurrent JVM/Node processes: indexer, dashboard, plus the manager's own analysis engine) |
| Memory | 8192 MB (indexer + manager + dashboard concurrently; matches `pentagi-stack`'s size class, well above `opensearch-stack`'s 6144 MB single-JVM footprint) |
| Swap | 2048 MB |
| Rootfs | 16 GB, `platform-zfs` |
| `docker_storage` | 20 GB |
| `extra_mount` (indexer data) | 50 GB, `durable-zfs`, grow-only — smaller initial footprint than `opensearch-stack`'s 150G since there is no agent data yet in this phase |
| Template | `debian-13.1-2-docker-template.tar.gz` |
| `ansible_playbook` | `deploy-wazuh-stack` |
| `deployment_tier` | `platform` |
| `portainer_agent` | `false` |
| Tags | `wazuh`, `siem`, `security`, `docker` |
| `depends_on` | `harbor-stack`, `apt-cacher-stack`, `authentik-stack` (new — needed this pass for OIDC, unlike `opensearch-stack` which added it only at its own later Stage 4) |
| Provides | `wazuh-dashboard-http` (5601/tcp), `wazuh-manager-agent` (1514/tcp), `wazuh-manager-enrollment` (1515/tcp), `wazuh-api` (55000/tcp) — the last three are declared because the manager binds them regardless of phase scope, not because anything consumes them yet |

New `.env` var: `LAB_IP_WAZUH='192.168.40.15'`.

New SOPS secrets (`terraform/secrets.common.enc.yaml`):

| Secret | Purpose |
|---|---|
| `WAZUH_INDEXER_ADMIN_PASSWORD` | Replaces the indexer's demo `admin` password |
| `WAZUH_API_PASSWORD` | Replaces the manager/dashboard's shared `wazuh-wui` API service-account password |
| `WAZUH_OIDC_CLIENT_SECRET` | Authentik OAuth2 client secret for the dashboard's OIDC login, same pattern as `OPENSEARCH_OIDC_CLIENT_SECRET` |

New MikroTik rule: `edge_seg → infra_seg tcp/5601` for this stack's own
IP (`192.168.40.15`) — Traefik → dashboard, mirroring whatever rule
already lets Traefik reach `opensearch-stack`'s dashboard on the same
port at a different IP. Confirm at execution time whether that existing
rule is zone-wide or scoped to `192.168.40.14` specifically; add a
`192.168.40.15` entry if it's IP-scoped. This is an **additive-only**
firewall change under CLAUDE.md's Validation Tiers table — apply, then
run `provision.sh --stack` against 1–2 existing `infra_seg` stacks to
confirm no regression; a full teardown is not owed for this by itself.

## Step packets

The four files below are entirely repo-schema-bound (no competing public
pattern to fight) — literal content, following
`docs/agent-design/step-packet-schema.md`'s "give literal content, not a
file to model on" rule.

### wazuh-01-stack-contract

```yaml
id: wazuh-01-stack-contract
title: Author wazuh-stack's STACK_CONTRACT.md
depends_on: []

change: >
  Create terraform/lxc/stacks/wazuh-stack/STACK_CONTRACT.md, following
  terraform/lxc/stacks/opensearch-stack/STACK_CONTRACT.md's exact section
  structure (Purpose / Network / Inputs / Provides / Dependencies /
  Persistent State / What Must Not Be Edited Casually / Playbook /
  Implementation Files), populated with the facts below -- transcribe
  the tables verbatim, do not invent additional sections.

scope:
  allowed_paths:
    - terraform/lxc/stacks/wazuh-stack/STACK_CONTRACT.md
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any provision.sh / terragrunt apply run -- authoring only in this step"

gates:
  - id: file-exists
    cmd: "test -f terraform/lxc/stacks/wazuh-stack/STACK_CONTRACT.md"
    expect: "exit 0"
    critical: true
```

**Purpose section content**: "Wazuh (open-source SIEM/host intrusion
detection) — manager + indexer + dashboard, Wazuh's official single-node
Docker deployment. Server-only in this pass: no agents enrolled, no
telemetry, no ingestion into `opensearch-stack`. See
`docs/wazuh-stack/plan.md` for the full design and phase scope. Not a
resurrection of the separate, unrelated `security-stack` LXC (vmid 109,
`192.168.1.11`)."

**Network table**: Zone `infra_seg` (VLAN 40), IP `192.168.40.15/24`,
Gateway `192.168.40.1`, VMID `40015`.

**Inputs table**: `LAB_IP_HARBOR` (registry, `dockerhub` proxy-cache
project — no dedicated Wazuh project needed), `LAB_IP_APT_CACHER` (apt
proxy), `WAZUH_INDEXER_ADMIN_PASSWORD` (SOPS, new), `WAZUH_API_PASSWORD`
(SOPS, new), `WAZUH_OIDC_CLIENT_SECRET` (SOPS, new), `LAB_IP_AUTHENTIK`
(env, existing), `LAB_IP_WAZUH` (env, new — this stack's own IP).

**Provides table**: `wazuh-dashboard-http` 5601/tcp (fronted by Traefik
with real OIDC, same as `opensearch-stack`'s Dashboards route);
`wazuh-manager-agent` 1514/tcp, `wazuh-manager-enrollment` 1515/tcp,
`wazuh-api` 55000/tcp (all bound by the manager, none consumed by
anything yet this phase).

**Dependencies table**: `harbor-stack` (image pulls), `apt-cacher-stack`
(apt proxy during provisioning), `authentik-stack` (OIDC client for the
dashboard route).

**What Must Not Be Edited Casually**: note the stripped `memlock: -1:-1`
ulimits (nested-LXC rejects them, same as `opensearch-stack`), the
one-time cert-generation pre-step, and that `WAZUH_INDEXER_ADMIN_PASSWORD`/
`WAZUH_API_PASSWORD` are only consulted on first bootstrap (rotating the
SOPS secret later does not change the live password without Wazuh's own
password-rotation tool).

### wazuh-02-stack-yaml

```yaml
id: wazuh-02-stack-yaml
title: Author wazuh-stack's stack.yaml
depends_on: [wazuh-01-stack-contract]

change: >
  Create terraform/lxc/stacks/wazuh-stack/stack.yaml, transcribing the
  exact field structure of terraform/lxc/stacks/opensearch-stack/stack.yaml
  (including its extra_mount block shape) with the literal values given
  below. Do not add fields opensearch-stack's file doesn't have, and do
  not omit any of its required fields.

scope:
  allowed_paths:
    - terraform/lxc/stacks/wazuh-stack/stack.yaml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any provision.sh / terragrunt apply run -- authoring only in this step"

gates:
  - id: yaml-parses
    cmd: "python3 -c \"import yaml,sys; yaml.safe_load(open('terraform/lxc/stacks/wazuh-stack/stack.yaml'))\""
    expect: "exit 0"
    critical: true
```

Literal content to transcribe:

```yaml
hostname: wazuh-stack
ip_address: "192.168.40.15/24"
gateway: "192.168.40.1"
dns_server: "192.168.40.1"
network:
  zone: infra_seg
vmid: 40015
cores: 4
memory: 8192
swap: 2048
rootfs_size: 16
storage_profile: platform-zfs
docker_storage_size: "20G"
docker_mount:
  logical_name: docker-data
  path: /var/lib/docker
  size: "20G"
  backup_policy: include
  resize_control_plane: operational
  mutation_policy: grow-only
template_name: "debian-13.1-2-docker-template.tar.gz"
tags:
  - wazuh
  - siem
  - security
  - docker
depends_on:
  - harbor-stack
  - apt-cacher-stack
  - authentik-stack
provides:
  - service: wazuh-dashboard-http
    port: 5601
    protocol: tcp
  - service: wazuh-manager-agent
    port: 1514
    protocol: tcp
  - service: wazuh-manager-enrollment
    port: 1515
    protocol: tcp
  - service: wazuh-api
    port: 55000
    protocol: tcp

extra_mount_path: "/var/lib/wazuh-indexer-data"
extra_mount_size: "50G"
extra_mount_profile: durable-zfs
extra_mount:
  logical_name: wazuh-indexer-data
  path: /var/lib/wazuh-indexer-data
  size: "50G"
  profile: durable-zfs
  backup_policy: include
  resize_control_plane: operational
  mutation_policy: grow-only

registry_host: "{{ lookup('env', 'LAB_IP_HARBOR') | mandatory('LAB_IP_HARBOR env var is required') }}"
apt_cacher_host: "${lab_ip_apt_cacher}"

ansible_playbook: "deploy-wazuh-stack"
deployment_tier: platform
portainer_agent: false
```

### wazuh-03-terragrunt

```yaml
id: wazuh-03-terragrunt
title: Author wazuh-stack's terragrunt entrypoints
depends_on: [wazuh-02-stack-yaml]

change: >
  Create terraform/lxc/stacks/wazuh-stack/terragrunt.hcl and
  terraform/lxc/environments/pve-test-vm/wazuh-stack/terragrunt.hcl,
  each an exact copy of opensearch-stack's equivalent file with no
  content changes at all (both are pure path-relative boilerplate that
  resolves stack_name from its own directory name).

scope:
  allowed_paths:
    - terraform/lxc/stacks/wazuh-stack/terragrunt.hcl
    - terraform/lxc/environments/pve-test-vm/wazuh-stack/terragrunt.hcl
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any terragrunt plan/apply run -- authoring only in this step"

gates:
  - id: files-exist
    cmd: "test -f terraform/lxc/stacks/wazuh-stack/terragrunt.hcl && test -f terraform/lxc/environments/pve-test-vm/wazuh-stack/terragrunt.hcl"
    expect: "exit 0"
    critical: true
```

Literal content (identical for both files):

```hcl
include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "${get_repo_root()}/terraform/lxc//"
}

inputs = {
  stack_name      = basename(get_terragrunt_dir())
  stack_yaml_path = "${get_repo_root()}/terraform/lxc/stacks/${basename(get_terragrunt_dir())}/stack.yaml"
  generated_dir   = get_terragrunt_dir()
}
```

Only `pve-test-vm`'s entrypoint is written this step, matching the
branch model (`feat/*` validates on `pve-test-vm` before promotion) —
the `pve` production entrypoint is added later, at promotion time, same
as every other stack's history in this repo.

### wazuh-04-edge-manifest

```yaml
id: wazuh-04-edge-manifest
title: Author wazuh-stack's Traefik/Authentik edge manifest
depends_on: [wazuh-02-stack-yaml]

change: >
  Create terraform/lxc/stacks/wazuh-stack/edge.yaml, transcribing
  terraform/lxc/stacks/opensearch-stack/edge.yaml's exact EdgeManifest
  structure (apiVersion/kind/metadata/spec.routes shape, auth.mode: oidc)
  with the literal values below substituted for this stack.

scope:
  allowed_paths:
    - terraform/lxc/stacks/wazuh-stack/edge.yaml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any provision.sh / terragrunt apply run -- authoring only in this step"

gates:
  - id: yaml-parses
    cmd: "python3 -c \"import yaml,sys; yaml.safe_load(open('terraform/lxc/stacks/wazuh-stack/edge.yaml'))\""
    expect: "exit 0"
    critical: true
```

Literal content to transcribe:

```yaml
apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
kind: EdgeManifest
metadata:
  name: wazuh-edge
  stack: wazuh-stack
  annotations:
    repo.auth.oidc.client_id_env: WAZUH_OIDC_CLIENT_ID
    repo.auth.oidc.client_secret_env: WAZUH_OIDC_CLIENT_SECRET
spec:
  routes:
    - name: dashboard
      host: wazuh.${LAB_DOMAIN}
      backend:
        type: url
        url: http://${LAB_IP_WAZUH}:5601
      dns:
        enabled: true
        target: ${LAB_IP_PROXY}
        ttl: 5m
      tls:
        resolver: letsencrypt
      auth:
        mode: oidc
```

## Resolved in a second pass (2026-08-29)

The four items below were flagged in this plan's first pass as needing
live-container verification before becoming literal content. All four
are now resolved — `deploy-wazuh-stack.yml` and its helper script are
written and committed:

1. **The playbook itself** — written, following `opensearch-stack`'s
   shape (`lxc_base` + `docker_base` + direct tasks templating compose
   inline). Every vendored config file (`docker-compose.yml`,
   `certs.yml`, `internal_users.yml`, `wazuh.yml`, `wazuh.indexer.yml`,
   `wazuh_manager.conf`) is a literal transcription of the real
   `wazuh-docker` `v4.14.7` tag's own files, fetched and verified during
   this pass — not invented from a generic pattern.
2. **Default-password rotation** — resolved via Wazuh's own documented
   procedure (`documentation.wazuh.com`'s "Changing the default
   password of Wazuh users"): `hash.sh -p <password>` generates a
   plugin-compatible bcrypt hash non-interactively, written into
   `internal_users.yml`'s `admin` entry. `kibanaserver` is deliberately
   left at its vendor demo hash, matching the precedent
   `opensearch-stack` already set for exactly this internal-only
   service credential.
3. **OIDC config** — the dashboard-side hypothesis (direct transcription
   of `opensearch-stack`'s already-solved `opensearch_security.auth.type:
   "openid"` block) is now confirmed correct: Wazuh's own community docs
   put this in the same `opensearch_dashboards.yml` file at the same
   config keys. The indexer-side token-validation half
   (`openid_auth_domain` in the security plugin's `config.yml`) has no
   vendored source to transcribe — the playbook extracts it live from
   the running container instead of guessing its baseline shape, adds
   the domain via `add_openid_auth_domain.py`, and pushes it with
   `securityadmin.sh` (real, documented invocation, not guessed).
4. **A real gotcha found along the way, not previously known**: Wazuh's
   dashboard defaults to `server.ssl.enabled: true` (terminates its own
   TLS with a self-signed cert) — the same
   `reference_traefik_no_insecure_backend_tls` constraint already hit
   elsewhere in this repo (Traefik can't route to a self-signed HTTPS
   backend). Fixed by disabling the dashboard's own TLS so it serves
   plain HTTP on 5601, matching `opensearch-stack`'s dashboard and this
   plan's `edge.yaml`.

## Not yet resolved

1. **The MikroTik `edge_seg → infra_seg tcp/5601` rule** — confirm
   whether the existing rule that lets Traefik reach `opensearch-stack`'s
   dashboard is zone-wide or scoped to `192.168.40.14`, before deciding
   whether a new entry is needed for `192.168.40.15`. This is a real
   network mutation (Validation Tiers: additive-only tier) — not a step
   packet regardless, per this repo's Production Credential Controls and
   the general rule that ambiguous/mutating network changes are operator
   work, not local-model work.
2. **Promotion path** — `scaffold-stack.sh` was not actually used for
   this stack (see below); `provision.sh --stack wazuh-stack` against
   `pve-test-vm`, verifying the dashboard's OIDC login end to end, and
   the eventual `pve` promotion remain, and are plain operator-run
   infrastructure steps, not step packets.
3. **Untested end-to-end** — every fact above is verified against
   Wazuh's own published sources, but this playbook has not yet been
   run against a real host. The usual class of first-run surprises
   (cert-generator image availability through Harbor's `dockerhub`
   proxy-cache, `securityadmin.sh`'s exact exit behavior on this image,
   whether `hash.sh`'s output format matches what was seen in third-party
   write-ups) should be expected and are why `pve-test-vm` validation
   comes before any `stable`/`pve` promotion.

**Note on `scaffold-stack.sh`**: this stack's five files ended up
hand-authored directly rather than through the scaffolder, matching the
precedent `opensearch-stack`/`greenbone-stack` already set — real
complexity (cert generation, password rotation, two-sided OIDC wiring)
exceeded what the generic five-agent scaffolder path is meant for.

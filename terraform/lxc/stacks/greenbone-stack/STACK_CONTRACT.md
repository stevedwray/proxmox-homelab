# greenbone-stack — Stack Contract

## Purpose

Greenbone Community Edition (GVM/OpenVAS) vulnerability scanner. Provides an
authenticated, feed-updated network vulnerability scanning engine (GSA web UI +
GMP API) that can run authorized scans against homelab targets such as
`LAB_TARGET` (Metasploitable 2) and `harness-target`. Deployed as a standalone
scanner in this pass — wiring PentAGI to trigger/query scans via `gvm-tools`/GMP
is explicitly deferred future work, not part of this contract.

## Network

| Field        | Value                     |
|--------------|---------------------------|
| Zone         | `pentest_seg` (VLAN 70)   |
| IP           | `${lab_ip_greenbone}/24`  |
| Gateway      | `${lab_gw_pentest}`       |
| VMID         | 70011                     |

Deployed on both `pve-test-vm` (`192.168.70.111`, validation — currently
shut down, see README.md) and `pve` (`192.168.70.11`, production, live).
`pve` and `pve-test-vm` share the same physical MikroTik and VLAN 70
subnet, so network/firewall changes made for one apply to both.

Joins pentagi-stack's existing `pentest_seg` zone rather than a new dedicated
zone — reuses its containment policy (internet egress for feed sync and image
pulls, reach to `LAB_TARGET`/`harness-target`, explicit deny-by-default
elsewhere) with no new MikroTik zone required. PentAGI can reach this stack's
GMP socket-backed API in-zone with no additional cross-zone firewall rule.

## Inputs

| Input                       | Source                              | Notes |
|------------------------------|-------------------------------------|-------|
| `LAB_IP_HARBOR`              | env var (mandatory)                 | Registry host for proxying the ~15 upstream Greenbone images |
| `LAB_IP_APT_CACHER`          | `apt_cacher_host` (stack.yaml)       | apt proxy during provisioning |
| `GREENBONE_ADMIN_PASSWORD`   | SOPS (`terraform/secrets.common.enc.yaml`), mandatory | Initial `gvmd` admin password, set on first deploy |
| `LAB_IP_AUTHENTIK`           | env var (mandatory)                 | Authentik's LDAP outpost host (`:3389`), for per-user LDAP login |

## Provides

| Service     | Port | Protocol | Notes |
|-------------|------|----------|-------|
| `gvm-https` | 443  | tcp      | GSA UI over nginx's self-signed TLS — in-zone/direct access only, not the Traefik route |
| `gvm-http`  | 8080 | tcp      | Custom plain-HTTP nginx server block added by `deploy-greenbone-stack.yml` (not part of upstream's compose) — this is what Traefik's `edge.yaml` route targets. Port 9392 exists but is NOT usable for this: upstream's own generated nginx config redirects it straight to 443/self-signed-TLS (see "What Must Not Be Edited Casually") |

## Dependencies

| Stack             | Why |
|--------------------|-----|
| `harbor-stack`     | Docker image pulls (Greenbone's own registry proxied through a new `greenbone` Harbor proxy-cache project) |
| `apt-cacher-stack` | apt proxy during LXC provisioning |
| `authentik-stack`  | LDAP outpost (`ghcr.io/goauthentik/ldap`, port 3389/6636) — `gvmd` binds against it directly for per-user login (e.g. `steve`), reusing the same outpost `graylog-stack` already uses |

Cross-zone access needed: `edge_seg → pentest_seg tcp/8080` (Traefik → GSA UI
over the custom plain-HTTP nginx block, mirrors the existing
`edge_seg → pentest_seg tcp/8443` PentAGI rule); `pentest_seg → mgmt_seg
tcp/3389,6636` (this stack → Authentik's LDAP outpost — a genuinely new
capability for `pentest_seg`, applied live on the MikroTik 2026-08-01, no
prior rule let this zone reach `mgmt_seg` at all). No new egress rule is
needed for feed sync or Harbor image pulls — both are already covered by
`pentest_seg`'s existing internet-egress and
`pentest_seg → 192.168.30.110:80/443` (Harbor via Traefik) policies.

## Persistent State

| Path                        | Storage              | Contents |
|------------------------------|-----------------------|----------|
| Docker named volumes under `/var/lib/docker` | docker mount (20 GiB) | Feed data (VT/SCAP/CERT/notus), PostgreSQL DB, gvmd data, GSA static assets, nginx TLS certs |

Feed data (`vt_data_vol`, `scap_data_vol`, `cert_data_vol`, `notus_data_vol`) is
re-downloadable from Greenbone's community feed servers, but the initial full
sync is large and can take a long time — do not casually wipe these volumes.

## What May Depend on This Stack

Nothing yet. Future PentAGI GMP/`gvm-tools` integration (out of scope for this
pass) would make `pentagi-stack` a consumer of this stack's GMP API.

## What Must Not Be Edited Casually

- **The GSA reports page is broken by a real, upstream `gvmd` bug** — any
  `get_reports` GMP call (list or single-report) crashes `gvmd` with a
  Postgres error (`column "severity_error" does not exist`, an
  unsubstituted macro in one of gvmd's own query templates). Confirmed via
  `docker logs` (aborts immediately after the failed query) and in the GSA
  UI itself. Matches the known upstream bug class in `greenbone/gvmd`
  issue #2273 (fix in progress, not yet in the `:stable` tag this stack
  uses). Do not attempt to hand-patch the Postgres schema/views for this —
  use GMP's `get_results` instead, which takes a different code path and
  works fine. See `docs/greenbone-stack/plan.md` §4.
- **New GVM targets need `alive_tests: Consider Alive` if the target's
  firewall rule doesn't allow ICMP** (e.g. `harness-target`, TCP-only) —
  otherwise GVM's default host-alive check fails silently and the scan
  skips the host entirely, finishing in ~30s with zero results that look
  deceptively like a clean scan rather than a skipped one. Check whether
  `report_hosts` has any rows for the report to tell the difference.
- `ospd-openvas` requires `NET_ADMIN`/`NET_RAW` capabilities and
  `seccomp=unconfined`/`apparmor=unconfined` at the Docker level for packet
  capture and raw-socket scanning — this works under the same nested-Docker
  LXC `nesting` feature that already lets PentAGI's Kali worker containers run
  `nmap`; do not strip these without breaking active scanning.
- nginx's upstream default binds `127.0.0.1:443`/`127.0.0.1:9392` (loopback
  only) — the vendored compose overrides this to the container's routable
  address. This does NOT make 9392 usable for Traefik, though: upstream's
  own generated nginx config (`gvm-config`'s `nginx-config` template)
  hardcodes `listen 9392; return 301 https://...443` regardless of bind
  address — confirmed live. `deploy-greenbone-stack.yml` writes a separate
  `gsad-plain.conf` file straight into `nginx_config_vol`'s host path
  after `gvm-config` runs, adding a genuine plain-HTTP server block on
  port 8080 that mirrors upstream's 443 block's location/proxy_pass logic.
  Do not remove this task or assume 9392 works as a substitute.
- The `greenbone` Harbor proxy-cache project (registry
  `https://registry.community.greenbone.net`) is declared in
  `terraform/lxc/ansible/roles/harbor_postconfigure/defaults/main.yml` — a
  shared platform file. Changes there affect Harbor's setup for every stack
  that references the `greenbone` project prefix.
- LDAP auth (`method:ldap_connect`) is a *global* gvmd setting, not
  per-user — once enabled, gvmd tries LDAP bind for any username,
  including `admin`. Disabling it or changing `authdn` affects every
  local user's login, not just `steve`.
- The `cacert` file (`authentik-ldap-ca.pem`, fetched live from the
  outpost and bind-mounted into `gvmd`) is what actually lets `gvmd`
  trust the outpost's self-signed cert — `LDAPTLS_REQCERT=never` alone is
  NOT sufficient (confirmed live: gvm-libs ignores it, sets its own TLS
  options in code). Do not remove the cert-fetch task assuming the env
  var covers it.
- LDAP login is confirmed working on both `pve-test-vm` and `pve`, but hit
  transient bind-response flakiness in Authentik's LDAP outpost during
  initial testing (server-side success, client-side "Protocol error",
  resolved by a later retry with no config changes) — if this recurs,
  it's known upstream outpost flakiness, not a regression in this stack's
  config. See `docs/greenbone-stack/README.md`'s "LDAP login" section.

## Playbook

`deploy-greenbone-stack` (roles: `lxc_base`, `docker_base`)

Follows `deploy-pentagi-stack.yml`'s shape: vendors Greenbone's own
`compose.yaml` (images rewritten through Harbor's new `greenbone` proxy-cache
project) rather than running Greenbone's interactive installer. Unlike
`pentagi-stack`, no separate `.env` file is templated — the upstream
compose has no `${VAR}` substitution needing one. No stack-specific
Ansible role exists — the compose content lives directly in the playbook
file.

## Implementation Files

| File | Role |
|------|------|
| `terraform/lxc/stacks/greenbone-stack/stack.yaml` | Terraform-side stack definition (Platform Contract fields) |
| `terraform/lxc/stacks/greenbone-stack/edge.yaml` | Traefik/Authentik ingress intent for the GSA UI |
| `terraform/lxc/environments/pve-test-vm/greenbone-stack/terragrunt.hcl` | Terragrunt entrypoint (validation) |
| `terraform/lxc/environments/pve/greenbone-stack/terragrunt.hcl` | Terragrunt entrypoint (production) |
| `terraform/lxc/ansible/playbooks/deploy-greenbone-stack.yml` | Stack playbook |
| `terraform/lxc/ansible/roles/harbor_postconfigure/defaults/main.yml` | Shared platform file — declares the `greenbone` Harbor proxy-cache project this stack depends on |

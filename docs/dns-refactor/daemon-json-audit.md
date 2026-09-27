# Docker daemon.json / container DNS audit (dns-stack references)

**Date:** 2026-09-27. **Base:** `stable` @ `4c4212fe`. **Method:** static repo
audit only (no live access to `pve`, no SOPS, no SSH) — this confirms what the
playbooks *would write* on the next `provision.sh` run, not what is currently
on each container's disk.

## Result

**No stack's Docker daemon DNS, compose `dns:`, or managed `/etc/resolv.conf`
still resolves to `dns-stack`.** The 8 daemon.json fixes recorded in
[README.md](./README.md) (plus step-ca's resolv.conf) are all present on
`stable`. No playbook changes were needed. One stale doc line was corrected
(graylog `STACK_CONTRACT.md`).

## Reference IPs and variables

| Thing | pve | pve-test-vm | Source |
|---|---|---|---|
| `dns-stack` (CoreDNS) | `192.168.20.13` (destroyed 2026-09-08) | `192.168.20.113` (still running, rollback point) | `.env.template` / `.env.pve-test-vm.template` `LAB_IP_DNS`; `terraform/lxc/stacks/dns-stack/stack.yaml` (`${lab_ip_dns}`) |
| `technitium-stack` | `192.168.20.15` | `192.168.20.115` | `.env.template:97` / `.env.pve-test-vm.template:42` `LAB_IP_TECHNITIUM` |

Existing "lab DNS server" abstraction: env var **`LAB_IP_TECHNITIUM`**, used
via the established pattern
`lookup('env', 'LAB_IP_TECHNITIUM') | default(dns_server, true) | mandatory(...)`.
The inventory var `dns_server` (from each `stack.yaml`) is always the zone's
SDN/MikroTik **gateway** (`${lab_gw_*}` or a literal `x.x.x.1`) in every
stack — never dns-stack's IP — so the fallback is also safe.

## Docker daemon.json `dns` key

32 playbooks write `/etc/docker/daemon.json` (plus
`ansible/00-initial-setup/framework-desktop-bootstrap.yml:500`, bare-metal
framework, no `dns` key). Only these set a `dns` key:

| File:line (var / use) | Value | dns-stack? |
|---|---|---|
| `playbooks/deploy-harbor-stack.yml:17` / `:20` | `LAB_IP_TECHNITIUM` → fallback `dns_server` | No |
| `playbooks/deploy-portainer-stack.yml:18` / `:21` | `LAB_IP_TECHNITIUM` → fallback `dns_server` | No |
| `playbooks/deploy-netbox-stack.yml:84` / `:100` | `LAB_IP_TECHNITIUM` → fallback `dns_server` | No |
| `playbooks/deploy-authentik-stack.yml:68` / `:428` | `LAB_IP_TECHNITIUM` → fallback `dns_server` | No |
| `playbooks/deploy-monitoring-stack.yml:18` / `:36` | `LAB_IP_TECHNITIUM` (mandatory) | No |
| `playbooks/deploy-graylog-stack.yml:12` / `:27` | `LAB_IP_TECHNITIUM` (mandatory) | No |
| `playbooks/deploy-opensearch-stack.yml:32` / `:55` | `LAB_IP_TECHNITIUM` → fallback `dns_server` | No |
| `playbooks/deploy-wazuh-stack.yml:40` / `:60` | `LAB_IP_TECHNITIUM` → fallback `dns_server` | No |

All other daemon.json writers (cse-panel, pangolin-proxy, pterodactyl-lab,
deploy-stack, portainer-agent, ai-services, proxy, pentagi-upstream-control,
cse-code-eval, media-stack-lab, technitium, pentagi, greenbone,
mcp-utility, ci-runner, pentagi-upstream-vanilla-companion, cse-controller,
torrent-stack-lab, nextcloud, gaming-stack-lab) set no `dns` key, so Docker
inherits the container's `/etc/resolv.conf` (the zone gateway, below).
`roles/docker_base` writes no daemon.json at all (only a systemd
drop-in and prune timer).

## Compose-level `dns:` and resolv.conf

| File:line | Value | dns-stack? |
|---|---|---|
| `playbooks/deploy-monitoring-stack.yml:584` (grafana service `dns:`) | `monitoring_lab_ip_dns` = `LAB_IP_TECHNITIUM` (`:77`) | No |
| `roles/lxc_base/tasks/main.yml:6` (`/etc/resolv.conf`) | `dns_server` (zone gateway) | No |
| `playbooks/deploy-ci-runner.yml:271` (runner resolv.conf) | `dns_server` (`${lab_gw_build}`) | No |
| `playbooks/deploy-authentik-stack.yml:643` (resolv.conf) | `authentik_lab_ip_dns` = `LAB_IP_TECHNITIUM` | No |
| `playbooks/deploy-step-ca.yml:366` (resolv.conf) | `step_ca_lab_ip_dns` = `LAB_IP_TECHNITIUM` | No |
| `deploy-{authentik,step-ca,coredns}.yml`, `roles/{lxc_base,node_exporter}` temporary `printf 'nameserver 1.1.1.1…'` | public resolvers, bootstrap only | No |
| `playbooks/deploy-coredns.yml:298` | `LAB_IP_DNS` — dns-stack's own resolv.conf | Self (pve-test-vm only now) |

`stacks/*/edge.yaml` `dns:` blocks are DNS *record* definitions for the
edge reconciler, not resolvers. `torrent-stack` compose `DNS_SERVER=on` is a
gluetun setting, unrelated. No `.j2` template sets a compose `dns:` key.

## Changed

- `terraform/lxc/stacks/graylog-stack/STACK_CONTRACT.md` — input table
  listed `LAB_IP_DNS` as the Docker daemon DNS input; the playbook has used
  `LAB_IP_TECHNITIUM` since the fix. Doc-only.

## Remaining dns-stack references (not daemon DNS — left alone, flagged)

These still reference `LAB_IP_DNS` on `pve` but do not affect container name
resolution. Not changed here; candidates for the Phase 6 code/doc cleanup.

- `playbooks/deploy-monitoring-stack.yml:276-280` — VictoriaMetrics
  `coredns` scrape job targets `LAB_IP_DNS:9153`; on `pve` this is now a
  permanently-down target (also `ansible/files/victoriametrics-scrape.yml:5`).
- `playbooks/deploy-technitium-stack.yml:196` — `lab_ip_dns` is
  `mandatory`, so the playbook still fails if `LAB_IP_DNS` is unset; used only
  by the bootstrap-phase conditional forwarder at `:335`, which is skipped
  when the `LAB_DOMAIN` zone already exists in Technitium (true on `pve`
  post-cutover). Removing `LAB_IP_DNS` from `.env` would break this playbook.
- `playbooks/deploy-proxy-stack.yml:307` — substitutes `${LAB_IP_DNS}` into
  rendered Traefik files; harmless if no file uses the placeholder.
- `terraform/lxc/reconcile-edge.py:64` — CoreDNS probe server default.
- `roles/gvm_findings_ingest/files/assets/ip_to_stack.json:6` and
  `files/greenbone-scan-setup/setup_credentials.py:71` — asset-label mapping
  for the old IPs.
- `.env` / `.env.template` still export `LAB_IP_DNS=192.168.20.13`.

## Deliberately left alone (pve-test-vm)

`pve-test-vm` still runs its own `dns-stack` (`192.168.20.113`):
`.env.pve-test-vm*`, `terraform/lxc/network/pve-test-vm.zone-members.yaml`,
`scripts/teardown-deploy-test.sh` (`LAB_IP_DNS` authoritative checks),
`stacks/dns-stack/*`, `deploy-coredns.yml`, and
`stacks/technitium-stack/verify-coredns-technitium-parity.sh` were not
touched. Note that on pve-test-vm the daemon.json playbooks above also point
at Technitium (`LAB_IP_TECHNITIUM=192.168.20.115`), not its dns-stack.

## Uncertainty

- Static audit only: containers not re-provisioned since the fixes could
  still carry an old on-disk daemon.json. A live check would be
  `grep dns /etc/docker/daemon.json` on each Docker LXC on `pve`.
- `terraform/lxc/network/pve-test.zone-members.yaml:20` lists
  `192.168.20.13` — generated zone-members index for the older `pve-test`
  layout; not a resolver config, not changed.

## Validation

`ansible-playbook -i localhost, --syntax-check` (with
`ANSIBLE_CONFIG=terraform/lxc/ansible/ansible.cfg`) on the 9 playbooks that
set Docker/resolv DNS (harbor, portainer, netbox, authentik, monitoring,
graylog, opensearch, wazuh, step-ca): pass (rc=0). No playbooks were
modified.

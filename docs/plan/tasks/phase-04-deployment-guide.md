# Phase 04: Core Shared Services — Deployment Guide

This guide covers the deployment sequence for Phase 04 services on pve-test. Before starting,
read [development-status.md](../development-status.md) to understand which components are
rebuild-safe and which have known gaps requiring manual steps.

## Current rebuild confidence

| Service | Rebuild-safe | Primary gap |
| --- | --- | --- |
| Authentik | No | Secrets in plaintext; manual first-boot; outpost not automated |
| Traefik | No | Secrets in plaintext; LE cert not persisted; Authentik outpost manual |
| step-ca | Partial | CA rebuild invalidates all certs; automatic retroactive trust distribution not yet enforced in tooling |
| Monitoring | No | Secrets in plaintext; depends on Authentik OIDC provider in SOPS |

For the complete gap analysis see [development-status.md](../development-status.md).

## Deployment order

The four Phase 04 services must be deployed in this order:

1. **Authentik** (task 04-01) — identity provider; first-boot steps must be completed manually
2. **Traefik** (task 04-03) — reverse proxy; depends on Authentik outpost existing
3. **step-ca** (task 04-04) — internal CA; automatic post-deploy CA trust distribution must run retroactively
4. **Monitoring** (task 04-05) — metrics and logs; depends on Grafana OIDC credentials in SOPS

Infra services (Harbor, apt-cacher) and Portainer must already be running before any Phase 04
service is deployed.

## Secrets model

All secret values are in `terraform/secrets.enc.yaml`. The `./with-secrets` wrapper decrypts
and injects them as environment variables. **Never use `source .env` or pass secrets via
`--extra-vars`.**

Verify the target node before any operation:

```bash
./with-secrets bash -c 'echo "Node: $TF_VAR_proxmox_node; Workspace: $TF_WORKSPACE"'
# Must print: Node: pve-test; Workspace: pve-test
```

---

## 1. Authentik (Identity Provider)

See [04-core-services-01-deploy-authentik.md](04-core-services-01-deploy-authentik.md) for
the full task spec.

**Location**: `terraform/lxc/stacks/authentik-stack/`

```bash
cd /home/steve/git/proxmox-homelab

# Apply LXC
cd terraform/lxc/stacks/authentik-stack
../../../../with-secrets terragrunt apply

# Deploy application
cd /home/steve/git/proxmox-homelab
./with-secrets ansible-playbook \
  -i "10.57.1.10," \
  terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml

# Validate health
curl -s -o /dev/null -w "%{http_code}" http://10.57.1.10:9000/-/health/live/
curl -s -o /dev/null -w "%{http_code}" http://10.57.1.10:9000/-/health/ready/
# Expect: 204 for both
```

**Manual steps required after deploy (known rebuild gaps):**

1. Visit `http://10.57.1.10:9000/if/flow/initial-setup/`
2. Create admin account using `AUTHENTIK_SUPERUSER_PASSWORD` from SOPS
3. Create API token → add as `AUTHENTIK_SUPERUSER_API_TOKEN` in `terraform/secrets.enc.yaml`
4. Create Proxy Provider + outpost for Traefik forward-auth (unblocks Traefik deploy)
5. Create OIDC provider for Grafana → add resulting `GRAFANA_OAUTH_CLIENT_ID` and
   `GRAFANA_OAUTH_CLIENT_SECRET` to `terraform/secrets.enc.yaml` (unblocks Monitoring deploy)

These manual steps are the primary blocker for a fully automated rebuild.
`terraform-provider-authentik` is the automation path — not yet implemented.

**Network**: Zone `mgmt_seg` · IP `10.57.1.10` · VMID `150` · Ports `9000` (HTTP), `9443` (HTTPS)

---

## 2. Traefik (Reverse Proxy)

See [04-core-services-03-deploy-traefik.md](04-core-services-03-deploy-traefik.md) for the
full task spec.

**Location**: `terraform/lxc/stacks/proxy-stack/`

```bash
cd /home/steve/git/proxmox-homelab

# Apply LXC
cd terraform/lxc/stacks/proxy-stack
../../../../with-secrets terragrunt apply

# Deploy application
cd /home/steve/git/proxmox-homelab
./with-secrets ansible-playbook \
  -i "10.57.2.10," \
  terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml

# Validate
curl -o /dev/null -w "%{http_code}" http://10.57.2.10
# Expect: 301 or 302 (HTTP → HTTPS redirect)

curl -sv https://10.57.2.10/dashboard/ 2>&1 | grep -i "issuer"
# Expect: "(STAGING) Let's Encrypt" — staging CA for all pve-test dev passes
```

**Known gaps:**

- `CF_DNS_API_TOKEN` must be injected from SOPS (not extra-vars); compose file must use `env_file`
- `stack.yaml` must include platform-supported `extra_mount_*` fields so `/opt/proxy-stack/certs`
  survives LXC rebuild
- Authentik Proxy Provider outpost must exist (created in step 1 above) before forward-auth works

**Network**: Zone `edge_seg` · IP `10.57.2.10` · VMID `153` · Ports `80`, `443`

---

## 3. step-ca (Internal Certificate Authority)

See [04-core-services-04-deploy-step-ca.md](04-core-services-04-deploy-step-ca.md) for the
full task spec.

**Location**: `terraform/lxc/stacks/step-ca-stack/` (systemd service — not Docker)

```bash
cd /home/steve/git/proxmox-homelab

# Apply LXC
cd terraform/lxc/stacks/step-ca-stack
../../../../with-secrets terragrunt apply

# Deploy application
cd /home/steve/git/proxmox-homelab
./with-secrets ansible-playbook \
  -i "10.57.1.11," \
  terraform/lxc/ansible/playbooks/deploy-step-ca.yml

# Validate ACME directory
curl -sk https://10.57.1.11/acme/acme/directory | jq .

# Retroactive CA trust distribution — required post-step-ca action
# Target behavior: this is executed automatically by deployment tooling.
./with-secrets ansible-playbook -i "10.57.2.10," terraform/lxc/ansible/playbooks/trust-homelab-ca.yml
./with-secrets ansible-playbook -i "192.168.1.40," terraform/lxc/ansible/playbooks/trust-homelab-ca.yml

# Verify resolver from inside Traefik container
TRAEFIK_VMID=$(pct list | awk 'NR>1 && ($4=="proxy-stack" || $4=="traefik") {print $1; exit}')
pct exec "$TRAEFIK_VMID" -- curl -s \
  --cacert /usr/local/share/ca-certificates/homelab-root.crt \
  https://10.57.1.11/acme/acme/directory | jq .
```

**Known gaps:**

- CA rebuild generates a new root keypair — all previously issued certs become invalid;
  `certs/homelab-root.crt` in the repo changes on each rebuild
- CA persistence strategy not yet decided (regenerate vs persist encrypted keypair)
- Automatic retroactive trust distribution after step-ca deploy is required but not yet
  enforced in scripts; until tooling is updated, run the trust playbook against all
  already-deployed managed hosts as a temporary workaround

**Network**: Zone `mgmt_seg` · IP `10.57.1.11` · VMID `152` · Port `443`

---

## 4. Monitoring Stack (VictoriaMetrics + Grafana + Loki)

See [04-core-services-05-deploy-monitoring.md](04-core-services-05-deploy-monitoring.md) for
the full task spec.

**Prerequisite:** `GRAFANA_OAUTH_CLIENT_ID` and `GRAFANA_OAUTH_CLIENT_SECRET` must already be
in `terraform/secrets.enc.yaml` before running the playbook. Confirm with:

```bash
SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops --decrypt terraform/secrets.enc.yaml \
  | grep -E "GRAFANA_OAUTH_CLIENT_ID|GRAFANA_OAUTH_CLIENT_SECRET"
```

If either value is still `CHANGEME_`, return to step 1 and complete the Authentik OIDC
provider setup.

**Location**: `terraform/lxc/stacks/monitoring-stack/`

```bash
cd /home/steve/git/proxmox-homelab

# Apply LXC
cd terraform/lxc/stacks/monitoring-stack
../../../../with-secrets terragrunt apply

# Deploy application
cd /home/steve/git/proxmox-homelab
./with-secrets ansible-playbook \
  -i "10.57.1.12," \
  terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml

# Validate
curl -s http://10.57.1.12:3000/api/health | jq .database   # Expect: "ok"
curl -s http://10.57.1.12:8428/metrics | head -5            # Expect: VM metrics output
curl -s http://10.57.1.12:3100/ready                        # Expect: ready

# OOM check
ssh root@pve-test.gibbsgreatly.xyz "dmesg | grep -i oom | tail -5"
# Should be empty
```

**Known gaps:**

- All three Grafana secrets (`GRAFANA_ADMIN_PASSWORD`, `GRAFANA_OAUTH_CLIENT_ID`,
  `GRAFANA_OAUTH_CLIENT_SECRET`) must come from SOPS via `env_file`, not extra-vars or hardcoded
- Grafana datasources must be added manually via the Grafana UI after deploy
- VictoriaMetrics currently only scrapes CoreDNS — expand before Phase 05

**Network**: Zone `mgmt_seg` · IP `10.57.1.12` · VMID `154` · Ports `8428`, `3100`, `3000` (Grafana via Traefik)

---

## Validation checklist

After all four services are deployed:

```bash
# Container health
curl -s -o /dev/null -w "%{http_code}" http://10.57.1.10:9000/-/health/live/   # 204
curl -o /dev/null -w "%{http_code}" http://10.57.2.10                          # 301/302
curl -sk https://10.57.1.11/health                                              # 200
curl -s http://10.57.1.12:3000/api/health | jq .database                       # "ok"

# No literal credentials in compose files
pct exec 150 -- grep -r "CHANGEME\|password.*=.*[a-zA-Z0-9]\{16\}" /opt/authentik-stack/
TRAEFIK_VMID=$(pct list | awk 'NR>1 && ($4=="proxy-stack" || $4=="traefik") {print $1; exit}')
pct exec "$TRAEFIK_VMID" -- cat /opt/proxy-stack/docker-compose.yml | grep CF_DNS_API_TOKEN
pct exec 154 -- cat /opt/monitoring-stack/docker-compose.yml | grep GRAFANA_ADMIN_PASSWORD

# Restart survival
for vmid in 150 153 152 154; do pct restart $vmid; done
# Then re-run the health checks above
```

---

## Security scanning before merging

```bash
# Terraform IaC scan
/home/steve/.local/bin/snyk iac test terraform/

# Code quality scan
./with-secrets sonar-scanner
```

Stop and present options if either scan reports new issues.

---

## Troubleshooting

**Terragrunt targets wrong node:**

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
# Must be pve-test — if not, check .env
```

**Ansible playbook fails — check secrets available:**

```bash
./with-secrets env | grep AUTHENTIK_
./with-secrets env | grep GRAFANA_
```

**Container unreachable — check networking inside container:**

```bash
ssh root@10.57.1.10    # or whichever IP
ip -4 addr show
ip route show
docker ps -a
```

**Authentik health returns 5xx — wait for initialization:**

```bash
watch -n 5 'curl -s -o /dev/null -w "%{http_code}" http://10.57.1.10:9000/-/health/ready/'
# First 2–3 minutes after deploy is normal startup time
```

---

## Next steps after Phase 04

Once all four services are deployed and validated on pve-test:

1. Merge all feature branches to `dev/pve-test`
2. Phase 05 (Supply Chain) — assumes Phase 04 services are stable
3. Phase 06 (Application Migration) — assumes Phase 04 + Phase 05 complete
4. Outstanding rebuild-safety work: secrets injection for Traefik/Authentik/Monitoring,
  `terraform-provider-authentik`, LE cert persistence via `extra_mount_*`

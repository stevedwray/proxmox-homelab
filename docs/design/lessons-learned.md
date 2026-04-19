# Lessons Learned

Distilled observations from development passes — things that are non-obvious, caused
problems, or must be remembered for future rebuilds. The raw session notes are in
`docs/design/archive/Observations.md`.

## Infrastructure and networking

**Portainer agent and server versions must match exactly.**
Agent v2.40.0 uses TLS from the first byte; older servers send a plain-HTTP handshake and
the connection fails. A mismatched agent also locks to the first server that claims it — a
restart is required to clear the pairing state. Pin agent and server to the same explicit
version tag in all compose files. Never use `latest`.

**IP allocation must be verified with a ping, not just IPAM.**
NetBox records intended allocations but cannot detect addresses live on the network that
were never registered. Before assigning any IP: `ping -c 3 <ip>` from the same subnet.
If it responds, the address is in use regardless of what IPAM shows.

**Default Terraform workspace targets `pve`, not `pve-test`.**
Without `TF_WORKSPACE=pve-test` (set by `.env`), `terragrunt apply` targets the production
node. Any operation that mutates running containers on `pve` without intent is the result
of a missing workspace export. The `with-secrets` wrapper handles this when `.env` is
correctly configured.

**SDN zone type is VLAN, not Simple.**
The original plan used Simple zones (Proxmox holds gateway IPs, performs SNAT). The settled
design uses VLAN zones with MikroTik as the L3 gateway. `snat: false` on all SDN zones is
mandatory — SNAT at Proxmox double-NATs with MikroTik and breaks LAN-to-container ingress.
The Terraform SDN provisioner handles Simple zones only; VLAN zones are applied by
`ansible/00-initial-setup/proxmox-sdn-setup.yml`.

**`jq` should be installed in the pve-test bootstrap.**
Multiple setup and validation steps use it for Harbor and NetBox API checks. Add it to the
Ansible bootstrap alongside other base tooling.

## Harbor

**Harbor's own images pull from Docker Hub on the first deployment pass.**
This is expected and documented. Harbor cannot source its own images from itself before it
exists. On subsequent passes, all images come from Harbor. This is the Stage 1 → Stage 2
transition in the bootstrap model.

**Harbor scan results lag after a proxy-cache pull and may need an explicit trigger.**
After a `docker pull` through the proxy cache, `scan_overview` can remain `null` for some
time. Trigger the scan endpoint explicitly and poll the artifact list until the Trivy
summary appears. Repository paths for nested image names (e.g., `goauthentik/server`) need
double URL-encoding in API calls.

**Harbor GC schedule API requires a 6-field cron string (seconds as first field).**
The standard 5-field cron `0 3 * * 0` is rejected. Use `0 0 3 * * 0` instead.

## Secrets and configuration

**step-ca ACME challenge type must be httpChallenge, not tlsChallenge.**
step-ca verifies domain ownership by calling back to Traefik on port 80. Using tlsChallenge
requires step-ca to reach Traefik on port 443 with a valid cert — a circular dependency
during initial PKI bootstrapping. Requires MikroTik policy: `mgmt_seg → edge_seg tcp/80`.

**LE staging CA for all pve-test dev passes.**
Always use `https://acme-staging-v02.api.letsencrypt.org/directory` in Traefik's
`letsencrypt` resolver for pve-test development. Staging certs show
`(STAGING) Let's Encrypt` in browsers — this is correct and expected. Switching to
production consumes rate-limit quota and is only done when promoting to `pve`.

**LE acme.json must be persisted outside the LXC.**
The ACME cert storage lives inside the LXC filesystem. Rebuilding the LXC destroys the
cert, triggering a new LE request. On pve-test with the staging CA this is harmless; on
production it consumes rate-limit quota. The fix is platform-supported `extra_mount_*`
fields in `stack.yaml` so `/opt/proxy-stack/certs` is persisted.

## Authentik

**Authentik must be in `mgmt_seg` with explicit allow rules from `edge_seg` and any app zone.**
Traefik (edge_seg) reaches the Authentik forward-auth endpoint at `10.57.1.10:9000`.
Any service that delegates auth to Authentik must also be able to reach it. Verify zone
reachability before wiring up any protected route.

**Authentik initial setup and OIDC provider configuration are currently manual.**
After deployment, an operator must use the web UI to create the initial admin user, generate
an API token, create Proxy Providers for Traefik forward-auth, and create OIDC providers for
each integrated service (Grafana). This is the main obstacle to a fully automated rebuild.
The `terraform-provider-authentik` can automate these steps and should be implemented before
the platform is considered rebuild-safe.

## Chainloop

**Chainloop has no Docker Compose self-hosting path.**
Chainloop self-hosting requires Helm on Kubernetes. A compose extraction from `helm template`
is unsupported and unpatchable. Use the Chainloop Cloud free tier for Phase 05 acceptance
criteria, or defer until a Kubernetes layer exists in the lab.

# Development Status

This document tracks **rebuild confidence** — not whether a container is currently running,
but whether the IaC (Terraform + Ansible) is complete enough that destroying and redeploying
a component from code produces a correct, fully integrated result with no manual steps.

The running containers on pve-test are ephemeral. They exist for development validation,
not as a measure of completion. A component is only considered development-complete when
its playbook can be run against a freshly provisioned LXC and produce a working, integrated
system automatically.

## How to read this table

| Column | Meaning |
| --- | --- |
| **IaC reproducible** | `terragrunt apply` + playbook produces a correct deployment from scratch at the right path with correct config |
| **Secrets managed** | All credentials injected from SOPS via `with-secrets`; nothing baked into compose files on disk |
| **Integrations wired** | Connects correctly to DNS, TLS, auth, and upstream services without manual steps |
| **Rebuild-safe** | Can be destroyed and redeployed from code with no operator UI or CLI intervention |

## Component status

| Component | VMID | IaC reproducible | Secrets managed | Integrations wired | Rebuild-safe | Primary gaps |
| --- | --- | --- | --- | --- | --- | --- |
| apt-cacher-ng | 142 | Yes | n/a | Yes | **Yes** | None known |
| CoreDNS | 151 | Yes | n/a | Yes | **Yes** | Zone records added manually; no IaC mechanism for new records |
| Harbor | 121 | Yes | Partial | Yes | **Partial** | Robot accounts and image pre-seeding need validation after rebuild |
| Portainer | 120 | Yes | Yes | No | No | SEC-02 (agent mTLS) not implemented; no Traefik/auth integration |
| NetBox | 143 | Unknown | Unknown | No | Unknown | Playbook not validated from scratch; IPAM is manual; no Traefik route |
| CI runner | 141 | Yes | Yes | Yes | **Partial** | GitHub runner token must be rotated and re-registered per rebuild |
| step-ca | 152 | Yes | Partial | Yes | Partial | CA rebuild produces a new root cert — all previously issued certs become invalid; CA trust distribution not in rebuild sequence |
| Traefik | 153 | Partial | **No** | Partial | **No** | See details below |
| Authentik | 150 | Partial | **No** | Partial | **No** | See details below |
| Monitoring | 154 | Partial | **No** | Partial | **No** | See details below |

---

## Detailed gap analysis

### Traefik (proxy-stack, VMID 153)

**What works:** LXC provisions correctly. Traefik starts, obtains a wildcard LE cert, and
routes traffic. The step-ca ACME resolver is pre-configured. The Authentik forwardAuth
middleware is defined.

**What is broken for rebuild:**

1. **Secrets in plaintext.** `CF_DNS_API_TOKEN` is written into
   `/opt/proxy-stack/docker-compose.yml` in cleartext. The playbook must inject it from
   SOPS at deploy time and the compose file must reference an environment variable — it must
   never contain a literal credential.

2. **LE cert not persisted.** The ACME cert storage (`certs/letsencrypt/acme.json`) lives
   inside the LXC filesystem. Rebuilding the LXC destroys it, triggering a new LE cert
   request. On pve-test with the staging CA this is harmless; on production it consumes
   rate-limit quota. Fix: add platform-supported `extra_mount_*` fields in
   `stack.yaml` so `/opt/proxy-stack/certs` survives LXC rebuild.

3. **Authentik outpost not automated.** The `authentik` forwardAuth middleware points at
   `http://10.57.1.10:9000/outpost.goauthentik.io/auth/traefik`. This URL only works if
   an Authentik Proxy Provider and outpost have been created in Authentik's UI or API.
   After an Authentik rebuild, these must be re-created before any protected route works.

4. **Deploy path mismatch.** The running stack is at `/opt/proxy-stack/`. Playbook path
   assumptions must be verified to match this.

---

### Authentik (authentik-stack, VMID 150)

**What works:** LXC provisions correctly. All four services start healthy (server, worker,
PostgreSQL, Redis). The OIDC provider for Grafana is configured with real credentials.

**What is broken for rebuild:**

1. **Secrets in plaintext.** Authentik credentials (`AUTHENTIK_SECRET_KEY`,
   `AUTHENTIK_POSTGRES_PASSWORD`, etc.) are in the compose file on disk. They must be
   injected from SOPS at deploy time.

2. **Initial setup is manual.** After a fresh deploy, an operator must:
   - Access the first-boot web UI at `http://10.57.1.10:9000/if/flow/initial-setup/`
   - Create the superuser account
   - Generate an API token and add it to SOPS as `AUTHENTIK_SUPERUSER_API_TOKEN`
   - Create a Proxy Provider + outpost for Traefik forward-auth
   - Create an OIDC provider for Grafana (produces `GRAFANA_OAUTH_CLIENT_ID` and
     `GRAFANA_OAUTH_CLIENT_SECRET`, which must also be added to SOPS)

   This sequence cannot be skipped — Traefik auth and Grafana OIDC both fail without it.
   It also cannot happen in parallel with Traefik or Monitoring deployment — there is a
   strict ordering dependency.

3. **Automation path.** The `terraform-provider-authentik` (Terraform provider) can
   manage all of the above: users, providers, outposts, and OIDC clients. Implementing
   this is the primary work needed to make Authentik rebuild-safe. The provider uses
   `AUTHENTIK_SUPERUSER_API_TOKEN` to authenticate, so the initial superuser creation
   (step 2 above) is the only remaining manual step — everything else becomes IaC.

---

### Monitoring (monitoring-stack, VMID 154)

**What works:** All four services run (VictoriaMetrics, Grafana, Loki, Promtail). Grafana
is configured for Authentik OIDC. VictoriaMetrics scrapes CoreDNS metrics.

**What is broken for rebuild:**

1. **Secrets in plaintext.** `GRAFANA_ADMIN_PASSWORD`, `GRAFANA_OAUTH_CLIENT_ID`, and
   `GRAFANA_OAUTH_CLIENT_SECRET` are all written into the compose file on disk.

2. **Depends on Authentik OIDC provider existing.** The Grafana OIDC client ID and secret
   come from an Authentik OIDC provider that was created manually. On a rebuild, those
   values will not exist until Authentik is configured (see Authentik gap above). Monitoring
   cannot be deployed in a rebuild until the Authentik OIDC provider is created and
   `GRAFANA_OAUTH_CLIENT_ID` / `GRAFANA_OAUTH_CLIENT_SECRET` are in SOPS.

3. **VictoriaMetrics scrape config is minimal.** Only CoreDNS (`10.57.1.13:9153`) is
   scraped. No scrape targets for other platform services. This is acceptable for the
   current development phase but should expand before Phase 05.

---

### step-ca (VMID 152)

**What works:** Deploys correctly. ACME directory is reachable. Traefik queries it.
The root CA cert is committed to the repo at `certs/homelab-root.crt`.

**What is broken for rebuild:**

1. **CA rebuild invalidates all issued certs.** `step ca init` in the playbook generates
   a new root CA keypair on each deployment. Any cert previously issued by the old CA
   (including any certs Traefik obtained via the step-ca resolver) becomes invalid. The
   committed `certs/homelab-root.crt` also changes. This is tolerable during development
   but means the CA and all consumers of it must be rebuilt together.

2. **CA trust distribution not in rebuild sequence.** The `trust-homelab-ca.yml` playbook
   exists but is not called automatically during the rebuild sequence. Containers deployed
   before step-ca will not trust the new root CA until `trust-homelab-ca.yml` is run
   against them retroactively. The `lxc_base` role installs the CA cert if
   `certs/homelab-root.crt` exists locally — so this only works if step-ca is deployed
   before any other LXC, or if a post-deploy trust-distribution step is added to the
   rebuild runbook.

3. **No internal certs issued yet.** The step-ca ACME storage in Traefik is empty —
   no `lab.gibbsgreatly.xyz` routes exist that request a step-ca cert. This is expected
   at the current stage but means the internal TLS path is untested end-to-end.

---

## Cross-cutting gaps

### Secrets model

**Design intent:** All secrets in SOPS (`terraform/secrets.enc.yaml`), injected at deploy
time by `with-secrets`. Compose files reference environment variables only — no literal
credentials on disk inside any LXC.

**Current reality:** Traefik, Authentik, and Monitoring all have credentials baked into
their compose files on disk inside the LXC. The playbooks write these files with the secret
values embedded rather than injecting them from SOPS.

**Impact:** Every component with secrets fails the rebuild-safe test. A playbook re-run
against an existing LXC would also overwrite the compose file with the same hardcoded
values — there is no SOPS injection step.

**Fix path:** Each playbook must use `with-secrets` (or read from SOPS-decrypted variables)
to render compose files with env-var references, and write those env vars into a
SOPS-sourced `.env` file that Docker Compose reads via `env_file`. No secret value should
appear in a committed or on-disk compose file.

### Authentik automation (the rebuild-safe blocker)

The Authentik initial setup sequence is the primary blocker for a fully automated rebuild.
The dependency chain is:

```
Authentik deployed → superuser created (manual) → API token in SOPS
  → terraform-provider-authentik runs → Proxy Provider + outpost created
  → Traefik forwardAuth works
  → OIDC provider created → GRAFANA_OAUTH_CLIENT_ID/SECRET in SOPS
  → Monitoring can be deployed with working OIDC
```

Until `terraform-provider-authentik` is implemented, this chain requires manual UI steps
after every Authentik rebuild, blocking Traefik auth and Monitoring deployment.

### LE cert persistence

The production LE wildcard cert (`*.gibbsgreatly.xyz`) lives at
`/opt/proxy-stack/certs/letsencrypt/acme.json` inside VMID 153. This is inside the LXC
filesystem and is destroyed on rebuild.

On pve-test with the **staging CA** this is benign — a new staging cert is issued freely.
On production (`pve`) with the **production CA** this consumes LE rate-limit quota.

Fix: add platform-supported `extra_mount_*` fields to the `proxy-stack` `stack.yaml`:

```yaml
extra_mount_path: "/opt/proxy-stack/certs"
extra_mount_size: "5G"
extra_mount_storage: infrastructure-containers
```

The persisted mount path survives LXC rebuilds. This must be in place before any
production deployment.

### CA trust distribution ordering

The intended CA trust sequence during a rebuild is:

1. Deploy step-ca (generates new root CA)
2. Fetch new `certs/homelab-root.crt` from step-ca
3. Run `trust-homelab-ca.yml` against all already-deployed LXCs (retroactive)
4. All subsequent LXC deployments pick up the CA cert automatically via `lxc_base`

This sequence is documented but not enforced. The rebuild runbook must include step 3
explicitly, or containers deployed before step-ca will not trust internal certs.

### MikroTik has no IaC

DNS forwarding rules, inter-zone firewall ACLs, and VLAN configuration are all applied
manually on the MikroTik. A full pve-test rebuild requires the operator to reconfigure the
MikroTik by hand using the commands in `terraform/lxc/network/pve-test.yaml`.

This is TM-09 (Critical) in the threat model. There is no automated backup or drift
detection. A MikroTik config change that removes ACLs eliminates all zone isolation.

---

## What "rebuild-safe" requires per component

The following conditions must all be true for a component to be considered rebuild-safe:

1. `terragrunt apply` provisions the LXC at the correct VMID, zone, and IP with no drift
2. The Ansible playbook runs to completion without errors against a fresh LXC
3. All secrets are injected from SOPS — no literal credentials in any file on disk
4. The compose file (if applicable) references environment variables only
5. All integrations (DNS resolution, TLS trust, Authentik auth, upstream services) work
   without additional manual steps
6. The component survives an LXC restart (`pct restart <vmid>`) and returns to healthy

### Current rebuild-safe components

- **apt-cacher-ng** — no secrets, no integrations beyond network
- **CoreDNS** — no secrets, DNS works, integrations are passive (MikroTik forwards to it)

### Components requiring remediation before rebuild-safe

| Component | Primary work item |
| --- | --- |
| Traefik | Secrets injection from SOPS; LE cert persistence; Authentik outpost automation |
| Authentik | Secrets injection from SOPS; `terraform-provider-authentik` for initial config |
| Monitoring | Secrets injection from SOPS; depends on Authentik automation first |
| step-ca | CA trust distribution in rebuild sequence; decide on CA persistence strategy |
| Harbor | Validate robot account automation; validate image pre-seeding after rebuild |
| NetBox | Validate playbook from scratch; add Traefik route |
| Portainer | SEC-02 (agent mTLS); decision on Traefik integration scope |

---

## Rebuild sequence (target state)

The following is the intended deployment order once all gaps above are closed.
This is the Mode 2 (deployment) sequence — see [bootstrap.md](../design/bootstrap.md).

1. MikroTik configured (manual — until MikroTik IaC exists)
2. Proxmox SDN VLAN zones applied (`proxmox-sdn-setup.yml`)
3. Portainer (VMID 120) — `terragrunt apply` + `deploy-portainer-stack`
4. Harbor (VMID 121) — `terragrunt apply` + `deploy-harbor-stack` (pulls from Docker Hub on first pass)
5. apt-cacher (VMID 142) — `terragrunt apply` + `deploy-apt-cacher-stack`
6. NetBox (VMID 143) — `terragrunt apply` + `deploy-netbox-stack`
7. **step-ca (VMID 152)** — `terragrunt apply` + `deploy-step-ca` → fetch new root cert → `trust-homelab-ca.yml` against all deployed LXCs
8. Harbor image pre-seed — pull all Phase 04 images through Harbor proxy cache
9. **Authentik (VMID 150)** — `terragrunt apply` + `deploy-authentik-stack` → `terraform-provider-authentik` configures providers and outpost automatically
10. **Traefik (VMID 153)** — `terragrunt apply` + `deploy-proxy-stack` → LE staging cert obtained automatically
11. CoreDNS (VMID 151) — `terragrunt apply` + `deploy-coredns` → MikroTik FWD rule for `lab.gibbsgreatly.xyz`
12. **Monitoring (VMID 154)** — `terragrunt apply` + `deploy-monitoring-stack`
13. CI runner (VMID 141) — `terragrunt apply` + `deploy-ci-runner` → register with GitHub Actions

Steps marked **bold** have outstanding gaps that must be closed before this sequence works end-to-end.

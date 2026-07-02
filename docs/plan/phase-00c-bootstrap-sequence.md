# Phase 00c — Bootstrap Sequence

## Goal

Execute the two-stage bootstrap that resolves the circular infrastructure dependency and
establishes the permanent platform foundation before Phase 04 begins.

- **Part A — Stage 1:** Deploy temporary Portainer, Harbor, and CI runner. Configure
  Harbor proxy cache projects. Pre-seed Harbor with all images that Stage 2 and Phase 04
  will need. Validate CI pipeline execution against the Stage 1 runner.
- **Part B — Stage 2:** Deploy permanent Portainer, Harbor, and CI runner using Stage 1
  Harbor as the image source. Tear down Stage 1 containers once Stage 2 is confirmed
  healthy.

After this phase, the platform foundation is ready for Phase 04 (Core Shared Services). All
subsequent container deployments source images from Harbor at `192.168.40.10`. No container
deployed from Phase 04 onwards pulls directly from Docker Hub or any external registry at
runtime.

The design rationale for the two-stage model — including the bootstrap ordering
and the relationship between Phase 03d and this phase — is documented in
[docs/design/bootstrap.md](../design/bootstrap.md).

## Live task docs

- [00c-bootstrap-01 — Stage 1: Temporary bootstrap containers](tasks/00c-bootstrap-01-stage1-temporary.md)
- [00c-bootstrap-02 — Stage 2: Production containers and Stage 1 teardown](tasks/00c-bootstrap-02-stage2-production.md)

---

## Prerequisites

- pve-test host is running with Proxmox VE installed (Phase 00a complete)
- Phase 03d complete — `with-secrets` wrapper is merged and executable, age key is present
  at `~/.config/sops/age/keys.txt`
- SDN VLAN zones applied to `pve-test`: `mgmt_seg` (VLAN 20), `infra_seg` (VLAN 40), and
  `build_seg` (VLAN 10) — apply with `ansible/00-initial-setup/proxmox-sdn-setup.yml`
  until Terraform VLAN zone support is implemented
- MikroTik VLAN interfaces and IP gateways are configured for all three zones — see
  `terraform/lxc/network/pve-test.yaml` for the full command set
- `terraform/secrets.enc.yaml` has real values for:
  - `TF_VAR_proxmox_api_url`, `TF_VAR_pm_api_token_id`, `TF_VAR_pm_api_token_secret`
  - `TF_VAR_lxc_password`
  - `TF_VAR_portainer_admin_password`
  - `HARBOR_ADMIN_PASSWORD`
  - `HARBOR_ROBOT_USER`, `HARBOR_ROBOT_PASSWORD`
- `storage-template` pool exists on `pve-test` with the Debian Docker LXC template
- `infrastructure-containers` pool exists on `pve-test`

---

## Part A — Stage 1: Temporary bootstrap containers

Stage 1 deploys Portainer, Harbor, and CI runner as temporary containers. These containers
pull images directly from Docker Hub because no Harbor instance exists yet. They exist to
produce the environment that Stage 2 requires, not as the final state.

The `with-secrets` wrapper is used for all deployments in Stage 1, exactly as it will be
in Stage 2. The temporary nature of the containers does not change the secrets delivery
model on the operator workstation.

---

### A1 — Portainer (temporary)

Portainer's Stage 1 instance provides Docker management visibility throughout the bootstrap.
It is labelled temporary because it is planned for in-place replacement in Stage 2 — the
Stage 2 Portainer is functionally identical but its LXC is provisioned to pull from Harbor
rather than Docker Hub.

| Field | Value |
|---|---|
| VMID | 20020 |
| Zone | `mgmt_seg` |
| IP | `192.168.20.20/24` |
| Gateway | `192.168.20.1` |
| Image source | Docker Hub (direct) |

**Secrets required** (keys in `terraform/secrets.enc.yaml`):

- `TF_VAR_pm_api_token_id`, `TF_VAR_pm_api_token_secret` — Proxmox API authentication
- `TF_VAR_lxc_password` — LXC root password
- `TF_VAR_portainer_admin_password` — Portainer admin account

**Deploy:**

```bash
cd /home/steve/git/proxmox-homelab/terraform/lxc/stacks/portainer-stack
/home/steve/git/proxmox-homelab/with-secrets terragrunt apply

cd /home/steve/git/proxmox-homelab
./with-secrets ansible-playbook \
  -i "192.168.20.20," \
  terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml
```

**Validate:**

```bash
curl -s http://192.168.20.20:9000/api/system/status | jq .Version
# Expect: a non-empty version string
```

**Teardown:** Covered in Part B after Stage 2 Portainer is confirmed healthy.

---

### A2 — Harbor (temporary)

Harbor's Stage 1 instance bootstraps its component images directly from Docker Hub — there
is no prior Harbor to serve them from. Once running, Harbor's proxy cache projects are
configured and the `harbor_postconfigure` role applies robot account, scan-on-push, and GC
schedule settings. The critical Stage 1 deliverable is the pre-seeding step (A4): all
Stage 2 and Phase 04 images are pulled through the proxy cache so that Stage 2 deployments
never require a direct Docker Hub connection.

| Field | Value |
|---|---|
| VMID | 40010 |
| Zone | `infra_seg` |
| IP | `192.168.40.10/24` |
| Gateway | `192.168.40.1` |
| Image source | Docker Hub (direct) |

**Secrets required** (keys in `terraform/secrets.enc.yaml`):

- `TF_VAR_pm_api_token_id`, `TF_VAR_pm_api_token_secret` — Proxmox API authentication
- `TF_VAR_lxc_password` — LXC root password
- `HARBOR_ADMIN_PASSWORD` — Harbor admin account

**Deploy:**

```bash
cd /home/steve/git/proxmox-homelab/terraform/lxc/stacks/harbor-stack
/home/steve/git/proxmox-homelab/with-secrets terragrunt apply

cd /home/steve/git/proxmox-homelab
./with-secrets ansible-playbook \
  -i "192.168.40.10," \
  terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml
```

**Validate:**

```bash
curl -s http://192.168.40.10/api/v2.0/ping
# Expect: "Pong"

./with-secrets bash -c \
  'curl -sk -u "admin:${HARBOR_ADMIN_PASSWORD}" http://192.168.40.10/api/v2.0/scanners | jq ".[] | {name, is_default, health}"'
# Expect: {"name":"Trivy","is_default":true,"health":"healthy"}
```

**Teardown:** Covered in Part B. Harbor is the last Stage 1 container to be replaced
because Stage 2 Portainer and CI runner pull from Stage 1 Harbor during their deployment.

---

### A3 — CI runner (temporary)

The Stage 1 CI runner is deployed to validate that GitHub Actions self-hosted pipelines
execute correctly before the permanent runner takes its place. At least one full pipeline
run must succeed on the Stage 1 runner before Stage 2 begins. The runner registration token
is short-lived and must be retrieved from GitHub immediately before deployment.

| Field | Value |
|---|---|
| VMID | 10063 |
| Zone | `build_seg` |
| IP | `192.168.10.63/24` |
| Gateway | `192.168.10.1` |
| Image source | Docker Hub (direct) |

**Secrets required** (keys in `terraform/secrets.enc.yaml`):

- `TF_VAR_pm_api_token_id`, `TF_VAR_pm_api_token_secret` — Proxmox API authentication
- `TF_VAR_lxc_password` — LXC root password
- `GH_RUNNER_TOKEN` — GitHub Actions runner registration token (retrieve from
  GitHub → Repository → Settings → Actions → Runners → New runner; token is valid for
  60 minutes)

**Deploy:**

```bash
cd /home/steve/git/proxmox-homelab/terraform/lxc/stacks/ci-runner-01
/home/steve/git/proxmox-homelab/with-secrets terragrunt apply

cd /home/steve/git/proxmox-homelab
./with-secrets ansible-playbook \
  -i "192.168.10.63," \
  terraform/lxc/ansible/playbooks/deploy-ci-runner.yml
```

**Validate:**

```bash
# Confirm runner appears as online in GitHub Actions UI:
# Repository → Settings → Actions → Runners → ci-runner-01 must show "Idle"

# Trigger a self-hosted workflow job and confirm it completes:
gh workflow run validate.yml --ref docs/repo-review
gh run list --workflow=validate.yml --limit 1
```

**Teardown:** Covered in Part B after Stage 2 CI runner is confirmed healthy.

---

### A4 — Harbor pre-seeding

Pre-seeding is the critical Stage 1 handoff step. All images needed for Stage 2 deployments
and Phase 04 services are pulled through Harbor's proxy cache so that no Stage 2 deployment
needs to contact Docker Hub or any external registry at runtime.

Run from the workstation after Harbor (A2) is healthy and `harbor_postconfigure` has
created the `robot$ci-runner` account.

**Authenticate to Harbor:**

```bash
./with-secrets bash -c \
  'echo "${HARBOR_ROBOT_PASSWORD}" | docker login 192.168.40.10 -u "${HARBOR_ROBOT_USER}" --password-stdin'
```

**Pull Phase 04 images through the Harbor proxy cache:**

```bash
# Authentik identity provider
AUTHENTIK_VERSION="2024.12.3"
docker pull 192.168.40.10/ghcr/goauthentik/server:${AUTHENTIK_VERSION}
docker pull 192.168.40.10/dockerhub/library/postgres:16-alpine
docker pull 192.168.40.10/dockerhub/library/redis:alpine

# Traefik reverse proxy
TRAEFIK_VERSION="v3.3"
docker pull 192.168.40.10/dockerhub/library/traefik:${TRAEFIK_VERSION}

# Monitoring stack
GRAFANA_VERSION="11.5.2"
VM_VERSION="v1.101.0"
LOKI_VERSION="3.4.2"
PROMTAIL_VERSION="3.4.2"
docker pull 192.168.40.10/dockerhub/grafana/grafana-oss:${GRAFANA_VERSION}
docker pull 192.168.40.10/dockerhub/victoriametrics/victoria-metrics:${VM_VERSION}
docker pull 192.168.40.10/dockerhub/grafana/loki:${LOKI_VERSION}
docker pull 192.168.40.10/dockerhub/grafana/promtail:${PROMTAIL_VERSION}

# NetBox IPAM
docker pull 192.168.40.10/dockerhub/netboxcommunity/netbox:latest
docker pull 192.168.40.10/dockerhub/library/postgres:16-alpine
docker pull 192.168.40.10/dockerhub/library/valkey:8-alpine
```

**Pull Stage 2 bootstrap-container images** (so Stage 2 Portainer and CI runner can pull
from Harbor rather than Docker Hub):

```bash
# Portainer
docker pull 192.168.40.10/dockerhub/portainer/portainer-ce:latest
docker pull 192.168.40.10/dockerhub/portainer/agent:latest

# Harbor component images — pull via Harbor's own dockerhub proxy cache.
# These allow Stage 2 Harbor to source from Stage 1 Harbor during the brief
# overlap window before Stage 1 Harbor is destroyed.
# Design note: if the timing of the Stage 1 Harbor teardown makes this
# impractical, Stage 2 Harbor falls back to a direct Docker Hub bootstrap
# and these images are re-pulled automatically. Revisit if a snapshot-based
# Harbor migration is later required.
docker pull 192.168.40.10/dockerhub/goharbor/harbor-core:v2.11.0
docker pull 192.168.40.10/dockerhub/goharbor/harbor-db:v2.11.0
docker pull 192.168.40.10/dockerhub/goharbor/harbor-jobservice:v2.11.0
docker pull 192.168.40.10/dockerhub/goharbor/harbor-portal:v2.11.0
docker pull 192.168.40.10/dockerhub/goharbor/harbor-registryctl:v2.11.0
docker pull 192.168.40.10/dockerhub/goharbor/registry-photon:v2.11.0
docker pull 192.168.40.10/dockerhub/goharbor/nginx-photon:v2.11.0
docker pull 192.168.40.10/dockerhub/goharbor/redis-photon:v2.11.0
docker pull 192.168.40.10/dockerhub/goharbor/trivy-adapter-photon:v2.11.0
```

**Wait for Trivy scan results and check for CRITICAL findings before proceeding to Stage 2:**

```bash
./with-secrets bash -c \
  'curl -s -u "admin:${HARBOR_ADMIN_PASSWORD}" \
    "http://192.168.40.10/api/v2.0/projects/ghcr/repositories/goauthentik%2Fserver/artifacts?with_scan_overview=true" | \
    jq ".[0].scan_overview"'
```

Do not proceed to Stage 2 if any pre-seeded image has an unacknowledged CRITICAL finding.
Check whether a newer patch version is available and pull it instead.

---

## Part B — Stage 2: Production containers and Stage 1 teardown

Stage 2 deploys permanent Portainer, Harbor, and CI runner at the same VMIDs as Stage 1.
The deployment order is chosen to keep Stage 1 Harbor running as long as possible, since
Stage 2 Portainer and CI runner pull their images from it.

The recommended deployment order is:
1. Portainer (Stage 2) — Stage 1 Harbor still running
2. CI runner (Stage 2) — Stage 1 Harbor still running
3. Harbor (Stage 2) — Stage 1 Harbor torn down immediately before Stage 2 Harbor is applied

All stage-2 Ansible playbooks reference images at `192.168.40.10/...` via robot account
authentication. No direct Docker Hub pulls occur for Stage 2 Portainer or CI runner.

---

### B1 — Portainer (permanent)

The permanent Portainer LXC is functionally identical to Stage 1 but its Ansible playbook
references all images from Harbor rather than Docker Hub. Deploy after Stage 1 Harbor (A2)
and pre-seeding (A4) are confirmed complete.

| Field | Value |
|---|---|
| VMID | 20020 |
| Zone | `mgmt_seg` |
| IP | `192.168.20.20/24` |
| Gateway | `192.168.20.1` |
| Image source | Stage 1 Harbor (`192.168.40.10`) |

**Secrets required** (keys in `terraform/secrets.enc.yaml`):

- `TF_VAR_pm_api_token_id`, `TF_VAR_pm_api_token_secret` — Proxmox API authentication
- `TF_VAR_lxc_password` — LXC root password
- `TF_VAR_portainer_admin_password` — Portainer admin account
- `HARBOR_ROBOT_USER`, `HARBOR_ROBOT_PASSWORD` — robot account for image pulls

**Tear down Stage 1 Portainer, then deploy Stage 2:**

```bash
# Destroy Stage 1
cd /home/steve/git/proxmox-homelab/terraform/lxc/stacks/portainer-stack
/home/steve/git/proxmox-homelab/with-secrets terragrunt destroy

# Apply Stage 2 (same stack directory, updated to use Harbor image refs)
/home/steve/git/proxmox-homelab/with-secrets terragrunt apply

cd /home/steve/git/proxmox-homelab
./with-secrets ansible-playbook \
  -i "192.168.20.20," \
  terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml
```

**Validate:**

```bash
curl -s http://192.168.20.20:9000/api/system/status | jq .Version
# Expect: a non-empty version string
```

**Record in NetBox:** Update the VMID 20020 record to reflect Stage 2 status.

---

### B2 — CI runner (permanent)

The permanent CI runner replaces Stage 1 and runs all subsequent self-hosted GitHub Actions
jobs. A fresh runner registration token is required. After Stage 2 CI runner is registered,
disable or remove the Stage 1 runner from GitHub Actions Settings to avoid duplicate
execution.

| Field | Value |
|---|---|
| VMID | 10063 |
| Zone | `build_seg` |
| IP | `192.168.10.63/24` |
| Gateway | `192.168.10.1` |
| Image source | Stage 1 Harbor (`192.168.40.10`) |

**Secrets required** (keys in `terraform/secrets.enc.yaml`):

- `TF_VAR_pm_api_token_id`, `TF_VAR_pm_api_token_secret` — Proxmox API authentication
- `TF_VAR_lxc_password` — LXC root password
- `HARBOR_ROBOT_USER`, `HARBOR_ROBOT_PASSWORD` — robot account for image pulls
- `GH_RUNNER_TOKEN` — fresh runner registration token (valid for 60 minutes)

**Tear down Stage 1 CI runner, then deploy Stage 2:**

```bash
# Destroy Stage 1
cd /home/steve/git/proxmox-homelab/terraform/lxc/stacks/ci-runner-01
/home/steve/git/proxmox-homelab/with-secrets terragrunt destroy

# Apply Stage 2
/home/steve/git/proxmox-homelab/with-secrets terragrunt apply

cd /home/steve/git/proxmox-homelab
./with-secrets ansible-playbook \
  -i "192.168.10.63," \
  terraform/lxc/ansible/playbooks/deploy-ci-runner.yml
```

**Validate:**

```bash
# Confirm runner appears as online: GitHub → Repository → Settings → Actions → Runners
# Run a self-hosted pipeline job and confirm completion:
gh workflow run validate.yml --ref docs/repo-review
gh run list --workflow=validate.yml --limit 1
```

**Remove Stage 1 runner from GitHub:**

```bash
# In GitHub UI: Settings → Actions → Runners → select the offline Stage 1 runner → Remove
```

**Record in NetBox:** Update the VMID 10063 record to reflect Stage 2 status.

---

### B3 — Harbor (permanent)

Harbor is replaced last, after Stage 2 Portainer and CI runner are confirmed healthy. The
Stage 2 Harbor LXC uses the same stack configuration and plays the same role as Stage 1
Harbor. Because Harbor is replacing itself, Stage 2 Harbor bootstraps its component images
from Docker Hub on first boot (or from Stage 1 Harbor if the pre-seeded Harbor component
images are still available — see Part A seeding note). Once Stage 2 Harbor is healthy,
configure proxy cache projects and run `harbor_postconfigure` to restore robot account,
scan-on-push, and GC schedule settings.

| Field | Value |
|---|---|
| VMID | 40010 |
| Zone | `infra_seg` |
| IP | `192.168.40.10/24` |
| Gateway | `192.168.40.1` |
| Image source | Stage 1 Harbor or Docker Hub (bootstrap only) |

**Secrets required** (keys in `terraform/secrets.enc.yaml`):

- `TF_VAR_pm_api_token_id`, `TF_VAR_pm_api_token_secret` — Proxmox API authentication
- `TF_VAR_lxc_password` — LXC root password
- `HARBOR_ADMIN_PASSWORD` — Harbor admin account

**Tear down Stage 1 Harbor, then deploy Stage 2:**

```bash
# Destroy Stage 1 Harbor (brief downtime begins here)
cd /home/steve/git/proxmox-homelab/terraform/lxc/stacks/harbor-stack
/home/steve/git/proxmox-homelab/with-secrets terragrunt destroy

# Apply Stage 2 Harbor at same VMID
/home/steve/git/proxmox-homelab/with-secrets terragrunt apply

cd /home/steve/git/proxmox-homelab
./with-secrets ansible-playbook \
  -i "192.168.40.10," \
  terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml
```

**Validate:**

```bash
curl -s http://192.168.40.10/api/v2.0/ping
# Expect: "Pong"

./with-secrets bash -c \
  'curl -sk -u "admin:${HARBOR_ADMIN_PASSWORD}" http://192.168.40.10/api/v2.0/scanners | jq ".[] | {name, is_default, health}"'
# Expect: {"name":"Trivy","is_default":true,"health":"healthy"}
```

**Restore proxy cache configuration and robot account** by running Phase 03b
(`harbor_postconfigure`) against the fresh Stage 2 Harbor instance:

```bash
./with-secrets ansible-playbook \
  -i "192.168.40.10," \
  terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml \
  --tags postconfigure
```

Re-pull the Phase 04 images through the Stage 2 Harbor proxy cache (Stage 1 Harbor's
cached images do not carry over):

```bash
./with-secrets bash -c \
  'echo "${HARBOR_ROBOT_PASSWORD}" | docker login 192.168.40.10 -u "${HARBOR_ROBOT_USER}" --password-stdin'
# Then re-run the docker pull commands from Part A step A4
```

**Record in NetBox:** Update the VMID 40010 record to reflect Stage 2 status and note that
Phase 03b postconfigure has been applied.

---

## Acceptance criteria

- [ ] Stage 1 Portainer is running at `192.168.20.20` (VMID 20020) and API responds
- [ ] Stage 1 Harbor is running at `192.168.40.10` (VMID 40010) and returns `"Pong"`
- [ ] Harbor Trivy scanner health is `"healthy"`
- [ ] Harbor proxy cache projects (`dockerhub`, `ghcr`, `quay`, `lscr`) exist
- [ ] Harbor robot account `robot$ci-runner` exists and can authenticate
- [ ] Stage 1 CI runner registered with GitHub Actions and at least one pipeline run succeeded
- [ ] All Phase 04 images listed in Part A step A4 are available in Harbor and scanned
- [ ] No pre-seeded image has an unacknowledged CRITICAL Trivy finding
- [ ] Stage 2 Portainer is running at `192.168.20.20` (VMID 20020, replacing Stage 1)
- [ ] Stage 2 CI runner is running at `192.168.10.63` (VMID 10063, replacing Stage 1)
- [ ] Stage 2 Harbor is running at `192.168.40.10` (VMID 40010, replacing Stage 1)
- [ ] Stage 1 Portainer LXC is absent (`qm status 20020` returns not found or stopped)
- [ ] Stage 1 Harbor LXC is absent (`qm status 40010` returns not found or stopped)
- [ ] Stage 1 CI runner LXC is absent (`qm status 10063` returns not found or stopped)
- [ ] Stage 1 runner removed from GitHub Actions Settings
- [ ] Harbor postconfigure re-applied on Stage 2 Harbor
- [ ] Phase 04 images re-pulled and available in Stage 2 Harbor
- [ ] NetBox records updated for VMIDs 20020, 40010, and 10063

# 00c-bootstrap-01 — Stage 1: Temporary bootstrap containers

> Historical task packet.
> This document reflects the earlier `pve-test` bootstrap workflow and retired
> branch model.
> Keep it as implementation history only. For current workflow and environment
> rules, use [docs/workflow/branch-model.md](../../workflow/branch-model.md)
> and [docs/workflow/environments.md](../../workflow/environments.md).

## Status

PENDING

## Phase

Phase 00c — Bootstrap Sequence

## GitHub Issue

Not assigned yet.

## Prerequisites

- Phase 03d complete — `with-secrets` is merged and executable at the repository root
- Age private key present at `~/.config/sops/age/keys.txt`
- pve-test is reachable and Proxmox VE is installed
- `storage-template` pool exists with `debian-13.1-2-docker-template.tar.gz`
- `infrastructure-containers` pool exists
- SDN VLAN zones are applied to `pve-test`: `mgmt_seg` (VLAN 20), `infra_seg` (VLAN 40),
  `build_seg` (VLAN 10) — use `ansible/00-initial-setup/proxmox-sdn-setup.yml` if not yet
  applied
- MikroTik VLAN interfaces and IP gateways configured for all three zones
- `terraform/secrets.enc.yaml` contains real values for:
  - `TF_VAR_proxmox_api_url`, `TF_VAR_pm_api_token_id`, `TF_VAR_pm_api_token_secret`
  - `TF_VAR_lxc_password`
  - `TF_VAR_portainer_admin_password`
  - `HARBOR_ADMIN_PASSWORD`
  - `HARBOR_ROBOT_USER`, `HARBOR_ROBOT_PASSWORD`

## Objective

Three temporary containers are running on `pve-test`: Portainer (VMID 120), Harbor (VMID
121), and CI runner (VMID 141). Harbor is configured with proxy cache projects, Trivy
scanning, robot account, and GC schedule. All Stage 2 and Phase 04 required images are
pre-pulled through Harbor's proxy cache and have no CRITICAL Trivy findings. At least one
self-hosted GitHub Actions pipeline run has completed successfully.

## Scope

- Deploy Portainer LXC (VMID 120) on `mgmt_seg` at `10.57.1.20`
- Deploy Harbor LXC (VMID 121) on `infra_seg` at `10.57.3.10`
- Run `harbor_postconfigure` (proxy caches, robot account, Trivy, GC schedule)
- Deploy CI runner LXC (VMID 141) on `build_seg` at `10.57.0.63`
- Register the CI runner with GitHub Actions
- Pre-seed Harbor with all Stage 2 and Phase 04 images
- Verify Trivy scan results — no unacknowledged CRITICAL findings

## Out of Scope

- Deploying Stage 2 (permanent) containers — that is task 00c-bootstrap-02
- Deploying Phase 04 services (Authentik, Traefik, step-ca, monitoring)
- NetBox deployment — use ping and Proxmox API verification instead
- Configuring Harbor project namespaces beyond the proxy cache projects
- Tearing down any container

## Inputs

- [docs/plan/phase-00c-bootstrap-sequence.md](../phase-00c-bootstrap-sequence.md)
- [docs/design/bootstrap.md](../../design/bootstrap.md)
- `terraform/lxc/stacks/portainer-stack/`
- `terraform/lxc/stacks/harbor-stack/`
- `terraform/lxc/stacks/ci-runner-01/`
- `terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml`
- `terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml`
- `terraform/lxc/ansible/playbooks/deploy-ci-runner.yml`

## Expected Outputs

- VMID 120 running at `10.57.1.20` — Portainer API responds
- VMID 121 running at `10.57.3.10` — Harbor API returns `"Pong"`, Trivy is healthy
- VMID 141 running at `10.57.0.63` — CI runner registered and at least one job succeeded
- Harbor proxy cache projects exist for `dockerhub`, `ghcr`, `quay`, `lscr`
- `robot$ci-runner` account exists and can authenticate
- All Phase 04 images pre-pulled and scanned in Harbor with no unacknowledged CRITICAL
  findings

## Constraints and Conventions

- All `terragrunt apply` and `ansible-playbook` commands must be wrapped with
  `./with-secrets`. Do not use `source .env` or any Bitwarden CLI invocation.
- Stage 1 containers pull images directly from Docker Hub. This is the only phase where
  direct Docker Hub pulls are permitted at deployment time.
- Do not proceed to Step 6 (pre-seeding) if any earlier validation check fails. The
  pre-seeding step depends on Harbor being fully configured.
- Do not run `terragrunt destroy` in this task. Teardown happens in task 00c-bootstrap-02.
- Secret values must never appear in the terminal history, log output, or any committed
  file. Key names only.
- If the GitHub Actions runner registration token expires (60-minute lifetime), retrieve a
  fresh one from GitHub before re-running the CI runner deployment step.

## Acceptance Criteria

- [ ] VMID 120 exists on `pve-test` and Portainer API at `10.57.1.20:9000` responds
- [ ] VMID 121 exists on `pve-test` and `curl http://10.57.3.10/api/v2.0/ping` returns `"Pong"`
- [ ] Harbor Trivy scanner health is `"healthy"`
- [ ] Harbor proxy cache projects `dockerhub`, `ghcr`, `quay`, and `lscr` exist
- [ ] `robot$ci-runner` account exists in Harbor robot accounts list
- [ ] VMID 141 exists on `pve-test` and the runner shows as `Idle` in GitHub Actions Settings
- [ ] At least one self-hosted GitHub Actions workflow run has completed successfully
- [ ] All images listed in the pre-seeding step are available in Harbor
- [ ] No pre-seeded image has an unacknowledged CRITICAL Trivy finding

## Session Prompt

```text
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Execute Stage 1 of the bootstrap sequence. Deploy three temporary containers
(Portainer, Harbor, CI runner), configure Harbor, pre-seed images for Stage 2 and
Phase 04, and validate CI pipeline execution.

This task makes NO changes to source code, Terraform, Ansible, or shell scripts.
It deploys infrastructure and commits nothing.

READ THESE FILES FIRST (before running any command):
  docs/plan/phase-00c-bootstrap-sequence.md
  docs/design/bootstrap.md
  docs/plan/tasks/00c-bootstrap-01-stage1-temporary.md

---

BRANCH: No new branch needed for this task — it is infrastructure-only and commits nothing.

---

STEP 0 — Verify workstation prerequisites:

  # with-secrets must exist and be executable
  ls -la /home/steve/git/proxmox-homelab/with-secrets

  # Age key must be present
  ls -la ~/.config/sops/age/keys.txt

  # SOPS decryption must work
  SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt \
    sops --decrypt /home/steve/git/proxmox-homelab/terraform/secrets.enc.yaml > /dev/null
  echo "SOPS: OK"

  # with-secrets must inject credentials
  cd /home/steve/git/proxmox-homelab
  ./with-secrets echo "secrets: OK"

---

STEP 1 — Verify pve-test and SDN prerequisites:

  ssh root@pve-test.gibbsgreatly.xyz "pvesh get /nodes/pve-test/sdn/zones"
  # Expect: tvmgmt, tvinfra, tvsegb (or similar — all three zone types present)

  ssh root@pve-test.gibbsgreatly.xyz "pvesm list storage-template | grep debian-13.1-2-docker-template"
  # Expect: at least one match

  ssh root@pve-test.gibbsgreatly.xyz "pvesm list infrastructure-containers"
  # Expect: LVM-thin or ZFS pool listing (not an error)

---

STEP 2 — Deploy Portainer (VMID 120, mgmt_seg, 10.57.1.20):

  # Verify IP is free
  ping -c 2 10.57.1.20
  # Expect: no reply (Request timeout)

  cd /home/steve/git/proxmox-homelab/terraform/lxc/stacks/portainer-stack
  /home/steve/git/proxmox-homelab/with-secrets terragrunt apply

  cd /home/steve/git/proxmox-homelab
  ./with-secrets ansible-playbook \
    -i "10.57.1.20," \
    terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml

  # Validate
  curl -s http://10.57.1.20:9000/api/system/status | jq .Version
  # Expect: non-empty version string

---

STEP 3 — Deploy Harbor (VMID 121, infra_seg, 10.57.3.10):

  # Verify IP is free
  ping -c 2 10.57.3.10
  # Expect: no reply

  cd /home/steve/git/proxmox-homelab/terraform/lxc/stacks/harbor-stack
  /home/steve/git/proxmox-homelab/with-secrets terragrunt apply

  cd /home/steve/git/proxmox-homelab
  ./with-secrets ansible-playbook \
    -i "10.57.3.10," \
    terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml

  # Validate Harbor API
  curl -s http://10.57.3.10/api/v2.0/ping
  # Expect: "Pong"

  # Validate Trivy scanner
  ./with-secrets bash -c \
    'curl -sk -u "admin:${HARBOR_ADMIN_PASSWORD}" \
      http://10.57.3.10/api/v2.0/scanners | jq ".[] | {name, is_default, health}"'
  # Expect: {"name":"Trivy","is_default":true,"health":"healthy"}

  # Confirm robot$ci-runner account exists
  ./with-secrets bash -c \
    'curl -sk -u "admin:${HARBOR_ADMIN_PASSWORD}" \
      http://10.57.3.10/api/v2.0/robots | jq ".[].name"'
  # Expect: "robot$ci-runner" in the list

---

STEP 4 — Deploy CI runner (VMID 141, build_seg, 10.57.0.63):

  # Retrieve a fresh registration token before running this step.
  # GitHub → Repository → Settings → Actions → Runners → New self-hosted runner
  # Copy the --token value from the displayed command. Token is valid for 60 minutes.
  # Store it in terraform/secrets.enc.yaml as GH_RUNNER_TOKEN before proceeding:
  #   SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.enc.yaml

  # Verify IP is free
  ping -c 2 10.57.0.63
  # Expect: no reply

  cd /home/steve/git/proxmox-homelab/terraform/lxc/stacks/ci-runner-01
  /home/steve/git/proxmox-homelab/with-secrets terragrunt apply

  cd /home/steve/git/proxmox-homelab
  ./with-secrets ansible-playbook \
    -i "10.57.0.63," \
    terraform/lxc/ansible/playbooks/deploy-ci-runner.yml

  # Validate: runner must show as Idle in GitHub UI
  # GitHub → Repository → Settings → Actions → Runners → ci-runner-01 → status: Idle

  # Trigger a self-hosted workflow run
  gh workflow run validate.yml --ref baseline/teardown-validated
  # Wait approximately 2 minutes, then check:
  gh run list --workflow=validate.yml --limit 3
  # Expect: at least one completed run with status "success" or "completed"

---

STEP 5 — Authenticate to Harbor for pre-seeding:

  ./with-secrets bash -c \
    'echo "${HARBOR_ROBOT_PASSWORD}" | \
      docker login 10.57.3.10 -u "${HARBOR_ROBOT_USER}" --password-stdin'
  # Expect: "Login Succeeded"

---

STEP 6 — Pre-seed Harbor with Stage 2 and Phase 04 images:

  # Phase 04 images — Authentik
  AUTHENTIK_VERSION="2024.12.3"
  docker pull 10.57.3.10/ghcr/goauthentik/server:${AUTHENTIK_VERSION}
  docker pull 10.57.3.10/dockerhub/library/postgres:16-alpine
  docker pull 10.57.3.10/dockerhub/library/redis:alpine

  # Phase 04 images — Traefik
  TRAEFIK_VERSION="v3.3"
  docker pull 10.57.3.10/dockerhub/library/traefik:${TRAEFIK_VERSION}

  # Phase 04 images — Monitoring stack
  GRAFANA_VERSION="11.5.2"
  VM_VERSION="v1.101.0"
  LOKI_VERSION="3.4.2"
  PROMTAIL_VERSION="3.4.2"
  docker pull 10.57.3.10/dockerhub/grafana/grafana-oss:${GRAFANA_VERSION}
  docker pull 10.57.3.10/dockerhub/victoriametrics/victoria-metrics:${VM_VERSION}
  docker pull 10.57.3.10/dockerhub/grafana/loki:${LOKI_VERSION}
  docker pull 10.57.3.10/dockerhub/grafana/promtail:${PROMTAIL_VERSION}

  # Phase 03b/04 images — NetBox
  docker pull 10.57.3.10/dockerhub/netboxcommunity/netbox:latest
  docker pull 10.57.3.10/dockerhub/library/valkey:8-alpine

  # Stage 2 bootstrap-container images — Portainer and CI runner
  docker pull 10.57.3.10/dockerhub/portainer/portainer-ce:latest
  docker pull 10.57.3.10/dockerhub/portainer/agent:latest

  # Stage 2 Harbor component images
  HARBOR_VERSION="v2.11.0"
  docker pull 10.57.3.10/dockerhub/goharbor/harbor-core:${HARBOR_VERSION}
  docker pull 10.57.3.10/dockerhub/goharbor/harbor-db:${HARBOR_VERSION}
  docker pull 10.57.3.10/dockerhub/goharbor/harbor-jobservice:${HARBOR_VERSION}
  docker pull 10.57.3.10/dockerhub/goharbor/harbor-portal:${HARBOR_VERSION}
  docker pull 10.57.3.10/dockerhub/goharbor/harbor-registryctl:${HARBOR_VERSION}
  docker pull 10.57.3.10/dockerhub/goharbor/registry-photon:${HARBOR_VERSION}
  docker pull 10.57.3.10/dockerhub/goharbor/nginx-photon:${HARBOR_VERSION}
  docker pull 10.57.3.10/dockerhub/goharbor/redis-photon:${HARBOR_VERSION}
  docker pull 10.57.3.10/dockerhub/goharbor/trivy-adapter-photon:${HARBOR_VERSION}

---

STEP 7 — Check Trivy scan results:

  # Harbor scans images automatically after pull. Wait 3–5 minutes, then check:
  ./with-secrets bash -c \
    'curl -s -u "admin:${HARBOR_ADMIN_PASSWORD}" \
      "http://10.57.3.10/api/v2.0/projects/ghcr/repositories/goauthentik%2Fserver/artifacts?with_scan_overview=true" | \
      jq ".[0].scan_overview"'

  # Repeat for other high-priority images (traefik, grafana-oss, etc.)
  # If any image shows CRITICAL severity findings, check for a newer version before
  # proceeding. Do not move to Stage 2 with unacknowledged CRITICAL findings.

---

DONE WHEN:
  - Portainer responds at http://10.57.1.20:9000/api/system/status
  - Harbor responds "Pong" at http://10.57.3.10/api/v2.0/ping and Trivy is healthy
  - CI runner shows as Idle in GitHub Actions and at least one pipeline run succeeded
  - All images in STEP 6 are available in Harbor
  - No unacknowledged CRITICAL Trivy findings on pre-seeded images
  - Task 00c-bootstrap-02 can begin
```

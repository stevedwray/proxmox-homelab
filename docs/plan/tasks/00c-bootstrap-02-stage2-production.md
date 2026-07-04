# 00c-bootstrap-02 — Stage 2: Production containers and Stage 1 teardown

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

- Task 00c-bootstrap-01 complete — all acceptance criteria met:
  - Portainer, Harbor, and CI runner running as Stage 1 temporary containers
  - Harbor pre-seeded with all Stage 2 and Phase 04 images
  - CI runner registered and at least one pipeline run succeeded
  - No unacknowledged CRITICAL Trivy findings on pre-seeded images
- `HARBOR_ROBOT_USER` and `HARBOR_ROBOT_PASSWORD` stored in `terraform/secrets.enc.yaml`
- NetBox is either deployed (VMID 143, `10.57.3.12`) or acknowledged as not yet available
  (IP allocations recorded manually in this case)

## Objective

The three temporary Stage 1 containers (Portainer VMID 120, Harbor VMID 121, CI runner
VMID 141) are replaced by permanent Stage 2 containers at the same VMIDs. Stage 2
containers source their images from Stage 1 Harbor rather than Docker Hub. Stage 1 Harbor
is the last container replaced — it remains running to serve Stage 2 Portainer and CI
runner images during their deployment. After Stage 2 Harbor is healthy and Harbor
postconfigure has been re-applied, all Stage 1 containers are confirmed absent and Phase 04
can begin.

## Scope

- Deploy permanent Portainer at VMID 120 (`10.57.1.20`), sourcing images from Stage 1
  Harbor
- Deploy permanent CI runner at VMID 141 (`10.57.0.63`), sourcing images from Stage 1
  Harbor
- Deploy permanent Harbor at VMID 121 (`10.57.3.10`), replacing Stage 1 Harbor
- Re-apply `harbor_postconfigure` on Stage 2 Harbor (robot account, scan-on-push,
  proxy cache projects, GC schedule)
- Re-pull Phase 04 images through Stage 2 Harbor proxy cache
- Confirm all three Stage 1 containers are absent
- Register Stage 2 CI runner with GitHub Actions and remove Stage 1 runner
- Record VMID 120, 121, and 141 transitions in NetBox

## Out of Scope

- Deploying Phase 04 services (Authentik, Traefik, step-ca, monitoring)
- Configuring Authentik SSO for Harbor, Portainer, or CI
- Running Phase 05 supply chain jobs on the Stage 2 CI runner

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

- VMID 120 running permanent Portainer, images from Harbor
- VMID 121 running permanent Harbor with postconfigure applied
- VMID 141 running permanent CI runner, images from Harbor
- Stage 1 LXCs absent from `pve-test`
- Stage 1 runner removed from GitHub Actions Settings
- Phase 04 images available in Stage 2 Harbor

## Constraints and Conventions

- All `terragrunt` and `ansible-playbook` commands must be wrapped with `./with-secrets`.
  Do not use `source .env` or any Bitwarden CLI invocation.
- The deployment order is fixed: Portainer → CI runner → Harbor. Do not replace Stage 1
  Harbor until Stage 2 Portainer and CI runner are confirmed healthy. Stage 1 Harbor is
  the image source for Stage 2 Portainer and CI runner deployments.
- Between `terragrunt destroy` and `terragrunt apply` for each VMID, there is a brief
  downtime window. This is expected and acceptable during the bootstrap phase.
- A fresh GitHub Actions runner registration token (valid for 60 minutes) is required
  before deploying the Stage 2 CI runner. Retrieve it from GitHub immediately before that
  step.
- After Stage 1 Harbor is destroyed, the Stage 2 Harbor bootstrap will pull its component
  images from Docker Hub if the Stage 1 pre-seeded Harbor component images are no longer
  available. This is an acceptable fallback.
- If NetBox is not yet deployed, record the Stage 2 transitions as inline notes in this
  task document rather than skipping the step entirely. NetBox can be updated when deployed
  in Phase 04.

## Acceptance Criteria

- [ ] VMID 120: Stage 2 Portainer running at `10.57.1.20`, API responds
- [ ] VMID 141: Stage 2 CI runner registered as `Idle` in GitHub Actions, labels
  `self-hosted`, `pve-test`, `build`
- [ ] VMID 121: Stage 2 Harbor running at `10.57.3.10`, `curl http://10.57.3.10/api/v2.0/ping`
  returns `"Pong"`
- [ ] Stage 2 Harbor Trivy scanner health is `"healthy"`
- [ ] Harbor proxy cache projects `dockerhub`, `ghcr`, `quay`, `lscr` exist on Stage 2
  Harbor
- [ ] `robot$ci-runner` exists on Stage 2 Harbor
- [ ] Stage 1 Portainer LXC is absent (VMID 120 shows not found or stopped in Proxmox)
- [ ] Stage 1 Harbor LXC is absent (VMID 121 shows not found or stopped in Proxmox)
- [ ] Stage 1 CI runner LXC is absent (VMID 141 shows not found or stopped in Proxmox)
- [ ] Stage 1 runner removed from GitHub Actions Runner list (or marked offline/deleted)
- [ ] Phase 04 images re-pulled and available in Stage 2 Harbor
- [ ] NetBox records updated (or noted as pending if NetBox not yet deployed)

## Session Prompt

```text
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Execute Stage 2 of the bootstrap sequence. Replace the three Stage 1 temporary
containers (Portainer, Harbor, CI runner) with permanent Stage 2 containers at the same
VMIDs. Tear down Stage 1 containers and confirm they are gone. Stage 1 must be fully
verified (task 00c-bootstrap-01 complete) before starting this task.

This task makes NO changes to source code, Terraform, Ansible, or shell scripts.

READ THESE FILES FIRST (before running any command):
  docs/plan/phase-00c-bootstrap-sequence.md
  docs/design/bootstrap.md
  docs/plan/tasks/00c-bootstrap-02-stage2-production.md

---

CRITICAL DEPLOYMENT ORDER:
  1. Portainer (VMID 120) — Stage 1 Harbor is still running; Stage 2 Portainer pulls
     from it
  2. CI runner (VMID 141) — Stage 1 Harbor is still running; Stage 2 CI runner pulls
     from it
  3. Harbor (VMID 121) — Stage 1 Harbor is destroyed immediately before Stage 2 Harbor
     is applied. This is the only step with Docker Hub fallback.

---

STEP 0 — Verify Stage 1 is still healthy and stage 2 prerequisites are met:

  # Stage 1 containers must still be running
  curl -s http://10.57.1.20:9000/api/system/status | jq .Version
  # Expect: non-empty version string

  curl -s http://10.57.3.10/api/v2.0/ping
  # Expect: "Pong"

  # Confirm pre-seeded images exist in Stage 1 Harbor
  ./with-secrets bash -c \
    'curl -s -u "admin:${HARBOR_ADMIN_PASSWORD}" \
      "http://10.57.3.10/api/v2.0/projects/dockerhub/repositories" | jq ".[].name"'
  # Expect: portainer/portainer-ce, portainer/agent, and others listed

  # Confirm robot$ci-runner account exists
  ./with-secrets bash -c \
    'curl -s -u "admin:${HARBOR_ADMIN_PASSWORD}" \
      "http://10.57.3.10/api/v2.0/robots" | jq ".[].name"'
  # Expect: "robot$ci-runner"

---

STEP 1 — Deploy Stage 2 Portainer (VMID 120, mgmt_seg, 10.57.1.20):

  # Destroy Stage 1 Portainer
  cd /home/steve/git/proxmox-homelab/terraform/lxc/stacks/portainer-stack
  /home/steve/git/proxmox-homelab/with-secrets terragrunt destroy
  # Confirm VMID 120 is gone:
  ssh root@pve-test.gibbsgreatly.xyz "qm status 120 2>&1 || echo 'VMID 120: absent'"

  # Apply Stage 2 Portainer (stack.yaml and playbook should now reference Harbor image refs)
  /home/steve/git/proxmox-homelab/with-secrets terragrunt apply

  cd /home/steve/git/proxmox-homelab
  ./with-secrets ansible-playbook \
    -i "10.57.1.20," \
    terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml

  # Validate Stage 2 Portainer
  curl -s http://10.57.1.20:9000/api/system/status | jq .Version
  # Expect: non-empty version string

---

STEP 2 — Deploy Stage 2 CI runner (VMID 141, build_seg, 10.57.0.63):

  # Retrieve a FRESH runner registration token before continuing.
  # GitHub → Repository → Settings → Actions → Runners → New self-hosted runner
  # Copy the --token value. Token is valid for 60 minutes.
  # Update secrets.enc.yaml with the new token:
  #   SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.enc.yaml
  # Set GH_RUNNER_TOKEN to the new value, save, and close.

  # Destroy Stage 1 CI runner
  cd /home/steve/git/proxmox-homelab/terraform/lxc/stacks/ci-runner-01
  /home/steve/git/proxmox-homelab/with-secrets terragrunt destroy
  # Confirm VMID 141 is gone:
  ssh root@pve-test.gibbsgreatly.xyz "qm status 141 2>&1 || echo 'VMID 141: absent'"

  # Apply Stage 2 CI runner
  /home/steve/git/proxmox-homelab/with-secrets terragrunt apply

  cd /home/steve/git/proxmox-homelab
  ./with-secrets ansible-playbook \
    -i "10.57.0.63," \
    terraform/lxc/ansible/playbooks/deploy-ci-runner.yml

  # Validate: Stage 2 runner shows as Idle in GitHub Actions Settings
  # GitHub → Repository → Settings → Actions → Runners → ci-runner-01 → Idle

  # Trigger a validation workflow run on Stage 2 runner
  gh workflow run validate.yml --ref baseline/teardown-validated
  gh run list --workflow=validate.yml --limit 3
  # Expect: at least one run completed on the Stage 2 runner

  # Remove Stage 1 runner from GitHub Actions
  # GitHub → Settings → Actions → Runners → select the offline Stage 1 runner → Remove

---

STEP 3 — Deploy Stage 2 Harbor (VMID 121, infra_seg, 10.57.3.10):

  # NOTE: Stage 1 Harbor will be destroyed in this step. Brief downtime is expected.
  # Stage 2 Portainer and CI runner (Steps 1 and 2) must be healthy before proceeding.

  # Destroy Stage 1 Harbor
  cd /home/steve/git/proxmox-homelab/terraform/lxc/stacks/harbor-stack
  /home/steve/git/proxmox-homelab/with-secrets terragrunt destroy
  # Confirm VMID 121 is gone:
  ssh root@pve-test.gibbsgreatly.xyz "qm status 121 2>&1 || echo 'VMID 121: absent'"

  # Apply Stage 2 Harbor at VMID 121
  /home/steve/git/proxmox-homelab/with-secrets terragrunt apply

  cd /home/steve/git/proxmox-homelab
  ./with-secrets ansible-playbook \
    -i "10.57.3.10," \
    terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml

  # Validate Stage 2 Harbor
  curl -s http://10.57.3.10/api/v2.0/ping
  # Expect: "Pong"

  ./with-secrets bash -c \
    'curl -sk -u "admin:${HARBOR_ADMIN_PASSWORD}" \
      http://10.57.3.10/api/v2.0/scanners | jq ".[] | {name, is_default, health}"'
  # Expect: {"name":"Trivy","is_default":true,"health":"healthy"}

  # Confirm deploy-harbor-stack.yml ran harbor_postconfigure (proxy caches, robot, GC).
  # If postconfigure did not run or is uncertain, run explicitly:
  ./with-secrets ansible-playbook \
    -i "10.57.3.10," \
    terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml \
    --tags postconfigure

  # Confirm robot$ci-runner exists on Stage 2 Harbor
  ./with-secrets bash -c \
    'curl -s -u "admin:${HARBOR_ADMIN_PASSWORD}" \
      "http://10.57.3.10/api/v2.0/robots" | jq ".[].name"'
  # Expect: "robot$ci-runner"

---

STEP 4 — Re-seed Stage 2 Harbor with Phase 04 images:

  # Stage 1 Harbor's cached images do not carry over. Re-run the full pre-seeding sequence.
  ./with-secrets bash -c \
    'echo "${HARBOR_ROBOT_PASSWORD}" | \
      docker login 10.57.3.10 -u "${HARBOR_ROBOT_USER}" --password-stdin'
  # Expect: "Login Succeeded"

  # Re-pull Phase 04 images
  AUTHENTIK_VERSION="2024.12.3"
  docker pull 10.57.3.10/ghcr/goauthentik/server:${AUTHENTIK_VERSION}
  docker pull 10.57.3.10/dockerhub/library/postgres:16-alpine
  docker pull 10.57.3.10/dockerhub/library/redis:alpine

  TRAEFIK_VERSION="v3.3"
  docker pull 10.57.3.10/dockerhub/library/traefik:${TRAEFIK_VERSION}

  GRAFANA_VERSION="11.5.2"
  VM_VERSION="v1.101.0"
  LOKI_VERSION="3.4.2"
  PROMTAIL_VERSION="3.4.2"
  docker pull 10.57.3.10/dockerhub/grafana/grafana-oss:${GRAFANA_VERSION}
  docker pull 10.57.3.10/dockerhub/victoriametrics/victoria-metrics:${VM_VERSION}
  docker pull 10.57.3.10/dockerhub/grafana/loki:${LOKI_VERSION}
  docker pull 10.57.3.10/dockerhub/grafana/promtail:${PROMTAIL_VERSION}

  docker pull 10.57.3.10/dockerhub/netboxcommunity/netbox:latest
  docker pull 10.57.3.10/dockerhub/library/valkey:8-alpine

---

STEP 5 — Confirm all Stage 1 containers are absent:

  ssh root@pve-test.gibbsgreatly.xyz "qm status 120 2>&1 || echo 'VMID 120: absent'"
  ssh root@pve-test.gibbsgreatly.xyz "qm status 121 2>&1 || echo 'VMID 121: absent'"
  ssh root@pve-test.gibbsgreatly.xyz "qm status 141 2>&1 || echo 'VMID 141: absent'"
  # NOTE: These are LXC containers. If qm does not apply, use pct instead:
  ssh root@pve-test.gibbsgreatly.xyz "pct status 120 2>&1 || echo 'VMID 120: absent'"
  ssh root@pve-test.gibbsgreatly.xyz "pct status 121 2>&1 || echo 'VMID 121: absent'"
  ssh root@pve-test.gibbsgreatly.xyz "pct status 141 2>&1 || echo 'VMID 141: absent'"

---

STEP 6 — Record transitions in NetBox (if NetBox is deployed):

  # NetBox is at 10.57.3.12 if deployed. If not yet deployed, record notes here instead.
  # For each VMID (120, 121, 141), update the device/VM record in NetBox to reflect:
  #   - Stage 2 status
  #   - Image source changed from Docker Hub to Harbor
  #   - Timestamp of transition

  # If NetBox is not yet deployed, record below as a note:
  #   VMID 120 (Portainer): Stage 2 deployed on <date>
  #   VMID 121 (Harbor): Stage 2 deployed on <date>
  #   VMID 141 (CI runner): Stage 2 deployed on <date>

---

DONE WHEN:
  - Stage 2 Portainer responds at http://10.57.1.20:9000/api/system/status
  - Stage 2 Harbor responds "Pong" at http://10.57.3.10/api/v2.0/ping and Trivy is healthy
  - Stage 2 CI runner shows as Idle in GitHub Actions and a pipeline run succeeded
  - Stage 1 LXCs (VMIDs 120, 121, 141) are confirmed absent from pve-test
  - Stage 1 runner is removed from GitHub Actions Settings
  - Phase 04 images are available in Stage 2 Harbor
  - Phase 04 (Core Shared Services) can begin
```

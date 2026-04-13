# 05-supply-chain-04 — Deploy Chainloop server and define workflow contract

## Status

CANCELLED

## Reason

Chainloop has no Docker Compose self-hosting path. The only supported self-hosting option is
the `oci://ghcr.io/chainloop-dev/charts/chainloop` Helm chart, which requires Kubernetes,
PostgreSQL, Vault, an OIDC provider, and an ECDSA keypair wired together by Helm init hooks.
There is no official Compose bundle. The image reference originally documented in this repo
(`ghcr/chainloop-dev/chainloop:v1.58.0`) is not a valid path in any registry — it was a
placeholder. Chainloop is deferred indefinitely until a Kubernetes layer exists in the lab.

Viable alternatives at that point: Chainloop Cloud free tier (no infrastructure required) or
K3s in a dedicated LXC with `helm install --set development=true` (requires ≥4 GB RAM).

See: docs/plans/Observations.md — Phase 05 observation 2 for full analysis.

## GitHub Issue

https://github.com/stevedwray/proxmox-homelab/issues/111

## Phase

Phase 05 — Supply Chain Security

## Prerequisites

- Task 05-01 complete — Trivy CI scan job exists
- Task 05-02 complete — Syft SBOM job exists
- Task 05-03 complete — Cosign signing job exists
- Phase 04 complete — monitoring stack running (Chainloop metrics visible)
- `192.168.1.45` available (verify in NetBox before deploying)

## Objective

Chainloop server is running at `192.168.1.45` (VMID 155), Chainloop CLI is installed on ci-runner-01, a workflow contract is defined requiring Trivy SARIF + SBOM + signature, and ci-runner-01 can connect to the Chainloop API. Contracts are **defined but NOT yet activated** — activation happens in Phase 06 when real image builds are present.

## Scope

- Create `terraform/lxc/stacks/chainloop-stack/stack.yaml`
- Copy `harbor-stack/terragrunt.hcl` to `chainloop-stack/terragrunt.hcl`
- Create `terraform/lxc/ansible/playbooks/deploy-chainloop-stack.yml` (Docker Compose)
- Add Chainloop CLI install task to `deploy-ci-runner.yml` and re-run the playbook
- Add `CHAINLOOP_TOKEN` as a GitHub Actions secret
- Define the workflow contract in `chainloop-contract.yaml` (committed to repo)
- Create the plumbing `chainloop-attest` CI job but leave it gated (inactive until Phase 06)

## Out of Scope

- Activating Chainloop CI contracts / end-to-end attestation runs (Phase 06)
- OPA/Rego policy writing beyond the contract stub (Phase 06)

## Inputs

- `docs/plan/phase-05-supply-chain.md` — Part D for compose, contract, and CI YAML
- Chainloop self-hosting docs: https://docs.chainloop.dev/getting-started/self-hosted
- Reference for stack.yaml: `terraform/lxc/stacks/harbor-stack/stack.yaml`

## Expected Outputs

- `terraform/lxc/stacks/chainloop-stack/stack.yaml` (new)
- `terraform/lxc/stacks/chainloop-stack/terragrunt.hcl` (new)
- `terraform/lxc/ansible/playbooks/deploy-chainloop-stack.yml` (new)
- `chainloop-contract.yaml` in repo root (new)
- `deploy-ci-runner.yml` updated with Chainloop CLI install
- `chainloop-attest` job in CI workflow (gated off until Phase 06)
- `.env.template` updated with `CHAINLOOP_TOKEN`

## Constraints and Conventions

- `stack.yaml` values: VMID 155, IP `192.168.1.45/24`, `cores: 2`, `memory: 2048`, `docker_storage_size: "20G"`
- All Chainloop compose images via Harbor proxy cache
- The `chainloop-attest` CI job must have `if: false` or similar gate so it does not execute until Phase 06 activates it
- `CHAINLOOP_TOKEN` must be stored only in `.env` and as a GitHub Actions secret — never hardcoded

## Acceptance Criteria

- [ ] LXC VMID 155 running at `192.168.1.45`
- [ ] Chainloop API responds at `http://192.168.1.45`
- [ ] Chainloop CLI installed on ci-runner-01 (pinned version)
- [ ] `chainloop config context list` succeeds from ci-runner-01
- [ ] `chainloop-contract.yaml` committed to repo with Trivy SARIF + SBOM + signature materials
- [ ] `chainloop-attest` CI job present in workflow but gated off
- [ ] `CHAINLOOP_TOKEN` set as GitHub Actions secret
- [ ] `.env.template` has `CHAINLOOP_TOKEN` placeholder
- [ ] Branch merged to `dev/pve-test`

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Deploy Chainloop server (VMID 155) and define the CI workflow contract.
Contracts are DEFINED but NOT ACTIVATED in this phase (activation happens in Phase 06).

CONTEXT:
- Reference for stack.yaml: terraform/lxc/stacks/harbor-stack/stack.yaml
- Full spec: docs/plan/phase-05-supply-chain.md (Part D)
- VMID 155, IP 192.168.1.45, cores 2, memory 2048, docker_storage_size 20G
- Chainloop self-hosting docs: https://docs.chainloop.dev/getting-started/self-hosted
- All Chainloop compose images must use Harbor proxy cache at 192.168.1.10

STEP 1 — Create branch:
  git checkout dev/pve-test && git pull
  git checkout -b feat/chainloop-stack

STEP 2 — Check IP availability:
  source .env
  curl -s -H "Authorization: Token ${NETBOX_API_TOKEN}" \
    "http://192.168.1.30/api/ipam/ip-addresses/?address=192.168.1.45" | jq .count
  # Must be 0

STEP 3 — Create stack files:
  - terraform/lxc/stacks/chainloop-stack/stack.yaml
  - terraform/lxc/stacks/chainloop-stack/terragrunt.hcl (copy from harbor-stack verbatim)

STEP 4 — Add CHAINLOOP_TOKEN to .env.template and .env:
  CHAINLOOP_TOKEN=   # Chainloop API token, generated after first boot

STEP 5 — Create Ansible playbook terraform/lxc/ansible/playbooks/deploy-chainloop-stack.yml:
  Follow the official Chainloop self-hosting guide for the docker-compose.yml.
  Use Harbor proxy image references (not direct pulls from Docker Hub/GHCR).

STEP 6 — Deploy:
  source .env && source .env.pve-test
  cd terraform/lxc/stacks/chainloop-stack && terragrunt apply
  cd /home/steve/git/proxmox-homelab
  ansible-playbook -i "192.168.1.45," terraform/lxc/ansible/playbooks/deploy-chainloop-stack.yml

STEP 7 — Generate API token and store it:
  # Follow the Chainloop post-install guide to create an API token
  # Store in .env as CHAINLOOP_TOKEN
  gh secret set CHAINLOOP_TOKEN -R <owner>/<repo>

STEP 8 — Install Chainloop CLI on ci-runner-01:
  Add to terraform/lxc/ansible/playbooks/deploy-ci-runner.yml:
    - name: Install Chainloop CLI
      ansible.builtin.shell: |
        curl -sSfL https://artifacts.chainloop.dev/cli/install.sh | \
          bash -s -- --version v<PIN>
      args:
        creates: /usr/local/bin/chainloop
  Re-run the playbook:
    ansible-playbook -i "10.57.0.63," terraform/lxc/ansible/playbooks/deploy-ci-runner.yml
  Verify:
    ssh root@10.57.0.63 "chainloop version"
    ssh root@10.57.0.63 "chainloop config context list"

STEP 9 — Create workflow contract:
  Create chainloop-contract.yaml in the repo root:
    schemaVersion: v1
    materials:
      - name: trivy-scan
        type: SARIF
        required: true
      - name: sbom
        type: SBOM_SPDX_JSON
        required: true
      - name: cosign-signature
        type: STRING
        required: true

STEP 10 — Add gated chainloop-attest CI job:
  Add to the CI workflow (from docs/plan/phase-05-supply-chain.md Part D).
  Include: if: false  # Activate in Phase 06
  needs: [trivy-image-scan, generate-sbom, sign-image]

STEP 11 — Commit and merge:
  git add terraform/lxc/stacks/chainloop-stack/ \
          terraform/lxc/ansible/playbooks/deploy-chainloop-stack.yml \
          terraform/lxc/ansible/playbooks/deploy-ci-runner.yml \
          chainloop-contract.yaml .github/workflows/ .env.template
  git commit -m "feat(chainloop): deploy Chainloop server, define workflow contract (VMID 155)"
  git checkout dev/pve-test && git merge feat/chainloop-stack
  git push origin dev/pve-test

DONE WHEN: Chainloop server responding, CLI on ci-runner-01 works, contract defined, CI job gated.
```

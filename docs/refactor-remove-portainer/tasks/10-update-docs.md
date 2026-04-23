# Task 10: Update platform documentation

## Type

Documentation

## Objective

Update `PLATFORM_CONTRACT.md`, `docs/design/architecture.md`, and
`terraform/lxc/README.md` to reflect the new two-phase deployment model and the Tier 1
/ Tier 2 Portainer split. Correct any text that implies Terraform invokes Ansible.

## Files

- `terraform/lxc/PLATFORM_CONTRACT.md`
- `docs/design/architecture.md`
- `terraform/lxc/README.md`
- `docs/plan/README.md` (if it references Terraform invoking Ansible)

## Preconditions

- Tasks 07, 08, 09 complete.

## Operations

1. Read all four files in full before editing.

**`terraform/lxc/PLATFORM_CONTRACT.md`:**

2. Add `direct_stack` to the shared Ansible roles list with description: "Deploys a
   Docker Compose stack directly via `community.docker.docker_compose_v2`. Used by
   simple platform stacks and as the `app_stack` replacement for NetBox."

3. Note that `app_stack` and `portainer_api` are **Tier 2 (apps) only**.

4. Add `deployment_tier` to the `stack.yaml` field reference table:
   - Field: `deployment_tier`
   - Required: Yes
   - Values: `platform` or `apps`
   - Description: Determines deployment method and Portainer agent behaviour.
     `platform`: direct Ansible Compose deployment, no agent.
     `apps`: Portainer API deployment, agent installed.

5. Update the `portainer_agent` row: note it is meaningful for Tier 2 stacks only.
   Platform stacks must set `portainer_agent: false`.

6. Update the `portainer_server_ip` platform variable: note it is Tier 2 only.

**`docs/design/architecture.md` — ADR-04:**

7. Locate ADR-04 (Container Management Plane). Update the decision text:
   - Previous: Portainer is observability-only (read access); agents deployed across
     all zones with step-ca mutual TLS.
   - Revised: Portainer is a management UI for Tier 2 application stacks only.
     Platform (Tier 1) containers do not install the Portainer agent and are not
     deployed via the Portainer API.

8. Update the rationale: Docker socket exposure on PKI/IAM/registry containers is
   unacceptable; bootstrap circularity eliminated.

9. Update SEC-02 scope in the security constraints table to Tier 2 application stacks
   only.

**`terraform/lxc/README.md`:**

10. Add a "Deployment model" section describing the two-phase workflow:
    ```
    Phase 1 — Infrastructure: ./with-secrets terragrunt run-all apply
    Phase 2 — Configuration:  ./with-secrets ./scripts/provision.sh [--tier platform|apps] [--stack <name>]
    ```
    Include the full rebuild sequence from `task-sequence.md`.

**`docs/plan/README.md`:**

11. Search for text implying Terraform invokes Ansible (e.g. references to
    `local-exec`, Ansible running automatically after `apply`). Correct any such
    text to reflect the two-phase model.

## Postconditions

- No documentation states that Terraform invokes Ansible for stack configuration.
- ADR-04 reflects the Tier 1/Tier 2 Portainer split.
- `PLATFORM_CONTRACT.md` lists `direct_stack`, `deployment_tier`, and notes Tier 2
  scope for `app_stack`, `portainer_api`, and `portainer_server_ip`.

## Validation

```bash
# No remaining local-exec Ansible references in updated docs
rg -n "local-exec.*ansible|ansible.*local-exec" \
  terraform/lxc/PLATFORM_CONTRACT.md \
  terraform/lxc/README.md \
  docs/design/architecture.md \
  docs/plan/README.md
# Expected: no output

# direct_stack and deployment_tier appear in PLATFORM_CONTRACT.md
grep -n "direct_stack\|deployment_tier" terraform/lxc/PLATFORM_CONTRACT.md
# Expected: at least 2 lines

# SonarCloud scan
source .env && sonar-scanner
```

## Stop Conditions

- Stop if ADR-04 does not exist in `docs/design/architecture.md` — report the
  actual ADR numbering before editing.
- Stop if `docs/plan/README.md` does not exist — skip that file and report.

# ci-runner-01 — Stack Contract

## Purpose

Self-hosted GitHub Actions runner for CI jobs that require access to the homelab
network or local infrastructure (registry pulls, Ansible playbook validation,
Trivy image scans against Harbor, etc.). Jobs that run on `ubuntu-latest` cannot
reach `10.57.x.x`; those that need network access are tagged for this runner.

## Network

| Field        | Value                    |
|--------------|--------------------------|
| Zone         | `build_seg` (VLAN 10)    |
| IP           | `10.57.0.63/24`          |
| Gateway      | `10.57.0.1` (MikroTik)  |
| VMID         | 141                      |

## Inputs

| Input                       | Source      | Notes |
|-----------------------------|-------------|-------|
| `GITHUB_RUNNER_TOKEN`       | env var     | Registration token from GitHub Actions |
| `GITHUB_RUNNER_REPO`        | env var     | Repository the runner registers with |
| Harbor registry             | `10.57.3.10` | Docker image pulls via proxy cache |
| apt-cacher                  | `10.57.3.11:3142` | apt proxy during provisioning |
| Portainer server            | `10.57.1.20` | Agent registration |

## Provides

| Service             | Port | Protocol | Notes |
|---------------------|------|----------|-------|
| GitHub Actions runner | —  | outbound | Polls GitHub for jobs |
| Portainer agent     | 9001 | TCP      | Portainer server connects here |

No inbound ports are required. The runner connects outbound to GitHub.

## Dependencies

| Stack           | Why |
|-----------------|-----|
| harbor-stack    | Docker image pulls for job containers |
| apt-cacher-stack | apt proxy for runner provisioning and job steps |
| portainer-stack | Registers Portainer agent |

Cross-zone access needed: `build_seg → infra_seg tcp/80,443,3142` (covered by the
`all_zones → infra_seg` policy in `pve-test.yaml`).
build_seg → mgmt_seg is also required for metrics push (VictoriaMetrics port 8428,
Loki port 3100) if observability is wired up in Phase 04.

## Persistent State

| Path              | Storage               | Contents |
|-------------------|-----------------------|----------|
| Runner work dirs  | rootfs (20 GiB)       | Job workspace (ephemeral per job) |
| Docker volumes    | `docker_storage` (10 GiB) | Docker layer cache |

## What May Depend on This Stack

Nothing depends on ci-runner-01 being reachable. It is a consumer of the platform,
not a provider.

## What Must Not Be Edited Casually

- The runner registration token is single-use and time-limited. Re-registration
  requires a new token from the GitHub repository settings.
- The runner label/tag must match the `runs-on:` value in workflow YAML.

## Playbook

`deploy-ci-runner`

# Code Cleanup — Overview

**Initiated:** 2026-06-14, `baseline/teardown-validated` @ `c4c38d8`
**Scope:** SonarCloud security hotspots, cognitive complexity, bandit/ruff
  findings surfaced after adding Python scanning to the CI pipeline.
**Not in scope:** Feature work, TLS termination architecture changes,
  Phase 06 app migrations.

## Background

A comprehensive scan was run across all code types (Ansible, Terraform,
Python, shell) on 2026-06-14. Findings were classified against the SDN
topology to separate real risks from false positives. GitHub issues were
opened for each category.

The CI pipeline (`validate.yml`) now includes:
- ShellCheck (shell scripts)
- Terraform fmt + validate
- Ansible lint
- **Python lint + security** (`ruff` + `bandit`) — added in PR #358

SonarCloud runs on every push and analyses shell, Python, Ansible, YAML,
Terraform, and Dockerfile. Quality gate is currently **PASSING**.

## Documents

| Document | Purpose |
|---|---|
| [findings.md](findings.md) | Classified SonarCloud + bandit/ruff findings with SDN rationale |
| [sprint-plan.md](sprint-plan.md) | Session breakdown, branch names, gates, issue references |

## Relationship to main sprint plan

The main sprint plan (`docs/plan/sprint-plan.md`) governs infrastructure
work (TLS hardening, step-ca metrics, harness improvements). This
code-cleanup sprint runs in parallel where there is no live-infra
dependency, and integrates at one point (Session CC-3 is absorbed into the
main sprint's Session 2 branch `fix/tls-hardening`).

## Issue index

| # | Title | Priority | Session |
|---|---|---|---|
| [#355](https://github.com/stevedwray/proxmox-homelab/issues/355) | SSL cert verification disabled in Harbor Python tools | medium | CC-2 |
| [#356](https://github.com/stevedwray/proxmox-homelab/issues/356) | Ruff lint warnings across project Python files | medium | CC-2 |
| [#357](https://github.com/stevedwray/proxmox-homelab/issues/357) | Positive Harbor image policy check (follow-up) | low | CC-1 |
| [#359](https://github.com/stevedwray/proxmox-homelab/issues/359) | Authentik Ansible API calls HTTP → HTTPS:9443 | **high** | CC-3 (via `fix/tls-hardening`) |
| [#360](https://github.com/stevedwray/proxmox-homelab/issues/360) | Accept and suppress HTTP-on-SDN false positives | medium | CC-1 |
| [#361](https://github.com/stevedwray/proxmox-homelab/issues/361) | ReDoS regex in `edge_manifest.py` and `harbor_scan_smoke.py` | medium | CC-2 |
| [#362](https://github.com/stevedwray/proxmox-homelab/issues/362) | Add non-root USER to netbox-stack Dockerfile | low | CC-1 |
| [#363](https://github.com/stevedwray/proxmox-homelab/issues/363) | Suppress shell:S6506 false positive in setup-dev-env.sh | low | CC-1 |
| [#364](https://github.com/stevedwray/proxmox-homelab/issues/364) | Cognitive complexity — NetBox integrations | medium | CC-4 |
| [#365](https://github.com/stevedwray/proxmox-homelab/issues/365) | Cognitive complexity — Authentik reconciler + Harbor tooling | low | CC-5 |

## Current state

- PR #358 (`fix/ci-pipeline-cleanup`) open — adds Python lint CI job and
  fixes Harbor IP. **Python lint CI job will fail until #356 is resolved.**
- All findings classified; issues created.
- No code-cleanup sessions started yet.

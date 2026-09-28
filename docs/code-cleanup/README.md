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
Terraform, and Dockerfile. Quality gate: **FAILING since 2026-09-28**
(see "CI gate failures accepted at the 2026-09-28 promotion" below).

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

## CI gate failures accepted at the 2026-09-28 promotion

PR #434 promoted `stable` to `main`: 404 commits, 8 Sep to 28 Sep. The
operator accepted it with four failing gates. None came from that day's
changes. They had built up unseen, because `validate.yml` and SonarCloud's
PR gate don't run for PRs from `task/*` branches into `stable`.

1. **ansible-lint:** 193 fatal violations across many playbooks.
2. **Harbor-only image references:** 10, in the `cse-code-eval`,
   `cse-panel-stack`, `cse-kali` and `cse-controller` compose files (a
   literal `harbor.lab.gibbsgreatly.xyz/...` instead of the registry
   variable), and 3 upstream images in `pterodactyl-lab`.
3. **ruff (Python lint + security):** unused imports and variables in
   deep-research and harbor-findings files, among others.
4. **SonarCloud quality gate:** security E and reliability E on new code
   (53 open bugs and vulnerabilities). The 7 blockers, triaged but not
   actioned:

   | Finding | Triage |
   |---|---|
   | `.github/workflows/netbox-populate.yml:32` githubactions:S8482 "executing downloaded artifacts" | False positive: pipes the GitHub OIDC token response to `json.load`; nothing is executed. |
   | `scripts/secrets_env.py:120-121` pythonsecurity:S2083 path traversal in `login()` | Low risk: the role name comes from the repo's `secrets/manifest.json` profile, not from user input. Could validate `role` against `^[a-z0-9-]+$`. |
   | `terraform/lxc/ansible/files/deep-research-files/serve.py:86, 109` S2083 path traversal | Probably a false positive: paths come from stdlib `SimpleHTTPRequestHandler.translate_path`, which drops `..` components. Not tested live. |
   | `terraform/lxc/ansible/files/greenbone-scan-setup/setup_credentials.py:98` S6418 hard-coded secret | False positive: `"credential": "mikrotik-gvm-scan"` is a credential *name*. |
   | `terraform/lxc/ansible/files/deep-research-agent/src/engine/orchestrator.py:15` S8508 mutable default | Real, minor: replace with `None` plus an in-function default. |

   The rest are lower severity:
   - mostly S5332 plain-HTTP warnings on internal lab traffic (`edge.yaml`
     files, Technitium's API, docs-rag embeddings);
   - S7493 synchronous `open()` in async functions in the deep-research
     agent;
   - S4423 TLS-protocol warnings in `openbao_*.py` and `secrets_env.py`;
   - a missing `uv.lock` for deep-research-agent.

**Next:**
- Mark the false positives in SonarCloud, giving the reason.
- Fix the two small real items.
- Decide whether `validate.yml` should also run on PRs into `stable`, so
  these failures surface before a promotion rather than at it.

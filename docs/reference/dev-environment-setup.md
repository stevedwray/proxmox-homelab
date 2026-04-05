# Development Environment Setup

This reference document describes the development environment configuration and tooling used by the Proxmox homelab automation repository.

## Devcontainer Configuration

The project includes a development container definition for consistent tooling.

```json
{
    "name": "Proxmox Homelab Development",
    "image": "mcr.microsoft.com/devcontainers/base:ubuntu-22.04",
    "features": {
        "ghcr.io/devcontainers/features/terraform:1": {},
        "ghcr.io/devcontainers/features/python:1": {
            "version": "3.11"
        },
        "ghcr.io/devcontainers/features/git:1": {}
    },
    "customizations": {
        "vscode": {
            "extensions": [
                "hashicorp.terraform",
                "redhat.ansible",
                "ms-python.python",
                "continue.continue",
                "ms-vscode.vscode-json",
                "ms-vscode-remote.remote-wsl"
            ]
        }
    },
    "postCreateCommand": "pip install -r requirements.txt && ansible-galaxy install -r ansible/requirements.yml",
    "mounts": [
        "source=${localWorkspaceFolder}/.env,target=/workspaces/${localWorkspaceFolderBasename}/.env,type=bind,consistency=cached"
    ]
}
```

## Python Requirements

The repository installs the following Python dependencies:

```text
ansible>=7.0.0
proxmoxer>=2.0.0
requests>=2.28.0
python-dotenv>=1.0.0
paramiko>=3.0.0
jinja2>=3.1.0
pyyaml>=6.0
netaddr>=0.8.0
```

Install them with:

```bash
pip install -r requirements.txt
```

## Ansible Collections

The Ansible automation depends on these collections:

```yaml
collections:
  - community.general
  - community.crypto
  - ansible.posix
```

Install them using:

```bash
ansible-galaxy install -r ansible/requirements.yml
```

## CI and Security Scanning

The repository includes a GitHub workflow for security scanning.

```yaml
name: Security Scan

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  sast-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run Trivy vulnerability scanner
        uses: aquasecurity/trivy-action@master
        with:
          scan-type: 'fs'
          scan-ref: '.'
          format: 'sarif'
          output: 'trivy-results.sarif'
      - name: Upload Trivy scan results
        uses: github/codeql-action/upload-sarif@v2
        with:
          sarif_file: 'trivy-results.sarif'
      - name: Run Semgrep
        uses: returntocorp/semgrep-action@v1
        with:
          config: >-
            p/security-audit
            p/secrets
            p/terraform

  terraform-security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Setup Terraform
        uses: hashicorp/setup-terraform@v2
      - name: Terraform Security Scan
        uses: triat/terraform-security-scan@v3.1.0
        with:
          tfsec_actions_comment: true
          tfsec_output_format: sarif
          tfsec_output_file: tfsec.sarif
      - name: Upload tfsec scan results
        uses: github/codeql-action/upload-sarif@v2
        with:
          sarif_file: tfsec.sarif
```

## Pre-commit Configuration

The repository uses pre-commit hooks to enforce formatting and linting:

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.4.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
      - id: detect-private-key
      - id: check-merge-conflict

  - repo: https://github.com/aquasecurity/tfsec
    rev: v1.28.1
    hooks:
      - id: tfsec

  - repo: https://github.com/antonbabenko/pre-commit-terraform
    rev: v1.81.0
    hooks:
      - id: terraform_fmt
      - id: terraform_validate
      - id: terraform_docs

  - repo: https://github.com/ansible/ansible-lint
    rev: v6.17.2
    hooks:
      - id: ansible-lint
        files: \.(yaml|yml)$
        exclude: .github/
```

## Git Ignore and Local Secrets

The repository excludes generated and sensitive files:

- `.env`, `.env.local`, `*.env`
- Terraform state and locking files
- Ansible host_vars and group_vars
- Python virtual environments and cache
- IDE files
- SSH keys
- Log files

This keeps local secrets and transient build artifacts out of version control.

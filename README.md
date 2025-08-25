# Proxmox Homelab Infrastructure

Infrastructure as Code for Proxmox-based homelab using Terraform and Ansible.

## Overview

This repository contains automation scripts and configurations for managing a Proxmox-based homelab environment with:
- Infrastructure provisioning via Terraform
- Configuration management via Ansible
- Security scanning and validation
- AI-assisted development with Continue.dev

## Quick Start

1. **Setup Environment**
   ```bash
   # Run the setup script (installs tools, creates structure)
   ./scripts/setup-dev-env.sh
   
   # Validate the setup
   ./scripts/validate-environment.sh
   ```

2. **Configure Settings**
   ```bash
   # Copy and edit environment settings
   cp .env.template .env
   nano .env  # Add your Proxmox details
   ```

3. **Deploy Test Infrastructure**
   ```bash
   cd terraform/environments/test-vm
   terraform init
   terraform plan
   terraform apply
   ```

4. **Configure Systems**
   ```bash
   cd ansible
   ansible-playbook -i inventory/test-lab.yml 01-base-system/base-config.yml
   ```

## Repository Structure

```
proxmox-homelab/
├── .devcontainer/          # Development container config
├── .github/workflows/      # CI/CD pipelines
├── .vscode/               # VSCode settings and tasks
├── .continue/             # AI assistant configuration
├── terraform/
│   ├── environments/
│   │   ├── test-vm/       # VMware lab environment
│   │   └── production/    # Production hardware
│   └── modules/           # Reusable Terraform modules
├── ansible/
│   ├── 01-base-system/    # Base system configuration
│   ├── 02-infrastructure/ # Infrastructure services
│   ├── 03-applications/   # Application deployment
│   └── inventory/         # Host inventories
├── docs/                  # Documentation
├── scripts/               # Automation scripts
└── backups/              # Backup storage
```

## Key Features

- **Infrastructure as Code**: Complete automation of Proxmox infrastructure
- **Security First**: Automated security scanning and validation
- **AI-Enhanced**: Continue.dev integration for intelligent development
- **Testing**: Comprehensive validation and testing procedures
- **Documentation**: Well-documented procedures and troubleshooting

## Prerequisites

- WSL1 (for VMware Workstation compatibility)
- Proxmox VE lab environment
- Git, Terraform, Ansible (installed by setup script)

## Documentation

See the `docs/` directory for detailed documentation including:
- Setup and installation guides
- Configuration references
- Troubleshooting procedures
- Best practices

## Development Workflow

1. Make changes to infrastructure code
2. Run security scans with `pre-commit run --all-files`
3. Test changes in lab environment
4. Deploy to production when validated

## Support

For issues and questions, see the troubleshooting guide in `docs/troubleshooting.md`

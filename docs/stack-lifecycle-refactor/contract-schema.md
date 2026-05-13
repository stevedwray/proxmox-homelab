## 1. Schema Overview

This document proposes the first-pass shared schema for `stack.yaml` used by the
platform (Terraform) and configuration (Ansible) layers. It is a documentation
artifact only: no files are moved or renamed in this draft. The goal is to
classify every commonly-used field, propose top-level sections, provide an
annotated exemplar, and identify extension hooks.

## 2. Top-Level Schema Sections

Each proposed top-level section and a one-line description:

- `identity`: stack name, hostname, identifiers and human-facing metadata
- `infrastructure`: sizing, storage, host placement that Terraform consumes
- `network`: attachment intent, zone, IP and gateway intent
- `services`: service-level provides/dependencies and capability flags
- `maintenance`: operational knobs (ansible_playbook, deployment_tier, tags)
- `validation`: validators, expected endpoints and contract asserts
- `integrations`: pointers to external systems (registry, apt proxy, portainer)

## 3. Field Classification

| Field | Current Section | Classification | Consumed By | Notes |
|---|---:|---|---|---|
| hostname | identity | source-of-truth | Terraform, Ansible | LXC hostname and inventory key |
| ip_address | network | source-of-truth | Terraform, Ansible | CIDR in stack example |
| gateway | network | both | Terraform (default) & generated inventory | can be env default or per-stack override |
| proxmox_node | infrastructure | source-of-truth | Terraform | placement target |
| network.zone | network | source-of-truth | Terraform, inventory generator | SDN/bridge intent |
| vmid | infrastructure | source-of-truth | Terraform | optional explicit VMID |
| cores | infrastructure | source-of-truth | Terraform | sizing |
| memory | infrastructure | source-of-truth | Terraform | sizing (MiB) |
| swap | infrastructure | source-of-truth | Terraform | sizing (MiB) |
| rootfs_size | infrastructure | source-of-truth | Terraform | GiB |
| rootfs_storage | infrastructure | source-of-truth | Terraform | storage pool |
| docker_storage_size | infrastructure | source-of-truth | Terraform | container volume sizing |
| ostemplate | infrastructure | source-of-truth | Terraform | template image reference |
| tags | identity | source-of-truth | Docs, validation, tooling | free-form labels |
| depends_on | services | source-of-truth | Orchestration tooling | ordering metadata |
| provides | services | source-of-truth | Validation tooling | advertised services/ports |
| ansible_playbook | maintenance | source-of-truth | Provisioning scripts | playbook name consumed by scripts/provision.sh |
| deployment_tier | maintenance | source-of-truth | Terraform + Ansible | `platform` vs `apps` behavior |
| portainer_agent | integrations | source-of-truth | Ansible roles | boolean feature flag |
| portainer_server_ip | integrations | tf-derived | Terraform/env → generated inventory | platform var by default, overridable per-stack |
| registry_host | integrations | both | Terraform defaults / stack override → Ansible | platform variable flows into inventory |
| apt_cacher_host | integrations | both | Terraform defaults / stack override → Ansible | special-case (apt-cacher-stack sets empty) |
| extra_mount_path | infrastructure | source-of-truth | Terraform, Ansible | mount path for large data |
| extra_mount_size | infrastructure | source-of-truth | Terraform | size for extra mount |
| extra_mount_storage | infrastructure | source-of-truth | Terraform | storage pool for extra mount |
| app_stack_name | identity | source-of-truth | platform defaults | convenience alias |
| keyctl | maintenance | source-of-truth | Ansible role toggle | feature flag |

Notes: classification rules
- source-of-truth — a field that should live in `stack.yaml` and be authoritative
- tf-derived — produced by platform variables or env → generated inventory
- ansible-derived — produced only by Ansible or runtime discovery
- both — can be provided in `stack.yaml` or inherited from platform defaults
- generated — not present in `stack.yaml`; produced by render step (inventory)

## 4. Annotated Exemplar (apt-cacher-stack)

Below is the exemplar `apt-cacher-stack/stack.yaml` annotated with the
classification and consumers (inline comments show classification only).

---
# apt-cacher-ng transparent apt proxy — infra_seg zone
hostname: apt-cacher-stack           # source-of-truth
ip_address: "${lab_ip_apt_cacher}/24"  # source-of-truth
gateway: "${lab_gw_infra}"         # both
proxmox_node: pve-test               # source-of-truth
network:
  zone: infra_seg                    # source-of-truth
vmid: 142                            # source-of-truth
cores: 1                             # source-of-truth
memory: 256                          # source-of-truth
swap: 128                            # source-of-truth
rootfs_size: 8                       # source-of-truth
rootfs_storage: infrastructure-containers  # source-of-truth
docker_storage_size: "20G"          # source-of-truth
ostemplate: "storage-template:vztmpl/debian-13.1-2-docker-template.tar.gz"  # source-of-truth
tags:
  - apt-cache                        # source-of-truth
  - infrastructure
  - build
depends_on: []                       # source-of-truth
provides:
  - service: apt-proxy               # source-of-truth
    port: 3142
    protocol: tcp
ansible_playbook: "deploy-apt-cacher-stack"  # source-of-truth
deployment_tier: platform             # source-of-truth
portainer_agent: false                # source-of-truth

# pve-test service IPs (explicit — do not rely on variable defaults)
portainer_server_ip: "${lab_ip_portainer}"  # tf-derived (env) / consumed by Ansible
registry_host: "{{ lookup('env', 'LAB_IP_HARBOR') | mandatory('LAB_IP_HARBOR env var is required') }}"  # both
apt_cacher_host: ""  # This container IS the apt-cacher; no self-proxy  # both (special-case)
---

## 5. Proposed Schema Structure (skeleton)

identity:
  name: <stack-dir-or-override>
  hostname: <string>
  tags: [ ... ]

infrastructure:
  proxmox_node: <string>
  vmid: <int?>
  cores: <int>
  memory: <int>
  swap: <int>
  rootfs:
    size_gib: <int>
    storage_pool: <string>
  extra_mount:   # optional
    path: <string>
    size: <string>
    storage_pool: <string>
  ostemplate: <string>

network:
  zone: <string>
  ip_address: <cidr>
  gateway: <string?>

services:
  provides:
    - service: <id>
      port: <int>
      protocol: <tcp|udp>
  depends_on: [ <stack-name> ... ]

maintenance:
  ansible_playbook: <string>
  deployment_tier: <platform|apps>
  feature_flags:
    portainer_agent: <bool>
    keyctl: <bool>

validation:
  validators: [ <script|check-id> ... ]
  expected_endpoints: [ { host: <ip>, port: <int>, proto: <tcp|udp> } ... ]

integrations:
  registry_host: <ip|string>  # platform default unless overridden
  apt_cacher_host: <ip|string>
  portainer_server_ip: <ip>

## 6. Special-Case Extension Points

- DNS publication (`dns-stack`): Capability flag `publishes_dns: true` plus
  an optional `dns` extension block that declares zone-specific publication
  templates. Approach: `per-stack extension block` recommended.
- Ingress publication (`proxy-stack`): Capability flag `publishes_ingress` and
  `ingress.publish` block with route templates. Approach: `per-stack extension block`.
- Trust distribution (`step-ca-stack`): expose `trust.capabilities: [distribute-ca]`
  and a `trust` extension to declare targets. Approach: `capability flag + extension`.
- Identity bootstrap (`authentik-stack`): `identity.bootstrap: { method: <oauth|api>, params: ... }`.
  Approach: `per-stack extension block`; mark as deferred for stacks that cannot
  express the lifecycle as simple provides/depends.
- External registration lifecycle (`ci-runner-01`): `lifecycle.registration` block
  describing registration API endpoints and retry policy. Approach: `per-stack extension`.

## 7. Open Schema Questions

1. Field naming conventions: underscores vs. hyphens; recommend underscores for
   consistency with existing `stack.yaml` examples.
2. Environment-level vs per-stack network intent: when should `network.zone` be
   promoted to environment policy vs per-stack field?
3. Non-secret vars layering: canonical precedence (stack.yaml → env TF_VAR → platform defaults).
4. `provides`/`depends_on` identity model: should service identifiers be
   normalized across stacks or remain free-form?
5. Treatment of generated fields: which derived host-vars must be considered
   stable API (and thus documented in PLATFORM_CONTRACT.md)?
6. Migration path: how to roll the schema out without breaking existing `stack.yaml` files.

---

Deliverables next: produce the Field Classification spreadsheet as a machine-friendly
CSV, reproduce the apt-cacher exemplar as a fully-annotated file in this doc,
and cross-map `special-cases.md` entries to the extension points above.

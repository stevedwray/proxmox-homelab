# cse-kali — Stack Contract

## Purpose

Kali attacker for the CyberSecEval cyber range's autonomous-offensive
benchmark (Meta CyberSecEval 4). Disposable LXC running a stock Kali Linux
Docker container with a modest pentest toolset (nmap, sqlmap, nikto,
hydra, etc.) installed at deploy time. Consumers reach it via SSH to the
LXC host itself (standard for every LXC in this platform) and invoke
tools via `docker exec` — the container does not run its own SSH server,
avoiding a custom Kali+sshd image build.

## Network

| Field   | Value |
|---|---|
| Zone | `pentest_seg` (VLAN 70) |
| IP | `192.168.70.210/24` |
| Gateway | `${lab_gw_pentest}` |
| VMID | 70010 |

Deployed on `pve-test` — joins the existing `pentest_seg` zone (extended
to this node 2026-09-18, see
`docs/cyberseceval-implementation/plan/cyberseceval-implementation-plan.md`
§1a/§11) rather than a new dedicated zone, reusing its containment policy
(internet egress, Harbor/apt-cacher reach, explicit deny-by-default
elsewhere). `pve-test`'s copy of `pentest_seg` is its own independent SDN
zone (this node isn't clustered with `pve`/`pve-test-vm`), sharing the
same physical VLAN 70/subnet on the MikroTik — confirmed live: VLAN 70 was
already tagged on the trunk port facing `pve-test`, and the zone's
existing default-deny/allow rules match on `in-interface`/subnet, not
per-host IP, so they cover this stack automatically.

## Inputs

| Input | Source | Notes |
|---|---|---|
| `lab_gw_pentest`/`lab_subnet_pentest_cidr` | `.env` (shared, not node-specific) | Same VLAN 70 gateway/subnet every `pentest_seg` tenant uses |

## Provides

| Service | Port | Protocol | Notes |
|---|---|---|---|
| `kali-shell` | 22 | tcp | Root SSH to the LXC host (standard `lxc_base` provisioning, not a service this stack adds) — tools are reached via `docker exec cse-kali <command>` from there |

## Dependencies

| Stack | Why |
|---|---|
| `infra_seg`'s Harbor/apt-cacher (on `pve`, reached cross-node) | Docker image pull (`kalilinux/kali-rolling` via Harbor's `dockerhub` proxy-cache) and apt package installs during provisioning |

No new cross-zone MikroTik rule needed — `pentest_seg`'s existing
egress/Harbor-reach policies already cover this by subnet, not by
per-host IP (confirmed live 2026-09-18).

## Persistent State

None. The container is disposable by design — tool installs happen at
every deploy (idempotent `apt-get install`), nothing is expected to
survive a `docker compose down`/LXC destroy.

## What May Depend on This Stack

The CyberSecEval autonomous-offensive benchmark's attacker/target JSON
definition (once the controller side is built on `pve-tiny` — deferred,
see plan §1a open decision #3) and the future Metasploitable3 target on
this same `pentest_seg` zone.

## What Must Not Be Edited Casually

- `network_mode: host` on the Kali container is deliberate — several
  tools (raw-socket nmap scan types in particular) need the LXC's real
  network namespace, not Docker's default bridge/NAT. Don't switch this
  to bridge networking without checking whether it breaks scan types
  CyberSecEval actually uses.
- `cap_add: [NET_ADMIN, NET_RAW]` + `security_opt: [seccomp=unconfined,
  apparmor=unconfined]` mirrors `greenbone-stack`'s `ospd-openvas`
  service, which needs the identical capabilities for the identical
  reason (raw-socket scanning) under the same nested-Docker LXC
  `nesting` feature. Don't strip these.
- The tool list in `deploy-cse-kali.yml`'s `cse_kali_packages` var is
  intentionally modest (not the full `kali-linux-large`/
  `kali-linux-everything` metapackage) to keep deploy time and
  `docker_storage_size` reasonable. Extend it there, not via a manual
  `docker exec apt-get install` that won't survive a redeploy.

## Playbook

`deploy-cse-kali` (roles: `lxc_base`, `docker_base`)

Follows `deploy-harness-target.yml`'s shape (write compose, `docker
compose up -d`, wait-for-ready), with one addition: an idempotent
`docker exec apt-get install` step for the pentest toolset, since the
stock `kalilinux/kali-rolling` image ships with no tools pre-installed.

## Implementation Files

| File | Role |
|---|---|
| `terraform/lxc/stacks/cse-kali/stack.yaml` | Terraform-side stack definition |
| `terraform/lxc/stacks/cse-kali/docker-compose.yml` | Kali container definition |
| `terraform/lxc/environments/pve-test/cse-kali/terragrunt.hcl` | Terragrunt entrypoint |
| `terraform/lxc/ansible/playbooks/deploy-cse-kali.yml` | Stack playbook |

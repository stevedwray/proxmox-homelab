# cse-kali — Stack Contract

## Purpose

Kali attacker for the CyberSecEval cyber range's autonomous-offensive
benchmark (Meta CyberSecEval 4). Disposable LXC running a stock Kali Linux
Docker container with a modest pentest toolset (nmap, sqlmap, nikto,
hydra, etc.) installed at deploy time.

Two separate access paths now exist:
- **Operator/human access**: SSH to the LXC host itself
  (`192.168.70.210:22`, standard for every LXC in this platform), tools
  reached via `docker exec cse-kali <command>`.
- **Autonomous-agent access** (added 2026-09-19, plan §7/§11/§13):
  CyberSecEval's `autonomous_uplift` benchmark SSHes directly into the
  attacker host as the LLM-under-test and expects a plain login shell
  with tools already on `PATH` — `docker exec` indirection doesn't fit
  that model. The container now runs its own `sshd`, reached at
  `192.168.70.212:22` (a second IP, see Network below) as a dedicated
  `kali` user with passwordless `sudo` (not root login itself, and not
  the fleet-wide automation SSH key — see Persistent State).

## Network

| Field   | Value |
|---|---|
| Zone | `pentest_seg` (VLAN 70) |
| IP | `192.168.70.210/24` (LXC host) + `192.168.70.212/24` (agent SSH, see below) |
| Gateway | `${lab_gw_pentest}` |
| VMID | 70010 |

**Why a second IP, and why not just a second port**: the Kali container
uses `network_mode: host` (needed for raw-socket nmap scans — see below),
so it shares one network namespace with the LXC host's own `sshd`. That
`sshd` is systemd-socket-activated and **wildcard-binds** `0.0.0.0:22`
(confirmed live 2026-09-19 via `ss`, not assumed) — a wildcard bind on a
port blocks any other process from binding that same port on *any*
address in that namespace. CyberSecEval's `test_case_generator` hardcodes
port 22 with no override, so the container's own `sshd` needs port 22
specifically, on a different IP: `192.168.70.212`, added to `eth0` as a
secondary address. The container's `sshd` actually listens on
`192.168.70.212:2222` (a different *port* too, since a specific-address
bind on 22 would still collide with the host's wildcard bind on the
*same* port) — an `iptables` `DNAT` rule on the LXC host
(`-d 192.168.70.212 --dport 22 -j DNAT --to-destination
192.168.70.212:2222`) makes that transparent to any client, which
connects to `.212:22` as normal. **Not `REDIRECT`**: that target always
rewrites the destination to `127.0.0.1`, which has nothing listening on
port 2222 — confirmed live as an actual "connection refused" failure
before switching to `DNAT`.

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
| `kali-shell` | 22 | tcp | Root SSH to the LXC host `192.168.70.210` (standard `lxc_base` provisioning, not a service this stack adds) — tools are reached via `docker exec cse-kali <command>` from there |
| `cse-kali-agent-ssh` | 22 (externally) / 2222 (actual `sshd`) | tcp | `192.168.70.212`, dedicated `kali` user, key-only auth, passwordless `sudo` — for the autonomous-offensive benchmark's LLM-under-test, not humans |

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
survive a `docker compose down`/LXC destroy. The `kali` agent user,
its `sudo` grant, and its `authorized_keys` are all recreated
idempotently by `deploy-cse-kali.yml` on every run, so a redeploy after
a destroy restores them without any manual step.

The agent's key is a **dedicated keypair, not the fleet-wide automation
SSH key** — chosen deliberately (2026-09-19) so a leaked or misbehaving
autonomous-benchmark run's blast radius stays scoped to this one
disposable container, not every LXC this repo manages. The public key
is committed in `deploy-cse-kali.yml` (non-secret by nature); the
private key lives only on `cse-controller`'s durable mount
(`/srv/cyberseceval/config/cse-kali-agent-key`), never in git. It's
currently one static keypair, not yet rotated per benchmark run — that
waits on the actual run-orchestration script (plan §13), still to be
built.

The secondary IP (`192.168.70.212` on `eth0`) and the `iptables` `DNAT`
rule are both host-level, **not Terraform-managed** and **not
persistent across an LXC reboot** — `deploy-cse-kali.yml` reapplies both
idempotently on every run, so a routine `provision.sh --stack cse-kali`
self-heals them, but a bare reboot without a redeploy would leave the
agent's SSH path unreachable until the next deploy.

## What May Depend on This Stack

`cse-controller` (on `pve-tiny`) — reaches this stack's agent SSH path
directly, no MikroTik rule needed (confirmed live, `infra_seg` carries
no default-deny egress). The CyberSecEval autonomous-offensive
benchmark's attacker/target JSON definition will reference
`192.168.70.212` as the attacker IP once the run-orchestration script
exists. `metasploitable3-win2k8` is the paired target on this same
`pentest_seg` zone.

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
- The agent `sshd`'s `DNAT` rule targets `192.168.70.212:2222`
  specifically — do not switch it to `REDIRECT` (rewrites to
  `127.0.0.1`, breaks silently since nothing listens there — confirmed
  live) or change the internal port without updating both the
  `sshd_config.d` file and the `iptables` rule together; they must
  agree on `cse_kali_agent_ssh_port`.
- The "Confirm sshd actually started" task matters — an early version of
  this playbook started `sshd` without checking its exit code, and a
  bind failure was silently swallowed (traced back to the wildcard-bind
  conflict above). Don't remove that check.

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

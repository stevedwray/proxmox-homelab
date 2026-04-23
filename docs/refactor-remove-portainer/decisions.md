# Decisions — Portainer Removal Refactor

These decisions are the binding contract for all executor sessions. Every task
references the decisions it implements. Stop and report to the architecture session
if any task requires violating a decision.

---

## Decision 0: Portainer is app-tier only

Portainer is retained in the homelab but narrowed to application stacks only.
Platform and infrastructure containers (Harbor, Authentik, step-ca, Traefik, CoreDNS,
monitoring, NetBox, apt-cacher-ng, CI runner, the Portainer server itself) do not
install a Portainer agent and are not deployed via the Portainer API.

**Why:** The Portainer agent exposes the Docker socket to the Portainer server. For
platform containers holding PKI (step-ca), identity (Authentik), the container registry
(Harbor), and observability state (monitoring), Docker socket cross-zone exposure is an
unacceptable blast radius if Portainer is compromised. Additionally, deploying any
platform service via the Portainer API requires Portainer to be healthy first —
creating a bootstrap circularity the current codebase works around with a `block/rescue`
hack. Removing the dependency eliminates both problems.

**Portainer's value** for app-tier stacks (interactive start/stop/restart,
troubleshooting, manual recovery) is real and is explicitly preserved.

**Applies to:** Tasks 02–06, 07

---

## Decision 1: Platform stacks deploy via Ansible-managed Docker Compose

Platform container stacks are deployed using `community.docker.docker_compose_v2` with
`state: present`. This is the already-proven mechanism in the existing Tier 1 playbooks
(authentik, monitoring, proxy, harbor via harbor_installer). It is not raw `docker
compose` shell commands.

`state: present` ensures containers are running regardless of whether compose file
content has changed since the last run. This is the correct idempotency model: a
container stopped by a reboot is restarted on the next Ansible run without requiring a
compose file content change.

**Why:** The existing platform playbooks already use this module and it works correctly.
Raw `docker compose up -d` gated on a SHA256 content check is fragile and will silently
leave stopped containers down after a host reboot.

**Applies to:** Task 01, 02–06

---

## Decision 2: Terraform and Ansible are separate phases

Terraform provisions LXC infrastructure. Ansible configures everything inside the
container. Neither phase invokes the other.

Terraform generates `stacks/<stack>/inventory.yml` as the handoff artefact. The
`ansible_playbook` field from `stack.yaml` is rendered into inventory.yml so that
`provision.sh` can determine which playbook to run for each stack.

The following Terraform `null_resource` blocks call `ansible-playbook` and are
**retained** because they configure Proxmox host-level infrastructure, not LXC
container internals:
- `configure_network_sdn_attachment` — SDN VNet create/destroy
- `configure_keyctl` — Proxmox host keyctl feature flag
- `prime_sdn_host_route` — SDN host route for Ansible reachability
- `configure_network_firewall` — Proxmox firewall rules
- `configure_network_vnet_firewall` — Proxmox VNet firewall rules

The following `null_resource` block is **removed**:
- `null_resource.ansible_provision` — the LXC stack playbook runner (~line 425 in
  `terraform/lxc/main.tf`)

**Why:** Configuration can be re-run without touching Terraform state. Ansible runs
natively parallel across hosts. A Terraform error means a provisioning problem; an
Ansible error means a configuration problem. The boundary is explicit rather than
hidden inside Terraform's dependency graph.

**Applies to:** Tasks 08, 09

---

## Decision 3: `stack.yaml` is the single source of execution intent

`stack.yaml` is canonical for stack identity, resource sizing, dependency ordering, and
execution mapping. The following fields drive the Ansible orchestration layer:

- `deployment_tier` — required; must be `platform` or `apps`; no silent defaults
- `ansible_playbook` — required for any stack that Ansible configures; used by
  `provision.sh` to determine which playbook to run
- `depends_on` — optional; used by `provision.sh` for ordering

Stacks with no `ansible_playbook` set are skipped by `provision.sh` with a SKIP
message (not an error).

**Why:** `stack.yaml` is already read by Terraform. Having a single file as the
authoritative source prevents drift between the Terraform module, the inventory,
and the Ansible orchestrator.

**Applies to:** Tasks 00, 07, 09

---

## Decision 4: `direct_stack` is the standard role for simple platform stacks

A new Ansible role `direct_stack` implements compose deployment for platform stacks
whose Docker setup is straightforward (write compose file, write .env, run `state:
present`). It uses `community.docker.docker_compose_v2` internally (per Decision 1).

Its variable interface mirrors `app_stack` to minimise the diff when updating playbooks.

For existing Tier 1 playbooks with complex bespoke deployment logic (harbor_installer,
inline config file generation), the playbooks keep their existing Docker deployment
mechanism. `direct_stack` is mandatory only for:
- NetBox, which currently uses `app_stack` and requires a direct replacement
- Any new platform stacks created after this refactor

**Why:** NetBox is the only current Tier 1 stack that uses `app_stack`. Creating
`direct_stack` provides a clean, tested replacement. Forcing all existing complex
playbooks to adopt it is unnecessary risk for this refactor.

**Applies to:** Tasks 01, 06

---

## Decision 5: `deployment_tier` must be explicit in every `stack.yaml`

Every active `stack.yaml` file must declare `deployment_tier: platform` or
`deployment_tier: apps`. There are no silent defaults. An absent `deployment_tier` is
treated as a configuration error by `provision.sh`.

**Why:** Silent defaults create ambiguity. Any new stack added without an explicit tier
classification should be caught as an error, not silently assumed to be a platform
stack.

**Applies to:** Task 07

---

## Decision 6: Single LXC OS template; Tier 1 playbooks mask the agent service

One Debian 13 Docker template is maintained. The Portainer agent systemd service unit
(`portainer-agent.service`) is baked into this template but is masked by Tier 1
playbooks so it never starts.

Every Tier 1 playbook (harbor, authentik, monitoring, proxy, netbox, portainer server,
step-ca, CoreDNS, apt-cacher, CI runner) must contain a task that masks the service:

```yaml
- name: Mask portainer-agent service (platform tier — no agent on this host)
  ansible.builtin.systemd:
    name: portainer-agent.service
    masked: true
    enabled: false
  failed_when: false
```

`failed_when: false` is required because step-ca, CoreDNS, and apt-cacher-ng do not
use Docker and may not have the service unit at all.

Tier 2 (app) playbooks call the `portainer_agent` role as before. The role writes the
compose file and starts/enables the service.

**Why:** The two-template approach adds a build-before-apply bootstrap dependency that
breaks the teardown/rebuild test sequence. Masking the service via Ansible is simpler,
requires no additional infrastructure, and produces the same security outcome.
The role's own code (`tasks/main.yml` line 52) already notes the service must be
pre-installed in the template.

**Applies to:** Tasks 02–06

---

## Decision 7: Bootstrap order is preserved from teardown/rebuild choreography

`provision.sh` runs platform stacks in the following order, which is compatible with
the Stage 3a bootstrap sequence from `docs/design/bootstrap.md`:

```
portainer-stack      (needs nothing; Portainer server itself)
harbor-stack         (needs nothing; image registry for all others)
apt-cacher-stack     (needs nothing; apt proxy)
ci-runner-01         (needs harbor)
dns-stack            (needs nothing; CoreDNS)
step-ca-stack        (needs nothing; PKI)
authentik-stack      (needs harbor)
proxy-stack          (needs step-ca for cert resolver; needs harbor)
monitoring-stack     (needs harbor)
netbox-stack         (needs harbor)
```

Changing this order requires explicit approval from the architecture session.

**Applies to:** Task 09

---

## Decision 8: Validation gates per task

Every executor session must run all validation commands listed in the task document
before reporting completion. Sessions that hit a stop condition report the condition,
the relevant file and line, and stop. They do not attempt to resolve the condition
unless a resolution is explicitly described in the task document.

The architecture session updates the next prompt based on reported stop conditions.

**Applies to:** All tasks

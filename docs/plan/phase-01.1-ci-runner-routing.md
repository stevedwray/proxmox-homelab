# Phase 01.1 — Replace SNAT with Routing for SDN Segment Egress

## Goal

Replace the SNAT/MASQUERADE rules on pve-test with proper routing for SDN-backed
container segments. This restores correct attribution in service logs, removes
double-NAT for internet-bound traffic, and enables bidirectional LAN → container
access without requiring per-service DNAT rules.

Specifically applies to `seg_c` (`build_seg` / `artifacts_seg`) which currently
uses `snat: true` in `terraform/lxc/network/pve-test.yaml`. As additional SDN
segments are added, they should follow the routing model from the start.

## Related issues

- **#78** — fix(network): remove SNAT from `seg_c`, use routing for SDN egress
- **#79** — docs(network): document router static route as SDN deployment prerequisite
- **#80** — feat(network): add routing-based egress validation to the test suite
- **#81** — ops(ci): re-register `ci-runner-01` after SNAT removal

---

## Background and motivation

### What SNAT does here

When a container in `build_seg` (`10.57.0.63`) sends traffic toward the internet,
pve-test masquerades it as its own LAN IP (`192.168.1.40`) before forwarding it to
the home router. This works for *egress*, but:

- **Breaks LAN → container ingress.** No DNAT rules exist, so traffic from your
  desktop cannot reach `10.57.0.x` at all.
- **Hides container identity in logs.** Any service receiving traffic from the
  ci-runner (GitHub, package mirrors, Harbor on production) sees `192.168.1.40`
  rather than the actual container IP.
- **Double-NAT for internet-bound traffic.** pve-test SNATs to `192.168.1.40`,
  then the home router SNATs again to the WAN IP. Conntrack state is maintained
  in two kernel tables.

### Why routing is better

pve-test already satisfies all routing prerequisites:

| Prerequisite | State |
|---|---|
| IP forwarding enabled | `net.ipv4.ip_forward = 1` |
| `tvnetc` interface has gateway IP `10.57.0.1/24` | Live |
| Default route via `192.168.1.1` for internet egress | Live |
| pve-test reachable from LAN at `192.168.1.40` | Live |

The only missing piece is a static route on the home router:

```
10.57.0.0/24 via 192.168.1.40
```

With that route in place:

- Desktop → `10.57.0.x`: router knows to send via `192.168.1.40`, pve-test
  forwards via `tvnetc` — **ingress works with no per-service config**.
- `10.57.0.x` → internet: pve-test follows its default route via `192.168.1.1`.
  The home router SNATs to the WAN IP — **one NAT only, at the boundary**.

NAT at the WAN boundary (home router → internet) is unavoidable with RFC1918
addresses. NAT at the pve-test → LAN boundary is not.

### MikroTik command reference

The home router is a MikroTik. Add the static route in the MikroTik terminal:

```
/ip route add dst-address=10.57.0.0/24 gateway=192.168.1.40 comment="pve-test SDN seg_c"
```

Or via Winbox/WebFig: **IP → Routes → Add**, set destination `10.57.0.0/24`,
gateway `192.168.1.40`.

**This route must be added before the SNAT rules are removed.** If the route is
absent when SNAT is removed, containers in `seg_c` will lose internet egress.

---

## Prerequisites

- Home router static route `10.57.0.0/24 via 192.168.1.40` is in place and
  verified (ping `8.8.8.8` from ci-runner without SNAT active).
- `.env` is sourced (`PM_API_TOKEN_ID`, `PM_API_TOKEN_SECRET`, `PM_API_URL`,
  `LXC_PASSWORD`).
- `gh` CLI is authenticated.
- `ci-runner-01` VMID 141 is running on pve-test.

---

## Step A — Add static route to MikroTik router

This is an out-of-band manual step. It must be done first.

### A1 — Add the route

In the MikroTik terminal:

```bash
/ip route add dst-address=10.57.0.0/24 gateway=192.168.1.40 comment="pve-test SDN seg_c"
```

### A2 — Verify the route is active

From you workstation:

```bash
# Should reach the ci-runner LXC directly without going via pve-test SNAT
ping -c 3 10.57.0.63

# Or from a container on a different segment / vmbr0 network
ssh root@pve-test.gibbsgreatly.xyz \
  'pct exec 141 -- ping -c 3 8.8.8.8'
```

If `ping 10.57.0.63` works from your desktop and `ping 8.8.8.8` works from the
container, routing is functional. **Do not proceed until both pass.**

---

## Step B — Remove SNAT from `seg_c` in `pve-test.yaml`

**File:** `terraform/lxc/network/pve-test.yaml`

Change `seg_c`'s `snat` field from `true` to `false`:

```yaml
  seg_c:
    ...
    sdn:
      ...
      subnet: "10.57.0.0/24"
      gateway: "10.57.0.1"
      snat: false          # was: true — egress via router static route instead
```

The Terraform check `network_layer_sdn_attachment_egress_is_complete` in
`terraform/lxc/main.tf` requires that `subnet`, `gateway`, and `snat` are either
all set or all absent — `snat: false` is valid and satisfies this check.

---

## Step C — Update `configure-network-sdn-vnet.yml` to respect `snat: false`

**File:** `terraform/lxc/ansible/playbooks/configure-network-sdn-vnet.yml`

The current `Create SDN subnet when missing` task unconditionally passes
`--snat {{ (network_sdn_snat | bool) | ternary('1', '0') }}` to `pvesh create`.
This already works for `false` — `pvesh` will set `snat=0` on the subnet entry,
which means Proxmox will not install a MASQUERADE rule.

However the existing live subnet on `tvnetc` has `snat=1`. It must be **updated**,
not just left in place. Add an update task alongside the existing create:

```yaml
- name: Update SDN subnet SNAT when it differs from desired state
  ansible.builtin.command:
    argv:
      - pvesh
      - set
      - /cluster/sdn/vnets/{{ network_sdn_vnet }}/subnets/{{ network_sdn_existing_subnet.subnet }}
      - --snat
      - "{{ (network_sdn_snat | bool) | ternary('1', '0') }}"
  delegate_to: "{{ network_sdn_pve_host }}"
  vars:
    ansible_user: root
    ansible_ssh_private_key_file: "{{ network_sdn_ssh_key }}"
    ansible_ssh_common_args: '-F /dev/null -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'
  when: >-
    (network_sdn_subnet | default('', true)) | length > 0
    and network_sdn_existing_subnet | length > 0
    and (network_sdn_existing_subnet.snat | default(false) | bool) != (network_sdn_snat | bool)
  changed_when: true
```

This task must be placed **after** the existing `Assert the existing SDN subnet
matches the desired egress config` task is removed or relaxed — currently that
task fails if the gateway/SNAT diverges from desired state. Replace the assert
with the update task so drifted configs are corrected rather than errored on.

Also fix the `changed_when` predicate on `Apply pending SDN changes on pve-test`
to account for the subnet update path.

---

## Step D — Re-apply the SDN configuration on pve-test

```bash
cd /home/steve/git/proxmox-homelab
source .env

cd terraform/lxc/stacks/ci-runner-01
terragrunt apply
```

The Terraform `null_resource` for SDN network configuration will re-run the
playbook. The new update task will set `snat=0` on the existing subnet and call
`pvesh set /cluster/sdn` to apply.

Verify after apply:

```bash
ssh root@pve-test.gibbsgreatly.xyz \
  "pvesh get /cluster/sdn/vnets/tvnetc/subnets --output-format json | python3 -m json.tool"
# snat should be 0

ssh root@pve-test.gibbsgreatly.xyz "iptables -t nat -L -n | grep 10.57"
# should show NO MASQUERADE/SNAT entry for 10.57.0.0/24
```

---

## Step E — Add egress validation task to the test suite

**File:** `terraform/lxc/ansible/playbooks/validate-network-layer.yml`

The existing playbook tests east-west reachability between containers on the same
VNet. It does not test north-south egress. Add a parameterised egress task that
runs from the client LXC and verifies internet reachability via routing:

```yaml
- name: Confirm internet egress is reachable from the client LXC (routing, no SNAT)
  ansible.builtin.command:
    cmd: >-
      pct exec {{ network_validation_client_vmid }} -- bash -lc
      "timeout 5 bash -lc 'cat </dev/null >/dev/tcp/8.8.8.8/53'"
  delegate_to: "{{ network_validation_pve_host }}"
  ...
  when: network_validation_test_egress | default(false) | bool
  changed_when: false
```

Guard the task with `network_validation_test_egress: true` so existing
matrix runs that don't set this var are unaffected.

---

## Step F — Re-register ci-runner-01

The ci-runner is currently offline (runner registered under the previous
deployment; the LXC was redeployed today and config.sh was not re-run).

```bash
# 1. Generate a fresh token (valid for 1 hour)
RUNNER_TOKEN=$(gh api \
  --method POST \
  repos/stevedwray/proxmox-homelab/actions/runners/registration-token \
  --jq .token)
echo "Token acquired: ${RUNNER_TOKEN:0:4}..."

# 2. Re-run the deploy playbook through the ProxyJump inventory
cd /home/steve/git/proxmox-homelab
source .env

ansible-playbook \
  -i terraform/lxc/stacks/ci-runner-01/inventory.ini \
  terraform/lxc/ansible/playbooks/deploy-ci-runner.yml \
  --extra-vars "runner_registration_token=${RUNNER_TOKEN}"

# 3. Verify
gh api repos/stevedwray/proxmox-homelab/actions/runners \
  --jq '.runners[] | {name, status}'
```

---

## Step G — Document the router dependency in pve-test.yaml

**File:** `terraform/lxc/network/pve-test.yaml`

Add a comment block near the top of the `attachments` section:

```yaml
# Out-of-band prerequisite: for each SDN subnet with a gateway defined below,
# a corresponding static route must exist on the home router (MikroTik)
# pointing to pve-test (192.168.1.40) as the next hop.
#
# Current required routes:
#   10.57.0.0/24 via 192.168.1.40   (seg_c: build_seg / artifacts_seg)
#
# MikroTik command:
#   /ip route add dst-address=<subnet> gateway=192.168.1.40 comment="pve-test SDN <seg>"
#
# Without these routes, LAN → SDN container ingress will not work and container
# traffic bound for the internet will be dropped (no SNAT fallback).
```

---

## Verification checklist

After all steps are complete:

- [ ] `iptables -t nat -L -n` on pve-test shows **no** MASQUERADE/SNAT entry for
  `10.57.0.0/24`
- [ ] `pvesh get /cluster/sdn/vnets/tvnetc/subnets` shows `snat: 0`
- [ ] `ping 10.57.0.63` succeeds from workstation desktop
- [ ] `ping 8.8.8.8` succeeds from inside the ci-runner LXC
- [ ] GitHub runner `ci-runner-pve-test` is **online**
- [ ] `Validate` workflow completes green on next push to `dev/pve-test`

---

## Future segments

When `seg_a` and `seg_b` are given subnets and gateways (for services in
`apps_seg`, `infra_seg`, `media_seg`, `observe_seg`), apply the same pattern:

1. Add `subnet`, `gateway`, `snat: false` to the attachment in `pve-test.yaml`
2. Add the corresponding static route to the MikroTik and update the comment block
3. Extend `validate-network-layer.yml` egress coverage if needed

No code changes to the playbook or Terraform are required — the parametric model
already handles multiple subnets.

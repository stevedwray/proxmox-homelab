# 00b-pve-test-05 — Redeploy ci-runner-01 and verify Portainer isolation

## Status

PENDING

## Phase

Phase 00b — pve-test Management Bootstrap

## Prerequisites

- Task 00b-04 complete: `TF_VAR_portainer_server_ip=192.168.1.20` set and committed in `.env.pve-test`
- Task 00b-03 complete: Portainer running and reachable at `192.168.1.20:9000`
- `gh` CLI logged in on workstation (the playbook auto-generates the runner registration token)
- `.env` and `.env.pve-test` present in repo root

## Objective

ci-runner-01 (VMID 141) is running on pve-test at `10.57.0.63`, registered as a Portainer
agent with the **local** server at `192.168.1.20` (not production `192.168.1.4`), and the
GitHub Actions runner shows status `online`. The `build_seg` SDN zone (`tvsegc` / `tvnetc`)
is automatically recreated by the apply. This is the first live proof that pve-test is
fully isolated from production Portainer.

## Scope

- `terragrunt apply` in `terraform/lxc/stacks/ci-runner-01/` (recreates LXC and SDN zone)
- Run `deploy-ci-runner.yml` Ansible playbook (installs runner, auto-generates runner token, registers with GitHub)
- Verify runner shows `online` in GitHub Actions

## Out of Scope

- Modifying `ci-runner-01/stack.yaml` or `terragrunt.hcl`
- Any Phase 03b/03c/04 deployments

## Inputs

- `terraform/lxc/stacks/ci-runner-01/stack.yaml`
- `terraform/lxc/stacks/ci-runner-01/terragrunt.hcl`
- `.env` and `.env.pve-test`

## Expected Outputs

- VMID 141 running on pve-test at `10.57.0.63`
- `tvsegc` zone and `tvnetc` VNet live in Proxmox SDN on pve-test
- ci-runner-01 registered as environment in Portainer at `192.168.1.20`
- GitHub Actions runner `ci-runner-pve-test` online

## Constraints and Conventions

- Safety check: verify all three env vars before apply — stop immediately if any is wrong
- Source `.env` first, then `.env.pve-test` last
- The `configure-network-sdn-vnet.yml` playbook runs automatically during `terragrunt apply`
  and recreates the SDN zone and VNet; no manual Proxmox SDN steps needed
- The `deploy-ci-runner.yml` playbook auto-generates the runner registration token via
  `gh api` — no manual token generation required, but `gh` must be authenticated
- This task now requires code changes (see Blockers section below) and a commit

## Blockers — Network fixes required before playbook can succeed

Three issues in `terraform/lxc/network/pve-test.yaml` prevent the playbook from completing.
Fix all three, then re-run `terragrunt apply` followed by `deploy-ci-runner.yml`.

### Fix 1 — Disable VNet firewall on `seg_c`

**File:** `terraform/lxc/network/pve-test.yaml`

The `seg_c` attachment has `firewall: true`. When only `build_seg` is deployed (no
`artifacts_seg` members yet), the firewall rule generator produces zero ACCEPT rules.
`configure_network_vnet_firewall` then writes `/etc/pve/sdn/firewall/tvnetc.fw` with
`policy_forward: DROP` and an empty `[RULES]` section, which blocks all traffic through
the `tvnetc` bridge — including SSH from `pve-test` to `10.57.0.63`.

Change:

```yaml
  seg_c:
    description: Third SDN VNet attachment for artifact flow validation on pve-test
    type: sdn_vnet
    bridge: tvnetc
    firewall: false    # was: true — re-enable when artifacts_seg has members deployed
```

This sets `network_firewall = false` on the LXC NIC and skips`configure_network_vnet_firewall`
entirely (count = 0). Any previously written `tvnetc.fw` will be left stale on disk but
harmless — the firewall is not loaded if the NIC flag is off.

### Fix 2 — Enable SNAT on the `10.57.0.0/24` subnet

**File:** `terraform/lxc/network/pve-test.yaml`

The `seg_c` SDN attachment has `snat: false`. The runner registration step
(`./config.sh --url https://github.com/... --token ...`) requires outbound internet
access from `10.57.0.63`. Without SNAT, packets from the `10.57.0.0/24` SDN subnet have
no masquerade rule and cannot reach the internet.

Change:

```yaml
      snat: true    # was: false
```

`configure-network-sdn-vnet.yml` will update the existing subnet entry on re-apply via the
`pvesh set /cluster/sdn/vnets/tvnetc/subnets/...` task (it diffs current vs desired state).

### Fix 3 — Add router static route (out-of-band, MikroTik)

The `wait_for_connection` task in `deploy-ci-runner.yml` runs on the workstation (no
`delegate_to`), so the workstation needs a route to `10.57.0.0/24` via pve-test.

Run on the MikroTik router before executing the playbook:

```
/ip route add dst-address=10.57.0.0/24 gateway=192.168.1.40 comment="pve-test SDN seg_c"
```

This is documented as a prerequisite in `pve-test.yaml` (`attachments.seg_c` comment block)
but was not in place when the initial apply ran. Verify it exists before re-running:

```bash
ssh admin@192.168.1.1 "/ip route print where dst-address=10.57.0.0/24"
```

### Re-apply sequence after fixes

```bash
# 1. Source env (order matters)
source /home/steve/git/proxmox-homelab/.env
source /home/steve/git/proxmox-homelab/.env.pve-test

# 2. Confirm targets
echo "node=$TF_VAR_proxmox_node"   # must print: pve-test

# 3. Re-apply to push snat change and drop the VNet firewall resource
cd /home/steve/git/proxmox-homelab/terraform/lxc/stacks/ci-runner-01
terragrunt apply

# 4. Confirm SSH from pve-test to container works
ssh root@pve-test.gibbsgreatly.xyz "nc -zv 10.57.0.63 22"

# 5. Confirm outbound internet from container works
ssh root@pve-test.gibbsgreatly.xyz "lxc-attach -n 141 -- curl -s --max-time 5 https://github.com"

# 6. Run the playbook
cd /home/steve/git/proxmox-homelab
ansible-playbook \
  -i terraform/lxc/stacks/ci-runner-01/inventory.yml \
  terraform/lxc/ansible/playbooks/deploy-ci-runner.yml
```

> **Note on VNet firewall re-enablement:** Re-enable `firewall: true` on `seg_c` when
> `artifacts_seg` gains its first deployed member. At that point the rule generator will
> produce valid FORWARD ACCEPT rules for TCP 5000/8081 between the two zones and the
> DROP default becomes meaningful.

## Acceptance Criteria

- [ ] `TF_VAR_proxmox_node` prints `pve-test` before apply
- [ ] `TF_WORKSPACE` prints `pve-test` before apply
- [ ] `TF_VAR_portainer_server_ip` prints `192.168.1.20` before apply
- [ ] `terragrunt apply` exits 0
- [ ] `pvesh get /nodes/pve-test/lxc` shows VMID 141
- [ ] SSH to `10.57.0.63` succeeds as root
- [ ] `tvsegc` zone and `tvnetc` VNet visible in Proxmox SDN on pve-test
- [ ] ci-runner-01 appears as an environment in Portainer at `192.168.1.20`
- [ ] `gh api repos/stevedwray/proxmox-homelab/actions/runners --jq '.runners[] | select(.name == "ci-runner-pve-test") | .status'` prints `online`
- [ ] Production Portainer at `192.168.1.4` not required at any point

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Redeploy ci-runner-01 after the Phase 00b wipe, targeting the new pve-test-local
Portainer server at 192.168.1.20. This is both a restore of CI capacity and a live
proof-of-isolation test for Phase 00b.

CONTEXT:
- ci-runner-01 was destroyed in task 00b-01 (wipe step). Its SDN zone (tvsegc / tvnetc)
  was also removed by the destroy provisioner — this is expected behaviour.
- .env.pve-test now has TF_VAR_portainer_server_ip=192.168.1.20 (set in task 00b-04).
- terragrunt apply will recreate the LXC AND automatically re-create the build_seg SDN
  zone via configure-network-sdn-vnet.yml. No manual SDN setup needed.
- deploy-ci-runner.yml auto-generates the runner registration token via gh API. Ensure
  gh is authenticated on the workstation before running the playbook.
- This task has no code changes — no commit needed.

STEP 1 — Source environment and verify:

  source /home/steve/git/proxmox-homelab/.env
  source /home/steve/git/proxmox-homelab/.env.pve-test

  # Stop immediately if any value is wrong:
  echo "Node target     : $TF_VAR_proxmox_node"       # must print: pve-test
  echo "TF workspace    : $TF_WORKSPACE"               # must print: pve-test
  echo "Portainer server: $TF_VAR_portainer_server_ip" # must print: 192.168.1.20

STEP 2 — Apply:

  cd /home/steve/git/proxmox-homelab/terraform/lxc/stacks/ci-runner-01
  terragrunt apply

  # The apply will:
  #   1. Run configure-network-sdn-vnet.yml (recreates tvsegc zone + tvnetc VNet)
  #   2. Provision VMID 141 on pve-test at 10.57.0.63
  #   3. Generate inventory.yml

STEP 3 — Configure the runner:

  cd /home/steve/git/proxmox-homelab
  ansible-playbook \
    -i terraform/lxc/stacks/ci-runner-01/inventory.yml \
    terraform/lxc/ansible/playbooks/deploy-ci-runner.yml

  # The playbook will:
  #   1. Auto-generate a runner registration token via gh api
  #   2. Install and register the runner (name: ci-runner-pve-test)
  #   3. Poll GitHub API until runner status == online

STEP 4 — Verify:

  # Runner online (check GitHub):
  gh api repos/stevedwray/proxmox-homelab/actions/runners \
    --jq '.runners[] | select(.name == "ci-runner-pve-test") | {name, status}'
  # Expected: {"name": "ci-runner-pve-test", "status": "online"}

  # SDN recreated on pve-test:
  ssh root@pve-test.gibbsgreatly.xyz \
    "pvesh get /cluster/sdn/zones --output-format json | jq '.[] | select(.zone == \"tvsegc\") | .zone'"
  # Expected: "tvsegc"

DONE WHEN:
- terragrunt apply exits 0
- Runner shows online in GitHub Actions
- No connection to 192.168.1.4 (production Portainer) required
```

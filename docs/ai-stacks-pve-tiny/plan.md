# ai-stacks-pve-tiny plan

Written with `.github/prompts/plan-change.prompt.md`, following
`docs/agent-design/step-packet-schema.md`. Step blocks are meant to be run
one at a time with `.github/prompts/implement-step.prompt.md`. Everything
that touches a live node is written as plain operator instructions, not
step blocks.

## How to execute this plan

| Phase | Who runs it | How | Production approval |
|---|---|---|---|
| 0 — preflight | Operator, from a terminal at the repo root | Paste the commands in Phase 0 and paste the output back into a Claude Code session for the go/no-go | None (read-only) |
| 1 — step blocks `ai-tiny-01`…`05` plus `ai-tiny-05b` | Local model | VS Code Copilot, **Repo Tools** agent mode: `/implement-step` with "run implement-step against docs/ai-stacks-pve-tiny/plan.md, step ai-tiny-01-storage-profile" (then `-02`, `-03`, `-04`, `-05`, and `-05b`, one per invocation). `.github/prompts/implement-step.prompt.md` governs it: do the one step, run its gates, write a hand-back into `README.md`, stop. A Claude Code session can also run a step by being told "execute step <id> from docs/ai-stacks-pve-tiny/plan.md exactly as written, then run its gates". | None (repo edits only) |
| 1 — review + commit | Operator (or Claude Code) | Read each hand-back in `README.md`, or re-run the step's gates if it's missing (see `docs/agent-design/README.md` §3), then `git commit` on `task/ai-stacks-pve-tiny`. Then run the read-only `terragrunt plan` loop at the end of Phase 1. | None (`terragrunt plan` is on the read-only allowlist) |
| 2 — ai_seg on pve-tiny | Operator | Switch/MikroTik by hand, then the commands in 2b–2d | Yes: `TASK_APPROVAL=ai-stacks-pve-tiny-sdn` |
| 3 — cutovers | Operator, one stack per session/approval | Generic procedure plus that stack's section | Yes: one `TASK_APPROVAL` per stack (table in Phase 3) |
| 4 — soak/decommission | Operator | Commands in Phase 4, then step block `ai-tiny-06` via `/implement-step` as in Phase 1 | Yes: `ai-stacks-pve-tiny-decommission-<stack>` |

**Production approval flow (CLAUDE.md, Production Credential Controls)**
for every approval-marked row above:
1. A Claude Code session posts a Preflight Summary: target node
   (`pve-tiny`, plus `pve` for the stop/export/destroy commands), whether
   it mutates, exact CTs/VMIDs, exact commands from this plan, and what's
   out of scope.
2. The operator says "Proceed" in chat.
3. The operator runs `export TASK_APPROVAL=<name>` and the commands.
4. The session posts an After-Action Summary and updates the Progress
   table in `README.md`.

**Tooling notes:**
- Wrapper: `./with-secrets-prod-tiny` (node `pve-tiny`), **not**
  `./with-secrets-prod`. The latter sets `PVE_ENV=pve`, so `provision.sh`
  silently SKIPs with "inventory file not found".
- Plain `ssh root@pve…`/`ssh root@pve-tiny…` commands (`pct …`, `tar`)
  need no wrapper. Claude Code's auto-mode classifier blocks them even
  when read-only, so the operator runs them from their own terminal.
- If Claude Code runs `ansible-playbook` or `provision.sh` through its
  Bash tool and hits `Ansible requires blocking IO`, wrap the command as
  `script -qec "<command>" /dev/null`. This doesn't apply in a normal
  terminal.
- `terragrunt` commands take `--working-dir terraform/lxc/environments/pve-tiny/<stack>`,
  run from the repo root.
- Workstation staging directory for data archives (outside the repo,
  since it holds real user data): create it once, before the first
  cutover, with `mkdir -m 700 -p ~/pve-tiny-migration`.

## Goal

Move four AI-related LXCs from `pve` to `pve-tiny`:

| Stack | VMID | IP | Zone | State that must survive |
|---|---|---|---|---|
| `mcp-utility-stack` | 50011 | 192.168.50.10 | `ai_seg` (VLAN 50) | none (cache and pgvector index can be rebuilt; reindexed on provision) |
| `secpipe-stack` | 50012 | 192.168.50.12 | `ai_seg` (VLAN 50) | none (writes only into OpenSearch) |
| `opensearch-stack` | 40014 | 192.168.40.14 | `infra_seg` (VLAN 40) | `/var/lib/opensearch-data` (all indices, security index, Dashboards saved objects) |
| `ai-services-stack` | 50013 | 192.168.50.11 | `ai_seg` (VLAN 50) | Docker volumes `ai-services-openwebui-data`, `ai-services-searxng-data`, `ai-services-deep-research-config` |

`pentagi-stack`/`pentagi-upstream-control` are out of scope (deprecated;
decommission separately).

## Decisions (operator, 2026-09-26)

1. **Scope:** the four stacks above, including `secpipe-stack`.
2. **Mechanism:** redeploy from IaC on pve-tiny at the **same IP**, plus a
   cold copy of only the stateful paths. No vzdump/restore and no
   `terragrunt import`.
3. **Storage:** a new `platform-nvme` profile puts rootfs and Docker on
   pve-tiny's 2TB `nvme-lvm`. OpenSearch's data mount uses the existing
   `durable-nvme` profile.
4. **SDN validation:** `ai_seg` is added directly on pve-tiny, with no
   pve-test-vm detour (same as the `cse_seg` precedent). It is proven with
   a temporary host IP before any CT moves.

## Why this shape

- **Same IP means nothing outside the CT changes.** MikroTik firewall rules
  are IP/subnet-based. Traefik `edge.yaml` backends are IPs. Portainer
  endpoints are registered as `tcp://<ip>:9001`. Consumers (secpipe →
  OpenSearch/MCP, Grafana → OpenSearch, Harbor/GVM ingest → OpenSearch,
  VS Code → docs-rag) all use IPs or FQDNs that resolve to the same IPs.
  None of them need touching.
- **Old and new can't run at the same time**, since they share an IP. So
  each cutover is: stop old → copy state off the stopped old CT → create
  new → load state → verify. The old CT stays on pve, stopped, with
  `onboot=0`, as an instant rollback until decommission.
- **Terraform stays the source of truth.** Each new CT is created by
  `terragrunt apply` in a new `terraform/lxc/environments/pve-tiny/<stack>/`
  dir, so its state is clean from the start. The old CT on pve is retired
  with `pct destroy` rather than `terragrunt destroy`, because the changed
  `storage_profile` no longer resolves against `storage/pve.yaml`. That's
  the same way `dns-stack` was removed.
- **Cold copy through `pct mount`.** The cutover is allowed to proceed only
  after Phase 0 confirms both old stateful CTs are unprivileged and have no
  custom `lxc.idmap` entries (therefore they use the default 100000 idmap).
  A host-side `tar --numeric-owner` from the old
  CT's mounted filesystem, restored into the new CT's mounted filesystem,
  keeps ownership correct without any uid shifting. The archive is staged
  on the workstation, which also gives an offline copy of the data until
  decommission.
- **`provision.sh` under `./with-secrets-prod-tiny` is safe for these
  stacks:** edge reconcile SKIPs (there's no `proxy-stack` inventory under
  `environments/pve-tiny/`), and Portainer registration SKIPs (it only runs
  for `PVE_ENV=pve`). Both are fine, because the existing Traefik routes and
  Portainer endpoints already point at the unchanged IPs.

## Facts checked in the repo (not live)

- `storage/pve-tiny.yaml` has only `platform-default` (boot SSD
  `local-lvm`) and `durable-default`/`durable-nvme`. Current profiles on
  these stacks (`platform-default`, `platform-monitoring-zfs`,
  `durable-zfs`) are pve-specific names that don't exist, or resolve
  wrongly, on pve-tiny.
- `network/pve-tiny.yaml` has `infra_seg`/`mgmt_seg`/`cse_seg`, and no
  `ai_seg`.
- `proxmox-sdn-setup.yml` needs a `sdn_subnet_<vnet>`/`sdn_gw_<vnet>` pair
  per vnet. `tvai` has none yet. The ai_seg env vars exist only in
  uppercase in `.env` (`LAB_SUBNET_AI_CIDR`, `LAB_GW_AI`), unlike the
  lowercase ones the playbook uses for other zones.
- `terragrunt apply` creates **and starts** the CT (and its SDN vnet
  attachment), but doesn't deploy the app. `provision.sh` does that.
- OpenSearch needs `vm.max_map_count=262144` on the **host**. That was
  checked by hand on pve, and nothing in the repo sets it.
- `mcp-utility-stack`'s playbook builds from `~/git/cve-mcp-server` on
  the controller.
- Capacity: these four add 14GB RAM / 8 vCPU. pve-tiny already carries
  the cse-* stacks (7GB), so the total is about 21GB of 32GB. **This uses
  up the headroom the original pve-tiny plan reserved for
  harbor-stack/graylog-stack**, which is accepted as part of the scope
  decision.

## Not verified live (Claude's production reads are blocked). Phase 0 covers these.

Old CTs actually unprivileged and using the default idmap; real data sizes; pve-tiny free RAM, cores
and `nvme-lvm` space; `vm.max_map_count` on pve-tiny; existing backup jobs
on both nodes; whether VLAN 50 reaches pve-tiny's switch port.

---

## Phase 0 — Read-only preflight (operator)

Run these and paste the output back into the session before anything else.
They're all read-only.

```bash
# pve: old CT config, data sizes, backup jobs
ssh root@pve.gibbsgreatly.xyz '
for id in 50011 50012 50013 40014; do echo "== $id"; pct config $id | grep -E "^(hostname|memory|cores|rootfs|mp[0-9]|net0|unprivileged|onboot|lxc\.idmap)"; done
pct exec 50013 -- du -sh /var/lib/docker/volumes/ai-services-openwebui-data/_data /var/lib/docker/volumes/ai-services-searxng-data/_data /var/lib/docker/volumes/ai-services-deep-research-config/_data
pct exec 40014 -- du -sh /var/lib/opensearch-data
cat /etc/pve/jobs.cfg 2>/dev/null
'

# pve-tiny: capacity, storage, sysctl, SDN, backup jobs
ssh root@pve-tiny.gibbsgreatly.xyz '
pct list; nproc; free -g; pvesm status; lvs
sysctl vm.max_map_count
pvesh get /cluster/sdn/vnets --output-format json
pvesh get /cluster/sdn/zones --output-format json
for vnet in tvinfra tvmgmt tvcse tvai; do pvesh get /cluster/sdn/vnets/$vnet/subnets --output-format json 2>/dev/null || true; done
cat /etc/pve/firewall/cluster.fw 2>/dev/null
cat /etc/pve/jobs.cfg 2>/dev/null
echo "== pending SDN changes (count of objects carrying a pending state; must be 0)"
pending_rc=0
check_pending() {
  label="$1"; shift
  if ! json=$("$@"); then echo "$label: ERROR reading pending state" >&2; return 1; fi
  if ! count=$(printf "%s\n" "$json" | python3 -c "import json,sys;d=json.load(sys.stdin);assert isinstance(d,list) and all(isinstance(x,dict) for x in d);print(sum(1 for x in d if \"state\" in x))"); then echo "$label: ERROR parsing pending JSON" >&2; return 1; fi
  echo "$label: $count"
  [ "$count" -eq 0 ]
}
check_pending zones pvesh get /cluster/sdn/zones --pending 1 --output-format json || pending_rc=1
check_pending vnets pvesh get /cluster/sdn/vnets --pending 1 --output-format json || pending_rc=1
if ! current_vnets_json=$(pvesh get /cluster/sdn/vnets --output-format json); then echo "ERROR reading current VNets" >&2; pending_rc=1; current_vnets_json="[]"; fi
if ! current_vnets=$(printf "%s\n" "$current_vnets_json" | python3 -c "import json,sys;d=json.load(sys.stdin);assert isinstance(d,list) and all(isinstance(x,dict) and isinstance(x.get(\"vnet\"),str) for x in d);print(\" \".join(x[\"vnet\"] for x in d))"); then echo "ERROR parsing current VNets" >&2; pending_rc=1; current_vnets=""; fi
for vnet in $current_vnets; do check_pending "subnets/$vnet" pvesh get /cluster/sdn/vnets/$vnet/subnets --pending 1 --output-format json || pending_rc=1; done
[ "$pending_rc" -eq 0 ] || exit 1
'

# workstation: staging space and the cve-mcp-server source clone
mkdir -m 700 -p ~/pve-tiny-migration
df -h ~ ; test -d /home/steve/git/cve-mcp-server && echo cve-mcp-src-ok
```

**Go/no-go:**
- every old CT shows `unprivileged: 1`, and 40014/50013 show no
  `lxc.idmap` lines; if either stateful CT has a custom mapping, stop and
  redesign the copy/ownership conversion before proceeding
- pve-tiny `free -g` "available" ≥ 16
- `nvme-lvm` free ≥ 300G
- workstation free space > (OpenSearch `du` + OpenWebUI `du`) × 1.2
- `cve-mcp-src-ok` printed
- the pending-SDN block exits 0 and every count line shows `0`. Any API
  error, malformed JSON or non-zero count makes the remote preflight exit
  non-zero. The playbook's final
  `pvesh set /cluster/sdn` applies **all** pending SDN config on the node,
  not just `tvai`, so any unrelated pending edit would be applied with it
  in 2b. If any count is non-zero, run the corresponding
  `pvesh get … --pending 1 --output-format json` command directly to see
  what is pending. Then resolve it
  (apply deliberately under its own approval, or revert it in the GUI's
  SDN panel) before Phase 2. This check was written from the Proxmox API
  docs (pending objects carry a `state` of new/changed/deleted) and hasn't
  been run live yet; an API-shape mismatch is therefore a hard stop, not a
  zero count.

Record whether pve's `jobs.cfg` covers 40014/50013 and whether pve-tiny has
any backup job. That decides the backup follow-up in Phase 4.

---

## Phase 1 — Repo changes (step blocks, local model)

All six steps (`01`…`05` plus `05b`) are pure repo edits. They can land before any cutover:
nothing reads them until the operator runs `terragrunt`/`provision.sh`
under `./with-secrets-prod-tiny`. Commit them on `task/ai-stacks-pve-tiny`.

### ai-tiny-01-storage-profile

```yaml
id: ai-tiny-01-storage-profile
title: Add platform-nvme storage profile for pve-tiny (plus pve-test-vm alias)
depends_on: []

change: >
  In terraform/lxc/storage/pve-tiny.yaml, under `profiles:`, directly after
  the existing `platform-default:` block (after its line
  `    docker_required_content_type: rootdir`, before the blank line and
  `extra_mount_profiles:`), insert exactly the block in LITERAL_1 below. In
  terraform/lxc/storage/pve-test-vm.yaml, insert exactly the block in
  LITERAL_2 at the end of `profiles:` (directly before the blank line that
  precedes `extra_mount_profiles:`). Change nothing else in either file.

  LITERAL_1 (2-space indent, as shown):
    # Rootfs + Docker both on the 2TB NVMe pool (nvme-lvm), not the boot
    # SSD's local-lvm. Added for the AI-stack relocation from pve
    # (docs/ai-stacks-pve-tiny/plan.md): those four stacks alone
    # thin-allocate ~116GB of rootfs+docker, more than the boot SSD's pool
    # can safely carry alongside the cse-* stacks already on it.
    platform-nvme:
      rootfs_storage: nvme-lvm
      docker_storage: nvme-lvm
      rootfs_required_content_type: rootdir
      docker_required_content_type: rootdir

  LITERAL_2 (2-space indent, as shown):
    # Alias only: stacks whose stack.yaml selects platform-nvme (a pve-tiny
    # profile, docs/ai-stacks-pve-tiny/plan.md) still resolve here.
    platform-nvme:
      rootfs_storage: infrastructure-containers
      docker_storage: infrastructure-containers
      rootfs_required_content_type: rootdir
      docker_required_content_type: rootdir

scope:
  allowed_paths:
    - terraform/lxc/storage/pve-tiny.yaml
    - terraform/lxc/storage/pve-test-vm.yaml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Editing terraform/lxc/storage/pve.yaml"
    - "Any terragrunt, provision.sh, ssh or ansible-playbook run"

gates:
  - id: profile-resolves
    cmd: |
      python3 -c "import yaml;d=yaml.safe_load(open('terraform/lxc/storage/pve-tiny.yaml'));p=d['profiles']['platform-nvme'];assert (p['rootfs_storage'],p['docker_storage'])==('nvme-lvm','nvme-lvm');assert d['profiles']['platform-default']['rootfs_storage']=='local-lvm';t=yaml.safe_load(open('terraform/lxc/storage/pve-test-vm.yaml'));assert t['profiles']['platform-nvme']['rootfs_storage']=='infrastructure-containers';print('ok')"
    expect: "prints ok, exit 0"
    critical: true
  - id: only-two-files-changed
    cmd: "git diff --name-only -- terraform/lxc/storage/"
    expect: "exactly terraform/lxc/storage/pve-test-vm.yaml and terraform/lxc/storage/pve-tiny.yaml"
    critical: true
```

### ai-tiny-02-network-ai-seg

```yaml
id: ai-tiny-02-network-ai-seg
title: Declare ai_seg (VLAN 50) on pve-tiny
depends_on: []

change: >
  In terraform/lxc/network/pve-tiny.yaml, (1) under `attachments:`, directly
  after the `cse_seg:` attachment block (after its last line
  `      snat: false`, before the blank line and `zones:`), insert a blank
  line followed by exactly LITERAL_1; (2) under `zones:`, directly after the
  `cse_seg:` zone entry (after its line
  `      - "cse-code-eval (LXC, VMID 100071) — 192.168.100.71"`, before the
  blank line and `inventory:`), insert exactly LITERAL_2. Change nothing
  else in the file; the `${...}` placeholders are literal text, not to be
  expanded.

  LITERAL_1 (2-space indent, as shown):
    # ai_seg — AI/LLM application services + MCP adapters (VLAN 50,
    # 192.168.50.0/24). Same physical VLAN/subnet/gateway as pve's ai_seg
    # (terraform/lxc/network/pve.yaml) — pve-tiny joins it so the relocated
    # ai-services-stack/mcp-utility-stack/secpipe-stack keep their existing
    # IPs, MikroTik firewall rules and Traefik backends unchanged
    # (docs/ai-stacks-pve-tiny/plan.md).
    ai_seg:
      description: AI/LLM application services + external-utility MCP adapters
      type: sdn_vnet
      bridge: tvai
      firewall: false
      sdn:
        zone: tvai
        zone_type: vlan
        bridge: vmbr0
        nodes:
          - pve-tiny
        vnet: tvai
        vlan_tag: 50
        alias: pve-tiny AI segment
        subnet: "${lab_subnet_ai_cidr}"
        gateway: "${lab_gw_ai}"
        snat: false

  LITERAL_2 (2-space indent, as shown):
    ai_seg:
      description: AI/LLM application services + external-utility MCP adapters
      attachment: ai_seg
      containers: []  # filled in by ai-tiny-06 once each stack has cut over

scope:
  allowed_paths:
    - terraform/lxc/network/pve-tiny.yaml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Editing terraform/lxc/network/pve.yaml"
    - "Any terragrunt, provision.sh, ssh or ansible-playbook run"

gates:
  - id: ai-seg-declared
    cmd: |
      python3 -c "import yaml;d=yaml.safe_load(open('terraform/lxc/network/pve-tiny.yaml'));a=d['attachments']['ai_seg'];s=a['sdn'];assert (a['type'],a['bridge'],s['zone'],s['vnet'],s['vlan_tag'],s['nodes'],s['bridge'],s['zone_type'])==('sdn_vnet','tvai','tvai','tvai',50,['pve-tiny'],'vmbr0','vlan');assert d['zones']['ai_seg']['attachment']=='ai_seg';assert set(d['attachments'])=={'lan','infra_seg','mgmt_seg','cse_seg','ai_seg'};assert set(d['zones'])=={'infra_seg','mgmt_seg','cse_seg','ai_seg'};print('ok')"
    expect: "prints ok, exit 0"
    critical: true
  - id: placeholders-literal
    cmd: |
      grep -c -F -e 'subnet: "${lab_subnet_ai_cidr}"' -e 'gateway: "${lab_gw_ai}"' terraform/lxc/network/pve-tiny.yaml
    expect: "2"
    critical: true
```

### ai-tiny-03-sdn-playbook-vars

```yaml
id: ai-tiny-03-sdn-playbook-vars
title: Add tvai vars and a scoped SDN reconciliation mode
depends_on: []

change: >
  In ansible/00-initial-setup/proxmox-sdn-setup.yml, directly after the
  existing line `    sdn_gw_tvcse: "{{ lookup('env', 'lab_gw_cse') }}"`
  insert these two lines (4-space indent):
      sdn_subnet_tvai: "{{ lookup('env', 'LAB_SUBNET_AI_CIDR') }}"
      sdn_gw_tvai: "{{ lookup('env', 'LAB_GW_AI') }}"
  Uppercase is deliberate: `.env` defines the ai_seg values only as
  LAB_SUBNET_AI_CIDR/LAB_GW_AI, not in lowercase like the other zones.
  Directly after the "Load network intent for target environment" task,
  insert LITERAL_1. Directly after the existing "Read current SDN VNets"
  task, insert LITERAL_2. On the existing "Disable Proxmox cluster firewall"
  task, add LITERAL_3 at task level directly after `changed_when: true`.
  Change nothing else. This preserves the playbook's existing default
  behavior for other callers, while Phase 2 can reject all pre-existing
  pending zone/VNet/subnet changes, reconcile only tvai, and explicitly
  leave the production firewall file untouched.

  LITERAL_1 (4-space task indentation, as shown):
    - name: Limit SDN reconciliation to explicitly requested VNets
      ansible.builtin.set_fact:
        proxmox_sdn_attachments: >-
          {{
            proxmox_sdn_attachments
            | selectattr('value.sdn.vnet', 'in', requested_sdn_vnets)
            | list
          }}
      when: requested_sdn_vnets | default([]) | length > 0

  LITERAL_2 (4-space task indentation, as shown):
    - name: Read pending SDN zones before scoped mutation
      ansible.builtin.command:
        cmd: pvesh get /cluster/sdn/zones --pending 1 --output-format json
      register: proxmox_sdn_pending_zones_result
      changed_when: false
      when: reject_pending_sdn_changes | default(false) | bool

    - name: Read pending SDN VNets before scoped mutation
      ansible.builtin.command:
        cmd: pvesh get /cluster/sdn/vnets --pending 1 --output-format json
      register: proxmox_sdn_pending_vnets_result
      changed_when: false
      when: reject_pending_sdn_changes | default(false) | bool

    - name: Read pending subnets on every current VNet before scoped mutation
      ansible.builtin.command:
        cmd: "pvesh get /cluster/sdn/vnets/{{ item }}/subnets --pending 1 --output-format json"
      loop: "{{ proxmox_sdn_vnets_result.stdout | from_json | map(attribute='vnet') | list }}"
      register: proxmox_sdn_pending_subnets_result
      changed_when: false
      when: reject_pending_sdn_changes | default(false) | bool

    - name: Refuse to apply unrelated pending SDN changes
      ansible.builtin.assert:
        that:
          - (proxmox_sdn_pending_zones_result.stdout | from_json | selectattr('state', 'defined') | list | length) == 0
          - (proxmox_sdn_pending_vnets_result.stdout | from_json | selectattr('state', 'defined') | list | length) == 0
          - (proxmox_sdn_pending_subnets_result.results | map(attribute='stdout') | map('from_json') | flatten | selectattr('state', 'defined') | list | length) == 0
        fail_msg: "Unrelated pending SDN changes exist; resolve them under their own approval before this scoped run."
        success_msg: "No pre-existing pending SDN changes exist."
      when: reject_pending_sdn_changes | default(false) | bool

  LITERAL_3 (6-space indentation):
      when: manage_cluster_firewall | default(true) | bool

scope:
  allowed_paths:
    - ansible/00-initial-setup/proxmox-sdn-setup.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Renaming or lower-casing the env var names above"
    - "Changing the default behavior when requested_sdn_vnets/reject_pending_sdn_changes/manage_cluster_firewall are not passed"
    - "Running the playbook (syntax-check only)"

gates:
  - id: vars-present
    cmd: |
      grep -c -F -e "sdn_subnet_tvai: \"{{ lookup('env', 'LAB_SUBNET_AI_CIDR') }}\"" -e "sdn_gw_tvai: \"{{ lookup('env', 'LAB_GW_AI') }}\"" ansible/00-initial-setup/proxmox-sdn-setup.yml
    expect: "2"
    critical: true
  - id: scoped-mode-present
    cmd: |
      python3 -c "p=open('ansible/00-initial-setup/proxmox-sdn-setup.yml').read();assert \"selectattr('value.sdn.vnet', 'in', requested_sdn_vnets)\" in p;assert 'when: requested_sdn_vnets | default([]) | length > 0' in p;assert p.count('when: reject_pending_sdn_changes | default(false) | bool')==4;assert '/cluster/sdn/zones --pending 1' in p;assert '/cluster/sdn/vnets --pending 1' in p;assert \"selectattr('state', 'defined')\" in p;assert 'when: manage_cluster_firewall | default(true) | bool' in p;print('ok')"
    expect: "prints ok, exit 0"
    critical: true
  - id: syntax-check
    cmd: "ansible-playbook --syntax-check -i localhost, ansible/00-initial-setup/proxmox-sdn-setup.yml"
    expect: "exit 0"
    critical: true
```

### ai-tiny-04-stack-storage-profiles

```yaml
id: ai-tiny-04-stack-storage-profiles
title: Point the four stacks at pve-tiny's NVMe storage profiles
depends_on: [ai-tiny-01-storage-profile]

change: >
  In each of terraform/lxc/stacks/{ai-services-stack,mcp-utility-stack,secpipe-stack}/stack.yaml
  replace the line `storage_profile: platform-default` with
  `storage_profile: platform-nvme`. In
  terraform/lxc/stacks/opensearch-stack/stack.yaml replace
  `storage_profile: platform-monitoring-zfs` with
  `storage_profile: platform-nvme`, `extra_mount_profile: durable-zfs` with
  `extra_mount_profile: durable-nvme`, and the indented
  `  profile: durable-zfs` (inside the `extra_mount:` block) with
  `  profile: durable-nvme`. Change no other line (sizes, IPs, vmids and
  zones all stay exactly as they are).

scope:
  allowed_paths:
    - terraform/lxc/stacks/ai-services-stack/stack.yaml
    - terraform/lxc/stacks/mcp-utility-stack/stack.yaml
    - terraform/lxc/stacks/secpipe-stack/stack.yaml
    - terraform/lxc/stacks/opensearch-stack/stack.yaml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Changing ip_address, vmid, network.zone, memory, cores or any size"

gates:
  - id: profiles-resolve-on-pve-tiny
    cmd: |
      python3 -c "import yaml;m=yaml.safe_load(open('terraform/lxc/storage/pve-tiny.yaml'));ss=['ai-services-stack','mcp-utility-stack','secpipe-stack','opensearch-stack'];ds=[yaml.safe_load(open('terraform/lxc/stacks/%s/stack.yaml'%s)) for s in ss];assert all(d['storage_profile']=='platform-nvme' and d['storage_profile'] in m['profiles'] for d in ds);o=ds[3];assert o['extra_mount_profile']=='durable-nvme' and o['extra_mount']['profile']=='durable-nvme' and 'durable-nvme' in m['extra_mount_profiles'];print('ok')"
    expect: "prints ok, exit 0"
    critical: true
  - id: diff-is-profile-lines-only
    cmd: "git diff -U0 -- terraform/lxc/stacks/ | grep -E '^[+-][^+-]' | grep -v -E '^[+-] *(storage_profile|extra_mount_profile|profile): ' | wc -l"
    expect: "0"
    critical: true
```

### ai-tiny-05-env-dirs

```yaml
id: ai-tiny-05-env-dirs
title: Move the four stacks' Terragrunt env dirs from pve to pve-tiny
depends_on: [ai-tiny-04-stack-storage-profiles]

change: >
  For each STACK in ai-services-stack, mcp-utility-stack, secpipe-stack,
  opensearch-stack: create terraform/lxc/environments/pve-tiny/STACK/terragrunt.hcl
  as a byte-identical copy of terraform/lxc/environments/pve-tiny/cse-controller/terragrunt.hcl
  (`cp`), then `git add` it; and run `git rm --cached terraform/lxc/environments/pve/STACK/terragrunt.hcl`
  followed by `rm terraform/lxc/environments/pve/STACK/terragrunt.hcl`. Do
  not delete anything else under terraform/lxc/environments/pve/STACK/:
  the untracked terraform.tfstate.d/, inventory.yml, etc. must stay
  until the operator decommissions the old CT.

scope:
  allowed_paths:
    - terraform/lxc/environments/pve-tiny/
    - terraform/lxc/environments/pve/ai-services-stack/terragrunt.hcl
    - terraform/lxc/environments/pve/mcp-utility-stack/terragrunt.hcl
    - terraform/lxc/environments/pve/secpipe-stack/terragrunt.hcl
    - terraform/lxc/environments/pve/opensearch-stack/terragrunt.hcl
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Deleting terraform.tfstate*, terraform.tfstate.d/, inventory.yml or any other untracked file under environments/pve/"
    - "Any terragrunt run"

gates:
  - id: new-hcl-identical
    cmd: "for s in ai-services-stack mcp-utility-stack secpipe-stack opensearch-stack; do cmp terraform/lxc/environments/pve-tiny/cse-controller/terragrunt.hcl terraform/lxc/environments/pve-tiny/$s/terragrunt.hcl || exit 1; done; echo ok"
    expect: "prints ok"
    critical: true
  - id: tracked-correctly
    cmd: "t=0; p=0; for s in ai-services-stack mcp-utility-stack secpipe-stack opensearch-stack; do t=$((t + $(git ls-files terraform/lxc/environments/pve-tiny/$s/terragrunt.hcl | wc -l))); p=$((p + $(git ls-files terraform/lxc/environments/pve/$s/terragrunt.hcl | wc -l))); done; echo tiny=$t pve=$p"
    expect: "tiny=4 pve=0"
    critical: true
  - id: old-state-kept
    cmd: "for s in ai-services-stack mcp-utility-stack secpipe-stack opensearch-stack; do test -d terraform/lxc/environments/pve/$s/terraform.tfstate.d || exit 1; done; echo ok"
    expect: "prints ok"
    critical: true
```

### ai-tiny-05b-provision-target-guard

```yaml
id: ai-tiny-05b-provision-target-guard
title: Extend provision.sh's inventory target guard to pve-tiny
depends_on: []

change: >
  In scripts/provision.sh, update the usage text's --target-env value list
  from `<pve-test-vm|pve>` to `<pve-test-vm|pve|pve-tiny>`. In
  expected_pve_host_for_env(), directly after the pve case, add exactly:
      pve-tiny) printf 'pve-tiny.gibbsgreatly.xyz' ;;
  Change nothing else. This makes the existing stale/wrong-inventory
  incident guard active for pve-tiny instead of silently returning an
  empty expected host.

scope:
  allowed_paths:
    - scripts/provision.sh
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any provision.sh, ansible-playbook, terragrunt or ssh run"

gates:
  - id: shell-syntax
    cmd: "bash -n scripts/provision.sh"
    expect: "exit 0"
    critical: true
  - id: pve-tiny-mapping-present
    cmd: |
      python3 -c "p=open('scripts/provision.sh').read();assert \"pve-tiny) printf 'pve-tiny.gibbsgreatly.xyz' ;;\" in p;assert '--target-env <pve-test-vm|pve|pve-tiny>' in p;print('ok')"
    expect: "prints ok, exit 0"
    critical: true
```

**After ai-tiny-01…05 and ai-tiny-05b land (operator):** commit on
`task/ai-stacks-pve-tiny` and run a read-only plan for each new env to
confirm it resolves: one container create, with rootfs, docker mount and
(for OpenSearch) the extra mount all on `nvme-lvm`, and nothing else.

```bash
for s in mcp-utility-stack secpipe-stack opensearch-stack ai-services-stack; do
  ./with-secrets-prod-tiny terragrunt plan --working-dir terraform/lxc/environments/pve-tiny/$s -no-color > /tmp/plan-$s.txt 2>&1; echo "$s exit $?"
  grep -E 'Plan:|datastore_id|storage' /tmp/plan-$s.txt | sort | uniq -c
done
```

---

## Phase 2 — ai_seg on pve-tiny (operator)

**2a. Switch trunk.** Add VLAN 50 as tagged on pve-tiny's port on the
physical switch (the same port that already carries 20/40/100). On the
MikroTik, confirm read-only that VLAN 50 is already tagged on the port
pve-tiny's traffic arrives on (`/interface bridge vlan print where
vlan-ids=50`). The cse_seg work found every existing VLAN tagged on
bridge+ether1+ether5, but check rather than assume, because `ether1` has
ingress filtering and drops untagged-set VLANs silently.

**2b. Create the tvai zone/vnet** (preflight summary → approval first).
The filter and firewall flag are mandatory: without them this shared
playbook reconciles every declared VNet and rewrites/restarts the Proxmox
cluster firewall. The approved scope here is only the tvai zone, VNet and
subnet plus the final SDN apply; tvinfra/tvmgmt/tvcse and
`/etc/pve/firewall/cluster.fw` are explicitly out of scope.

The `reject_pending_sdn_changes=true` flag is mandatory. Inside the same
playbook run, immediately before its first mutation, it reads pending zones,
VNets, and subnets for every currently existing VNet. An API error, malformed
JSON, or any object carrying a pending `state` fails the play before tvai is
created. This closes the time and coverage gap that a separate shortened
shell recheck would leave.

```bash
export TASK_APPROVAL="ai-stacks-pve-tiny-sdn"
./with-secrets-prod-tiny ansible-playbook -i 'pve-tiny.gibbsgreatly.xyz,' -u root \
  -e '{"target_hosts":"all","requested_sdn_vnets":["tvai"],"reject_pending_sdn_changes":true,"manage_cluster_firewall":false}' \
  ansible/00-initial-setup/proxmox-sdn-setup.yml
```
Expect: 0 failed, only `tvai` created, no firewall task, and the existing
tvinfra/tvmgmt/tvcse unchanged. Re-run the Phase 0 SDN/subnet/firewall reads
and diff them against the captured preflight output before continuing.

**2c. Prove VLAN 50 end-to-end before any CT moves:**

First confirm `.250` is absent from the MikroTik ARP table, DHCP leases and
any static IP allocation record. Ping is a secondary check only: a host that
blocks ICMP can still own the address. Then run this as one conditional block;
the SSH assignment is in the `else`, so an occupied address cannot fall
through into a duplicate assignment:

```bash
if ping -c2 -W1 192.168.50.250; then
  echo "STOP: .250 replied; pick and re-check another reserved ai_seg IP" >&2
  false
else
  ssh root@pve-tiny.gibbsgreatly.xyz '
    set -e
    if ip -4 addr show dev tvai | grep -qw 192.168.50.250/24; then echo "STOP: .250 already assigned on tvai" >&2; exit 1; fi
    ip addr add 192.168.50.250/24 dev tvai
    trap "ip addr del 192.168.50.250/24 dev tvai" EXIT
    ping -c3 -W2 192.168.50.1
    ip neigh show 192.168.50.1 dev tvai
  '
fi
```
Pass: replies from 192.168.50.1 and a resolved MAC in `ip neigh`.
If it fails, the trunk isn't passing VLAN 50. Fix 2a before going further.

**2d. OpenSearch host prerequisite** (only if Phase 0 showed < 262144):

```bash
ssh root@pve-tiny.gibbsgreatly.xyz 'echo "vm.max_map_count=262144" > /etc/sysctl.d/90-opensearch.conf && sysctl --system >/dev/null && sysctl vm.max_map_count'
```

---

## Phase 3 — Per-stack cutover (operator, one stack per approval)

Order: **mcp-utility → secpipe → opensearch → ai-services**. That goes from
stateless to stateful and from least to most user-facing. mcp-utility goes
first as the canary for the whole path (SDN, storage profile, apply,
provision). Don't start the next stack until the previous one passes its
checks.

| Stack | VMID | IP | TASK_APPROVAL | Stateful |
|---|---|---|---|---|
| mcp-utility-stack | 50011 | 192.168.50.10 | `ai-stacks-pve-tiny-mcp-utility` | no |
| secpipe-stack | 50012 | 192.168.50.12 | `ai-stacks-pve-tiny-secpipe` | no |
| opensearch-stack | 40014 | 192.168.40.14 | `ai-stacks-pve-tiny-opensearch` | yes |
| ai-services-stack | 50013 | 192.168.50.11 | `ai-stacks-pve-tiny-ai-services` | yes |

### Generic procedure

Set `S=<stack> ID=<vmid> IP=<ip>` and `export TASK_APPROVAL=<from table>`.

1. **Fingerprint (stateful only)**: see the per-stack section below.
2. **Stop the old CT and keep it from coming back:**
   ```bash
   ssh root@pve.gibbsgreatly.xyz "pct shutdown $ID --timeout 180 && pct set $ID --onboot 0 && pct status $ID"
   ```
   Expect `status: stopped`. **Downtime starts here.**
3. **Export state (stateful only)**: see the per-stack section below.
4. **Confirm the IP is free:** `ping -c3 -W1 $IP` must get no reply.
5. **Create the new CT:**
   ```bash
   ./with-secrets-prod-tiny terragrunt plan  --working-dir terraform/lxc/environments/pve-tiny/$S -no-color
   ./with-secrets-prod-tiny terragrunt apply --working-dir terraform/lxc/environments/pve-tiny/$S
   ```
   Review the plan before typing `yes`: one container plus its local files,
   with no destroys.
6. **Deploy the app:**
   ```bash
   ./with-secrets-prod-tiny scripts/provision.sh --target-env pve-tiny --stack $S
   ```
   `SKIP edge reconcile` / `SKIP portainer env registration` lines are
   expected, and so are `SKIP <dep>: inventory file not found` lines for
   dependencies that live on pve.
7. **Import state (stateful only)**, then re-run step 6 once so the
   playbook converges against the imported data.
8. **Verify**: see the per-stack checks below. If a consumer can't reach
   `$IP` for more than about a minute after start, the MikroTik may still
   hold the old CT's MAC. Check `/ip arp print where address=$IP` and remove
   the dynamic entry.

**Rollback (any time before Phase 4):** `ssh root@pve-tiny.gibbsgreatly.xyz
"pct shutdown $ID"`, then `ssh root@pve.gibbsgreatly.xyz "pct set $ID
--onboot 1 && pct start $ID"`. Verify the old service before doing anything
else. Anything written on the new CT in between is lost (for example, new
OpenWebUI chats).

To abandon a stack's move permanently, get a separate approval named
`ai-stacks-pve-tiny-abandon-<stack>`. While the pve-tiny stack definition
and state still exist, review
`terragrunt plan -destroy --working-dir terraform/lxc/environments/pve-tiny/$S`,
then run `terragrunt destroy` through `./with-secrets-prod-tiny`. Confirm
VMID `$ID` is absent on pve-tiny. Only then restore that stack's pve
`terragrunt.hcl` and `stack.yaml` from the recorded migration-base commit
(`4c4212fe` for this plan), remove its tracked pve-tiny
`terragrunt.hcl`, and remove the target environment's generated/state
directory. Never delete the target state before its target CT has been
destroyed and absence verified.

### mcp-utility-stack checks
```bash
for p in 8000 8001; do curl -s -o /dev/null -w "$p %{http_code}\n" http://192.168.50.10:$p/mcp; done
```
Expect 200/401/405/406 on both, which matches the playbook's own health
check. Then run one real `search_docs` call from VS Code (docs-rag
reindexes on provision, so the first call may be slow).

### secpipe-stack checks
```bash
ssh root@192.168.50.12 'systemctl is-enabled cve-enrichment-sync.timer cve-deep-dive.timer; systemctl start cve-enrichment-sync.service; systemctl status --no-pager cve-enrichment-sync.service | tail -5'
```
Expect both `enabled`, and the manual run to finish without error (it
reads OpenSearch and MCP, both of which must be up).

### opensearch-stack: fingerprint, export, import, checks

Fingerprint (step 1, old CT still running):
```bash
./with-secrets-prod-tiny bash -c 'printf "user = \"admin:%s\"\n" "$OPENSEARCH_ADMIN_PASSWORD" | ssh root@192.168.40.14 "curl -sk -K - \"https://127.0.0.1:9200/_cat/indices?h=index,docs.count&s=index\""' > ~/pve-tiny-migration/opensearch-before.txt
```
(`~/pve-tiny-migration` must already exist; see "Tooling notes" at the
top.)

Export (step 3, old CT stopped):
```bash
set -o pipefail
ssh root@pve.gibbsgreatly.xyz 'pct mount 40014 >/dev/null && trap "pct unmount 40014" EXIT && tar -C /var/lib/lxc/40014/rootfs/var/lib/opensearch-data --numeric-owner -cpf - .' > ~/pve-tiny-migration/opensearch-stack.tar && echo export-ok
tar -tf ~/pve-tiny-migration/opensearch-stack.tar | wc -l
sha256sum ~/pve-tiny-migration/opensearch-stack.tar | tee ~/pve-tiny-migration/opensearch-stack.tar.sha256
```

Import (step 7, after the first provision):
```bash
sha256sum -c ~/pve-tiny-migration/opensearch-stack.tar.sha256
ssh root@pve-tiny.gibbsgreatly.xyz 'pct shutdown 40014 --timeout 180 && pct mount 40014 >/dev/null && trap "pct unmount 40014" EXIT && D=/var/lib/lxc/40014/rootfs/var/lib/opensearch-data && test -d $D && find $D -mindepth 1 -delete && tar -C $D --numeric-owner -xpf -' < ~/pve-tiny-migration/opensearch-stack.tar && echo import-ok
ssh root@pve-tiny.gibbsgreatly.xyz 'pct start 40014'
```
Then repeat generic step 6 exactly for `opensearch-stack`.

Checks: run the fingerprint command again into `opensearch-after.txt`,
then `diff opensearch-before.txt opensearch-after.txt`. Expect the same
index list, with doc counts equal (or higher, if an ingest timer fired in
between). Also check that Dashboards login via Authentik works at the
public `opensearch`/dashboards hostname, and that the Grafana OpenSearch
datasource still returns data.

### ai-services-stack: fingerprint, export, import, checks

Fingerprint (step 1):
```bash
ssh root@192.168.50.11 "docker exec openwebui python3 -c \"import sqlite3;c=sqlite3.connect('/app/backend/data/webui.db');print('users',c.execute('select count(*) from user').fetchone()[0],'chats',c.execute('select count(*) from chat').fetchone()[0])\"" | tee ~/pve-tiny-migration/openwebui-before.txt
```

Export (step 3):
```bash
set -o pipefail
ssh root@pve.gibbsgreatly.xyz 'pct mount 50013 >/dev/null && trap "pct unmount 50013" EXIT && tar -C /var/lib/lxc/50013/rootfs/var/lib/docker/volumes --numeric-owner -cpf - ai-services-openwebui-data/_data ai-services-searxng-data/_data ai-services-deep-research-config/_data' > ~/pve-tiny-migration/ai-services-stack.tar && echo export-ok
tar -tf ~/pve-tiny-migration/ai-services-stack.tar | wc -l
sha256sum ~/pve-tiny-migration/ai-services-stack.tar | tee ~/pve-tiny-migration/ai-services-stack.tar.sha256
```

Import (step 7):
```bash
sha256sum -c ~/pve-tiny-migration/ai-services-stack.tar.sha256
ssh root@pve-tiny.gibbsgreatly.xyz 'pct shutdown 50013 --timeout 180 && pct mount 50013 >/dev/null && trap "pct unmount 50013" EXIT && cd /var/lib/lxc/50013/rootfs/var/lib/docker/volumes && for v in ai-services-openwebui-data ai-services-searxng-data ai-services-deep-research-config; do test -d $v/_data || exit 1; find $v/_data -mindepth 1 -delete; done && tar --numeric-owner -xpf -' < ~/pve-tiny-migration/ai-services-stack.tar && echo import-ok
ssh root@pve-tiny.gibbsgreatly.xyz 'pct start 50013'
```
Then repeat generic step 6 exactly for `ai-services-stack`.

Checks: re-run the fingerprint into `openwebui-after.txt` (users and chats
equal); `curl -s -o /dev/null -w '%{http_code}\n' http://192.168.50.11:8081/`
returns 200; log in at `https://openwebui.<LAB_DOMAIN>` via Authentik and
confirm an old chat opens and a new prompt reaches the Framework model;
one SearXNG query; one deep-research run.

---

## Phase 4 — Soak and decommission (operator)

Leave each old CT stopped on pve for at least 7 days after its cutover.

**Before destroying 40014 or 50013, all of these are mandatory:**

1. A pve-tiny backup job covers the CT and includes its Docker/data mount.
   If Phase 0 showed no such job, adding one is a prerequisite follow-up
   outside this plan.
2. At least one backup taken *after the import and final provision* completed
   successfully. Record its task/log and backup volume ID; merely having a
   configured job is not evidence.
3. The backup artifact is present on its intended independent datastore and
   its embedded CT configuration is readable. Confirm the mount entries are
   included rather than marked `backup=0`.
4. Re-run the application checks from Phase 3 immediately before
   decommission.

If any item fails, keep both the old CT and the workstation archive. The
archive and its `.sha256` file remain after old-CT decommission too; retire
them only after a later restore rehearsal (to a non-conflicting VMID, never
started on the production IP) proves the pve-tiny backup usable, or after a
second independently verified backup generation exists.

Per stack, with approval `ai-stacks-pve-tiny-decommission-<stack>`:
```bash
ssh root@pve.gibbsgreatly.xyz "pct status $ID && pct destroy $ID --purge"
rm -rf terraform/lxc/environments/pve/$S      # untracked state only; terragrunt.hcl was git-rm'd in ai-tiny-05
```
pve's `tvai` zone stays in place. Removing an existing zone is a
full-teardown-tier change, and it isn't needed for this move.

### ai-tiny-06-zone-membership-docs

Run after all four stacks have cut over and passed their checks.

```yaml
id: ai-tiny-06-zone-membership-docs
title: Record the relocated stacks in the network intent files
depends_on: [ai-tiny-02-network-ai-seg]

change: >
  In terraform/lxc/network/pve-tiny.yaml: replace the line
  `    containers: []  # filled in by ai-tiny-06 once each stack has cut over`
  (under zones.ai_seg) with LITERAL_1, and replace the line
  `    containers: []  # empty — this pass only creates the zone; harbor-stack has not moved yet`
  (under zones.infra_seg) with LITERAL_2. In terraform/lxc/network/pve.yaml,
  under zones.ai_seg, replace the `    containers:` line and the three list
  items below it (beginning `- "mcp-utility-stack`, `- "ai-services-stack`,
  `- "secpipe-stack`) with LITERAL_3. Change nothing else.

  LITERAL_1 (4-space indent on first line):
      containers:
        - "mcp-utility-stack (VMID 50011) — 192.168.50.10 — relocated from pve, docs/ai-stacks-pve-tiny/plan.md"
        - "secpipe-stack (VMID 50012) — 192.168.50.12 — relocated from pve, docs/ai-stacks-pve-tiny/plan.md"
        - "ai-services-stack (VMID 50013) — 192.168.50.11 — relocated from pve, docs/ai-stacks-pve-tiny/plan.md"

  LITERAL_2 (4-space indent on first line):
      containers:
        - "opensearch-stack (VMID 40014) — 192.168.40.14 — relocated from pve, docs/ai-stacks-pve-tiny/plan.md"

  LITERAL_3 (4-space indent):
      containers: []  # mcp-utility/ai-services/secpipe relocated to pve-tiny at the same IPs (network/pve-tiny.yaml, docs/ai-stacks-pve-tiny/plan.md); tvai zone left in place

scope:
  allowed_paths:
    - terraform/lxc/network/pve-tiny.yaml
    - terraform/lxc/network/pve.yaml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Editing attachments: or policies: in either file"

gates:
  - id: membership-recorded
    cmd: |
      python3 -c "import yaml;t=yaml.safe_load(open('terraform/lxc/network/pve-tiny.yaml'));p=yaml.safe_load(open('terraform/lxc/network/pve.yaml'));a=t['zones']['ai_seg']['containers'];assert len(a)==3 and all('relocated from pve' in x for x in a);i=t['zones']['infra_seg']['containers'];assert len(i)==1 and i[0].startswith('opensearch-stack (VMID 40014)');assert p['zones']['ai_seg']['containers']==[];assert 'ai_seg' in p['attachments'];print('ok')"
    expect: "prints ok, exit 0"
    critical: true
```

---

## Out of scope / follow-ups

- Backup job on pve-tiny for 40014/50013 (see Phase 4). Required before
  decommission.
- Promotion `task/ai-stacks-pve-tiny` → `stable` → `main`: operator's call
  once all four have soaked.
- pentagi-stack/pentagi-upstream-control decommission.
- Revisit the harbor/graylog → pve-tiny idea
  (`docs/pve-tiny-network-onboarding/plan.md` Phase 2). pve-tiny's RAM
  headroom is mostly used up after this move.

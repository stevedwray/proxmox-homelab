# Phase 02 — pve-test Memory Upgrade (32 GB)

## Goal

Increase the pve-test nested Proxmox VM from 16 GB to 32 GB RAM to provide headroom for Phase 04 services (Authentik, step-ca, Headscale, VictoriaMetrics, Grafana, Loki, and reverse proxy) alongside the already-running Harbor and NetBox stacks.

**This phase is a hard gate — do not begin Phase 04 until this is complete.**

## Repository context

Current LXC memory allocations on pve-test:

| Stack | Configured limit | Notes |
|---|---|---|
| `harbor-stack` (VMID 121) | 8,192 MB | `terraform/lxc/stacks/harbor-stack/stack.yaml` |
| `netbox-stack` (VMID 119) | 4,096 MB | `terraform/lxc/stacks/netbox-stack/stack.yaml` |
| `test-docker` | 2,048 MB | validation |
| `test-lxc` | 2,048 MB | validation |
| `ci-runner-01` (VMID 141) | 4,096 MB | deployed in Phase 01 |
| **Total configured** | **~20,480 MB** | |

Phase 04 planned additions: Authentik (~2 GB), step-ca (~512 MB), reverse proxy (~512 MB), VictoriaMetrics + Grafana + Loki (~3 GB). Peak concurrent working set will be 18–28 GB against a 16 GB host VM — OOM risk is real.

## Prerequisites

- Phase 01 (ci-runner-01) complete
- Access to the **host** Proxmox node (the physical/parent machine that runs pve-test as a VM)
- pve-test is a QEMU VM on the host; its VMID on the host needs to be known

## Related issues

- **#67** — chore: bump pve-test VM memory to 32 GB before Phase 4

---

## Part A — Collect working-set baselines before resizing

Run these **after Harbor and NetBox have been live for at least a few hours** to get representative numbers.

### From the pve-test host (SSH in as root):

```bash
# Harbor LXC (VMID 121)
pct exec 121 -- bash -c "free -h && echo '---' && docker stats --no-stream 2>/dev/null || true"

# NetBox LXC (VMID 119)
pct exec 119 -- bash -c "free -h && echo '---' && docker stats --no-stream 2>/dev/null || true"

# Overall host pressure
free -h
```

Record the results. If either stack's working set is significantly below its configured limit, right-size it:

| Stack | Right-size rule | New limit |
|---|---|---|
| `harbor-stack` | Stable below 5 GB RSS → reduce | 6,144 MB |
| `netbox-stack` | Stable below 2 GB RSS → reduce | 3,072 MB |

If right-sizing: edit the relevant `stack.yaml` memory field and apply via Terragrunt (live resize, no LXC restart needed):

```bash
# Example for harbor-stack if right-sizing:
cd /home/steve/git/proxmox-homelab/terraform/lxc/stacks/harbor-stack
# Edit stack.yaml: memory: 6144
source ~/.env 2>/dev/null || source /home/steve/git/proxmox-homelab/.env
terragrunt apply
```

Commit any `stack.yaml` changes before proceeding to the host resize.

---

## Part B — Resize pve-test VM to 32 GB

This requires the pve-test VM to be **shut down**. Schedule accordingly — Harbor and NetBox will be unavailable during the window.

### Find the pve-test VMID on the host Proxmox

From the host Proxmox shell or UI:

```bash
# On the HOST Proxmox node:
qm list | grep pve-test
```

Note the VMID (call it `<pvetest-vmid>`).

### Graceful shutdown procedure

```bash
# ON the HOST Proxmox node:

# 1. Stop all LXCs gracefully inside pve-test first
#    SSH into pve-test first, then:
# ssh root@<pve-test-ip>
# systemctl stop pve-guests.service  # stops all LXCs in order
# exit

# 2. Shut down pve-test VM from the host
qm shutdown <pvetest-vmid>

# Wait for VM to reach stopped state:
watch qm status <pvetest-vmid>
# Target: status: stopped
```

### Resize memory on the host

```bash
# Option A — CLI (preferred)
qm set <pvetest-vmid> --memory 32768

# Verify:
qm config <pvetest-vmid> | grep memory
# Expected: memory: 32768
```

Alternatively, use the Proxmox web UI: Datacenter → \<host\> → pve-test → Hardware → Memory → Edit → set to 32768 MB.

### Start pve-test and verify

```bash
# On the HOST Proxmox node:
qm start <pvetest-vmid>

# Wait for boot, then SSH into pve-test:
# ssh root@<pve-test-ip>
free -h
# Expected: ~30 GB total, ~28+ GB available (before LXCs start)

# Restart LXCs:
systemctl start pve-guests.service

# Or start individually in dependency order:
# pct start 119  # netbox-stack
# pct start 121  # harbor-stack
# pct start 141  # ci-runner-01
```

### Verify services are healthy post-restart

```bash
# Harbor health check (run from pve-test or any host that can reach 192.168.1.10):
curl -k https://192.168.1.10/api/v2.0/ping
# Expected: "Pong"

# NetBox health check:
curl http://192.168.1.30/api/
# Expected: JSON with API version info

# CI runner:
gh api repos/stevedwray/proxmox-homelab/actions/runners \
  --jq '.runners[] | {name, status}'
# Expected: ci-runner-pve-test online
```

---

## Part C — Update documentation if pve-test is managed by Terraform

Check whether `pve-test` is defined anywhere in the Terraform codebase:

```bash
grep -r "pve-test\|pvetest" /home/steve/git/proxmox-homelab/terraform/ --include="*.tf" --include="*.yaml" -l
```

If it is Terraform-managed, update the memory parameter and apply from the host. If managed manually, add a comment to the relevant stack file or `docs/reference/` noting the new spec (32 GB, updated April 2026).

---

## Commit and close

```bash
cd /home/steve/git/proxmox-homelab

# Stage any stack.yaml right-sizing changes:
git add terraform/lxc/stacks/*/stack.yaml

git commit -m "chore(infra): right-size LXC memory limits based on observed working sets

harbor-stack: 8192 → <new> MB (observed RSS ~X GB)
netbox-stack: 4096 → <new> MB (observed RSS ~X GB)
pve-test VM resized to 32 GB on host Proxmox.

Closes #67"

git push origin dev/pve-test
gh issue close 67 --comment "pve-test VM resized to 32 GB. All stacks healthy post-restart. Observed working sets documented in commit."
```

---

## Acceptance criteria

- [ ] Working-set baselines recorded for harbor-stack and netbox-stack
- [ ] `stack.yaml` limits updated if right-sizing applied and `terragrunt apply` confirmed
- [ ] pve-test VM memory is 32 GB (`qm config <vmid> | grep memory` shows `32768`)
- [ ] `free -h` inside pve-test shows ~30 GB total after resize
- [ ] All LXCs start cleanly after pve-test reboot (check `pct list`)
- [ ] Harbor responds to health check: `curl -k https://192.168.1.10/api/v2.0/ping` → `"Pong"`
- [ ] NetBox responds to health check: `curl http://192.168.1.30/api/` → JSON
- [ ] CI runner is back online in GitHub Actions
- [ ] No OOM events: `dmesg | grep -i oom` returns nothing inside pve-test
- [ ] Issue #67 closed with commit reference

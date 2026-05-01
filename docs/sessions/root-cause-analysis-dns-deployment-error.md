# Root Cause Analysis: DNS Daemon Down

## Problem Statement

DNS stack (VMID 151, 10.57.1.13) reported as healthy in platform-status but daemon not responding to remote queries. Live-preflight gate in stage3b-repair session failed with "connection refused" on port 53.

## Investigation Findings

### Finding 1: DNS Health Check Shows False Positive

| Metric | Value |
|---|---|
| Prior validation platform-status (20260501-004308) | "authoritative dns ok" |
| Current state platform-status (20260501-012218) | "authoritative dns ok" |
| Health check log file size | 0 bytes (both sessions) |
| **Actual daemon listening on port 53** | **NO** |
| **Remote DNS queries succeeding** | **NO** |

**Conclusion**: Platform-status health check is not reliable. It reports DNS as healthy despite the daemon being unavailable.

### Finding 2: DNS Container Running Wrong Service

Live verification from pve-test:

```
VMID 151 (dns-stack, 10.57.1.13):
- Docker container running: portainer/agent:2.21.1 (NOT CoreDNS)
- Process name: "portainer-agent"
- Port bound: 9001/tcp (NOT 53/tcp)
```

**Conclusion**: DNS stack container was deployed with incorrect workload. It should be running CoreDNS but is running portainer agent instead.

### Finding 3: Systemic Deployment Issue

Other affected stacks:
- VMID 120 (portainer-stack): portainer-agent ✓ (correct)
- VMID 151 (dns-stack): portainer-agent ✗ (should be CoreDNS)
- VMID 153 (proxy-stack): portainer-agent ✗ (should be Traefik)

**Conclusion**: Multiple stacks deployed with wrong workloads. This is not isolated to DNS — suggests a template or deployment ordering issue.

### Finding 4: Listeners Log Contradiction

Listeners logs from both prior (20260501-004308) and current (20260501-012218) sessions show:
- No port 53/TCP binding
- No port 53/UDP binding
- Time between checks: ~8 hours

**Conclusion**: DNS was never listening during either session. The health check has been consistently wrong or cached.

## Root Causes

1. **Container workload mismatch**: DNS stack LXC deployed with portainer-agent service instead of CoreDNS. This blocks all DNS queries.

2. **Health check fidelity**: Platform-status DNS health check reports "authoritative dns ok" despite daemon not running. Health log is empty (0 bytes), suggesting check is not actually executing or output not captured.

3. **Deployment template error**: Multiple stacks (dns-stack, proxy-stack) running portainer-agent when they should run different services. Suggests Terraform/Ansible stack definitions are pointing to wrong container images or playbooks.

## Impact

- **DNS queries fail**: All remote DNS lookups to 10.57.1.13:53 receive "connection refused"
- **Edge reconciliation affected**: DNS failure in edge stack affects downstream stacks dependent on DNS (proxy-stack Traefik rendering, etc.)
- **Platform deployment blocked**: Stage 3b platform repair cannot proceed without DNS
- **Health check unreliability**: False positive from platform-status masks the real problem, affecting future troubleshooting

## Implications for Session Decision

**Current situation**:
- Option A (emergency DNS recovery) — will not work because the problem is container workload mismatch, not a transient crash
- Option B (full platform cycle) — only viable option, since multiple stacks have deployment errors that cannot be recovered without full redeploy
- Option C (root cause analysis) — **COMPLETE** — the root cause is deployment template/manifest error, not transient failure

**Recommendation**: Proceed with **Option B — Full platform cycle (teardown + redeploy)**. This will reset all containers to correct workloads and clear the systematic deployment error affecting dns-stack, proxy-stack, and potentially others.

## Next Steps

1. Approve full teardown cycle
2. Redeploy from clean baseline
3. Re-validate platform state matches manifest expectations (not just health check reports)
4. After redeploy, return to Stage 3b repair session

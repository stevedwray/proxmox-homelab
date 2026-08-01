# mcp-utility-stack — Stack Contract

## Purpose

Runs `cve-mcp-server` (upstream `mukul975/cve-mcp-server`, local `local-dev`
branch merged onto `v0.2.0`) as a network-reachable MCP server, giving AI
agents structured CVE/vulnerability research (NVD, EPSS, CISA KEV, OSV,
GitHub/GitLab advisories, MITRE, VulnCheck, plus configured threat-intel
sources) via HTTP instead of a local `stdio` process. It is the first
"external-utility" adapter in `docs/mcp-stack/plan.md`'s MCP design: it
holds no internal infrastructure credentials, but needs real internet
egress to public CVE/advisory APIs — the opposite trust posture from
`mcp-discovery-stack`, which is why it lives in its own zone.

## Network

| Field        | Value                    |
|--------------|--------------------------|
| Zone         | `ai_seg` (SDN VLAN 50) — shares this zone with future AI/LLM app containers; not a dedicated zone (a `research_seg`/VLAN 81 attempt was abandoned 2026-08-01, see `docs/mcp-stack/plan.md`) |
| IP           | `${lab_ip_mcp_utility}/24` |
| Gateway      | `${lab_gw_ai}` |
| VMID         | `50011` (`50010` on this node is `harness-target`, a pre-existing unrelated stack — a real collision hit here 2026-08-01, don't reuse it) |

## Inputs

| Input | Source | Notes |
|-------|--------|-------|
| `NVD_API_KEY` | secrets.common.enc.yaml | Raises NVD rate limit from 5/30s to 50/30s |
| `GITHUB_TOKEN` | secrets.common.enc.yaml | GitHub Advisories/Code Search rate limit |
| `VULNCHECK_TOKEN` | secrets.common.enc.yaml | NVD++ fallback source |
| `VIRUSTOTAL_KEY` | secrets.common.enc.yaml | Threat-intel cluster, deliberately in scope per 2026-08-01 operator decision |
| `SHODAN_KEY` | secrets.common.enc.yaml | Threat-intel cluster, same decision |
| `GREYNOISE_API_KEY` | secrets.common.enc.yaml | Threat-intel cluster, same decision |

`ABUSEIPDB_KEY`/`URLSCAN_KEY`/`CIRCL_PDNS_USER`/`CIRCL_PDNS_PASS` are
intentionally left unset — those sources stay unreachable both at the app
layer (no key) and the network layer (not in the `ai_seg` egress
allowlist).

## Provides

| Service | Port | Protocol | Notes |
|---------|------|----------|-------|
| `cve-mcp-http` | `8000` | `tcp` | MCP Streamable HTTP endpoint at `/api/mcp`. No built-in authentication — access control is network-level only (MikroTik inbound rule), see Security notes below. |

## Dependencies

| Stack | Why |
|-------|-----|
| `apt-cacher-stack` | apt proxy during host provisioning |

No Harbor dependency: the `cve-mcp-server` image is built directly on the
host from source copied by the Ansible controller (see the playbook's
header comment) rather than pulled from a registry — this is a single
small custom image with no other consumer yet.

## Persistent State

| Path | Storage | Contents |
|------|---------|----------|
| `/var/lib/docker` | `docker_storage` (5G) | Docker image/container layers |
| Docker named volume (cache) | Docker volume | SQLite cache (`CACHE_DB_PATH`, default `~/.cve-mcp/cache.db` inside the container) |
| Docker named volume (audit log) | Docker volume | Rotating audit log file (`AUDIT_LOG_PATH`) — writes to a **file only, not stdout** (confirmed by reading `src/cve_mcp/audit.py`: `RotatingFileHandler`, no `StreamHandler`). The container's `json-file` Docker log driver does **not** capture this — it's a real gap, not yet fixed, tracked in `cve-mcp-server`'s own `docs/api-service-plan.md`. |

## What May Depend On This Stack

Any authenticated internal client on `lan` or `pentest_seg` (per the
`ai_seg` inbound firewall rule) wanting CVE/vulnerability research —
starting with an interactive Claude Code session on the workstation, and
`pentagi-stack`/`greenbone-stack` findings review. No stack currently
depends on it in an automated way.

## What Must Not Be Edited Casually

- **No built-in authentication.** Anything that can reach `ai_seg:8000`
  can call every enabled tool. The only access control is the MikroTik
  inbound rule (`lan`, `pentest_seg` → `ai_seg:8000`) — do not widen
  that rule without adding real app-layer auth first.
- **Egress allowlist is a real security boundary, not a formality.** The
  `ai_seg` MikroTik policy allows only the named hosts documented in
  `terraform/lxc/network/pve-test-vm.yaml`'s `ai_seg` egress policy
  (grepped from `cve-mcp-server`'s own source, not guessed). Adding a new
  data source to the upstream server requires adding its host to that
  allowlist too, or the tool will silently fail closed.
- **`ABUSEIPDB_KEY`/`URLSCAN_KEY`/`CIRCL_PDNS_*` staying unset is
  deliberate**, not an oversight — don't "complete" the `.env` by filling
  them in without revisiting the egress allowlist and the scope decision
  that excluded them.

## Playbook

`deploy-mcp-utility-stack`

`docker_base` role + a single templated `docker-compose.yml`
(`community.docker.docker_compose_v2`), same pattern as `deploy-greenbone-stack.yml`.

## Implementation Files

| File | Role | Status |
|------|------|--------|
| `terraform/lxc/stacks/mcp-utility-stack/stack.yaml` | Terraform-side stack definition | existing |
| `terraform/lxc/environments/pve-test-vm/mcp-utility-stack/terragrunt.hcl` | Terragrunt entrypoint (boilerplate) | existing |
| `terraform/lxc/stacks/mcp-utility-stack/inventory.yml` | Generated Terraform→Ansible handoff — do not hand-edit, regenerated by `terragrunt apply` | generated |
| `terraform/lxc/ansible/playbooks/deploy-mcp-utility-stack.yml` | Stack playbook | existing |

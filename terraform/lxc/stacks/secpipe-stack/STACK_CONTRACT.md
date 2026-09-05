# secpipe-stack — Stack Contract

## Purpose

CVE correlation/enrichment pipeline. Reads `harbor-findings` and
`gvm-findings` from `opensearch-stack`, calls `cve-mcp-server`
(`mcp-utility-stack`) for CVSS/EPSS/KEV/PoC triage per CVE, calls an LLM
for a short risk narrative, and writes the result into a new
`unified-cve-exposure` index plus back onto each originating finding's
own `severity_assessed`/`assessed_reason`/`assessed_by`/`assessed_at`
fields.

See `docs/threat-vuln-platform/plan.md` for the full design and phase
scope. **Phase 1 (this deployment): GVM + Harbor only.** Wazuh, Security
Onion, and T-Pot ingestion (and their own eventual contribution to this
pipeline) are a separate, later piece of work.

Not a resurrection of `wazuh-analysis`/`so-analysis`/`tpotce-analysis`/
`security-analysis` (separate repos, separate infra) — this stack starts
fresh against `opensearch-stack`, informed by but not built from those
repos' code.

## Network

| Field        | Value                    |
|--------------|--------------------------|
| Zone         | `ai_seg` (VLAN 50)       |
| IP           | `192.168.50.12/24`       |
| Gateway      | `192.168.50.1`           |
| VMID         | 50012                    |

Same zone as `mcp-utility-stack` (192.168.50.10) — no new cross-zone rule
needed for the CVE-MCP calls. One new cross-zone rule needed:
`ai_seg → infra_seg:9200` (OpenSearch) — already anticipated in
`project_harbor_alerting_automation_plan` memory as a planned future rule
for exactly this purpose.

## Inputs

| Input | Source | Notes |
|-------|--------|-------|
| `ANTHROPIC_API_KEY` | SOPS `terraform/secrets.common.enc.yaml` | **New secret**, added 2026-08-18. Temporary LLM provider while the local LLM is occupied with benchmarking work — recovered from `wazuh-analysis/.env`'s exposed plaintext copy, operator confirmed no rotation needed. |
| `OPENAI_API_KEY` | SOPS `terraform/secrets.common.enc.yaml` | **New secret**, added 2026-08-18. Same as above, recovered from `tpotce-analysis/.env`. |
| `OPENSEARCH_ADMIN_PASSWORD` | SOPS `terraform/secrets.common.enc.yaml` | Already exists (opensearch-stack's own admin credential) — used to bootstrap this role's own scoped `es_findings_writer`-based user, same pattern as `es_findings_ingest`/`gvm_findings_ingest`. |
| `LAB_IP_OPENSEARCH` | `.env` | Already exists. |
| `LAB_IP_MCP_UTILITY` | `.env` | Already exists — `cve-mcp-server`'s address, same zone. |
| `LAB_IP_SECPIPE` | `.env` | **New.** This stack's own IP. |
| apt-cacher | `apt_cacher_host:3142` | apt proxy during provisioning |

## Provides

Nothing consumed by other stacks — this is a leaf in the dependency
graph (reads from `opensearch-stack`/`mcp-utility-stack`, writes back to
`opensearch-stack` only).

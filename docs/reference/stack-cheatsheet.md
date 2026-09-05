# Stack Cheat Sheet

Quick orientation reference — every real stack in this repo, one line
each, on `pve` (production). No tool call needed to read this: for a
question like "what VMID is X" or "what's Y's IP," this is faster and
more reliable than either `search_docs` or grepping several files, since
it's compiled directly from each stack's own `STACK_CONTRACT.md` and
`.env`'s production IP values (not derived from `network/pve.yaml`'s
zone-comment lists, which were found to be incomplete/stale when this
was compiled — missing `graylog-stack`/`opensearch-stack`/etc entirely,
and mislabeling `ai-services-stack` as "not yet deployed" when it's been
live for weeks).

For anything conceptual (why a decision was made, a gotcha, cross-stack
reasoning), use `search_docs` — this file is deliberately just facts, not
prose. For a specific file's full content, use `get_document`.

**Compiled 2026-08-25, manually cross-checked, not mechanically
regenerated.** Correct as of that date; re-verify against the stack's own
`STACK_CONTRACT.md` before trusting it for anything that matters — this
is a cache, not a source of truth.

| Stack | VMID | Zone | IP | Purpose |
|---|---|---|---|---|
| `ai-services-stack` | 50013 | `ai_seg` | 192.168.50.11 | OpenWebUI + SearXNG chat UI; client of Ollama/llamacpp on `framework`, now via `ollama-reliability-proxy` |
| `apt-cacher-stack` | 40011 | `infra_seg` | 192.168.40.11 | Transparent apt proxy for all LXC containers during provisioning |
| `authentik-stack` | 20010 | `mgmt_seg` | 192.168.20.10 | Identity provider / SSO gateway for the platform |
| `ci-runner-01` | 10063 | `build_seg` | 192.168.10.63 | Self-hosted GitHub Actions runner |
| `dns-stack` | 20013 | `mgmt_seg` | 192.168.20.13 | Rollback-only CoreDNS — **not** the active DNS delegate (`technitium-stack` is) |
| `graylog-stack` | 20014 | `mgmt_seg` | 192.168.20.14 | Production log platform (Graylog 7.1.3) |
| `greenbone-stack` | 70011 | `pentest_seg` | 192.168.70.11 | GVM/OpenVAS vulnerability scanner, live network scanning |
| `harbor-stack` | 40010 | `infra_seg` | 192.168.40.10 | Private container registry + proxy-cache for all image pulls |
| `harness-target` | 50010 | plain LAN (`vmbr0`) | 192.168.1.55 | Repeatable, deliberately vulnerable target for automated PentAGI test harness runs — **PentAGI is deprecated** (see `docs/pentagi-stack/README.md`); this target has no other current consumer |
| `harness-target-pve` | 70012 | `pentest_seg` | 192.168.70.12 | Disposable Struts2/Redis target for controlled PentAGI model comparisons — **PentAGI is deprecated** (see `docs/pentagi-stack/README.md`); this target has no other current consumer |
| `mcp-utility-stack` | 50011 | `ai_seg` | 192.168.50.10 | `cve-mcp-server` + `docs-rag-mcp` + `pgvector` — the MCP tool servers this session built |
| `monitoring-stack` | 20012 | `mgmt_seg` | 192.168.20.12 | Metrics (Grafana + VictoriaMetrics) |
| `netbox-stack` | 40012 | `infra_seg` | 192.168.40.12 | IPAM/DCIM — not yet exposed as an MCP tool (see `docs/coding-stack/plan.md` open items) |
| `opensearch-stack` | 40014 | `infra_seg` | 192.168.40.14 | OpenSearch + Dashboards — findings store for Harbor/GVM vuln ingestion |
| `portainer-stack` | 20020 | `mgmt_seg` | 192.168.20.20 | Container management UI + agent registration hub |
| `proxy-stack` | 30010 | `edge_seg` | 192.168.30.10 | Traefik edge ingress / TLS termination |
| `secpipe-stack` | 50012 | `ai_seg` | 192.168.50.12 | CVE correlation/enrichment pipeline (`cve_enrichment_sync`) |
| `step-ca-stack` | 20011 | `mgmt_seg` | 192.168.20.11 | Internal CA, issues TLS certs across the platform |
| `technitium-stack` | 20015 | `mgmt_seg` | 192.168.20.15 | **LIVE authoritative DNS** for `lab.gibbsgreatly.xyz` |
| `test-storage` | — | `build_seg` | not fixed (ephemeral mutation-test target) | Dedicated storage-validation LXC for `docs/storage-refactor` |

Not a stack, but relevant: `framework.gibbsgreatly.xyz` (`192.168.1.8`,
bare-metal Ubuntu) hosts Ollama/llamacpp-router directly — every AI-stack
entry above that talks to a model reaches it there, not on any `ai_seg`
IP.

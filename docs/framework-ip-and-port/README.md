# framework-ip-and-port (planning workspace)

Status: **planned, not started** (2026-09-27). Branch
`task/framework-dns-only-plan`.

The Framework Desktop (`framework.gibbsgreatly.xyz`, bare-metal Ubuntu 26)
was given `192.168.1.8` by mistake. That address belongs to **gazaar**, a
NAS that is powered on only for backups, so the two collide. The goals:

1. **Move framework to `192.168.1.18`.** Make every client reach it by name
   first, so the move is a single DNS record change. The IP is then
   published in one place, the MikroTik static record, written by
   `mikrotik-dns-framework.yml` from `LAB_IP_FRAMEWORK`.
2. **Migrate everything that used framework's Ollama** (now removed) to the
   Nathanw llama.cpp fork: `:8080` for chat and a new `:8085` for
   embeddings. Bring both servers under IaC.

Records that exist *to* record an address (IPAM and scan-asset data) keep
the literal on purpose.

The executable steps are in [plan.md](plan.md): Phase A is DNS-only,
Phase C is Ollama → llama.cpp, and Phase B is the re-IP. Use the plan's
"Execution order" table. Code changes that are more than a line or two ship
as tested patches in [patches/](patches/). This file keeps the audit that
motivated the plan, the port registry, and the hand-back log.

**Broken right now (2026-09-27), because Ollama is gone:**

- docs-rag-mcp `search_docs` (it embeds every query via Ollama).
- The weekly CVE deep-dive (enabled; next run Sunday 23:00).
- The `llm.${LAB_DOMAIN}` Traefik route: its LM Studio backend on `:8090`
  is not running either.
- The Ollama half of framework's stats collector.

## Audit (2026-09-27, repo state at `f94ed09d`)

`git grep -nE '192\.168\.1\.8([^0-9]|$)'` found 34 tracked files. About
half are under `docs/` and are historical. The live code/config hits are
listed below.

### Hard-coded literals: migrated by this plan

| File | What | Step |
|---|---|---|
| `terraform/lxc/ansible/roles/cve_enrichment_sync/defaults/main.yml:42` | `cve_enrichment_sync_ollama_url: "http://192.168.1.8:11434"` (also feeds the deep-dive URL and the unit's `OLLAMA_URL`) | fwllm-02 (replaces the Ollama provider; fwdns-04 is superseded) |
| `terraform/lxc/ansible/roles/cve_enrichment_sync/files/cve_enrichment_sync.py:620` | `OLLAMA_URL` fallback | fwllm-02 (replaces the Ollama provider; fwdns-04 is superseded) |
| `terraform/lxc/ansible/roles/cve_enrichment_sync/files/cve_deep_dive.py:283` | `OLLAMA_URL` fallback | fwllm-02 (replaces the Ollama provider; fwdns-04 is superseded) |
| `terraform/lxc/network/pve.yaml:362`, `pve-test-vm.yaml:561` | policy `ai_seg → 192.168.1.8` (8080, 11434) | fwdns-07 |
| `terraform/lxc/network/pve.yaml:487`, `pve-test-vm.yaml:463` | policy `pentest_seg → 192.168.1.8` (PentAGI-era) | fwdns-07 (removed) |
| `scripts/pentagi-test-harness/test_sequence*.json` | `router_url: http://192.168.1.8:8080` | fwdns-10 (removed) |
| `ansible/00-initial-setup/proxmox-{gpu-unified-memory-tuning,vlan-aware-bridge}.yml` | usage-comment examples `-i "192.168.1.8,"` | fwdns-11 |

### Indirect through env vars: consolidated by this plan

`.env` / `.env.template` set four variables, all to `192.168.1.8`:

| Var | Consumers | Becomes |
|---|---|---|
| `LAB_IP_LLM_GPU` | `llm-gpu-stack/edge.yaml` (Traefik `llm.` backend :8090), legacy `llm-gpu-stack/stack.yaml`, `TF_VAR_lab_ip_llm_gpu` | `LAB_FQDN_FRAMEWORK` in edge.yaml (fwdns-02); var removed (fwdns-11) |
| `LAB_IP_COMFYUI` | `comfyui-stack/edge.yaml` (Traefik `comfyui.` backend :8188), legacy `comfyui-stack/stack.yaml`, `TF_VAR_lab_ip_comfyui` | `LAB_FQDN_FRAMEWORK` (fwdns-02); var removed (fwdns-11) |
| `FRAMEWORK_HOST_IP` | `ansible_host` in `ansible/inventory/{inventory,dev,production}.yml` | `LAB_FQDN_FRAMEWORK` (fwdns-06); var removed (fwdns-11) |
| `LAB_IP_FRAMEWORK` | monitoring-stack node_exporter/cadvisor scrape targets; MikroTik `ai_seg`/`cse_seg` → framework rules | clients move to `LAB_FQDN_FRAMEWORK` / the RouterOS address-list (fwdns-03, -08, -09); var **kept** as the single input to `mikrotik-dns-framework.yml`, which publishes the DNS record; changes to `.18` in fwip-02 |

The unset, optional `FRAMEWORK_HOST` variable (read by
`deploy-ai-services-stack.yml` and `deploy-pentagi-stack.yml`) already
defaulted to the FQDN. ai-services moves to `LAB_FQDN_FRAMEWORK` (fwdns-05).
PentAGI is deprecated and is left as is.

### Router (MikroTik) state

The snapshot is `router/config/current-config.json`, **stale, last scraped
2026-08-13**:

- Static DNS: `framework.gibbsgreatly.xyz` A `192.168.1.8`. This record is
  the single source of truth once the plan is done. There is also
  `gazaar.gibbsgreatly.xyz` A `192.168.1.8`; it is unused by the repo, and
  fwdns-00 checks it.
- Forward accepts with `dst-address=192.168.1.8`:
  - `ai_seg → 8080,11434`, from `mikrotik-firewall-ai-services-stack.yml`
  - `pentest_seg → 11434`, `8082`, `8080` and `22`. These four were added
    by hand for PentAGI, and no playbook owns them.
- `mikrotik-firewall-cse-seg.yml` (2026-09-19, newer than the snapshot)
  adds `cse_seg → framework:8080`, also by IP.

fwdns-08 replaces all of these with list-based rules on
`dst-address-list=framework`. The list's one static entry is the FQDN, and
RouterOS resolves it itself. The PentAGI rules are removed, not converted.

### Intentionally left as literals

| File | Why |
|---|---|
| `terraform/lxc/network/pve.yaml:721` (`inventory.static_hosts` → framework `ip:`) | IPAM record: NetBox's static-host import |
| `terraform/lxc/ansible/roles/gvm_findings_ingest/files/assets/ip_to_stack.json:22` | GVM findings are keyed by scanned IP; this map *is* IP data |
| `terraform/lxc/stacks/netbox-stack/integrations/tests/test_populate_static_hosts.py` | test fixture |
| `router/config/current-config.json` | a scrape of live state, refreshed rather than edited |
| `docs/**` | historical record |
| `terraform/lxc/stacks/{llm-gpu,comfyui}-stack/stack.yaml`, `variables.tf`/`main.tf` `lab_ip_llm_gpu`/`lab_ip_comfyui` | Legacy pve-framework LXC definitions: Framework is bare metal now and nothing provisions these. They reference the Terraform vars, not the IP. Retiring them is separate cleanup (see plan.md Out of scope). |

Other repos: `~/git/ai-code-testing/docs/` mentions the IP only in a
"never use the bare IP" note. `~/git/oci` has nothing.

## Ollama consumers (2026-09-27)

Ollama `:11434` refuses connections; no Ollama container or unit remains
on framework.

| Consumer | Where | Uses | Migration |
|---|---|---|---|
| docs-rag-mcp | mcp-utility-stack (pve-tiny, ai_seg) | `/api/embed`, nomic-embed-text, every query + reindex | `:8085` `/v1/embeddings` + full re-embed (fwllm-03) |
| CVE deep-dive | secpipe-stack (pve-tiny), weekly, **enabled** | `/api/generate`, laguna | `:8080` provider `llamacpp` (fwllm-02) |
| CVE routine narrative | secpipe-stack | `ollama` provider (not the default; anthropic is) | same provider switch (fwllm-02) |
| Ollama stats textfile collector + "Local AI" dashboard | framework / monitoring-stack | `/api/ps` | llama-server `--metrics` (fwllm-06, -07) |
| VS Code Copilot "Framework Ollama" (4 models) | workstation `~/.config/Code/User/chatLanguageModels.json` | `:11434/v1/chat/completions` | operator edit → `:8080` |
| OpenWebUI | ai-services-stack | already `ENABLE_OLLAMA_API=false` | none |
| PentAGI, ollama-reliability-proxy, local-ai-canary, benchmarks | deprecated / workstation tooling | `:11434` | retirement candidates (plan.md Out of scope) |

Direct `:8080` clients: OpenWebUI (already keyed), deep-research,
cse-controller, `cse-small-batch-run.yml`, and VS Code. All of them need
`LLM_GPU_STACK_API_KEY` once `:8080` requires it (fwllm-04 + operator).

## Port registry: Framework Desktop

Inventory only (operator decision 2026-09-27): ports are part of each
service's contract and stay literal where they are used. This table is the
one place that lists them all.

| Port | Service on framework | Consumers (network path) | Notes |
|---|---|---|---|
| 22 | SSH | operator workstation / Ansible (LAN) | The pentest_seg → :22 PentAGI harness rule is removed by fwdns-08 |
| 8080 | llama-server chat, `nathanw-llamacpp.service` (Nathanw fork, native Vulkan) | OpenWebUI + deep-research (ai_seg), secpipe CVE (ai_seg), cse-controller (cse_seg), Traefik `llm.` (edge_seg, fwllm-05), VS Code (LAN) | API key required from fwllm-01 on; `--metrics` |
| 8085 | llama-server embeddings, `nathanw-llamacpp-embed.service` (new, fwllm-01) | docs-rag-mcp (ai_seg) | nomic-embed-text-v1.5, no key, `--metrics` |
| 8081 | *(legacy)* OpenWebUI container | none; superseded by ai-services-stack | Retirement candidate |
| 8082 | *(legacy)* SearXNG container | none; superseded by ai-services-stack | Retirement candidate; why embeddings use 8085 |
| 8083 | cAdvisor | monitoring-stack scrape (mgmt_seg) | |
| 8090 | *(dead)* LM Studio | was Traefik `llm.` | Not running; route moves to 8080 |
| 8188 | ComfyUI | Traefik `comfyui.${LAB_DOMAIN}` (edge_seg) | |
| 9001 | Portainer agent | portainer-stack | The endpoint URL must be the FQDN before the re-IP (fwdns-00 item 6) |
| 9100 | node_exporter (HTTPS, step-ca cert) | monitoring-stack scrape (mgmt_seg) | Cert SANs come from `ansible_host` + `inventory_hostname` |
| 11434 | *(gone)* Ollama | none after Phase C | The ai_seg rule stops allowing it (fwdns-07/-08) |

## Hand-back log

Each step's executor appends an entry here: the step id, the edit made, and
each gate's actual result.

_(none yet)_

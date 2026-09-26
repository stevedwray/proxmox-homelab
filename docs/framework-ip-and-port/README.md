# framework-ip-and-port (planning workspace)

Status: **planned, not started** (2026-09-27). Branch
`task/framework-dns-only-plan`.

Goal: stop hard-coding the Framework Desktop's address (`192.168.1.8`,
`framework.gibbsgreatly.xyz`, bare-metal Ubuntu 26) in code and config. After
this plan, every client reaches it by name, and the one place its IP is set
is DNS: the MikroTik static record for `framework.gibbsgreatly.xyz`, which
Technitium also answers from. The exceptions are records that exist *to*
record an address (IPAM and scan-asset data). Those keep the literal on
purpose.

The executable steps are in [plan.md](plan.md). This file keeps the audit
that motivated the plan, the port registry, and the hand-back log.

## Audit (2026-09-27, repo state at `f94ed09d`)

`git grep -nE '192\.168\.1\.8([^0-9]|$)'` found 34 tracked files. About
half are under `docs/` and are historical. The live code/config hits are
listed below.

### Hard-coded literals: migrated by this plan

| File | What | Step |
|---|---|---|
| `terraform/lxc/ansible/roles/cve_enrichment_sync/defaults/main.yml:42` | `cve_enrichment_sync_ollama_url: "http://192.168.1.8:11434"` (also feeds the deep-dive URL and the unit's `OLLAMA_URL`) | fwdns-04 |
| `terraform/lxc/ansible/roles/cve_enrichment_sync/files/cve_enrichment_sync.py:620` | `OLLAMA_URL` fallback | fwdns-04 |
| `terraform/lxc/ansible/roles/cve_enrichment_sync/files/cve_deep_dive.py:283` | `OLLAMA_URL` fallback | fwdns-04 |
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
| `LAB_IP_FRAMEWORK` | monitoring-stack node_exporter/cadvisor scrape targets; MikroTik `ai_seg`/`cse_seg` → framework rules | clients move to `LAB_FQDN_FRAMEWORK` / the RouterOS address-list (fwdns-03, -08, -09); var **kept** as the documented IP for IP-by-nature data |

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

## Port registry: Framework Desktop

Inventory only (operator decision 2026-09-27): ports are part of each
service's contract and stay literal where they are used. This table is the
one place that lists them all.

| Port | Service on framework | Consumers (network path) | Notes |
|---|---|---|---|
| 22 | SSH | operator workstation / Ansible (LAN) | pentest_seg → :22 PentAGI harness rule removed by fwdns-08 |
| 8080 | llama-server (Nathanw build, systemd; formerly llamacpp-router) | ai-services-stack OpenWebUI (ai_seg), cse-controller (cse_seg), deep-research-agent `config_template.yaml` | The ai_seg and cse_seg firewall rules both allow it |
| 8083 | cAdvisor | monitoring-stack scrape (mgmt_seg) | `deploy-monitoring-stack.yml` cadvisor job |
| 8090 | LM Studio (Vulkan) | Traefik `llm.${LAB_DOMAIN}` (edge_seg) | `llm-gpu-stack/edge.yaml` |
| 8188 | ComfyUI | Traefik `comfyui.${LAB_DOMAIN}` (edge_seg) | `comfyui-stack/edge.yaml` |
| 9100 | node_exporter (HTTPS, step-ca cert) | monitoring-stack scrape (mgmt_seg) | Cert SANs come from `ansible_host` + `inventory_hostname` |
| 11434 | Ollama | secpipe-stack cve_enrichment_sync fallback (ai_seg), docs-rag-mcp embeddings, `scripts/ollama-reliability-proxy` | Ollama is no longer in active use for chat (2026-09-22), but the ai_seg rule keeps 11434 so behaviour doesn't change |
| 8082 | *(gone)* SearXNG | none | Moved to ai-services-stack on 2026-08-02. The pentest_seg rule for it is removed by fwdns-08. |

## Hand-back log

Each step's executor appends an entry here: the step id, the edit made, and
each gate's actual result.

_(none yet)_

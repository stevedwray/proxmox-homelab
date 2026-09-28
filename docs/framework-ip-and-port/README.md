# framework-ip-and-port (planning workspace)

Status: **All three phases complete.** Phases A and C were merged to
`stable` in #432 (2026-09-28). Phase B, the re-IP cutover, ran on
2026-09-28 from `task/framework-reip-cutover`: framework is now
`192.168.1.18`, and `192.168.1.8` is gazaar's alone. That branch is not yet
merged. NetBox was corrected by hand the same day; the populate CI job's
fix is on `fix/netbox-populate-no-docker` (see the hand-back log).

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

**Broken at the start (2026-09-27), because Ollama was gone. All fixed the
same day by Phase C:**

- docs-rag-mcp `search_docs`, which embedded every query via Ollama (now
  llama.cpp `:8085`).
- The weekly CVE deep-dive (now llama.cpp `:8080`).
- The `llm.${LAB_DOMAIN}` Traefik route, whose LM Studio backend on `:8090`
  was dead (now `:8080`).
- The Ollama half of framework's stats collector (now llama.cpp
  `/metrics`).

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

### fwdns-00 pre-flight (operator-run, 2026-09-27)

- Item 2, router snapshot: refreshed on the workstation. Exactly six rules
  have `dst-address=192.168.1.8`: `*55` (ai_seg 8080,11434), `*90` (cse_seg
  8080), `*36` (pentest 11434), `*37` (pentest 8082), `*45` (pentest 8080)
  and `*48` (pentest 22). No extra rules and no gazaar-specific rules. `*55`'s
  comment was checked byte for byte (`od -c`) and matches fwdns-08's
  `ai-services-stack: ai_seg to framework llamacpp-router/ollama` exactly
  (an earlier paste had lost the space). Static DNS: `framework` and `gazaar` are both A `192.168.1.8`,
  TTL 1d.
- Item 3, RouterOS: **7.24.2** (was 7.23.1 at the 2026-08-13 snapshot).
- Item 4, resolution from consumers: **pass**. `getent hosts
  framework.gibbsgreatly.xyz` returns `192.168.1.8` from ai-services
  (.50.11), secpipe (.50.12), mcp-utility (.50.10), cse-controller
  (.100.70), monitoring (.20.12) and proxy (.30.10).
- Item 6, Portainer: endpoint Id 9 (`framework.gibbsgreatly.xyz`) URL is
  `tcp://192.168.1.8:9001`. **Change it to the FQDN before Phase B.**

### fwdns-01-env-fqdn

Added the `LAB_FQDN_FRAMEWORK` line after `LAB_FQDN_HARBOR` in `.env` and
`.env.template`. Gates: env-value `ok`; template-has-var `1`.

### fwdns-02-edge-manifests

llm-gpu and comfyui edge.yaml backends now use `${LAB_FQDN_FRAMEWORK}`.
Gates: dry-run-render gives exactly
`http://framework.gibbsgreatly.xyz:8090` and `:8188`; edge-manifest-tests OK.

### fwdns-03-monitoring-scrape

Both scrape targets use `LAB_FQDN_FRAMEWORK`. Gates: syntax-check exit 0;
no-ip-var `0`; fqdn-var `2`.

### fwdns-07-network-intent

ai_seg policy is now `to: framework.gibbsgreatly.xyz`, `ports: [8080,
8085]` in both files. Deleted the pentest_seg → 192.168.1.8 entries
(9 lines in pve.yaml, 5 in pve-test-vm.yaml). Gates: ports
`[[8080, 8085], [8080, 8085]]`; yaml parses; only `pve.yaml:712 ip:
192.168.1.8` left; netbox integration tests OK; zone-members tests OK.

### fwdns-08-mikrotik-framework-playbook

Created `ansible/00-initial-setup/mikrotik-firewall-framework-fqdn.yml`,
copied exactly from the plan's content block (293 lines). Gates:
syntax-check exit 0; no-ip-literal `0`.

### fwdns-09-trim-legacy-mikrotik-entries

Removed the `lab_ip_framework` var and the framework rule entry from
`mikrotik-firewall-ai-services-stack.yml` and `mikrotik-firewall-cse-seg.yml`,
and repointed both header comments to the new playbook. Gates: syntax-check
exit 0; no-framework-ip `0` / `0`.

### Operator apply: router (fwdns-08), 2026-09-27

Validation tier: the operator approved the narrower checks (add-before-remove,
the playbook's assertions, live reachability) instead of a pve-test-vm
teardown. The playbook finished with `failed=0`, and a re-scrape confirmed
the result:
- The `framework` list holds the FQDN plus a dynamic `192.168.1.8` entry.
- The new rules are `*B2` (ai_seg 8080,8085) and `*B3` (cse_seg 8080).
- 0 rules with a literal `dst-address=192.168.1.8` remain.

From ai-services (.50.11) and cse-controller (.100.70),
`:8080/v1/models` returned 200. The post-apply snapshot is committed
with this entry.

### Operator deploy: monitoring-stack (fwdns-03), 2026-09-27

`provision.sh --stack monitoring-stack`: `failed=0`. The smoke test failed
because it still required `dns-stack`, whose target was dropped on
2026-09-08; fixed in `6157817d`, after which the smoke test passes. The FQDN
targets were first **down**: VictoriaMetrics resolves through Docker's DNS,
which on monitoring (and on authentik, netbox, graylog, opensearch and
wazuh) is Technitium. Technitium is authoritative only for `LAB_DOMAIN`, so
it recursed `framework.gibbsgreatly.xyz` to the public internet and got
NXDOMAIN. The plan's research note saying Technitium resolved the name was
wrong. With the operator's approval, the new
`technitium-framework-forwarder.yml` (`65a4cb50`, also imported by
`deploy-technitium-stack.yml`) adds a conditional forwarder zone for the
FQDN, pointing at the MikroTik (`LAB_GW_MGMT`). The IP is still published
only on the MikroTik. Applied with `failed=0 changed=1`. Both
`framework.gibbsgreatly.xyz:8083` and `:9100` (HTTPS, cert SAN verified)
are now `up`.

### Operator deploy: Traefik edge (fwdns-02), 2026-09-27

`reconcile-edge.py` dry-run: validation and render passed, and the Authentik
reconcile planned 0 writes. The overall status was `failed` only because of
EGR211: a pre-existing, unrelated drift on `nextcloud-stack` (its route
needs no Authentik objects, but some exist). A diff of the rendered files
against the live `/opt/proxy-stack/dynamic/` showed only the `llm-gpu` and
`comfyui` backend changes, apart from end-of-file newlines.
`provision.sh --stack proxy-stack`: `failed=0`, smoke test passed. Route
checks: comfyui 302, grafana 302, portainer 200.

### fwllm-01-native-llamacpp-playbook

Applied the patch. Gates: applied; syntax-check exit 0; chat-flags `1`.

### fwllm-04-api-key-consumers

Applied the patch. Gates: applied; py-compile OK; syntax-check exit 0 (all
three playbooks).

### Operator: embeddings model + fwllm-01 live apply, 2026-09-27

The model download checked out (`sha256sum -c` OK). Before the apply,
MemAvailable was 14966 MB with only `llama-server` holding significant
memory. `framework-desktop-llamacpp-native.yml`: `failed=0 changed=7`, with
all four self-checks passing (both `/health`, 401 without the key,
`/metrics` with the key, and a 768-dim embedding).

Consumers were redeployed immediately afterwards, on pve-tiny:
- `ai-services-stack`: `failed=0`.
- `cse-controller`: `failed=0`.

Keyed `:8080` checks all replied `OK`:
- OpenWebUI (browser).
- Inside the `deep-research` container, using its own
  `OPENAI_API_BASE`/`OPENAI_API_KEY`.
- Inside `cse-controller-worker`, using `FRAMEWORK_LLM_API_KEY`.
- From the workstation, via curl.

The 1-case CSE batch was not run: it spans 9 benchmarks with a paid judge,
and the in-container check covers the key path fwllm-04 changed.

VS Code: `chatLanguageModels.json` was backed up and rewritten. The Ollama
provider and the `:8079` model are gone. The `:8080` model id is now
`qwen3.8-flash-next`, with the key inline. Input/output limits are
6144/2048 for now. Copilot still fails locally ("No lowest priority node
found") because its own prompt doesn't fit, so VS Code is blocked until
fwllm-08 raises `--ctx-size`. Raise the VS Code limits then.

### fwdns-06-inventory-and-bootstrap

The three inventories now use `LAB_FQDN_FRAMEWORK`. Deleted the 27-line
IP-SAN reissue block from `framework-desktop-bootstrap.yml`. Gates:
inventory-resolves-fqdn gives `"ansible_host": "framework.gibbsgreatly.xyz"`;
no-old-var clean; bootstrap-syntax exit 0; san-block-gone `0`.

### fwllm-02 / -03 / -05 / -06 / -07

Every patch applied cleanly in order. Gates:
- 02: py-compile OK; no-ollama-code clean; secpipe syntax exit 0.
- 03: unit tests OK (3 tests); mcp-utility syntax exit 0.
- 05: render gives `- url: http://framework.gibbsgreatly.xyz:8080`.
- 06: monitoring and bootstrap syntax exit 0; collector gone.
- 07: live-metric-names finds `llamacpp:tokens_predicted_total`,
  `requests_processing` and `requests_deferred` (15 `llamacpp:` series in
  all; the fork uses upstream names); JSON valid; 0 `ollama` in
  `local-ai.json`.

### Operator deploys: step 4, 2026-09-27

- **mcp-utility-stack (fwllm-03):** deploy `failed=0`. The first full
  re-embed hit HTTP 500s: the embeddings server rejects inputs over 2048
  tokens (`input (2677 tokens) is too large`), and docs-rag's 6000-char
  chunks ran ~2.2 chars/token on this repo's YAML/code-dense markdown.
  Ollama had silently truncated them. Fixed in `6de94488`: `chunking.py` now
  assumes 2 chars/token (3000-char cap) and hard-splits oversized
  paragraphs and lines. Unit tests cover this, and over the repo's 480
  docs the largest chunk is 2999 chars. After a redeploy and a second wipe
  (container stopped first), the reindex summary was
  `{'total_files': 455, 'changed': 455, 'failed': []}`, with 7163 chunks.
  `rebuild_ivfflat_index` runs at the end of the reindex, so the
  low-recall notice after TRUNCATE needs no action.
- **secpipe-stack (fwllm-02):** deploy `failed=0`. A manual deep-dive dry
  run (`--top-n 1`, with the unit's own `Environment=` loaded via
  `systemctl show -p Environment`; the plan's command lacked
  `ELASTICSEARCH_URL`) gave `assessed=1 errors=0`.
- **proxy-stack (fwllm-05):** rendered diff = only `llm-gpu-stack.yml`
  `:8090` -> `:8080`. Deploy `failed=0`, smoke test passed.
  `https://llm.lab.gibbsgreatly.xyz/v1/chat/completions`: 401 without the
  key, 200 with it.
- **monitoring-stack (fwllm-06/-07):** deploy `failed=0`, smoke test
  passed. The `llamacpp` job's `:8080` (chat) and `:8085` (embeddings)
  targets are both up.
- **framework bootstrap (fwllm-06):** `failed=0 changed=7`. It removed
  `ollama_stats_textfile.py` and `ollama_stats.prom`. The `docker`/
  `containerd` directory tasks reported `changed` for mode only (now 711);
  the bind mounts from `vg0-containers` are intact, and all 5 containers
  were still up (3 days).

### Operator: measure chat context, 2026-09-27

MemAvailable (MB) after each `-e framework_llamacpp_chat_ctx_size=C` apply:
8192 -> 14966 (baseline), 16384 -> 14000, 32768 -> 13500,
65536 -> 12235, 131072 -> 9788. Every value stayed above the 8192 floor, so
**131072** is kept (`n_ctx_slot = 131072`, `kv_unified = 'true'`). Deep-dive
dry run at 131072: `finish_reason='length'`, i.e. the model spent its
4096-token output budget reasoning. That is tuning, not context (see
follow-ups).

### fwllm-08-set-measured-ctx

`framework_llamacpp_chat_ctx_size` default 8192 -> 131072, with the
measurements in the comment, so a plain playbook re-run keeps the measured
value.

### Follow-ups (operator-deferred, not part of this plan)

- **docs-rag ranking quality (pre-existing, also true under Ollama).**
  nomic-embed-text wants `search_query: ` / `search_document: ` prefixes;
  docs-rag sends neither. Measured: the relevant-vs-distractor cosine gap
  was 0.07 without prefixes and 0.18 with them. The search also uses
  ivfflat `lists = 100` with the default `probes = 1`, so each query scans
  ~1% of rows. Fix: add both prefixes, set `ivfflat.probes` (~10) per
  search, then do a full re-embed.
- **CVE deep-dive output budget.** `LLAMACPP_MAX_TOKENS=4096` can be used up
  by reasoning (`finish_reason='length'`). Raise it (context is now 131072)
  or limit reasoning.
- **VS Code limits.** `chatLanguageModels.json` still has 6144/2048; raise
  them now that the context is 131072.
- **nextcloud-stack Authentik drift (EGR211).** Its route needs no
  Authentik objects, but some exist. Unrelated to this plan.

### Incident: post-commit hook redeployed mcp-utility against `pve`, 2026-09-27

Committing `9603847d` triggered the untracked `.git/hooks/post-commit`,
which runs `./with-secrets-prod scripts/provision.sh --stack
mcp-utility-stack` in the background. That targets **pve**, but the stack
has lived on pve-tiny since the AI-stack move. It was not blocked because
the hook sets its own standing approval
(`TASK_APPROVAL=docs-rag-mcp-housekeeping-reindex`, confirmed from the next
run's log). A leftover exported `TASK_APPROVAL` (`fwllm-06-07-monitoring`)
was also in the shell, but it was not what let the run through. The stale `terraform/lxc/environments/pve/mcp-utility-stack/`
inventory still points at `192.168.50.10`, so the run hit the real LXC and
copied at least one file (`cve-mcp-server` `Dockerfile`, `changed`).

Remediation:
- `unset TASK_APPROVAL`; approvals now go inline per command
  (`TASK_APPROVAL=... ./with-secrets-prod-tiny ...`).
- Hook line 41 -> `./with-secrets-prod-tiny`, backup at
  `post-commit.bak`. The hook stays default-deny without an approval.
- `TASK_APPROVAL=mcp-utility-restore-after-hook ./with-secrets-prod-tiny
  scripts/provision.sh --stack mcp-utility-stack`: `failed=0`. All three
  containers up; reindex `changed: 1, failed: []`.

The `Timeout when waiting for 192.168.20.11:443` fatal is a pre-existing
ignored task (`ignored=1`) in every ai-services/mcp-utility deploy.
Follow-ups: remove the stale `environments/pve/mcp-utility-stack/`
inventory, and decide whether the hook's standing approval should stay:
CLAUDE.md asks for a per-task approval for every production mutation. The
next commit's hook run (`0e241012`) went to pve-tiny as intended.

### fwdns-05-ai-services-var

Replaced the `ai_services_framework_host` block with the plan's replacement
block (`LAB_FQDN_FRAMEWORK`), and made the four STACK_CONTRACT.md
replacements (each matched once). Gates: syntax-check exit 0; no-old-var
`0` / `0`; only the historical "before 2026-08-02" line (132) keeps the IP.
No redeploy: the resolved value is unchanged.

### fwdns-10-remove-pentagi-harness

`git rm -r scripts/pentagi-test-harness` (4 files). Gates: gone; no-code-refs
clean.

### fwdns-11-retire-ip-vars-and-comments

`.env` drops `LAB_IP_LLM_GPU`/`LAB_IP_COMFYUI`/`FRAMEWORK_HOST_IP`, and
`LAB_IP_FRAMEWORK` gets the "read ONLY by mikrotik-dns-framework.yml"
comment. `.env.template` drops those plus `TF_VAR_lab_ip_llm_gpu`/
`TF_VAR_lab_ip_comfyui` (both variables default to `""` in `variables.tf`,
so Terraform is unaffected) and gains `LAB_IP_FRAMEWORK` after
`LAB_FQDN_FRAMEWORK`. The two usage comments now use `-i
"framework.gibbsgreatly.xyz,"`. Gates: vars-gone clean; env-sources ok;
edge-still-renders shows both urls on `framework.gibbsgreatly.xyz` (`llm`
on `:8080` since fwllm-05).

### fwdns-12-final-audit

`git grep -lE '192\.168\.1\.8([^0-9]|$)' -- ':!docs' | sort` returns exactly
the expected set:
- `.env`, `.env.template`
- `ansible/00-initial-setup/mikrotik-firewall-pentagi-to-ai-services-searxng.yml`
- `router/config/current-config.json`
- `terraform/lxc/ansible/roles/gvm_findings_ingest/files/assets/ip_to_stack.json`
- `terraform/lxc/network/pve.yaml`
- `terraform/lxc/stacks/ai-services-stack/STACK_CONTRACT.md`
- `terraform/lxc/stacks/netbox-stack/integrations/tests/test_populate_static_hosts.py`

Phase A (DNS-only) is complete.

### fwip-01-mikrotik-dns-playbook

Applied the patch. Gates: applied; syntax-check exit 0; no-ip-literal `1`
(the header comment naming gazaar's `192.168.1.8`).

### Operator: lower the TTL (Phase B prep), 2026-09-27

`TASK_APPROVAL=fwip-dns-ttl-lower ./with-secrets-prod ansible-playbook
ansible/00-initial-setup/mikrotik-dns-framework.yml -e framework_dns_ttl=5m`
gave `framework.gibbsgreatly.xyz -> 192.168.1.8 (ttl 5m); address-list
'framework' re-resolved`, `failed=0`, at **Sun 27 Sep 16:30 NZDT**. The
record is now owned by the playbook (comment added); the address is
unchanged. The cutover is possible from Mon 28 Sep 16:30 NZDT.

### Portainer endpoint by FQDN (fwdns-00 item 6), 2026-09-27

Endpoint Id 9 (`framework.gibbsgreatly.xyz`) was changed from
`tcp://192.168.1.8:9001` to `tcp://framework.gibbsgreatly.xyz:9001` via
`PUT /api/endpoints/9` (`{"URL": ...}` only); the UI edit had not saved.
Read-back after 20 s: the new URL, `Status: 1` (up).

fwip-02 is deliberately held until cutover day. Committing `.18` early
would let any re-run of the DNS playbook repoint the name before framework
moves.

### Pre-cutover review, 2026-09-28 (read-only, plus plan updates)

Live state at 12:44 NZDT:
- MikroTik answers `framework.gibbsgreatly.xyz` A `192.168.1.8` with TTL
  300 (playbook-owned). gazaar is A `192.168.1.8`, TTL 1d, untouched.
- `.18` doesn't answer ping.
- Chat `:8080/health` and embeddings `:8085/health` both return 200.

Findings, all folded into plan.md's Phase B:

- **Technitium still held a one-day answer** (TTL 4683 s at 12:44, so it
  expires about 14:02 NZDT). It was fetched just before the TTL was
  lowered. The runbook now checks both resolvers' TTLs as a precondition.
- **Technitium flush.** `technitium-framework-forwarder.yml` deleted
  Technitium's cached answer only when it created the zone. It now does so
  on every run, so re-running it is the cutover's "flush Technitium and
  assert it matches the MikroTik" step. Syntax-checked; it takes effect the
  first time it runs, during the cutover.
- **Wrappers after the OpenBao switch.**
  - `PVE_ENV= ./with-secrets` fails ("unknown profile ''"), so the framework
    playbook commands in the plan and in both playbook headers now use
    `TASK_APPROVAL=<task> ./with-secrets-prod`. A read-only
    `ansible-inventory` through it resolves framework, and the `pve`
    profile lists every field Phase B needs.
  - Plain `./with-secrets` (dev profile) still loads the MikroTik
    credentials for the router re-scrape.
- **node_exporter cert** SANs are `DNS:framework.gibbsgreatly.xyz,
  IP Address:192.168.1.8`, valid to 2026-12-22. `step ca renew` keeps its
  SANs, so the runbook's new step 6 deletes the cert and re-runs the
  bootstrap to reissue it with DNS only.
- **NetBox:** the daily populate workflow runs from `main`. The runbook
  now dispatches it against the cutover branch, falling back to the first
  scheduled run after `main` is promoted.
- **Other runbook changes:**
  - inline approvals throughout;
  - a guard that `.env` says `.18` before the DNS cutover and the TTL
    restore;
  - commit the hand-back only after the checks (the post-commit hook);
  - rollback-after-step-3 now reverts fwip-02 and re-runs the Technitium
    flush.
- fwip-02 was simulated on a scratch worktree of `origin/stable` (not
  committed). All three of its gates pass (NetBox tests 128 OK), and the
  resulting `.8`/`.18` file sets match fwip-03's expected lists.

### Phase B cutover, 2026-09-28 (fwip-02, runbook, fwip-03)

Run from `task/framework-reip-cutover`, starting 13:12 NZDT. The operator
accepted starting before the 16:30 window: the MikroTik, Technitium and
both Pi-holes had been checked at a TTL of 300 s or less, and gazaar was
off.

- **fwip-02** (`caa3840e`): `.env`, `.env.template`, `pve.yaml` and
  `ip_to_stack.json` now say `.18`. All three gates pass (NetBox tests 128
  OK).
- **Pre-cutover check found two more resolvers.** The router's DHCP hands
  LAN clients, including the workstation, the Pi-holes 192.168.1.22 and .23.
  Both already served the 300 s answer. They are now in the runbook's
  precondition. `.23` served its expired `.8` answer once, with TTL 0,
  while it refreshed; the next query returned `.18`.
- **Netplan** was confirmed before the change: `00-installer-config.yaml`,
  one `192.168.1.8/24` line. The operator ran step 2 (`netplan try`) and
  accepted it from `.18`, because Claude Code's permission check blocks
  remote file writes. The backup is `/root/00-installer-config.yaml.pre-reip`.
- **DNS:**
  - The MikroTik record went to `.18` (5m), and the address-list
    re-resolved to `.18`.
  - The Technitium playbook flushed its cache; the assertion passed.
  - After 5 minutes, `getent` returned `.18` on ai-services, secpipe,
    mcp-utility, cse-controller, monitoring and proxy.
  - The TTL was restored to 1h (still `.18`).
- **Consumers:**
  - `comfyui.` 302.
  - `llm.` 401 without the key and 200 with it (a real completion, about
    24 tok/s).
  - `:8085` embeddings: 768 dimensions.
  - VictoriaMetrics `up{stack="framework"}` is 1 for node_exporter,
    cadvisor, llamacpp :8080 and :8085.
  - Ansible ping OK; the Portainer agent port 9001 is open.
  - Not checked by Claude: OpenWebUI chat, docs-rag `search_docs`, and the
    Portainer UI endpoint state. These are for the operator.
- **node_exporter cert:** the operator deleted the old cert, and the
  bootstrap reissued it. The SANs are now `DNS:framework.gibbsgreatly.xyz`
  only, valid to 2026-12-27, and the scrape is still up. The service unit is
  `prometheus-node-exporter`, not `node_exporter`.
- **gazaar:** powered on. `.8` answers with MAC `00:d0:b8:25:4b:93`
  (framework's is `9c:bf:0d:01:f7:a7`), and forward and PTR records both say
  gazaar; SMB, NFS, rsync and SSH answer. A completed backup run is for the
  operator to confirm.
- **Router re-scrape:** `.8` is gazaar's record only; the framework record
  and address-list entry are `.18`, TTL 1h.
- **fwip-03:** both gates match their expected file lists exactly.
- **NetBox: not updated.** The branch was pushed and `netbox-populate.yml`
  dispatched against it (run 36363158889). The GitHub-OIDC login to
  OpenBao worked, but "Build populate container" failed: the self-hosted
  runner user gets `permission denied` on `/var/run/docker.sock`. This is
  CI breakage that predates the cutover: the workflow has no success in its
  last 100 runs, and the scheduled runs on `main` still fail earlier, at
  "Install SOPS" (the pre-OpenBao workflow). NetBox therefore still shows
  framework at `.8` until the runner's Docker access is fixed and the
  populate runs, from this branch or after `main` is promoted.
- **Bootstrap `changed` results: harmless, checked.** The `containers` LV
  (300G) is mounted at `/mnt/container-storage`, and its `docker/` and
  `containerd/` directories are bind-mounted onto `/var/lib/docker` and
  `/var/lib/containerd`, as `1df73e96` intended. Each pair is one inode,
  so "Create docker/containerd subdirectories" sets it to 0755 and the
  next task sets it back to 0711. Both report `changed` on every run; the
  end state is 0711, which is correct. The fix is to set the first task's
  mode to `'0711'` (not done yet).

### NetBox follow-up, 2026-09-28 (afternoon)

The daily `netbox-populate` job had never worked (no success back to at
least 2026-06-14). There were three causes:
1. The self-hosted runner's `runner` user has no access to
   `/var/run/docker.sock`, so `docker build` failed.
2. OpenBao's `ci-netbox-populate` JWT role accepts only
   `refs/heads/main` (`configure-openbao.yml`). A dispatch from a branch,
   as runbook step 9 had it, can never log in.
3. `main` still carries the SOPS version of the workflow.

- **CI fix (`fix/netbox-populate-no-docker`, `0f912630`, not pushed).**
  The fix does not add `runner` to the `docker` group. The repo is public
  and `security-scan.yml` runs fork PRs on the same runner (approval is
  needed only for first-time contributors), so the group would give those
  jobs root-equivalent access. Instead the workflow runs `populate.py`
  directly: the container only wrapped Python 3.13 and pyyaml.
  `deploy-ci-runner.yml` now installs `python3-yaml`.
- **Runner deployed:** `provision.sh --stack ci-runner-01` on pve, under
  the approval flow (`ci-runner-python-yaml`). ok=95, changed=5,
  failed=0; the smoke test passed. `runner` imports pyyaml 6.0.2. Docker
  and the runner service were not restarted, and the runner is online in
  GitHub. The job itself can only be verified once the fix reaches
  `main`.
- **NetBox corrected by hand.**
  - A dry run of the full populate showed 86 pending writes (months of
    backlog), plus two warnings: Portainer endpoint discovery failed with
    "connection refused", and threat-model derivation fails with
    `unhashable type: 'list'`. It was not applied.
  - Instead, populate's own `populate_static_hosts()` was run for the
    framework entry only. It created `192.168.1.18/24` (id 58) on
    framework's eth0 and set it as `primary_ip4`.
  - The stale `192.168.1.8/24` record (id 42, still on framework's eth0) was
    deleted by the operator (204). NetBox now has no `.8` address.
- **Open:**
  - push the fix branch and promote it to `main`, then check the first
    scheduled run;
  - the 86-write catch-up it will then apply, including the Portainer
    discovery warning;
  - the threat-model bug.

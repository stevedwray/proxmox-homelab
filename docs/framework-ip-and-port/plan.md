# framework-ip-and-port plan: get Framework off 192.168.1.8, DNS-only, Ollama → llama.cpp

Written with `.github/prompts/plan-change.prompt.md`, following
`docs/agent-design/step-packet-schema.md`. Execute one step at a time with
`.github/prompts/implement-step.prompt.md`. Write each hand-back into
[README.md](README.md)'s Hand-back log.

The audit behind this plan (every hit, and what is deliberately left alone)
is in [README.md](README.md). Read that first.

## Why

1. **IP collision.** `192.168.1.8` belongs to **gazaar**, a NAS that is
   usually powered off and switched on only for backups. The Framework
   Desktop was given the same address by mistake (static, in netplan), so
   the two collide whenever gazaar is on. Framework has to move to a new
   address (`192.168.1.18`). Making every consumer use DNS first is what
   makes that move a one-record change instead of a hunt through configs.
2. **Ollama is gone.** Framework now serves models from the Nathanw
   llama.cpp fork on `:8080`, and Ollama has been removed entirely (checked
   live 2026-09-27: `:11434` refuses connections, and no container or unit
   is left). Everything that still talks to Ollama is broken now, not just
   pending migration. The worst case is docs-rag-mcp: it embeds every
   `search_docs` query through Ollama, so docs search is currently down.

The plan has three phases. **A** (DNS-only) comes first because B depends
on it. **C** (llama.cpp) is the most urgent. **B** (re-IP) comes last. See
"Execution order" below.

## Target state

- Every client of the Framework Desktop uses **`framework.gibbsgreatly.xyz`**,
  through the new `LAB_FQDN_FRAMEWORK` env var where the consumer reads env,
  or as a literal FQDN default where it doesn't (Python fallbacks).
- MikroTik forward rules into framework match
  **`dst-address-list=framework`**. That list's single static entry is the
  FQDN, and RouterOS resolves it itself from its own static DNS record.
- The IP is published in exactly one place: the MikroTik static DNS record
  `framework.gibbsgreatly.xyz`, which `mikrotik-dns-framework.yml` writes
  from `LAB_IP_FRAMEWORK`. That playbook is the only code that reads the
  variable. The other copies of the address are IPAM/asset records: the
  NetBox static host and the GVM `ip_to_stack.json`.
- Framework is at **`192.168.1.18`**, and `gazaar.gibbsgreatly.xyz` keeps
  `192.168.1.8`.
- Every former Ollama consumer uses llama.cpp. Chat/completions go to
  `nathanw-llamacpp.service` on `:8080`, which requires an API key.
  Embeddings go to a new `nathanw-llamacpp-embed.service` on `:8085`. Both
  units are managed from this repo, and both expose `/metrics` to
  monitoring-stack.

## Decisions (resolved with operator, 2026-09-27)

1. **Firewall:** use a RouterOS FQDN address-list, not `LAB_IP_FRAMEWORK`.
   All framework-bound rules move into one new playbook,
   `mikrotik-firewall-framework-fqdn.yml`. They are removed from
   `mikrotik-firewall-ai-services-stack.yml` and `mikrotik-firewall-cse-seg.yml`.
   The ai_seg rule allows `8080,8085`; 11434 is dropped along with Ollama.
2. **PentAGI remnants:** remove, don't convert. That covers the four
   hand-added `pentest_seg → framework` router rules (Ollama, SearXNG,
   llamacpp-router, SSH), the matching `policies:` entries, and
   `scripts/pentagi-test-harness/`. `deploy-pentagi-stack.yml` itself is out
   of scope.
3. **Env vars:** one FQDN plus one IP. Add `LAB_FQDN_FRAMEWORK` and keep
   `LAB_IP_FRAMEWORK` as the source for the DNS record only. Remove
   `LAB_IP_LLM_GPU`, `LAB_IP_COMFYUI` and `FRAMEWORK_HOST_IP`.
4. **Ports:** inventory only (README.md port registry). Port literals stay
   where they are.
5. **New address:** `192.168.1.18`, set statically in framework's netplan,
   the same way as today. It is outside the DHCP pool (`.100–.200`), has no
   lease or static DNS record, no repo references, and no ping or ARP
   answer (checked 2026-09-27). A powered-off device like gazaar wouldn't
   answer either, so the lease and DNS checks are what count. Recheck them
   just before the cutover.
6. **Embeddings:** a second llama-server (same Nathanw build) with
   `--embeddings`, serving `nomic-embed-text-v1.5` (f16 GGUF, 274 MB) on
   **:8085**. Port 8082 was the proposal, but it is still in use by the
   legacy SearXNG container on framework. docs-rag-mcp switches to
   `/v1/embeddings` and gets a full re-embed.
7. **`llm.${LAB_DOMAIN}` route:** repoint it from the dead LM Studio
   (`:8090`) to `:8080`, and require `LLM_GPU_STACK_API_KEY` there
   (`--api-key-file`). Every direct `:8080` client then sends that key.
8. **`:8080` under IaC:** a new playbook,
   `framework-desktop-llamacpp-native.yml`, takes over the hand-written
   `nathanw-llamacpp.service` and adds `--alias`, `--metrics` and
   `--api-key-file`. It keeps `--ctx-size 8192` until a measured step
   raises it.

## Research this plan relies on

- **DNS already resolves everywhere that matters.**
  `dig framework.gibbsgreatly.xyz` returns `192.168.1.8` from the
  workstation and from each consumer LXC's own resolver (the MikroTik
  gateway). **Correction (2026-09-27, during execution):** Technitium
  (`192.168.20.15`) did *not* resolve it. It is the Docker-daemon resolver on
  monitoring and five other stacks, so containers there couldn't resolve the
  name. `technitium-framework-forwarder.yml` now forwards the FQDN to the
  MikroTik; see the README hand-back log. Several consumers already use the FQDN in
  production: ai-services-stack OpenWebUI, docs-rag-mcp, deep-research-agent
  and cse-controller.
- **Framework-local config holds no copy of the IP** apart from netplan
  (checked 2026-09-27: `grep -r 192.168.1.8` over `/etc`, `/opt` and
  steve's config found nothing). Its containers publish on all interfaces,
  so an address change needs no container changes.
- **Nothing enforces `terraform/lxc/network/*.yaml` policy destinations that
  aren't zones.** `main.tf` only turns `policies` into Proxmox firewall rules
  when `policy.to` is the stack's own zone (`inbound_zone_policies`).
  `netbox-stack/integrations/flows.py` only reads `from`/`to` as labels. The
  enforcement is the MikroTik playbooks (`NETWORK_CONTRACT.md`: "All
  policies are enforced at the MikroTik firewall"). An FQDN in `to:` is
  therefore documentation, just like `internet` already is.
- **node_exporter's TLS cert already carries the DNS SAN.** The
  `node_exporter` role issues with `--san "{{ ansible_host }}" --san "{{
  inventory_hostname }}"`, and `inventory_hostname` is
  `framework.gibbsgreatly.xyz`. The IP SAN exists only because
  `ansible_host` was set to the IP. Scraping by FQDN verifies against the
  existing cert. After fwdns-06, the IP-SAN "force reissue" block in
  `framework-desktop-bootstrap.yml` would delete and reissue the cert on
  every run (its `when:` looks for `IP Address:<ansible_host>`). fwdns-06
  deletes that block in the same edit.
- **Edge manifests expand env vars** (`edge_manifest.py`:
  `os.path.expandvars`), so `${LAB_FQDN_FRAMEWORK}` works in `backend.url`
  once it's exported. An unset var would be left as the literal string
  `${LAB_FQDN_FRAMEWORK}`. That is why fwdns-01 lands first, and why
  fwdns-02's gate greps the rendered output.
- **RouterOS is 7.23.1** (router snapshot `scrape_meta`), and address-list
  entries accept a DNS name, which the router resolves into dynamic child
  entries. fwdns-08's playbook still asserts that a resolved IPv4 entry
  exists before it adds any rule.
- **The router snapshot is stale** (2026-08-13), and it predates
  `mikrotik-firewall-cse-seg.yml`. fwdns-00 refreshes it.
- **What `:8080` actually is** (checked live 2026-09-27):
  - `nathanw-llamacpp.service`, hand-written, not in the repo. It runs as
    `steve` from `/home/steve/llama.cpp/build-vk/bin/llama-server`,
    Nathanw fork build `b02cb35`, with `--ctx-size 8192`, auto `--parallel`
    (4 slots sharing one unified KV cache), no API key and no `--metrics`.
  - The only model is Qwen3.8-Flash-Next UD-Q4_K_XL (111 GB resident, 14 GB
    MemAvailable left).
  - It accepts any `model` string. It returns HTTP 501 for `/v1/embeddings`.
  - It is a reasoning model: with a tiny `max_tokens`, all the output lands
    in `reasoning_content` and `content` is empty.
  - The fork's `--help` confirms `--metrics`, `--api-key-file`,
    `--embeddings` and `--pooling`.
- **Live Ollama consumers**, all broken now:
  - docs-rag-mcp: `/api/embed` for every query and every reindex.
  - secpipe's weekly CVE deep-dive: `/api/generate`, **enabled**, next run
    Sunday 23:00. It fails per CVE and moves on.
  - The routine CVE narrative's `ollama` provider (not the default).
  - framework's Ollama textfile collector and its dashboard panels.
  - VS Code Copilot's "Framework Ollama" models (workstation config, not
    repo).
- **Current `:8080` clients**, which need the key once it's required:
  - ai-services OpenWebUI: already sends `LLM_GPU_STACK_API_KEY`.
  - deep-research: sends `OPENAI_API_KEY` or `"dummy"`.
  - cse-controller: sends `"not-needed"` unless a key is given.
  - `cse-small-batch-run.yml`: `"not-needed"`.
  - VS Code: no key.
- **The patches in `patches/` were generated from real edits and checked**
  (2026-09-27): syntax-check, py_compile, the docs-rag unit tests, and a
  live call of the new `_call_llamacpp` against `:8080` (success path and
  empty-content error path). They were cut in plan order, on top of the
  fwdns steps they follow.

## Execution order

The steps are numbered by phase. Run them in this order.

| # | Step(s) | Why here |
|---|---|---|
| 1 | fwdns-00 pre-flight; fwdns-01, -02, -03, -07, -08, -09 | Everything later names framework by FQDN and relies on the address-list firewall (ai_seg → 8080,8085) |
| 2 | Operator: router apply (fwdns-08); edge + monitoring deploy | Opens ai_seg → :8085 before docs-rag needs it |
| 3 | fwllm-01, -04 (code) → operator: download embeddings model, apply fwllm-01 live, then immediately redeploy the fwllm-04 consumers | Adding the key breaks unkeyed clients until they are redeployed, so keep that window short |
| 4 | fwdns-06 (once the FQDN scrape is confirmed up in #2), fwllm-02, -03, -05, -06 (+ operator deploys), fwllm-07 | Restores docs-rag search, the CVE deep-dive, the `llm.` route and monitoring. fwllm-06's patch was cut on top of fwdns-06 |
| 5 | Operator: measure chat context → fwllm-08 | Raises `--ctx-size` from 8192 only as far as memory allows |
| 6 | fwdns-05, -10, -11, -12 | DNS-only clean-up |
| 7 | fwip-01 (done), -02 → operator: re-IP cutover → fwip-03 | Needs all of the above: no client may still hold the IP. Run from `task/framework-reip-cutover` (see Phase B intro) |

**docs-rag `search_docs` is down until step 4 (fwllm-03).**
`implement-step` normally fetches a step through `search_docs`. Until then,
give the local model this plan by path (`get_document`), or have the
operator or a frontier session run steps 1–4.

## Validation tier and approvals

- Code steps are validated by their own gates (syntax-check, unit tests,
  dry-run renders, `git apply --check`).
- The live applies are **production mutations**. Each one needs its own
  Preflight Summary, operator "Proceed", and `TASK_APPROVAL`. They are
  written as operator prose, not step blocks.
  - Stacks on **pve-tiny**: ai-services, secpipe, mcp-utility and
    cse-controller. Deploy them with `./with-secrets-prod-tiny`.
  - Stacks on **pve**: proxy/Traefik and monitoring. Deploy them with
    `./with-secrets-prod`.
  - Framework is not a Proxmox node, but its playbooks need `pve`'s
    secrets. Since the OpenBao switch (2026-09-28), run them as
    `TASK_APPROVAL=<task> ./with-secrets-prod ansible-playbook ...`. The
    earlier `PVE_ENV= ./with-secrets` form (used for the 2026-09-27 runs
    below) now fails with an empty profile.
- **The router change needs a tier decision.** Per CLAUDE.md, *modifying or
  removing an existing cross-zone rule* maps to "full teardown cycle on
  pve-test-vm". That is not useful here: pve and pve-test-vm share the same
  physical MikroTik, pve-test-vm is not currently in use, and a full
  teardown must be requested by name. **Proposed narrower validation
  instead:**
  - add-before-remove ordering inside the playbook
  - its own post-apply assertions
  - live reachability checks from each real consumer (ai-services-stack →
    :8080, mcp-utility-stack → :8085, cse-controller → :8080)

  The operator confirms or overrides this at the fwdns-08 apply.
- **The re-IP is a host network change on framework.** It is guarded by
  `netplan try` (auto-revert). See the Phase B runbook.

---

# Phase A: DNS-only addressing

## Operator pre-flight: fwdns-00 (read-only, not a step block)

Run these before fwdns-02's live deploy and before fwdns-08's apply. None of
them mutates anything.

1. **The IP is pinned statically** (confirmed 2026-09-27: framework's
   `/etc/netplan/00-installer-config.yaml` has `addresses: [192.168.1.8/24]`,
   a subiquity-written static config). Nothing to do here; Phase B changes
   it.
2. **Refresh the router snapshot:**
   `./with-secrets bash -c 'MIKROTIK_USER=${MIKROTIK_ADMIN:-$MIKROTIK_USER} MIKROTIK_PASSWORD=${MIKROTIK_ADMIN_PASSWORD:-$MIKROTIK_PASSWORD} router/scripts/scrape-config.sh'`
   (read-only REST GETs). Then run
   `jq '.. | objects | select(."dst-address"? == "192.168.1.8") | {".id", comment, "dst-port"}' router/config/current-config.json`
   and confirm the six legacy rules listed in fwdns-08's
   `framework_legacy_rule_comments`. Record any extra rule in README.md.
   fwdns-08 will not remove it, so decide what to do with it before the
   apply. Rules for **gazaar** (192.168.1.8 is its address too) must be
   left alone.
3. **RouterOS version:** 7.23.1 as of the last snapshot. Re-read `version`
   from the refreshed snapshot's `system_resource`.
4. **Resolution from each consumer network.** From ai-services-stack,
   secpipe-stack, mcp-utility-stack (all on pve-tiny, ai_seg),
   cse-controller (cse_seg), monitoring-stack (mgmt_seg) and
   proxy-stack/Traefik (edge_seg), run
   `getent hosts framework.gibbsgreatly.xyz`. Every one must print the
   framework address.
5. **`gazaar.gibbsgreatly.xyz` stays.** It is the NAS's real name and
   address. Nothing in this plan edits it.
6. **Portainer's framework endpoint URL.** It was registered by hand, not
   by this repo. Run a read-only
   `GET http://<portainer>:9000/api/endpoints` (the admin token is in SOPS)
   and note the framework endpoint's `URL`. If it is `tcp://192.168.1.8:9001`,
   change it to `tcp://framework.gibbsgreatly.xyz:9001` in the Portainer UI
   before Phase B.

---

### fwdns-01-env-fqdn

```yaml
id: fwdns-01-env-fqdn
title: Add LAB_FQDN_FRAMEWORK to .env and .env.template
depends_on: []

change: >
  In .env, insert one new line directly after the line starting
  `export LAB_FQDN_HARBOR=` (line 45):
  `export LAB_FQDN_FRAMEWORK="framework.gibbsgreatly.xyz"               # Framework Desktop FQDN -- the ONLY way clients should address it; IP lives in DNS (docs/framework-ip-and-port/plan.md)`
  In .env.template, insert the identical line directly after the line
  starting `export LAB_FQDN_HARBOR=` (line 125). Change nothing else in
  either file.

scope:
  allowed_paths:
    - .env
    - .env.template
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Removing or editing any existing variable (that is fwdns-11)"

gates:
  - id: env-value
    cmd: "bash -c 'source .env && test \"$LAB_FQDN_FRAMEWORK\" = framework.gibbsgreatly.xyz && echo ok'"
    expect: "prints ok"
    critical: true
  - id: template-has-var
    cmd: "grep -c '^export LAB_FQDN_FRAMEWORK=\"framework.gibbsgreatly.xyz\"' .env.template"
    expect: "prints 1"
    critical: true
```

### fwdns-02-edge-manifests

```yaml
id: fwdns-02-edge-manifests
title: Point Traefik llm./comfyui. backends at the Framework FQDN
depends_on: [fwdns-01-env-fqdn]

change: >
  In terraform/lxc/stacks/llm-gpu-stack/edge.yaml replace the line
  `        url: http://${LAB_IP_LLM_GPU}:8090` with
  `        url: http://${LAB_FQDN_FRAMEWORK}:8090`.
  In terraform/lxc/stacks/comfyui-stack/edge.yaml replace the line
  `        url: http://${LAB_IP_COMFYUI}:8188` with
  `        url: http://${LAB_FQDN_FRAMEWORK}:8188`.
  No other edits.

scope:
  allowed_paths:
    - terraform/lxc/stacks/llm-gpu-stack/edge.yaml
    - terraform/lxc/stacks/comfyui-stack/edge.yaml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running reconcile-edge.py or provision.sh (live deploy is operator-run)"

gates:
  - id: dry-run-render
    cmd: "bash -c 'source .env && rm -rf docs/framework-ip-and-port/artifacts/edge-render && python3 terraform/lxc/render-edge-traefik.py terraform/lxc/stacks/llm-gpu-stack/edge.yaml terraform/lxc/stacks/comfyui-stack/edge.yaml --output-dir docs/framework-ip-and-port/artifacts/edge-render >/dev/null && grep -rh \"url:\" docs/framework-ip-and-port/artifacts/edge-render'"
    expect: "exactly two lines: `- url: http://framework.gibbsgreatly.xyz:8090` and `- url: http://framework.gibbsgreatly.xyz:8188`; no `192.168.1.8`, no literal `${`"
    critical: true
  - id: edge-manifest-tests
    cmd: "cd terraform/lxc && python3 -m unittest test_edge_manifest"
    expect: "OK"
    critical: true
```

### fwdns-03-monitoring-scrape

```yaml
id: fwdns-03-monitoring-scrape
title: Scrape framework node_exporter/cAdvisor by FQDN
depends_on: [fwdns-01-env-fqdn]

change: >
  In terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml replace
  `                - targets: ["{{ lookup('env', 'LAB_IP_FRAMEWORK') }}:9100"]` with
  `                - targets: ["{{ lookup('env', 'LAB_FQDN_FRAMEWORK') }}:9100"]`
  and replace
  `                - targets: ["{{ lookup('env', 'LAB_IP_FRAMEWORK') }}:8083"]` with
  `                - targets: ["{{ lookup('env', 'LAB_FQDN_FRAMEWORK') }}:8083"]`.
  Those are the only two occurrences of LAB_IP_FRAMEWORK in the file.

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running provision.sh (live deploy is operator-run)"

gates:
  - id: syntax-check
    cmd: "cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/deploy-monitoring-stack.yml"
    expect: "exit 0"
    critical: true
  - id: no-ip-var
    cmd: "grep -c LAB_IP_FRAMEWORK terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml"
    expect: "prints 0"
    critical: true
  - id: fqdn-var
    cmd: "grep -c \"lookup('env', 'LAB_FQDN_FRAMEWORK')\" terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml"
    expect: "prints 2"
    critical: true
```

### Operator deploy: edge + monitoring (not a step block)

Run after fwdns-02 and fwdns-03 have landed and fwdns-00 items 1 and 4
pass. Target is `pve`, via the production approval flow.

- **Traefik routes (Authentik/Traefik tier):** reconcile the llm-gpu-stack
  and comfyui-stack edge manifests onto proxy-stack by the normal edge
  path. Then check
  `curl -sk -o /dev/null -w '%{http_code}' https://comfyui.lab.gibbsgreatly.xyz/`.
  Expect the Authentik redirect (302). A 502 means Traefik can't resolve or
  reach the FQDN; roll back the edge.yaml change. The `llm.` route returns
  502 before and after this change, because its LM Studio backend (`:8090`)
  is dead. fwllm-05 fixes it.
- **monitoring-stack:**
  `./with-secrets-prod scripts/provision.sh --stack monitoring-stack`. Then
  confirm that VictoriaMetrics `up{stack="framework"}` is 1 for both jobs.
  The `instance` label changes from `192.168.1.8:9100` to
  `framework.gibbsgreatly.xyz:9100`. Check Grafana's framework dashboards
  for any panel pinned to the old instance value.

**fwdns-06 must not run until the node_exporter scrape is confirmed up by
FQDN.** After fwdns-06, newly issued certs have no IP SAN, so an IP-based
scrape would start failing TLS.

### fwdns-04-cve-enrichment-fqdn

**Superseded by fwllm-02 — do not run.** The CVE role's hard-coded
`http://192.168.1.8:11434` pointed at Ollama, which no longer exists.
Changing it to an FQDN on `:11434` would still be broken. fwllm-02 replaces
the whole Ollama provider with llama.cpp, addressed by FQDN.

### fwdns-05-ai-services-var

```yaml
id: fwdns-05-ai-services-var
title: ai-services-stack reads LAB_FQDN_FRAMEWORK instead of FRAMEWORK_HOST
depends_on: [fwdns-01-env-fqdn]

change: >
  In terraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml replace the
  8-line block starting `    # FQDN, not LAB_IP_FRAMEWORK's raw IP -- matches the established`
  and ending with the `    ai_services_framework_host: ...` line with exactly
  the "fwdns-05 replacement block" below the step (4-space indent kept).
  In terraform/lxc/stacks/ai-services-stack/STACK_CONTRACT.md make four
  exact-string replacements:
  (a) "- Egress: `ai_seg → framework:8080,11434` (`192.168.50.0/24 →\n  192.168.1.8`) so OpenWebUI can reach llamacpp-router/Ollama." becomes
  "- Egress: `ai_seg → framework:8080,8085` (`192.168.50.0/24 →\n  dst-address-list framework`, resolved from `framework.gibbsgreatly.xyz` by the router) so OpenWebUI can reach llama-server.";
  (b) "| `FRAMEWORK_HOST` (falls back to `framework.gibbsgreatly.xyz`) |" becomes
  "| `LAB_FQDN_FRAMEWORK` (falls back to `framework.gibbsgreatly.xyz`) |";
  (c) " Matches `deploy-pentagi-stack.yml`'s identical `pentagi_framework_host` pattern, the other contained zone reaching framework the same way |" becomes " |";
  (d) "Use `FRAMEWORK_HOST`/`framework.gibbsgreatly.xyz`\n  (FQDN, not `LAB_IP_FRAMEWORK`'s raw IP)" becomes
  "Use `LAB_FQDN_FRAMEWORK`/`framework.gibbsgreatly.xyz`\n  (FQDN, never an IP)".

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml
    - terraform/lxc/stacks/ai-services-stack/STACK_CONTRACT.md
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Touching deploy-pentagi-stack.yml (deprecated, out of scope)"
    - "Running provision.sh -- the resolved value is unchanged, no redeploy is needed"

gates:
  - id: syntax-check
    cmd: "cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/deploy-ai-services-stack.yml"
    expect: "exit 0"
    critical: true
  - id: no-old-var
    cmd: "grep -c 'FRAMEWORK_HOST\\b' terraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml terraform/lxc/stacks/ai-services-stack/STACK_CONTRACT.md"
    expect: "both files print 0"
    critical: true
  - id: no-ip-in-contract
    cmd: "grep -n '192.168.1.8' terraform/lxc/stacks/ai-services-stack/STACK_CONTRACT.md"
    expect: "only the historical 'Before 2026-08-02 this variable held framework's flat-LAN IP' line remains"
    critical: false
```

#### fwdns-05 replacement block

```yaml
    # FQDN, never an IP -- LAB_FQDN_FRAMEWORK is the platform-wide name for
    # the Framework Desktop (docs/framework-ip-and-port/plan.md). DNS
    # resolution from containers on this LXC is already proven live
    # (Harbor's own hostname pull succeeded the same way during this
    # deployment).
    ai_services_framework_host: "{{ lookup('env', 'LAB_FQDN_FRAMEWORK') | default('framework.gibbsgreatly.xyz', true) }}"
```

### fwdns-06-inventory-and-bootstrap

Precondition (operator): the node_exporter scrape by FQDN has been
confirmed `up` (see the edge + monitoring deploy above).

```yaml
id: fwdns-06-inventory-and-bootstrap
title: Ansible reaches framework by FQDN; drop the one-shot IP-SAN reissue
depends_on: [fwdns-01-env-fqdn, fwdns-03-monitoring-scrape]

change: >
  In each of ansible/inventory/inventory.yml, ansible/inventory/dev.yml and
  ansible/inventory/production.yml replace
  `ansible_host: "{{ lookup('env', 'FRAMEWORK_HOST_IP') | default('framework.gibbsgreatly.xyz', true) }}"`
  with
  `ansible_host: "{{ lookup('env', 'LAB_FQDN_FRAMEWORK') | default('framework.gibbsgreatly.xyz', true) }}"`
  (indentation unchanged). In ansible/00-initial-setup/framework-desktop-bootstrap.yml
  delete the whole block from the comment line
  `    # Found live 2026-07-25: this inventory group's ansible_host defaults to`
  through the end of the task named
  `Remove node_exporter cert lacking an IP SAN (forces reissuance below)`
  (its last line is `        and ('IP Address:' + ansible_host) not in framework_node_exporter_cert_sans.stdout`),
  plus the one blank line after it, so that the task
  `Install node_exporter for host metrics collection (scraped by monitoring-stack)`
  directly follows the preceding `Refresh CA trust store` task's blank line.

scope:
  allowed_paths:
    - ansible/inventory/inventory.yml
    - ansible/inventory/dev.yml
    - ansible/inventory/production.yml
    - ansible/00-initial-setup/framework-desktop-bootstrap.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running framework-desktop-bootstrap.yml against framework"

gates:
  - id: inventory-resolves-fqdn
    cmd: "bash -c 'source .env && ansible -i ansible/inventory/inventory.yml framework.gibbsgreatly.xyz -m ansible.builtin.debug -a var=ansible_host'"
    expect: "\"ansible_host\": \"framework.gibbsgreatly.xyz\""
    critical: true
  - id: no-old-var
    cmd: "git grep -c FRAMEWORK_HOST_IP -- ansible/ ; test $? -eq 1 && echo clean"
    expect: "prints clean"
    critical: true
  - id: bootstrap-syntax
    cmd: "ansible-playbook --syntax-check -i localhost, ansible/00-initial-setup/framework-desktop-bootstrap.yml"
    expect: "exit 0"
    critical: true
  - id: san-block-gone
    cmd: "grep -c 'framework_node_exporter_cert_sans' ansible/00-initial-setup/framework-desktop-bootstrap.yml"
    expect: "prints 0"
    critical: true
```

### fwdns-07-network-intent

```yaml
id: fwdns-07-network-intent
title: Network intent names framework by FQDN; drop PentAGI policies
depends_on: []

change: >
  In both terraform/lxc/network/pve.yaml and terraform/lxc/network/pve-test-vm.yaml,
  in the `policies:` entry whose description starts
  `ai-services-stack to framework.gibbsgreatly.xyz (llamacpp-router,`,
  replace the line `    to: 192.168.1.8` with `    to: framework.gibbsgreatly.xyz`,
  and in the same entry replace `    ports: [8080, 11434]` with
  `    ports: [8080, 8085]` (llama-server chat + embeddings; Ollama is gone).
  In terraform/lxc/network/pve.yaml delete the whole policy entry
  (from its `  - from: pentest_seg` line through the last line of its
  description) whose `to:` is `192.168.1.8` and whose description begins
  `pentagi-stack to framework.gibbsgreatly.xyz (Ollama for embeddings,`
  (9 lines). In terraform/lxc/network/pve-test-vm.yaml delete the 5-line
  policy entry `  - from: pentest_seg` / `    to: 192.168.1.8` /
  `    protocol: tcp` / `    ports: [11434, 8082]` /
  `    description: pentagi-stack to framework.gibbsgreatly.xyz (Ollama, SearXNG)`.
  Leave the `inventory:` static_hosts `ip: 192.168.1.8` entry in pve.yaml
  untouched (IPAM record, intentional).

scope:
  allowed_paths:
    - terraform/lxc/network/pve.yaml
    - terraform/lxc/network/pve-test-vm.yaml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Editing any other policy, zone, or inventory entry"
    - "Running terragrunt / provision.sh"

gates:
  - id: framework-policy-ports
    cmd: "python3 -c \"import yaml; print([p['ports'] for f in ('terraform/lxc/network/pve.yaml','terraform/lxc/network/pve-test-vm.yaml') for p in yaml.safe_load(open(f))['policies'] if p.get('to')=='framework.gibbsgreatly.xyz'])\""
    expect: "prints [[8080, 8085], [8080, 8085]]"
    critical: true
  - id: yaml-parses
    cmd: "python3 -c \"import yaml; [yaml.safe_load(open(f)) for f in ('terraform/lxc/network/pve.yaml','terraform/lxc/network/pve-test-vm.yaml')]; print('ok')\""
    expect: "prints ok"
    critical: true
  - id: only-ipam-literal-left
    cmd: "grep -n '192.168.1.8$' terraform/lxc/network/pve.yaml terraform/lxc/network/pve-test-vm.yaml"
    expect: "exactly one line: pve.yaml `      ip: 192.168.1.8` (the static_hosts entry)"
    critical: true
  - id: netbox-integration-tests
    cmd: "python3 -m unittest discover -s terraform/lxc/stacks/netbox-stack/integrations -p 'test_*.py'"
    expect: "OK (128 tests at time of writing)"
    critical: true
  - id: zone-members-tests
    cmd: "cd terraform/lxc && python3 -m unittest test_generate_zone_members_index"
    expect: "OK"
    critical: true
```

### fwdns-08-mikrotik-framework-playbook

```yaml
id: fwdns-08-mikrotik-framework-playbook
title: New playbook owning all MikroTik rules into framework, via FQDN address-list
depends_on: [fwdns-01-env-fqdn]

change: >
  Create ansible/00-initial-setup/mikrotik-firewall-framework-fqdn.yml with
  exactly the content in the "fwdns-08 file content" block below the step.
  Transcribe it literally; do not restructure, rename vars, or merge tasks.

scope:
  allowed_paths:
    - ansible/00-initial-setup/mikrotik-firewall-framework-fqdn.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running the playbook (the live router apply is operator-run)"

gates:
  - id: syntax-check
    cmd: "ansible-playbook --syntax-check -i localhost, ansible/00-initial-setup/mikrotik-firewall-framework-fqdn.yml"
    expect: "exit 0"
    critical: true
  - id: no-ip-literal
    cmd: "grep -c '192.168.1.8' ansible/00-initial-setup/mikrotik-firewall-framework-fqdn.yml"
    expect: "prints 0"
    critical: true
```

#### fwdns-08 file content

```yaml
---
# Framework Desktop (framework.gibbsgreatly.xyz) firewall access, DNS-driven.
#
# Single owner of every MikroTik forward rule whose destination is the
# Framework Desktop. Rules match dst-address-list=framework; that list's one
# static entry is the FQDN, which RouterOS resolves itself (from its own
# /ip/dns/static record) into dynamic child entries. Changing Framework's IP
# therefore needs only the DNS record changed -- no playbook, env var or
# rule edit. See docs/framework-ip-and-port/plan.md.
#
# Replaces the dst-address=<IP> rules previously added by
# mikrotik-firewall-ai-services-stack.yml and mikrotik-firewall-cse-seg.yml,
# and removes the hand-added PentAGI-era pentest_seg -> framework rules
# (PentAGI is deprecated; those paths are removed, not converted).
# Ports: 8080 = llama-server chat (API key), 8085 = llama-server embeddings.
# Ollama's 11434 is gone from framework and is not re-opened.
#
# Order is add-before-remove: address-list, wait for it to resolve, add the
# list-based rules ahead of the first forward drop/reject, assert, and only
# then delete legacy rules -- no window without an allow. Legacy rules are
# matched by exact comment AND by still carrying a literal dst-address, so a
# re-run never touches anything this playbook created.
#
# pve, pve-tiny and pve-test-vm share this one physical router; ai_seg and
# cse_seg rules are subnet-scoped and apply to all of them at once.

- name: Ensure DNS-driven framework firewall rules on the live MikroTik
  hosts: localhost
  gather_facts: false

  vars:
    mikrotik_host: "{{ lookup('env', 'MIKROTIK_HOST') | mandatory('MIKROTIK_HOST env var is required') }}"
    mikrotik_rest_base_url: "https://{{ mikrotik_host }}/rest"
    mikrotik_user: >-
      {{
        lookup('env', 'MIKROTIK_ADMIN')
        | default(lookup('env', 'MIKROTIK_USER'), true)
        | default('api-user', true)
      }}
    mikrotik_password: >-
      {{
        lookup('env', 'MIKROTIK_ADMIN_PASSWORD')
        | default(lookup('env', 'MIKROTIK_PASSWORD'), true)
      }}

    lab_subnet_ai_cidr: "{{ lookup('env', 'LAB_SUBNET_AI_CIDR') | mandatory('LAB_SUBNET_AI_CIDR env var is required') }}"
    lab_subnet_cse_cidr: "{{ lookup('env', 'lab_subnet_cse_cidr') | mandatory('lab_subnet_cse_cidr env var is required') }}"
    framework_fqdn: "{{ lookup('env', 'LAB_FQDN_FRAMEWORK') | mandatory('LAB_FQDN_FRAMEWORK env var is required') }}"
    framework_address_list: "framework"
    framework_address_list_comment: "framework-fqdn: Framework Desktop, resolved by RouterOS DNS"

    framework_firewall_rules:
      - comment: "framework-fqdn: ai_seg to framework llama-server chat/embeddings"
        chain: "forward"
        action: "accept"
        protocol: "tcp"
        src-address: "{{ lab_subnet_ai_cidr }}"
        dst-address-list: "{{ framework_address_list }}"
        dst-port: "8080,8085"
      - comment: "framework-fqdn: cse_seg to framework llama-server"
        chain: "forward"
        action: "accept"
        protocol: "tcp"
        src-address: "{{ lab_subnet_cse_cidr }}"
        dst-address-list: "{{ framework_address_list }}"
        dst-port: "8080"

    framework_legacy_rule_comments:
      - "ai-services-stack: ai_seg to framework llamacpp-router/ollama"
      - "cse_seg to framework llama-server"
      - "pentest_seg to framework Ollama"
      - "pentest_seg to framework SearXNG"
      - "pentest_seg to framework llamacpp-router"
      - "pentest_seg to framework SSH (test-harness runner)"

  pre_tasks:
    - name: Assert MikroTik credentials are set
      ansible.builtin.assert:
        that:
          - mikrotik_user | length > 0
          - mikrotik_password | length > 0
        fail_msg: >-
          Set MIKROTIK_ADMIN/MIKROTIK_USER and MIKROTIK_ADMIN_PASSWORD/MIKROTIK_PASSWORD
          before running this playbook.

  tasks:
    # ── 1. Address-list entry (FQDN) ─────────────────────────────────────────

    - name: Read MikroTik firewall address-lists
      ansible.builtin.uri:
        url: "{{ mikrotik_rest_base_url }}/ip/firewall/address-list"
        method: GET
        user: "{{ mikrotik_user }}"
        password: "{{ mikrotik_password }}"
        force_basic_auth: true
        validate_certs: false  # nosonar: ansible:S4830 — MikroTik self-signed cert; HTTPS traffic still encrypted; private SDN
        return_content: true
        status_code: 200
      register: framework_address_lists
      no_log: true

    - name: Add framework FQDN address-list entry if missing
      ansible.builtin.uri:
        url: "{{ mikrotik_rest_base_url }}/ip/firewall/address-list/add"
        method: POST
        user: "{{ mikrotik_user }}"
        password: "{{ mikrotik_password }}"
        force_basic_auth: true
        validate_certs: false  # nosonar: ansible:S4830 — MikroTik self-signed cert; HTTPS traffic still encrypted; private SDN
        body_format: json
        body:
          list: "{{ framework_address_list }}"
          address: "{{ framework_fqdn }}"
          comment: "{{ framework_address_list_comment }}"
        status_code: [200, 201]
      when: >-
        (framework_address_lists.json
          | selectattr('list', 'equalto', framework_address_list)
          | selectattr('address', 'equalto', framework_fqdn)
          | list) | length == 0
      no_log: true

    - name: Wait for RouterOS to resolve the FQDN into the address-list
      ansible.builtin.uri:
        url: "{{ mikrotik_rest_base_url }}/ip/firewall/address-list"
        method: GET
        user: "{{ mikrotik_user }}"
        password: "{{ mikrotik_password }}"
        force_basic_auth: true
        validate_certs: false  # nosonar: ansible:S4830 — MikroTik self-signed cert; HTTPS traffic still encrypted; private SDN
        return_content: true
        status_code: 200
      register: framework_address_lists_resolved
      until: >-
        (framework_address_lists_resolved.json
          | selectattr('list', 'equalto', framework_address_list)
          | selectattr('address', 'match', '^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$')
          | list) | length > 0
      retries: 12
      delay: 5
      no_log: true

    - name: Report resolved framework address(es)
      ansible.builtin.debug:
        msg: >-
          {{ framework_fqdn }} resolved by RouterOS to
          {{ framework_address_lists_resolved.json
             | selectattr('list', 'equalto', framework_address_list)
             | selectattr('address', 'match', '^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$')
             | map(attribute='address') | list }}

    # ── 2. List-based rules, ahead of the first forward drop/reject ──────────

    - name: Read MikroTik firewall filter rules
      ansible.builtin.uri:
        url: "{{ mikrotik_rest_base_url }}/ip/firewall/filter"
        method: GET
        user: "{{ mikrotik_user }}"
        password: "{{ mikrotik_password }}"
        force_basic_auth: true
        validate_certs: false  # nosonar: ansible:S4830 — MikroTik self-signed cert; HTTPS traffic still encrypted; private SDN
        return_content: true
        status_code: 200
      register: firewall_filters
      no_log: true

    - name: Find first forward drop/reject rule for ordered insertion
      ansible.builtin.set_fact:
        forward_drop_anchor: >-
          {{
            (firewall_filters.json
              | selectattr('chain', 'defined')
              | selectattr('chain', 'equalto', 'forward')
              | selectattr('action', 'defined')
              | selectattr('action', 'in', ['drop', 'reject'])
              | list)
            | first | default({})
          }}

    - name: Add each missing list-based framework rule
      ansible.builtin.uri:
        url: "{{ mikrotik_rest_base_url }}/ip/firewall/filter/add"
        method: POST
        user: "{{ mikrotik_user }}"
        password: "{{ mikrotik_password }}"
        force_basic_auth: true
        validate_certs: false  # nosonar: ansible:S4830 — MikroTik self-signed cert; HTTPS traffic still encrypted; private SDN
        body_format: json
        body: >-
          {{
            item | combine({'place-before': forward_drop_anchor['.id']})
            if forward_drop_anchor != {} else item
          }}
        status_code: [200, 201]
      loop: "{{ framework_firewall_rules }}"
      loop_control:
        label: "{{ item.comment }}"
      when: >-
        (firewall_filters.json
          | selectattr('comment', 'defined')
          | selectattr('comment', 'equalto', item.comment)
          | selectattr('dst-address-list', 'defined')
          | selectattr('dst-address-list', 'equalto', item['dst-address-list'])
          | selectattr('src-address', 'defined')
          | selectattr('src-address', 'equalto', item['src-address'])
          | selectattr('dst-port', 'defined')
          | selectattr('dst-port', 'equalto', item['dst-port'])
          | list) | length == 0
      no_log: true

    - name: Re-read MikroTik firewall filter rules after add
      ansible.builtin.uri:
        url: "{{ mikrotik_rest_base_url }}/ip/firewall/filter"
        method: GET
        user: "{{ mikrotik_user }}"
        password: "{{ mikrotik_password }}"
        force_basic_auth: true
        validate_certs: false  # nosonar: ansible:S4830 — MikroTik self-signed cert; HTTPS traffic still encrypted; private SDN
        return_content: true
        status_code: 200
      register: firewall_filters_added
      no_log: true

    - name: Assert every list-based framework rule exists before removing anything
      ansible.builtin.assert:
        that:
          - >-
            (firewall_filters_added.json
              | selectattr('comment', 'defined')
              | selectattr('comment', 'equalto', item.comment)
              | selectattr('dst-address-list', 'defined')
              | selectattr('dst-address-list', 'equalto', item['dst-address-list'])
              | selectattr('dst-port', 'defined')
              | selectattr('dst-port', 'equalto', item['dst-port'])
              | list) | length == 1
        fail_msg: "Rule '{{ item.comment }}' missing or duplicated -- legacy rules NOT removed."
      loop: "{{ framework_firewall_rules }}"
      loop_control:
        label: "{{ item.comment }}"

    # ── 3. Remove legacy IP-based rules ──────────────────────────────────────

    - name: Build list of legacy IP-based framework rules
      ansible.builtin.set_fact:
        framework_legacy_rules: >-
          {{
            firewall_filters_added.json
            | selectattr('comment', 'defined')
            | selectattr('comment', 'in', framework_legacy_rule_comments)
            | selectattr('dst-address', 'defined')
            | list
          }}

    - name: Report legacy rules about to be removed
      ansible.builtin.debug:
        msg: "{{ framework_legacy_rules | map(attribute='comment') | list }}"

    - name: Remove legacy IP-based framework rules
      ansible.builtin.uri:
        url: "{{ mikrotik_rest_base_url }}/ip/firewall/filter/{{ item['.id'] }}"
        method: DELETE
        user: "{{ mikrotik_user }}"
        password: "{{ mikrotik_password }}"
        force_basic_auth: true
        validate_certs: false  # nosonar: ansible:S4830 — MikroTik self-signed cert; HTTPS traffic still encrypted; private SDN
        status_code: [200, 204]
      loop: "{{ framework_legacy_rules }}"
      loop_control:
        label: "{{ item.comment }}"
      no_log: true

    - name: Re-read MikroTik firewall filter rules after removal
      ansible.builtin.uri:
        url: "{{ mikrotik_rest_base_url }}/ip/firewall/filter"
        method: GET
        user: "{{ mikrotik_user }}"
        password: "{{ mikrotik_password }}"
        force_basic_auth: true
        validate_certs: false  # nosonar: ansible:S4830 — MikroTik self-signed cert; HTTPS traffic still encrypted; private SDN
        return_content: true
        status_code: 200
      register: firewall_filters_final
      no_log: true

    - name: Assert no legacy IP-based framework rule remains
      ansible.builtin.assert:
        that:
          - >-
            (firewall_filters_final.json
              | selectattr('comment', 'defined')
              | selectattr('comment', 'in', framework_legacy_rule_comments)
              | list) | length == 0
        fail_msg: "Legacy framework rules still present after removal."
```

### fwdns-09-trim-legacy-mikrotik-entries

```yaml
id: fwdns-09-trim-legacy-mikrotik-entries
title: Remove framework rules from the ai-services and cse_seg MikroTik playbooks
depends_on: [fwdns-08-mikrotik-framework-playbook]

change: >
  In ansible/00-initial-setup/mikrotik-firewall-ai-services-stack.yml:
  delete the vars line starting `    lab_ip_framework: "{{ lookup('env', 'LAB_IP_FRAMEWORK')`;
  delete the 7-line rule entry starting
  `      - comment: "ai-services-stack: ai_seg to framework llamacpp-router/ollama"`
  (through its `        dst-port: "8080,11434"` line); and replace the header
  comment line `#   2. ai_seg -> framework:8080,11434  (llamacpp-router, Ollama, egress)` with
  `#   2. ai_seg -> framework:8080,11434 -- moved to mikrotik-firewall-framework-fqdn.yml (FQDN address-list)`.
  In ansible/00-initial-setup/mikrotik-firewall-cse-seg.yml:
  delete the vars line starting `    lab_ip_framework: "{{ lookup('env', 'LAB_IP_FRAMEWORK')`;
  delete the 7-line rule entry starting
  `      - comment: "cse_seg to framework llama-server"`
  (through its `        dst-port: "8080"` line); and replace the header
  comment line starting `#   5. cse_seg -> framework:8080` with
  `#   5. cse_seg -> framework:8080 -- moved to mikrotik-firewall-framework-fqdn.yml (FQDN address-list)`.

scope:
  allowed_paths:
    - ansible/00-initial-setup/mikrotik-firewall-ai-services-stack.yml
    - ansible/00-initial-setup/mikrotik-firewall-cse-seg.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Editing any other rule, var, or task in either file"
    - "Running either playbook"

gates:
  - id: syntax-check
    cmd: "ansible-playbook --syntax-check -i localhost, ansible/00-initial-setup/mikrotik-firewall-ai-services-stack.yml ansible/00-initial-setup/mikrotik-firewall-cse-seg.yml"
    expect: "exit 0"
    critical: true
  - id: no-framework-ip
    cmd: "grep -c 'lab_ip_framework\\|LAB_IP_FRAMEWORK' ansible/00-initial-setup/mikrotik-firewall-ai-services-stack.yml ansible/00-initial-setup/mikrotik-firewall-cse-seg.yml"
    expect: "both files print 0"
    critical: true
```

### Operator apply: router (not a step block)

Run only after fwdns-00 items 2–4 pass and fwdns-08/-09 are committed. The
target is the shared MikroTik: this is a production mutation, so it needs
its own Preflight Summary and approval. Confirm the validation-tier proposal
at this point (see "Validation tier and approvals").

```bash
export TASK_APPROVAL="fwdns-08-mikrotik-framework-fqdn"
./with-secrets-prod ansible-playbook ansible/00-initial-setup/mikrotik-firewall-framework-fqdn.yml
```

Then, from each consumer:

- ai-services-stack:
  `curl -s -o /dev/null -w '%{http_code}' http://framework.gibbsgreatly.xyz:8080/v1/models`
- cse-controller: the same `:8080/v1/models` check
- mcp-utility-stack → `:8085` can only be checked after fwllm-01 is live
  (the embeddings server doesn't exist yet). It is part of the fwllm-03
  deploy check.

A non-`000` code means the path is open. On failure, the list-based rules
are still in place, so check `/ip firewall address-list print where
list=framework` on the router first. Afterwards, re-scrape the snapshot
(fwdns-00 item 2) and commit it. Separately, remove the PentAGI harness key
from framework's `~steve/.ssh/authorized_keys` (the pending item in
`project_pentagi_harness_key_cleanup`), because its firewall path is now
gone.

### fwdns-10-remove-pentagi-harness

```yaml
id: fwdns-10-remove-pentagi-harness
title: Delete the deprecated PentAGI test harness
depends_on: []

change: >
  Run `git rm -r scripts/pentagi-test-harness` (README.md, run_sequence.py,
  test_sequence.json, test_sequence_gptoss.json), then delete any leftover
  untracked scripts/pentagi-test-harness/__pycache__ directory.

scope:
  allowed_paths:
    - scripts/pentagi-test-harness/
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Touching deploy-pentagi-stack.yml or any pentagi-stack file"

gates:
  - id: gone
    cmd: "test ! -e scripts/pentagi-test-harness && echo gone"
    expect: "prints gone"
    critical: true
  - id: no-code-refs
    cmd: "git grep -n 'pentagi-test-harness' -- ':!docs' ; test $? -eq 1 && echo clean"
    expect: "prints clean"
    critical: true
```

### fwdns-11-retire-ip-vars-and-comments

```yaml
id: fwdns-11-retire-ip-vars-and-comments
title: Remove LAB_IP_LLM_GPU, LAB_IP_COMFYUI, FRAMEWORK_HOST_IP; FQDN in usage comments
depends_on: [fwdns-02-edge-manifests, fwdns-06-inventory-and-bootstrap, fwdns-09-trim-legacy-mikrotik-entries]

change: >
  In .env delete the three lines starting `export LAB_IP_LLM_GPU=`,
  `export LAB_IP_COMFYUI=` and `export FRAMEWORK_HOST_IP=`, and replace the
  line starting `export LAB_IP_FRAMEWORK=` with
  `export LAB_IP_FRAMEWORK='192.168.1.8'                           # Framework Desktop IPv4 -- read ONLY by ansible/00-initial-setup/mikrotik-dns-framework.yml, which publishes it as the framework.gibbsgreatly.xyz DNS record; every client uses LAB_FQDN_FRAMEWORK (docs/framework-ip-and-port/plan.md)`.
  In .env.template delete the lines starting `export FRAMEWORK_HOST_IP=`,
  `export LAB_IP_LLM_GPU=`, `export LAB_IP_COMFYUI=`,
  `export TF_VAR_lab_ip_llm_gpu=` and `export TF_VAR_lab_ip_comfyui=`, and
  insert the same LAB_IP_FRAMEWORK line as above directly after the line
  starting `export LAB_FQDN_FRAMEWORK=`.
  In ansible/00-initial-setup/proxmox-gpu-unified-memory-tuning.yml and
  ansible/00-initial-setup/proxmox-vlan-aware-bridge.yml replace
  `-i "192.168.1.8,"` with `-i "framework.gibbsgreatly.xyz,"` in the usage comment.

scope:
  allowed_paths:
    - .env
    - .env.template
    - ansible/00-initial-setup/proxmox-gpu-unified-memory-tuning.yml
    - ansible/00-initial-setup/proxmox-vlan-aware-bridge.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Editing terraform/lxc/variables.tf, main.tf, or llm-gpu-stack/comfyui-stack stack.yaml (legacy, out of scope)"

gates:
  - id: vars-gone
    cmd: "git grep -nE 'LAB_IP_LLM_GPU|LAB_IP_COMFYUI|FRAMEWORK_HOST_IP' -- ':!docs' ; test $? -eq 1 && echo clean"
    expect: "prints clean"
    critical: true
  - id: env-sources
    cmd: "bash -c 'source .env && test \"$LAB_FQDN_FRAMEWORK\" = framework.gibbsgreatly.xyz && test \"$LAB_IP_FRAMEWORK\" = 192.168.1.8 && echo ok'"
    expect: "prints ok"
    critical: true
  - id: edge-still-renders
    cmd: "bash -c 'source .env && rm -rf docs/framework-ip-and-port/artifacts/edge-render && python3 terraform/lxc/render-edge-traefik.py terraform/lxc/stacks/llm-gpu-stack/edge.yaml terraform/lxc/stacks/comfyui-stack/edge.yaml --output-dir docs/framework-ip-and-port/artifacts/edge-render >/dev/null && grep -rh \"url:\" docs/framework-ip-and-port/artifacts/edge-render'"
    expect: "both urls use framework.gibbsgreatly.xyz"
    critical: true
```

### fwdns-12-final-audit

```yaml
id: fwdns-12-final-audit
title: Confirm only allowlisted IP literals remain
depends_on: [fwdns-04-cve-enrichment-fqdn, fwdns-05-ai-services-var, fwdns-07-network-intent, fwdns-10-remove-pentagi-harness, fwdns-11-retire-ip-vars-and-comments]

change: >
  No edits. Run the gate and record its output in README.md's hand-back log.
  If it lists any file not in the expected set, stop and report it; do not
  fix it in this step.

scope:
  allowed_paths:
    - docs/framework-ip-and-port/README.md
  forbidden_actions:
    - "Any edit other than the README.md hand-back entry"

gates:
  - id: literal-audit
    cmd: "git grep -lE '192\\.168\\.1\\.8([^0-9]|$)' -- ':!docs' | sort"
    expect: >-
      exactly these files: .env, .env.template,
      ansible/00-initial-setup/mikrotik-firewall-pentagi-to-ai-services-searxng.yml (historical comment),
      router/config/current-config.json (permanent: the static DNS record and the resolved address-list entries),
      terraform/lxc/ansible/roles/gvm_findings_ingest/files/assets/ip_to_stack.json,
      terraform/lxc/network/pve.yaml,
      terraform/lxc/stacks/ai-services-stack/STACK_CONTRACT.md (historical line),
      terraform/lxc/stacks/netbox-stack/integrations/tests/test_populate_static_hosts.py
    critical: true
```

---

---

# Phase C: Ollama → llama.cpp (Nathanw fork)

Every step block below applies one patch from `patches/`, generated from
real, tested edits. The executor runs `git apply` and the gates, and does
nothing else: there is no hand-editing and no interpretation. If
`git apply --check` fails because a file has moved on since the patch was
cut, **stop and hand back**. Do not hand-merge.

| Former Ollama consumer | Moves to | Step |
|---|---|---|
| docs-rag-mcp embeddings (every `search_docs` query + reindex) | `:8085` `/v1/embeddings`, nomic-embed-text-v1.5 | fwllm-01, -03 |
| secpipe CVE deep-dive (weekly, enabled) + routine narrative's local provider | `:8080` `/v1/chat/completions`, provider `llamacpp` | fwllm-02 |
| framework Ollama textfile collector + "Local AI" dashboard panels | llama-server `--metrics`, scraped directly | fwllm-06, -07 |
| Traefik `llm.${LAB_DOMAIN}` (was LM Studio `:8090`, also dead) | `:8080` | fwllm-05 |
| VS Code Copilot "Framework Ollama" models (workstation) | `:8080` | operator, below |

### fwllm-01-native-llamacpp-playbook

```yaml
id: fwllm-01-native-llamacpp-playbook
title: Add the playbook that manages both native llama-server units on framework
depends_on: []

change: >
  Run `git apply --check docs/framework-ip-and-port/patches/fwllm-01-native-llamacpp-playbook.patch`,
  then `git apply docs/framework-ip-and-port/patches/fwllm-01-native-llamacpp-playbook.patch`.
  It creates ansible/00-initial-setup/framework-desktop-llamacpp-native.yml.
  Make no other edits.

scope:
  allowed_paths:
    - ansible/00-initial-setup/framework-desktop-llamacpp-native.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running the playbook (the live apply is operator-run)"

gates:
  - id: applied
    cmd: "git apply --reverse --check docs/framework-ip-and-port/patches/fwllm-01-native-llamacpp-playbook.patch && echo applied"
    expect: "prints applied"
    critical: true
  - id: syntax-check
    cmd: "ansible-playbook --syntax-check -i ansible/inventory/inventory.yml ansible/00-initial-setup/framework-desktop-llamacpp-native.yml"
    expect: "exit 0"
    critical: true
  - id: chat-flags
    cmd: "grep -c -- '--metrics --api-key-file' ansible/00-initial-setup/framework-desktop-llamacpp-native.yml"
    expect: "prints 1"
    critical: true
```

### fwllm-02-cve-llamacpp-provider

```yaml
id: fwllm-02-cve-llamacpp-provider
title: CVE narrative + deep-dive use llama.cpp instead of Ollama
depends_on: [fwdns-01-env-fqdn]

change: >
  Run `git apply --check docs/framework-ip-and-port/patches/fwllm-02-cve-llamacpp-provider.patch`,
  then `git apply` the same file. It replaces the `ollama` provider with
  `llamacpp` (`_call_llamacpp` -> /v1/chat/completions, Bearer key, content
  only, error on empty content) in cve_enrichment_sync.py and
  cve_deep_dive.py, and renames the role's ollama_* vars, unit Environment=
  lines and llm-user.env entry to llamacpp_*. Make no other edits.

scope:
  allowed_paths:
    - terraform/lxc/ansible/roles/cve_enrichment_sync/
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Changing cve_enrichment_sync_llm_provider's default (stays anthropic)"
    - "Running provision.sh"

gates:
  - id: applied
    cmd: "git apply --reverse --check docs/framework-ip-and-port/patches/fwllm-02-cve-llamacpp-provider.patch && echo applied"
    expect: "prints applied"
    critical: true
  - id: py-compile
    cmd: "python3 -m py_compile terraform/lxc/ansible/roles/cve_enrichment_sync/files/cve_enrichment_sync.py terraform/lxc/ansible/roles/cve_enrichment_sync/files/cve_deep_dive.py"
    expect: "exit 0"
    critical: true
  - id: no-ollama-code
    cmd: "grep -rnE 'ollama_url|ollama_model|_call_ollama|OLLAMA_' terraform/lxc/ansible/roles/cve_enrichment_sync/ ; test $? -eq 1 && echo clean"
    expect: "prints clean"
    critical: true
  - id: secpipe-syntax
    cmd: "cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/deploy-secpipe-stack.yml"
    expect: "exit 0"
    critical: true
```

### fwllm-03-docs-rag-embeddings

```yaml
id: fwllm-03-docs-rag-embeddings
title: docs-rag-mcp embeds via the llama.cpp embeddings server
depends_on: [fwdns-01-env-fqdn]

change: >
  Run `git apply --check docs/framework-ip-and-port/patches/fwllm-03-docs-rag-llamacpp-embeddings.patch`,
  then `git apply` the same file. It rewrites docs_rag_mcp/embeddings.py
  for /v1/embeddings (EMBED_BASE_URL, default framework FQDN :8085), adds
  tests/test_embeddings.py, and changes deploy-mcp-utility-stack.yml's
  OLLAMA_URL env to EMBED_BASE_URL. Make no other edits.

scope:
  allowed_paths:
    - terraform/lxc/ansible/files/docs-rag-mcp/
    - terraform/lxc/ansible/playbooks/deploy-mcp-utility-stack.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running provision.sh or touching the pgvector database"

gates:
  - id: applied
    cmd: "git apply --reverse --check docs/framework-ip-and-port/patches/fwllm-03-docs-rag-llamacpp-embeddings.patch && echo applied"
    expect: "prints applied"
    critical: true
  - id: unit-tests
    cmd: "cd terraform/lxc/ansible/files/docs-rag-mcp && python3 -m unittest discover -s tests -p 'test_*.py'"
    expect: "OK (3 tests)"
    critical: true
  - id: mcp-syntax
    cmd: "cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/deploy-mcp-utility-stack.yml"
    expect: "exit 0"
    critical: true
```

### fwllm-04-api-key-consumers

```yaml
id: fwllm-04-api-key-consumers
title: Every direct :8080 client sends LLM_GPU_STACK_API_KEY
depends_on: []

change: >
  Run `git apply --check docs/framework-ip-and-port/patches/fwllm-04-llamacpp-api-key-consumers.patch`,
  then `git apply` the same file. It adds OPENAI_API_KEY (the OpenWebUI
  key) to deep-research's environment in deploy-ai-services-stack.yml;
  adds FRAMEWORK_LLM_API_KEY to cse-controller's worker.env and makes
  cse_tasks.py fall back to it; and puts the key into
  cse-small-batch-run.yml's model spec. Make no other edits.

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml
    - terraform/lxc/ansible/playbooks/deploy-cse-controller.yml
    - terraform/lxc/stacks/cse-controller/cyberseceval-config/cse_tasks.py
    - ansible/00-initial-setup/cse-small-batch-run.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running any deploy"

gates:
  - id: applied
    cmd: "git apply --reverse --check docs/framework-ip-and-port/patches/fwllm-04-llamacpp-api-key-consumers.patch && echo applied"
    expect: "prints applied"
    critical: true
  - id: py-compile
    cmd: "python3 -m py_compile terraform/lxc/stacks/cse-controller/cyberseceval-config/cse_tasks.py"
    expect: "exit 0"
    critical: true
  - id: syntax-check
    cmd: "cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/deploy-ai-services-stack.yml playbooks/deploy-cse-controller.yml && cd ../../.. && ansible-playbook --syntax-check -i localhost, ansible/00-initial-setup/cse-small-batch-run.yml"
    expect: "exit 0"
    critical: true
```

### Operator: download the embeddings model (not a step block)

On framework, as steve (a 274 MB download, pinned by SHA-256):

```bash
mkdir -p /mnt/nvme2/models-gguf/nomic-embed-text-v1.5
curl -fL -o /mnt/nvme2/models-gguf/nomic-embed-text-v1.5/nomic-embed-text-v1.5.f16.gguf \
  https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/nomic-embed-text-v1.5.f16.gguf
echo "f7af6f66802f4df86eda10fe9bbcfc75c39562bed48ef6ace719a251cf1c2fdb  /mnt/nvme2/models-gguf/nomic-embed-text-v1.5/nomic-embed-text-v1.5.f16.gguf" | sha256sum -c
```

### Operator: apply fwllm-01 live, then redeploy the key consumers (not a step block)

Prerequisites: fwllm-01 and fwllm-04 are committed, the model download
checks out, and fwdns-08 is applied on the router (ai_seg → 8080,8085).

1. `free -m` on framework. Stop if anything other than
   `nathanw-llamacpp.service` holds a large share of memory. ComfyUI idle is
   fine; a second LLM is not.
2. `TASK_APPROVAL=fwllm-01-native-apply ./with-secrets-prod ansible-playbook -i ansible/inventory/inventory.yml ansible/00-initial-setup/framework-desktop-llamacpp-native.yml` (run on 2026-09-27 as `PVE_ENV= ./with-secrets ...`, before the OpenBao switch).
   This restarts the chat server (the model reloads over a few minutes),
   starts the embeddings server, and self-checks four things: `/health`
   on both, a 401 without the key, `/metrics` with the key, and a
   768-dimension embedding.
3. **Straight away**, because every client without the key gets 401 from
   here on:
   - `./with-secrets-prod-tiny scripts/provision.sh --stack ai-services-stack`
     (for deep-research's key; OpenWebUI already sends it)
   - `./with-secrets-prod-tiny scripts/provision.sh --stack cse-controller`
   - **VS Code Copilot:** in `~/.config/Code/User/chatLanguageModels.json`,
     delete the whole "Framework Ollama" provider (4 models on `:11434`)
     and the Nathanw `qwen3.8-flash-next-q2` model on `:8079` (nothing
     listens there). Keep the Nathanw Q4 model on
     `http://framework.gibbsgreatly.xyz:8080/v1/chat/completions` and set
     its id to `qwen3.8-flash-next`. VS Code asks for the API key on first
     use; give it `LLM_GPU_STACK_API_KEY`.
4. Checks:
   - OpenWebUI chat answers.
   - A deep-research query runs.
   - A 1-case CSE run completes (`cse-small-batch-run.yml`).

### Operator: deploy fwllm-02 and fwllm-03 (not a step block)

- **secpipe (pve-tiny):**
  `./with-secrets-prod-tiny scripts/provision.sh --stack secpipe-stack`.
  Then, on secpipe-stack, run one deep-dive by hand (dry run, no writes):
  `cd /opt/cve-enrichment-sync && export $(systemctl show -p Environment --value cve-deep-dive.service) && set -a && . ./es-user.env && . ./llm-user.env && set +a && python3 cve_deep_dive.py --top-n 1 --dry-run`.
  Loading the unit's own `Environment=` is required: without it the script
  falls back to `ELASTICSEARCH_URL=https://127.0.0.1:9200` and fails with
  "Connection refused" (found during execution, 2026-09-27).
  A `llama.cpp returned no content` warning means the prompt plus
  `LLAMACPP_MAX_TOKENS` does not fit the context. That is the input to
  the context measurement below.
- **mcp-utility (pve-tiny):**
  1. `./with-secrets-prod-tiny scripts/provision.sh --stack mcp-utility-stack`.
  2. Force a full re-embed. Vectors from Ollama and llama.cpp are not
     interchangeable, and the reindex skips files whose hash is unchanged.
     On mcp-utility-stack:
     `cd /opt/mcp-utility-stack && docker compose stop docs-rag-mcp && docker compose exec -T pgvector psql -U docs_rag -d docs_rag -c 'TRUNCATE doc_chunks, file_index;' && docker compose start docs-rag-mcp`
     Stop the container first, so a reindex that is already running can't
     write into the table mid-wipe. The ivfflat "low recall" notice after
     TRUNCATE is expected; the reindex rebuilds that index at the end.
  3. Watch `docker compose logs -f docs-rag-mcp` for the `reindex summary`
     line and check that it shows `'failed': []`. ("startup reindex
     completed" is only logged when files **failed**.) Every chunk has to
     fit the embeddings server's 2048-token limit; see the chunking fix in
     README.md's hand-back log.
  4. Check that `psql ... -c 'SELECT count(*) FROM doc_chunks;'` is greater
     than 0, and that a `search_docs` query returns hits.
- **Post-commit hook:** `.git/hooks/post-commit` reindexed with
  `./with-secrets-prod` (pve), under its own standing approval. It was
  switched to `./with-secrets-prod-tiny` on 2026-09-27, after it redeployed
  mcp-utility against pve once (see README.md "Incident"). The hook isn't
  tracked, so a fresh clone needs the same local edit.

### fwllm-05-llm-route-to-8080

```yaml
id: fwllm-05-llm-route-to-8080
title: Traefik llm.${LAB_DOMAIN} routes to llama-server :8080
depends_on: [fwdns-02-edge-manifests, fwllm-01-native-llamacpp-playbook]

change: >
  Run `git apply --check docs/framework-ip-and-port/patches/fwllm-05-llm-route-to-8080.patch`,
  then `git apply` the same file. It changes llm-gpu-stack/edge.yaml's
  backend url from `${LAB_FQDN_FRAMEWORK}:8090` to `${LAB_FQDN_FRAMEWORK}:8080`
  and replaces the LM Studio comment. Make no other edits.

scope:
  allowed_paths:
    - terraform/lxc/stacks/llm-gpu-stack/edge.yaml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running reconcile-edge.py or provision.sh"

gates:
  - id: applied
    cmd: "git apply --reverse --check docs/framework-ip-and-port/patches/fwllm-05-llm-route-to-8080.patch && echo applied"
    expect: "prints applied"
    critical: true
  - id: dry-run-render
    cmd: "bash -c 'source .env && rm -rf docs/framework-ip-and-port/artifacts/edge-render && python3 terraform/lxc/render-edge-traefik.py terraform/lxc/stacks/llm-gpu-stack/edge.yaml --output-dir docs/framework-ip-and-port/artifacts/edge-render >/dev/null && grep -rh \"url:\" docs/framework-ip-and-port/artifacts/edge-render'"
    expect: "one line: `- url: http://framework.gibbsgreatly.xyz:8080`"
    critical: true
```

Deploy after the fwllm-01 live apply (the key must already be enforced
before the route exposes `:8080`): reconcile the llm-gpu-stack edge onto
proxy-stack on **pve**. Then check
`curl -sk -o /dev/null -w '%{http_code}' https://llm.lab.gibbsgreatly.xyz/v1/chat/completions -X POST -d '{}'`.
Expect 401. With `-H "Authorization: Bearer $LLM_GPU_STACK_API_KEY"` and a
real body, expect 200. OpenWebUI's `llm.` connection now reaches the same
server as its direct `:8080` connection, so the model is listed twice.
That is harmless.

### fwllm-06-monitoring-llamacpp-metrics

```yaml
id: fwllm-06-monitoring-llamacpp-metrics
title: Scrape llama.cpp /metrics; retire the Ollama textfile collector
depends_on: [fwdns-03-monitoring-scrape, fwdns-06-inventory-and-bootstrap]

change: >
  Run `git apply --check docs/framework-ip-and-port/patches/fwllm-06-monitoring-llamacpp-metrics.patch`,
  then `git apply` the same file. It adds a `llamacpp` scrape job
  (framework FQDN :8080 with the API key as Bearer, and :8085) to
  deploy-monitoring-stack.yml; in framework-desktop-bootstrap.yml it
  replaces the Ollama collector copy task with a removal task and drops
  its ExecStart line; and it deletes
  ansible/00-initial-setup/files/ollama_stats_textfile.py. Make no other edits.

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml
    - ansible/00-initial-setup/framework-desktop-bootstrap.yml
    - ansible/00-initial-setup/files/ollama_stats_textfile.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running provision.sh or the bootstrap playbook"

gates:
  - id: applied
    cmd: "git apply --reverse --check docs/framework-ip-and-port/patches/fwllm-06-monitoring-llamacpp-metrics.patch && echo applied"
    expect: "prints applied"
    critical: true
  - id: monitoring-syntax
    cmd: "cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/deploy-monitoring-stack.yml"
    expect: "exit 0"
    critical: true
  - id: bootstrap-syntax
    cmd: "ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles ansible-playbook --syntax-check -i localhost, ansible/00-initial-setup/framework-desktop-bootstrap.yml"
    expect: "exit 0"
    critical: true
  - id: collector-gone
    cmd: "test ! -e ansible/00-initial-setup/files/ollama_stats_textfile.py && echo gone"
    expect: "prints gone"
    critical: true
```

Deploy:

1. monitoring-stack on **pve**:
   `./with-secrets-prod scripts/provision.sh --stack monitoring-stack`.
   Then check that `up{job="llamacpp"}` is 1 for `server="chat"` and
   `server="embeddings"`. If it is 0, mgmt_seg can't reach
   `framework:8080/8085`; check the router before anything else.
2. Re-run the framework bootstrap:
   `ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles TASK_APPROVAL=fwllm-06-bootstrap ./with-secrets-prod ansible-playbook -i ansible/inventory/inventory.yml ansible/00-initial-setup/framework-desktop-bootstrap.yml`.
   That removes the dead collector and its stale `.prom` file.

### fwllm-07-dashboard-llamacpp-panels

Precondition (operator): fwllm-01 is live. Record the output of this
command in the hand-back; the gate below uses it:
`curl -s -H "Authorization: Bearer $LLM_GPU_STACK_API_KEY" http://framework.gibbsgreatly.xyz:8080/metrics | grep -oE '^llamacpp:[a-z_]+' | sort -u`.
The panels use upstream llama.cpp's metric names. If the Nathanw fork
names them differently, the gate fails. Stop and hand back; do not guess
new names.

```yaml
id: fwllm-07-dashboard-llamacpp-panels
title: Local AI dashboard shows llama.cpp instead of Ollama
depends_on: [fwllm-06-monitoring-llamacpp-metrics]

change: >
  Run `git apply --check docs/framework-ip-and-port/patches/fwllm-07-dashboard-llamacpp-panels.patch`,
  then `git apply` the same file. It retitles and repoints the Ollama row
  and panels in monitoring-stack/dashboards/local-ai.json to
  llamacpp:tokens_predicted_total (rate), llamacpp:requests_processing /
  requests_deferred, and up{job="llamacpp"}, and updates one description
  string in uvm-threat-vulnerability-overview.json. Make no other edits.

scope:
  allowed_paths:
    - terraform/lxc/stacks/monitoring-stack/dashboards/local-ai.json
    - terraform/lxc/stacks/monitoring-stack/dashboards/uvm-threat-vulnerability-overview.json
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Inventing metric names not present in the live /metrics output"

gates:
  - id: live-metric-names
    cmd: "./with-secrets bash -c 'curl -s -H \"Authorization: Bearer $LLM_GPU_STACK_API_KEY\" http://framework.gibbsgreatly.xyz:8080/metrics | grep -cE \"^llamacpp:(tokens_predicted_total|requests_processing|requests_deferred) \"'"
    expect: "prints 3"
    critical: true
  - id: applied
    cmd: "git apply --reverse --check docs/framework-ip-and-port/patches/fwllm-07-dashboard-llamacpp-panels.patch && echo applied"
    expect: "prints applied"
    critical: true
  - id: json-valid-no-ollama
    cmd: "python3 -c \"import json; json.load(open('terraform/lxc/stacks/monitoring-stack/dashboards/local-ai.json')); json.load(open('terraform/lxc/stacks/monitoring-stack/dashboards/uvm-threat-vulnerability-overview.json')); print('ok')\" && grep -ci ollama terraform/lxc/stacks/monitoring-stack/dashboards/local-ai.json"
    expect: "prints ok then 0"
    critical: true
```

Deploy with the next monitoring-stack provision on **pve**.

### Operator: measure chat context (not a step block)

Today `--ctx-size 8192` is shared by all four slots. That is well below the
131k tags the Ollama-era clients (Copilot agent mode, CVE deep-dive) were
built around. On a 122 GB unified-memory APU, an oversized KV cache can
take the whole host down (see the GPU double-load and unified-memory OOM
memories), so raise it one measured step at a time:

1. For each candidate `C` in `16384`, `32768`, `65536`, `131072`, in order:
   1. `TASK_APPROVAL=fwllm-ctx-measure ./with-secrets-prod ansible-playbook -i ansible/inventory/inventory.yml ansible/00-initial-setup/framework-desktop-llamacpp-native.yml -e framework_llamacpp_chat_ctx_size=C`.
   2. On framework, record
      `awk '/^MemAvailable:/ {print int($2/1024)}' /proc/meminfo` and the
      `llama_kv_cache` size line from `~/llamacpp-native-test/server.log`.
   3. **Stop at the first `C` that leaves less than 8192 MB
      MemAvailable.** Re-run step 1.1 with the previous `C`, and don't try
      larger values.
2. Keep the largest `C` that passed, and re-run the deep-dive dry run
   above to confirm it now gets content.
3. Write the number into README.md's hand-back log. The frontier session
   then writes fwllm-08, a one-line literal edit of the
   `framework_llamacpp_chat_ctx_size:` default, so the measured value is
   committed. Until then, every plain re-run of the playbook resets the
   context to 8192.

### fwllm-08-set-measured-ctx

**Done (2026-09-27, `9603847d`).** Measured 131072 (MemAvailable 9788 MB,
above the 8192 MB floor). `framework_llamacpp_chat_ctx_size: 131072` in
`ansible/00-initial-setup/framework-desktop-llamacpp-native.yml`, with the
full measurement series in the comment. See README.md's hand-back log.

---

# Phase B: move framework to 192.168.1.18

**Where to run Phase B from (reviewed 2026-09-28).** Phases A and C and
fwip-01 are merged to `stable` via #432. Run everything below from
**`task/framework-reip-cutover`**, cut from `origin/stable` after the
OpenBao switch. Never run it from `task/framework-dns-only-plan`: that
branch's `with-secrets*` wrappers are the retired SOPS versions.

**Wrappers after the OpenBao switch.**
- `./with-secrets` picks its OpenBao profile from `PVE_ENV`, so the older
  `PVE_ENV= ./with-secrets` form for framework playbooks now fails ("unknown
  profile ''").
- Run framework-hosted playbooks (`framework-desktop-*.yml`) through
  `./with-secrets-prod`, which uses the `pve` profile. It carries
  `LLM_GPU_STACK_API_KEY`, `STEP_CA_PROVISIONER_PASSWORD`,
  `NODE_EXPORTER_SCRAPE_PASSWORD[_HASH]`, MikroTik, Technitium and NetBox,
  all checked with `secrets_env.py --list-fields`.
- Give `TASK_APPROVAL` inline, per command, never exported. This follows
  the 2026-09-27 post-commit hook incident.
- The router re-scrape still works through plain `./with-secrets` (the dev
  profile has the MikroTik read credentials; checked 2026-09-28).

### fwip-01-mikrotik-dns-playbook

```yaml
id: fwip-01-mikrotik-dns-playbook
title: Playbook that publishes framework's address as its MikroTik DNS record
depends_on: [fwdns-01-env-fqdn]

change: >
  Run `git apply --check docs/framework-ip-and-port/patches/fwip-01-mikrotik-dns-framework.patch`,
  then `git apply` the same file. It creates
  ansible/00-initial-setup/mikrotik-dns-framework.yml, which touches only the
  LAB_FQDN_FRAMEWORK static record (address from LAB_IP_FRAMEWORK, TTL,
  comment), flushes the router's DNS cache, and toggles the `framework`
  address-list entry so it re-resolves. Make no other edits.

scope:
  allowed_paths:
    - ansible/00-initial-setup/mikrotik-dns-framework.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running the playbook"

gates:
  - id: applied
    cmd: "git apply --reverse --check docs/framework-ip-and-port/patches/fwip-01-mikrotik-dns-framework.patch && echo applied"
    expect: "prints applied"
    critical: true
  - id: syntax-check
    cmd: "ansible-playbook --syntax-check -i localhost, ansible/00-initial-setup/mikrotik-dns-framework.yml"
    expect: "exit 0"
    critical: true
  - id: no-ip-literal
    cmd: "grep -c '192.168.1' ansible/00-initial-setup/mikrotik-dns-framework.yml"
    expect: "prints 1 (only the header comment naming gazaar's 192.168.1.8)"
    critical: true
```

### Operator: lower the TTL, one day ahead (not a step block)

The framework record's TTL is currently `1d`, so caches (Technitium,
clients) may hold the old answer for up to a day. At least 24 hours before
the cutover, with `LAB_IP_FRAMEWORK` still `192.168.1.8`:

```bash
TASK_APPROVAL=fwip-dns-ttl-lower ./with-secrets-prod ansible-playbook ansible/00-initial-setup/mikrotik-dns-framework.yml -e framework_dns_ttl=5m
```

**Done 2026-09-27 16:30 NZDT** (see README.md). The address doesn't change. This run takes ownership of the record (adds
the comment) and shortens the TTL.

### fwip-02-record-new-ip

```yaml
id: fwip-02-record-new-ip
title: Record 192.168.1.18 as framework's address in env and IPAM data
depends_on: [fwip-01-mikrotik-dns-playbook, fwdns-11-retire-ip-vars-and-comments]

change: >
  In .env and .env.template, on the line starting `export LAB_IP_FRAMEWORK=`,
  change `'192.168.1.8'` to `'192.168.1.18'` (keep the comment).
  In terraform/lxc/network/pve.yaml, in the `inventory:` static host entry
  `- name: framework`, change `      ip: 192.168.1.8` to `      ip: 192.168.1.18`.
  In terraform/lxc/ansible/roles/gvm_findings_ingest/files/assets/ip_to_stack.json
  change the key `"192.168.1.8": null` to `"192.168.1.18": null`.
  Change nothing else; in particular leave every gazaar reference and the
  netbox test fixture alone.

scope:
  allowed_paths:
    - .env
    - .env.template
    - terraform/lxc/network/pve.yaml
    - terraform/lxc/ansible/roles/gvm_findings_ingest/files/assets/ip_to_stack.json
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running the DNS playbook or touching framework's netplan"

gates:
  - id: env
    cmd: "bash -c 'source .env && test \"$LAB_IP_FRAMEWORK\" = 192.168.1.18 && echo ok' && grep -c \"^export LAB_IP_FRAMEWORK='192.168.1.18'\" .env.template"
    expect: "prints ok then 1"
    critical: true
  - id: ipam
    cmd: "python3 -c \"import json,yaml; h=[x for x in yaml.safe_load(open('terraform/lxc/network/pve.yaml'))['inventory']['static_hosts'] if x['name']=='framework'][0]; m=json.load(open('terraform/lxc/ansible/roles/gvm_findings_ingest/files/assets/ip_to_stack.json')); print(h['ip'], '192.168.1.18' in m, '192.168.1.8' in m)\""
    expect: "prints 192.168.1.18 True False"
    critical: true
  - id: netbox-tests
    cmd: "python3 -m unittest discover -s terraform/lxc/stacks/netbox-stack/integrations -p 'test_*.py'"
    expect: "OK"
    critical: true
```

### Operator: re-IP cutover (not a step block)

Preconditions. Check every one on the day:

- You are on `task/framework-reip-cutover` (cut from `origin/stable`), with
  fwip-02 committed and **pushed**. Step 8 dispatches CI against it.
- The TTL was lowered at least 24 hours ago (done 2026-09-27 16:30 NZDT).
- **Every cache holds only the 5-minute answer.** Both of these must print a
  TTL of 300 or less:
  ```bash
  dig +noall +answer framework.gibbsgreatly.xyz @192.168.1.1
  dig +noall +answer framework.gibbsgreatly.xyz @192.168.20.15   # Technitium
  ```
  Technitium held a one-day answer, fetched before the TTL change, until
  about 14:02 NZDT on 2026-09-28. If it still shows more than 300, wait,
  or flush it with the step 4 playbook first.
- Portainer's endpoint is by FQDN (done 2026-09-27).
- **gazaar is powered off.**
- Give the operator one Preflight Summary covering every production
  mutation below:
  - the framework netplan change;
  - the MikroTik DNS record, twice (cutover and TTL restore);
  - the Technitium cache flush;
  - the framework bootstrap (node_exporter cert reissue);
  - the NetBox populate.
  Out of scope: everything else. Get approval before starting.

1. **Recheck that .18 is still free:**
   - `ping -c2 192.168.1.18` gets no reply.
   - The router's DHCP leases and static DNS have no `.18`:
     ```bash
     ./with-secrets bash -c 'MIKROTIK_USER=${MIKROTIK_ADMIN:-$MIKROTIK_USER} MIKROTIK_PASSWORD=${MIKROTIK_ADMIN_PASSWORD:-$MIKROTIK_PASSWORD} router/scripts/scrape-config.sh'
     jq '.. | objects | select(.address? == "192.168.1.18")' router/config/current-config.json   # must print nothing
     ```
2. **Change framework's address under an auto-revert.** Run this inside
   tmux so it survives the SSH drop. On framework:
   ```bash
   sudo cp /etc/netplan/00-installer-config.yaml /root/00-installer-config.yaml.pre-reip
   sudo sed -i 's|- 192.168.1.8/24|- 192.168.1.18/24|' /etc/netplan/00-installer-config.yaml
   grep -n '192.168.1.18/24' /etc/netplan/00-installer-config.yaml   # exactly one line
   tmux new -s reip 'sudo netplan try --timeout 300'
   ```
   The SSH session drops. From the workstation, run
   `ssh steve@192.168.1.18 -t tmux attach -t reip` and press Enter to
   accept. If you can't reach `.18` within 300 s, netplan reverts to `.8`
   by itself.
3. **Publish the new address.** First confirm the checkout carries fwip-02:
   `bash -c 'source .env && echo $LAB_IP_FRAMEWORK'` must print
   `192.168.1.18`. Then:
   ```bash
   TASK_APPROVAL=fwip-dns-cutover ./with-secrets-prod ansible-playbook ansible/00-initial-setup/mikrotik-dns-framework.yml -e framework_dns_ttl=5m
   ```
   The playbook points the record at `.18`, flushes the router cache, and
   waits until the `framework` address-list holds exactly `192.168.1.18`.
4. **Flush Technitium and prove it agrees with the MikroTik:**
   ```bash
   ANSIBLE_CONFIG=terraform/lxc/ansible/ansible.cfg TASK_APPROVAL=fwip-technitium-flush ./with-secrets-prod ansible-playbook -i terraform/lxc/environments/pve/technitium-stack/inventory.yml terraform/lxc/ansible/playbooks/technitium-framework-forwarder.yml
   ```
   Since 2026-09-28 this playbook deletes Technitium's cached answer for the
   FQDN on every run, then asserts Technitium returns the same address as
   the MikroTik. The forwarder zone already exists, so nothing else changes.
   Then **wait 5 minutes** for per-host resolvers and Docker's embedded DNS,
   and check `getent hosts framework.gibbsgreatly.xyz` from the same
   consumer set as fwdns-00 item 4: ai-services, secpipe, mcp-utility,
   cse-controller, monitoring and proxy. Every one must print
   `192.168.1.18`.
5. **Consumer checks:**
   - OpenWebUI chat.
   - docs-rag `search_docs`.
   - `https://comfyui.lab.gibbsgreatly.xyz/` (302) and
     `https://llm.lab.gibbsgreatly.xyz/v1/chat/completions` (401 without the
     key, 200 with it).
   - VictoriaMetrics `up{stack="framework"}` = 1 for node_exporter,
     cadvisor and llamacpp (chat and embeddings).
   - `ansible -i ansible/inventory/inventory.yml framework.gibbsgreatly.xyz -m ping`.
   - The Portainer endpoint is up.
6. **Reissue node_exporter's cert without the old IP.** Its SANs are
   `DNS:framework.gibbsgreatly.xyz, IP Address:192.168.1.8` (checked
   2026-09-28, valid to 2026-12-22). After the move, that IP is gazaar's.
   The role's renewal timer (`step ca renew`) keeps the existing SANs, so it
   would never drop the IP by itself. On framework:
   ```bash
   sudo rm -f /etc/node_exporter/certs/tls.crt /etc/node_exporter/certs/tls.key
   ```
   Then, from the workstation:
   ```bash
   ANSIBLE_ROLES_PATH=terraform/lxc/ansible/roles TASK_APPROVAL=fwip-node-exporter-reissue ./with-secrets-prod ansible-playbook -i ansible/inventory/inventory.yml ansible/00-initial-setup/framework-desktop-bootstrap.yml
   ```
   The role issues a fresh cert when the file is missing, using
   `ansible_host` and `inventory_hostname`, which are both the FQDN now.
   Check it:
   `echo | openssl s_client -connect framework.gibbsgreatly.xyz:9100 2>/dev/null | openssl x509 -noout -ext subjectAltName`
   must show `DNS:framework.gibbsgreatly.xyz` and no IP address.
   VictoriaMetrics `up{stack="framework",job="node_exporter"}` must return
   to 1.
7. **Restore the TTL**, from the same checkout (its `.env` must still say
   `.18`):
   ```bash
   TASK_APPROVAL=fwip-dns-ttl-restore ./with-secrets-prod ansible-playbook ansible/00-initial-setup/mikrotik-dns-framework.yml
   ```
   The TTL is back to 1h. Never run this from a checkout still at `.8`: it
   would point the name back at gazaar's address.
8. **Power on gazaar.** Check that `192.168.1.8` answers as the NAS, that
   `gazaar.gibbsgreatly.xyz` still resolves to `.8`, and that a backup run
   completes.
9. **NetBox.** The daily `netbox-populate` workflow (02:17 UTC) runs from
   `main`, which will say `.8` until it is promoted. Dispatch it against
   the cutover branch instead:
   ```bash
   gh workflow run netbox-populate.yml --ref task/framework-reip-cutover
   gh run watch "$(gh run list --workflow netbox-populate.yml --limit 1 --json databaseId -q '.[0].databaseId')"
   ```
   Then check that the framework static host shows `192.168.1.18` in NetBox.
   If the run fails at the OpenBao login, CI's GitHub-OIDC role doesn't
   accept that branch. Leave it: NetBox corrects itself on the first
   scheduled run after `stable` → `main`.
10. **Record.**
    1. Re-scrape the router (step 1's command); it now shows `.18` for the
       framework record and `.8` only for gazaar.
    2. Run fwip-03.
    3. Only then commit the snapshot and README.md hand-back. A commit
       touching `docs/**/*.md` fires the local post-commit hook, which
       redeploys mcp-utility-stack under its standing approval, so don't
       commit mid-cutover.
11. **Promotion.** The operator decides when to open the PR for
    `task/framework-reip-cutover` → `stable`. `stable` → `main` goes out
    together with #432's pending promotion.

**Rollback before step 3:** on framework's console, run
`sudo cp /root/00-installer-config.yaml.pre-reip /etc/netplan/00-installer-config.yaml && sudo netplan apply`.
Nothing else has changed yet.

**Rollback after step 3:**
1. Revert fwip-02 in the checkout (`git revert <fwip-02 commit>`), so
   `.env` says `.8` again.
2. Restore the netplan backup as above.
3. Re-run step 3's DNS playbook, then step 4's Technitium playbook.

### fwip-03-final-audit

```yaml
id: fwip-03-final-audit
title: Confirm 192.168.1.8 now appears only as gazaar or history
depends_on: [fwip-02-record-new-ip]

change: >
  No edits. Run the gate and record its output in README.md's hand-back log.
  If it lists any file not in the expected set, stop and report it; do not
  fix it in this step.

scope:
  allowed_paths:
    - docs/framework-ip-and-port/README.md
  forbidden_actions:
    - "Any edit other than the README.md hand-back entry"

gates:
  - id: literal-audit
    cmd: "git grep -lE '192\\.168\\.1\\.8([^0-9]|$)' -- ':!docs' | sort"
    expect: >-
      exactly: ansible/00-initial-setup/mikrotik-dns-framework.yml (gazaar
      header comment), ansible/00-initial-setup/mikrotik-firewall-pentagi-to-ai-services-searxng.yml
      (historical comment), router/config/current-config.json (gazaar's
      record only, after the post-cutover re-scrape),
      terraform/lxc/stacks/ai-services-stack/STACK_CONTRACT.md (historical
      line), terraform/lxc/stacks/netbox-stack/integrations/tests/test_populate_static_hosts.py
      (fixture)
    critical: true
  - id: new-ip-sites
    cmd: "git grep -lE '192\\.168\\.1\\.18([^0-9]|$)' -- ':!docs' | sort"
    expect: >-
      exactly: .env, .env.template,
      router/config/current-config.json (after re-scrape),
      terraform/lxc/ansible/roles/gvm_findings_ingest/files/assets/ip_to_stack.json,
      terraform/lxc/network/pve.yaml
    critical: true
```


## Out of scope (recorded, not actioned)

- **pve-tiny network intent.** ai-services, secpipe and mcp-utility now run
  on pve-tiny (`docs/ai-stacks-pve-tiny/`), and cse_seg is pve-tiny-only.
  `terraform/lxc/network/pve-tiny.yaml` has no `ai_seg → framework` or
  `cse_seg → framework` policy entries. The router enforces these anyway,
  because the rules are subnet-scoped, but the intent file is incomplete.
  Add them in a follow-up, using `to: framework.gibbsgreatly.xyz`.
- **Legacy `llm-gpu-stack` / `comfyui-stack` LXC definitions** (their
  `stack.yaml` files, `var.lab_ip_llm_gpu`/`var.lab_ip_comfyui` in
  `variables.tf` and `main.tf`). They are pve-framework-era and nothing
  provisions them. Their `edge.yaml` files are live and are handled here.
  Retire the rest separately.
- **`deploy-pentagi-stack.yml`'s `FRAMEWORK_HOST`**: deprecated stack.
- **`configure-ai-stack-dns-records.yml`**: its hard-coded
  `192.168.50.10/.11` "-bg" records are the old ai_seg LXC addresses, not
  framework. They are stale and belong to a separate cleanup.
- **Other Ollama-era artifacts. These are retirement candidates, not
  migrated.** Nothing live depends on them once Phase C is done; the
  operator decides whether to delete or keep each:
  - `ansible/00-initial-setup/framework-desktop-ollama.yml` (deploys
    Ollama).
  - `scripts/ollama-reliability-proxy/` and `scripts/local-ai-canary/`
    (the canary uses the proxy).
  - `scripts/framework-ai-benchmark/`.
  - `harbor_repull` manifest's `ollama/ollama:rocm`.
  - PentAGI playbooks' Ollama settings.
  - `scaffold-stack.py`'s `OPENCODE_MODEL`.
  - `~/git/ai-code-testing/docs/ollama.md`.
  - Stale router static DNS `ollama.gibbsgreatly.xyz` and
    `lm.gibbsgreatly.xyz` (→ `.4`).
- **Legacy containers still running on framework:**
  - `openwebui` (:8081) and `searxng` (:8082), from
    `framework-desktop-openwebui.yml`. These are superseded by
    ai-services-stack on ai_seg, and they hold :8082.
  - `portainer-agent`, `cadvisor` and `comfyui` are current; keep them.
- **LM Studio (`:8090`, `framework-desktop-lmstudio.yml`)** is not running.
  Its route moves to `:8080` in fwllm-05; the playbook itself is a
  retirement candidate.
- **A NetBox static-host entry for gazaar** (`192.168.1.8`, NAS), so the
  address is visibly claimed in IPAM and this collision can't recur
  silently. It needs a `role` value the populate script accepts.
- **`.env` is tracked in git**, although CLAUDE.md calls it gitignored. It
  holds only non-secret config, but the mismatch is worth resolving
  separately.
- **Centralising port numbers**: deliberately not done (Decision 4).

# framework-ip-and-port plan: DNS-only addressing for the Framework Desktop

Written with `.github/prompts/plan-change.prompt.md`, following
`docs/agent-design/step-packet-schema.md`. Execute one step at a time with
`.github/prompts/implement-step.prompt.md`. Write each hand-back into
[README.md](README.md)'s Hand-back log.

The audit behind this plan (every hit, and what is deliberately left alone)
is in [README.md](README.md). Read that first.

## Target state

- Every client of the Framework Desktop uses **`framework.gibbsgreatly.xyz`**,
  through the new `LAB_FQDN_FRAMEWORK` env var where the consumer reads env,
  or as a literal FQDN default where it doesn't (Python fallbacks).
- MikroTik forward rules into framework match
  **`dst-address-list=framework`**. That list's single static entry is the
  FQDN, and RouterOS resolves it itself from its own static DNS record.
- The IP is set in exactly one authoritative place: the MikroTik static DNS
  record `framework.gibbsgreatly.xyz`. `LAB_IP_FRAMEWORK` stays in `.env` as
  the documented value for IP-by-nature data only. Nothing in code reads it.
- Moving Framework to another IP then means updating the DNS record (and
  the three IPAM/asset literals listed in README.md). No playbook, edge
  manifest, firewall rule or scrape config changes.

## Decisions (resolved with operator, 2026-09-27)

1. **Firewall:** use a RouterOS FQDN address-list, not `LAB_IP_FRAMEWORK`.
   All framework-bound rules move into one new playbook,
   `mikrotik-firewall-framework-fqdn.yml`. They are removed from
   `mikrotik-firewall-ai-services-stack.yml` and `mikrotik-firewall-cse-seg.yml`.
2. **PentAGI remnants:** remove, don't convert. That covers the four
   hand-added `pentest_seg → framework` router rules (Ollama, SearXNG,
   llamacpp-router, SSH), the matching `policies:` entries, and
   `scripts/pentagi-test-harness/`. `deploy-pentagi-stack.yml` itself is out
   of scope.
3. **Env vars:** one FQDN plus one IP. Add `LAB_FQDN_FRAMEWORK`, keep
   `LAB_IP_FRAMEWORK` (documentation/IPAM only), and remove `LAB_IP_LLM_GPU`,
   `LAB_IP_COMFYUI` and `FRAMEWORK_HOST_IP`.
4. **Ports:** inventory only (README.md port registry). Port literals stay
   where they are.

## Research this plan relies on

- **DNS already resolves everywhere that matters.**
  `dig framework.gibbsgreatly.xyz` returns `192.168.1.8` from the
  workstation and from Technitium (`192.168.20.15`, the resolver the LXCs
  use), checked 2026-09-27. Several consumers already use the FQDN in
  production: ai-services-stack OpenWebUI, docs-rag-mcp, deep-research-agent,
  ollama-reliability-proxy.
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
- **The router snapshot is stale** (2026-08-13), and it predates
  `mikrotik-firewall-cse-seg.yml`. fwdns-00 refreshes it before the router
  step.
- **RouterOS address-list entries accept a DNS name.** The router resolves
  it and keeps dynamic child entries with the resolved address(es). *Treat
  this as unverified on this router until fwdns-00's check passes.* The
  playbook in fwdns-08 also asserts that a resolved IPv4 entry appears
  before it adds any rule. (Per the standing rule: verify technical claims
  before relying on them.)

## Validation tier and approvals

- Code steps fwdns-01 to -07 and -10 to -12 are validated by their own gates
  (syntax-check, unit tests, dry-run renders).
- The live applies below are **production mutations**. Each one needs its
  own Preflight Summary, operator "Proceed", and `TASK_APPROVAL`. They are
  written as operator prose, not step blocks.
- **The router change needs a tier decision.** Per CLAUDE.md, *modifying or
  removing an existing cross-zone rule* maps to "full teardown cycle on
  pve-test-vm". That is not useful here: pve and pve-test-vm share the same
  physical MikroTik, pve-test-vm is not currently in use, and a full
  teardown must be requested by name. **Proposed narrower validation
  instead:**
  - add-before-remove ordering inside the playbook
  - its own post-apply assertions
  - live reachability checks from each real consumer (ai-services-stack →
    :8080, secpipe-stack → :11434, cse-controller → :8080)

  The operator confirms or overrides this at the fwdns-08 apply.

---

## Operator pre-flight: fwdns-00 (read-only, not a step block)

Run these before fwdns-02's live deploy and before fwdns-08's apply. None of
them mutates anything.

1. **Confirm the IP is pinned.** Nothing in this repo pins `192.168.1.8`
   (no DHCP lease in the router snapshot, no netplan in the bootstrap
   playbook). On framework, run `ip -4 addr show` and
   `ls /etc/netplan/ && sudo cat /etc/netplan/*.yaml`. Confirm that
   `192.168.1.8` is static or a MikroTik DHCP static lease. If it is dynamic,
   DNS can drift from reality, so fix that first.
2. **Refresh the router snapshot:**
   `./with-secrets bash -c 'MIKROTIK_USER=${MIKROTIK_ADMIN:-$MIKROTIK_USER} MIKROTIK_PASSWORD=${MIKROTIK_ADMIN_PASSWORD:-$MIKROTIK_PASSWORD} router/scripts/scrape-config.sh'`
   (read-only REST GETs). Then run
   `jq '.. | objects | select(."dst-address"? == "192.168.1.8") | {".id", comment, "dst-port"}' router/config/current-config.json`
   and confirm the six legacy rules listed in fwdns-08's
   `framework_legacy_rule_comments`. Record any extra rule in README.md.
   fwdns-08 will not remove it, so decide what to do with it before the
   apply.
3. **RouterOS version and FQDN address-list support:** read `version` from
   the refreshed snapshot's `system_resource`. RouterOS 7.x is expected.
4. **Resolution from each consumer network.** From ai-services-stack,
   secpipe-stack (both now on pve-tiny, ai_seg), cse-controller (cse_seg),
   monitoring-stack (mgmt_seg) and proxy-stack/Traefik (edge_seg), run
   `getent hosts framework.gibbsgreatly.xyz`. Every one must print
   `192.168.1.8`.
5. **`gazaar.gibbsgreatly.xyz`** also points at `192.168.1.8` in router
   static DNS and is unused by this repo. Decide whether to keep it as an
   alias or delete it. This is not a step here.

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
  path. Then check `curl -sk -o /dev/null -w '%{http_code}' https://llm.lab.gibbsgreatly.xyz/v1/models`
  (expect 401 without the key, or 200 with it; the point is not 502) and
  `https://comfyui.lab.gibbsgreatly.xyz/` (expect the Authentik redirect,
  302). A 502 means Traefik can't resolve or reach the FQDN; roll back the
  edge.yaml change.
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

```yaml
id: fwdns-04-cve-enrichment-fqdn
title: Replace hard-coded Ollama IP in cve_enrichment_sync role
depends_on: [fwdns-01-env-fqdn]

change: >
  In terraform/lxc/ansible/roles/cve_enrichment_sync/defaults/main.yml replace
  `cve_enrichment_sync_ollama_url: "http://192.168.1.8:11434"` with
  `cve_enrichment_sync_ollama_url: "http://{{ lookup('env', 'LAB_FQDN_FRAMEWORK') | default('framework.gibbsgreatly.xyz', true) }}:11434"`.
  In both terraform/lxc/ansible/roles/cve_enrichment_sync/files/cve_enrichment_sync.py
  and terraform/lxc/ansible/roles/cve_enrichment_sync/files/cve_deep_dive.py
  replace the string `"http://192.168.1.8:11434"` with
  `"http://framework.gibbsgreatly.xyz:11434"` (exactly one occurrence per file).

scope:
  allowed_paths:
    - terraform/lxc/ansible/roles/cve_enrichment_sync/defaults/main.yml
    - terraform/lxc/ansible/roles/cve_enrichment_sync/files/cve_enrichment_sync.py
    - terraform/lxc/ansible/roles/cve_enrichment_sync/files/cve_deep_dive.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Changing the model name, provider, or any other default"
    - "Running provision.sh (live deploy is operator-run)"

gates:
  - id: no-ip-left
    cmd: "git grep -c '192.168.1.8' -- terraform/lxc/ansible/roles/cve_enrichment_sync/ ; test $? -eq 1 && echo clean"
    expect: "prints clean"
    critical: true
  - id: py-compile
    cmd: "python3 -m py_compile terraform/lxc/ansible/roles/cve_enrichment_sync/files/cve_enrichment_sync.py terraform/lxc/ansible/roles/cve_enrichment_sync/files/cve_deep_dive.py"
    expect: "exit 0"
    critical: true
  - id: secpipe-syntax
    cmd: "cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/deploy-secpipe-stack.yml"
    expect: "exit 0"
    critical: true
```

The operator deploys this with secpipe-stack's next redeploy on **pve-tiny**
(`./with-secrets-prod-tiny scripts/provision.sh --stack secpipe-stack`,
production approval flow). Afterwards, check that
`systemctl show cve-enrichment-sync -p Environment` on secpipe-stack shows
`OLLAMA_URL=http://framework.gibbsgreatly.xyz:11434`. The default provider
is `anthropic`, so this URL is only used on the Ollama path. No urgency.

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
  (a) "(`192.168.50.0/24 →\n  192.168.1.8`)" becomes
  "(`192.168.50.0/24 →\n  dst-address-list framework`, resolved from `framework.gibbsgreatly.xyz` by the router)";
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
  replace the line `    to: 192.168.1.8` with `    to: framework.gibbsgreatly.xyz`.
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
      - comment: "framework-fqdn: ai_seg to framework llama-server/ollama"
        chain: "forward"
        action: "accept"
        protocol: "tcp"
        src-address: "{{ lab_subnet_ai_cidr }}"
        dst-address-list: "{{ framework_address_list }}"
        dst-port: "8080,11434"
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
- secpipe-stack:
  `curl -s -o /dev/null -w '%{http_code}' http://framework.gibbsgreatly.xyz:11434/api/tags`
- cse-controller: the same `:8080/v1/models` check

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
  `export LAB_IP_FRAMEWORK='192.168.1.8'                           # Framework Desktop IPv4 -- documentation/IPAM only; nothing in code reads it. Clients use LAB_FQDN_FRAMEWORK; the authoritative IP is the MikroTik static DNS record (docs/framework-ip-and-port/plan.md)`.
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
- **`gazaar.gibbsgreatly.xyz`** static DNS alias: operator decision
  (fwdns-00 item 5).
- **`.env` is tracked in git**, although CLAUDE.md calls it gitignored. It
  holds only non-secret config, but the mismatch is worth resolving
  separately.
- **Centralising port numbers**: deliberately not done (Decision 4).

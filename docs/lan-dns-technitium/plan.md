# lan-dns-technitium plan

Written with `.github/prompts/plan-change.prompt.md`, following
`docs/agent-design/step-packet-schema.md`. Step blocks are meant to be
executed one at a time with `.github/prompts/implement-step.prompt.md`.
Everything that mutates production (`pve`, `pve-tiny`, the MikroTik, the
Pis) is written as plain operator prose, not a step block, and goes
through CLAUDE.md's production approval flow (Preflight Summary ->
Operator Approval -> `TASK_APPROVAL` -> execute -> After-Action Summary).

**Literal content blocks are indented three spaces** (fences included)
so that `docs-rag-mcp`'s heading-based chunker does not mistake a
column-0 `# comment` or `## Heading` inside them for a plan heading.
When transcribing one, strip exactly three leading spaces from every line.

**Goal:** replace the two Raspberry Pi Pi-holes with Technitium as the
DNS resolver for the whole LAN — two synced Technitium nodes (`pve` +
`pve-tiny`) doing Pi-hole-style ad/malware blocking — and then, as a
separate and largely independent track, move LAN DHCP to Technitium
using the already-planned `docs/dhcp-refactor/` Stage E/F.

## Decisions (operator, 2026-09-29)

1. **Client path: mgmt_seg IPs.** LAN clients get `192.168.20.15`
   (`technitium-stack`, pve) and `192.168.20.17` (`technitium-tiny-stack`,
   pve-tiny) via the MikroTik's DHCP `dns-server`. Technitium stays
   single-NIC on `mgmt_seg`. IPv6 RA stops advertising the Pi-hole ULAs
   (`advertise-dns=no` on `bridgeLocal`'s ND entry); clients resolve over
   IPv4 only. No new firewall rule is needed: the live forward chain has
   no drop for `bridgeLocal -> mgmt_seg`, and UDP+TCP/53 from the LAN to
   `192.168.20.15` was confirmed working live on 2026-09-29.
2. **Pis: cold fallback, then retire.** `argon-02` keeps running Pi-hole
   untouched through a 7-day soak as the rollback target; both Pis are
   then decommissioned. `argon-01` is already broken (below).
3. **Upstream: DoH forwarding.** Cloudflare + Quad9 over HTTPS, matching
   the router's existing DoH posture, instead of Technitium's current
   full recursion.
4. **pve-tiny: new secondary stack.** `technitium-tiny-stack` (VMID
   `20017`, `192.168.20.17`, pve-tiny `mgmt_seg`) is a new stack on the
   per-environment layout from day one. The live primary's Terraform
   state is not touched (`docs/environment-isolation/` remains a separate
   task).

## Design decisions derived from research (not operator calls)

- **Sync = Technitium clustering for config + zone transfer for zones.**
  Technitium v14+ clustering (image `15.2.0` is in use) syncs Settings,
  Allowed, Blocked, Apps and Administration from primary to secondary —
  so forwarders, blocklists, allow/deny lists and the query-log app are
  configured once, on the primary. Zones sync only if added to the
  cluster catalog, **and the cluster then manages member zones' NS/SOA —
  which `deploy-technitium-stack.yml` actively fights** (it deletes any
  root NS other than `ns1.<zone>` and rewrites the SOA on every deploy;
  read, not assumed: lines ~515-630). So the lab and reverse **Primary**
  zones replicate with plain zone transfer + NOTIFY to Secondary zones on
  pve-tiny instead; only **Forwarder** zones (which that playbook never
  touches) join the cluster catalog. DHCP is not cluster-synced (known
  upstream gap, already recorded in `docs/dhcp-refactor/decisions.md`
  Decision 4).
- **Cluster domain: `cluster.lab.gibbsgreatly.xyz`.** Fixed forever once
  chosen. It is a child of the zone Technitium already hosts, so the
  router's existing `lab-zone-delegate` rule covers it with no change.
  Initializing the cluster also renames each node's DNS server domain to
  `<hostname>.cluster.lab.gibbsgreatly.xyz` and turns on HTTPS (self-signed)
  on port 53443 automatically (Technitium's own clustering docs).
- **Blocking applies to the LAN only.** Pi-holes only ever filtered
  `bridgeLocal` clients. Several platform stacks already use Technitium
  as their Docker-daemon resolver, so every SDN subnet goes in
  `blockingBypassList` — platform DNS behavior does not change.
- **LAN names the router still owns stay on the router.** Today LAN
  clients go Pi-hole -> MikroTik, and the MikroTik answers ~67 static
  `*.gibbsgreatly.xyz` A records (pve, nas, garuda, …), DHCP-generated
  `*.lan` names, and their PTRs. Technitium gets conditional-forwarder
  zones for `gibbsgreatly.xyz`, `lan`, and `1.168.192.in-addr.arpa`
  pointing at the MikroTik's `mgmt_seg` gateway (same pattern as the
  existing `technitium-framework-forwarder.yml`). `lab.gibbsgreatly.xyz`
  is a more specific Primary zone on Technitium, so it is not forwarded
  (no loop). Side effect worth knowing: Docker daemons that use Technitium
  now see the router's split-horizon answers for `gibbsgreatly.xyz` names
  instead of Cloudflare's public ones — the same view LAN clients already
  get.
- **`technitium-tiny-stack` uses `network_mode: host`** like the primary.
  Same single-NIC/single-container reasoning as
  `docs/dhcp-refactor/decisions.md` Decision 5, and two concrete reasons
  specific to this stack: clustering registers node IPs and serves 53443,
  which bridge NAT would mask behind a Docker-internal address; and it
  keeps the deferred "second DHCP relay target" option (dhcp-refactor
  Deferred section) open without a later redeploy.

## Live facts this plan is grounded in (checked 2026-09-29)

- **`argon-01` (`192.168.1.22`) answers ping but not DNS** (queries time
  out). `argon-02` (`192.168.1.23`) is healthy: Pi-hole **v5** (FTL
  `v5.25.2`, dnsmasq `pi-hole-v2.90+1`), blocks `doubleclick.net` ->
  `0.0.0.0`, resolves `lab` names and LAN PTRs via the router.
- The MikroTik's `lan` DHCP network already hands out **only
  `192.168.1.23`** (router scrape 2026-09-28). So the dhcp-refactor
  cutover packet's `192.168.1.22` DNS-option row is already stale.
- IPv6 ND on `bridgeLocal` advertises `dns=fd00::22,fd00::23` — one of
  which (`::22`) is the broken Pi.
- Technitium (`192.168.20.15`) currently does full recursion with no
  forwarders and returned `SERVFAIL` (EDE 22, No Reachable Authority) for
  `doubleclick.net` while `github.com`/`google.com` resolved — decision 3
  removes this path.
- The router's upstream is DoH to `https://1.1.1.1/dns-query`, and its
  DHCP server adds `*.lan` dynamic entries (`add-dns-entries-suffix=lan`).
- `192.168.20.17` and VMID `20017` appear nowhere in the repo; confirm
  live before first apply (Phase 2 prose).

---

## Phase 0 — Inventory the Pi-hole

### Operator: export argon-02's Pi-hole config

No automation has SSH access to the Pis. From the workstation (argon-02
is Pi-hole v5, so the gravity DB is SQLite at `/etc/pihole/gravity.db`):

```bash
D=docs/lan-dns-technitium/artifacts/pihole-export; mkdir -p "$D"
ssh pi@192.168.1.23 'sudo sqlite3 -separator "|" /etc/pihole/gravity.db "select enabled,address,comment from adlist;"' > "$D/adlists.txt"
ssh pi@192.168.1.23 'sudo sqlite3 -separator "|" /etc/pihole/gravity.db "select type,enabled,domain,comment from domainlist;"' > "$D/domainlist.txt"
ssh pi@192.168.1.23 'sudo sqlite3 -separator "|" /etc/pihole/gravity.db "select id,name,enabled from \"group\";"' > "$D/groups.txt"
ssh pi@192.168.1.23 'sudo sqlite3 -separator "|" /etc/pihole/gravity.db "select id,ip,comment from client;"' > "$D/clients.txt"
ssh pi@192.168.1.23 'sudo cat /etc/pihole/custom.list' > "$D/custom.list"
ssh pi@192.168.1.23 'sudo cat /etc/dnsmasq.d/05-pihole-custom-cname.conf 2>/dev/null' > "$D/cname.conf"
ssh pi@192.168.1.23 'sudo grep -E "^(PIHOLE_DNS_|REV_SERVER|CONDITIONAL|DNSSEC|BLOCKING_ENABLED)" /etc/pihole/setupVars.conf' > "$D/setupvars.txt"
```

(`domainlist.type`: 0 = exact allow, 1 = exact deny, 2 = regex allow,
3 = regex deny.) Adjust the SSH user if it isn't `pi`. Optional: decide
whether argon-01 is worth reviving — nothing in this plan depends on it.

### lan-dns-01-pihole-inventory

```yaml
id: lan-dns-01-pihole-inventory
title: Transcribe the Pi-hole export into a tracked inventory doc
depends_on: []   # requires the operator export above to exist

change: >
  Create docs/lan-dns-technitium/pihole-inventory.md from the files in
  docs/lan-dns-technitium/artifacts/pihole-export/. It must contain exactly
  these level-2 headings in this order: "## Adlists (enabled)", "## Adlists
  (disabled)", "## Exact allow", "## Exact deny", "## Regex rules",
  "## Local records", "## Groups and clients", "## Upstreams". Under each,
  list the entries one per line as markdown bullets (adlists: the URL only;
  domainlist rows: the domain, type 0 -> Exact allow, 1 -> Exact deny, 2 or
  3 -> Regex rules prefixed "allow:" or "deny:"; enabled=0 rows are listed
  with a trailing " (disabled)"; custom.list and cname.conf lines verbatim
  under Local records; groups.txt and clients.txt rows verbatim under
  Groups and clients; setupvars.txt lines verbatim under Upstreams). Write
  "- none" under any heading with no entries. Do not interpret or filter.

scope:
  allowed_paths:
    - docs/lan-dns-technitium/pihole-inventory.md
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Copying any password or API token from setupvars.txt"
    - "Committing anything under docs/lan-dns-technitium/artifacts/"

gates:
  - id: headings-present
    cmd: "test $(grep -cE '^## (Adlists \\(enabled\\)|Adlists \\(disabled\\)|Exact allow|Exact deny|Regex rules|Local records|Groups and clients|Upstreams)$' docs/lan-dns-technitium/pihole-inventory.md) -eq 8"
    expect: "exit 0"
    critical: true
  - id: adlist-count-matches
    cmd: "test $(awk '/^## Adlists \\(enabled\\)$/{f=1;next} /^## /{f=0} f && /^- http/' docs/lan-dns-technitium/pihole-inventory.md | wc -l) -eq $(grep -c '^1|' docs/lan-dns-technitium/artifacts/pihole-export/adlists.txt)"
    expect: "exit 0"
    critical: true
  - id: no-password
    cmd: "! grep -qiE 'WEBPASSWORD|API_KEY|TOKEN' docs/lan-dns-technitium/pihole-inventory.md"
    expect: "exit 0"
    critical: true
```

**Frontier review point:** read `pihole-inventory.md` before
`lan-dns-02`. If "Regex rules" or "Groups and clients" is non-trivial
(per-client policy, regex deny lists), built-in Technitium blocking can't
reproduce it — that needs the Advanced Blocking app and a revised
`lan-dns-02`. If "Local records" holds names the MikroTik statics don't
already cover, add them as records (not forwarders) in a follow-up step.

---

## Phase 1 — Make the primary a LAN-grade resolver

No LAN client uses Technitium yet, so this phase has no client-facing
effect. Blocking is bypassed for every SDN subnet, so platform stacks
that resolve through Technitium are unaffected except for the DoH
upstream and the router-forwarded `gibbsgreatly.xyz` view.

### lan-dns-02-resolver-playbook

```yaml
id: lan-dns-02-resolver-playbook
title: Add configure-technitium-lan-resolver.yml
depends_on: [lan-dns-01-pihole-inventory]

change: >
  Create terraform/lxc/ansible/playbooks/configure-technitium-lan-resolver.yml
  with exactly the literal content (with its 3-space indent stripped) in the plan section "Literal content:
  configure-technitium-lan-resolver.yml", then replace the single example
  entry in lan_resolver_block_list_urls with every URL listed under
  "## Adlists (enabled)" in docs/lan-dns-technitium/pihole-inventory.md (same
  order), fill lan_resolver_allowed_domains from "## Exact allow" and
  lan_resolver_blocked_domains from "## Exact deny" (skip entries marked
  "(disabled)"; leave [] when the section says "- none").

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/configure-technitium-lan-resolver.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running the playbook against any host"
    - "Adding regex entries to either domain list"

gates:
  - id: syntax-check
    cmd: "bash -c 'cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/configure-technitium-lan-resolver.yml'"
    expect: "exit 0"
    critical: true
  - id: blocklists-transcribed
    cmd: "test $(grep -cE '^      - \"?https?://' terraform/lxc/ansible/playbooks/configure-technitium-lan-resolver.yml) -ge 1 && ! grep -q 'EXAMPLE-REPLACE' terraform/lxc/ansible/playbooks/configure-technitium-lan-resolver.yml"
    expect: "exit 0"
    critical: true
  - id: bypass-excludes-lan
    cmd: "! grep -q '192.168.1.0/24' terraform/lxc/ansible/playbooks/configure-technitium-lan-resolver.yml"
    expect: "exit 0"
    critical: true
```

#### Literal content: configure-technitium-lan-resolver.yml

   ```yaml
   ---
   # LAN-resolver settings for technitium-stack, the Technitium cluster
   # primary (docs/lan-dns-technitium/plan.md, Phase 1).
   #
   # Makes Technitium a drop-in replacement for the Pi-holes: DoH upstream
   # forwarding, Pi-hole-style blocklists applied to the LAN only, forwarder
   # zones back to the MikroTik for the LAN names it still owns, and the
   # Query Logs app. Every setting here is a Technitium cluster parameter,
   # so technitium-tiny-stack inherits it through clustering -- run this
   # against the primary only.
   #
   # Standalone so it can be applied without re-running the whole Technitium
   # deploy; also imported at the end of deploy-technitium-stack.yml so
   # rebuilds keep it.

   - name: Configure Technitium as the LAN resolver
     hosts: all
     become: false
     gather_facts: false

     vars:
       technitium_ip: "{{ lookup('env', 'LAB_IP_TECHNITIUM') | default(ip_address | default(''), true) | mandatory('LAB_IP_TECHNITIUM env var is required') }}"
       technitium_admin_password: "{{ lookup('env', 'TECHNITIUM_ADMIN_PASSWORD') | mandatory('TECHNITIUM_ADMIN_PASSWORD env var is not set') }}"
       technitium_api_base: "http://{{ technitium_ip }}:5380/api"  # nosonar: ansible:S5332 — Technitium admin API, private mgmt_seg only
       lan_resolver_router: "{{ lookup('env', 'LAB_GW_MGMT') | mandatory('LAB_GW_MGMT env var is required') }}"

       # Decision 3: DoH forwarding, not full recursion.
       lan_resolver_forwarders:
         - "https://cloudflare-dns.com/dns-query (1.1.1.1)"
         - "https://dns.quad9.net/dns-query (9.9.9.9)"

       # Transcribed from docs/lan-dns-technitium/pihole-inventory.md.
       lan_resolver_block_list_urls:
         - "https://EXAMPLE-REPLACE/hosts"
       lan_resolver_allowed_domains: []
       lan_resolver_blocked_domains: []

       # Every SDN VLAN subnet bypasses blocking -- the Pi-holes only ever
       # filtered bridgeLocal, whose subnet is deliberately absent here.
       lan_resolver_blocking_bypass:
         - 192.168.10.0/24
         - 192.168.20.0/24
         - 192.168.30.0/24
         - 192.168.40.0/24
         - 192.168.50.0/24
         - 192.168.60.0/24
         - 192.168.70.0/24
         - 192.168.80.0/24
         - 192.168.81.0/24
         - 192.168.90.0/24
         - 192.168.100.0/24
         - 192.168.110.0/24
         - 192.168.120.0/24

       # Names the MikroTik still answers for LAN clients: its static
       # *.gibbsgreatly.xyz records, DHCP-generated *.lan names, and their PTRs.
       # lab.gibbsgreatly.xyz is a more specific Primary zone here, so it is
       # never forwarded (no loop with the router's lab-zone-delegate).
       lan_resolver_forwarder_zones:
         - gibbsgreatly.xyz
         - lan
         - 1.168.192.in-addr.arpa

       lan_resolver_query_log_app: "Query Logs (Sqlite)"

     tasks:
       - name: Log in to Technitium API and obtain session token
         ansible.builtin.uri:
           url: "{{ technitium_api_base }}/user/login?user=admin&pass={{ technitium_admin_password | urlencode }}&includeInfo=true"
           method: GET
           return_content: true
         register: lan_resolver_login
         retries: 10
         delay: 3
         until: lan_resolver_login.status == 200
         no_log: true

       - name: Extract Technitium API token
         ansible.builtin.set_fact:
           lan_resolver_token: "{{ (lan_resolver_login.content | from_json).token }}"
         no_log: true

       - name: Read current DNS settings
         ansible.builtin.uri:
           url: "{{ technitium_api_base }}/settings/get?token={{ lan_resolver_token }}"
           method: GET
           return_content: true
         register: lan_resolver_settings_raw
         no_log: true

       - name: Detect settings drift
         ansible.builtin.set_fact:
           lan_resolver_settings_drift: >-
             {{
               (s.forwarders | default([]) or []) != lan_resolver_forwarders
               or s.forwarderProtocol | default('') != 'Https'
               or not (s.enableBlocking | default(false))
               or s.blockingType | default('') != 'AnyAddress'
               or (s.blockListUrls | default([]) or []) != lan_resolver_block_list_urls
               or (s.blockingBypassList | default([]) or []) | sort != lan_resolver_blocking_bypass | sort
               or not (s.dnssecValidation | default(false))
             }}
         vars:
           s: "{{ (lan_resolver_settings_raw.content | from_json).response }}"

       - name: Apply LAN resolver settings
         ansible.builtin.uri:
           url: "{{ technitium_api_base }}/settings/set?forwarders={{ lan_resolver_forwarders | join(',') | urlencode }}&forwarderProtocol=Https&concurrentForwarding=true&dnssecValidation=true&recursion=AllowOnlyForPrivateNetworks&enableBlocking=true&blockingType=AnyAddress&blockListUrls={{ lan_resolver_block_list_urls | join(',') | urlencode }}&blockListUpdateIntervalHours=24&blockingBypassList={{ lan_resolver_blocking_bypass | join(',') | urlencode }}&token={{ lan_resolver_token }}"
           method: POST
           return_content: true
           status_code: [200]
         register: lan_resolver_settings_set
         changed_when: true
         failed_when: (lan_resolver_settings_set.content | from_json).status | default('') != 'ok'
         when: lan_resolver_settings_drift | bool
         no_log: true

       - name: Download block lists now instead of waiting for the 24h timer
         ansible.builtin.uri:
           url: "{{ technitium_api_base }}/settings/forceUpdateBlockLists?token={{ lan_resolver_token }}"
           method: POST
           status_code: [200]
         when: lan_resolver_settings_drift | bool
         no_log: true

       - name: List Technitium zones
         ansible.builtin.uri:
           url: "{{ technitium_api_base }}/zones/list?token={{ lan_resolver_token }}"
           method: GET
           return_content: true
         register: lan_resolver_zone_list
         no_log: true

       - name: Create router forwarder zones if absent
         ansible.builtin.uri:
           url: "{{ technitium_api_base }}/zones/create?zone={{ item }}&type=Forwarder&protocol=Udp&forwarder={{ lan_resolver_router }}&dnssecValidation=false&proxyType=DefaultProxy&initializeForwarder=true&token={{ lan_resolver_token }}"
           method: POST
           return_content: true
           status_code: [200]
         register: lan_resolver_fwd_create
         changed_when: true
         failed_when: (lan_resolver_fwd_create.content | from_json).status | default('') != 'ok'
         loop: "{{ lan_resolver_forwarder_zones }}"
         when: item not in (lan_resolver_zone_list.content | from_json).response.zones | map(attribute='name') | list
         no_log: true

       - name: Add allowed domains
         ansible.builtin.uri:
           url: "{{ technitium_api_base }}/allowed/add?domain={{ item | urlencode }}&token={{ lan_resolver_token }}"
           method: POST
           return_content: true
           status_code: [200]
         register: lan_resolver_allow_add
         changed_when: false
         failed_when: (lan_resolver_allow_add.content | from_json).status | default('') != 'ok'
         loop: "{{ lan_resolver_allowed_domains }}"
         no_log: true

       - name: Add blocked domains
         ansible.builtin.uri:
           url: "{{ technitium_api_base }}/blocked/add?domain={{ item | urlencode }}&token={{ lan_resolver_token }}"
           method: POST
           return_content: true
           status_code: [200]
         register: lan_resolver_block_add
         changed_when: false
         failed_when: (lan_resolver_block_add.content | from_json).status | default('') != 'ok'
         loop: "{{ lan_resolver_blocked_domains }}"
         no_log: true

       - name: List installed apps
         ansible.builtin.uri:
           url: "{{ technitium_api_base }}/apps/list?token={{ lan_resolver_token }}"
           method: GET
           return_content: true
         register: lan_resolver_apps
         no_log: true

       - name: List store apps when the query-log app is missing
         ansible.builtin.uri:
           url: "{{ technitium_api_base }}/apps/listStoreApps?token={{ lan_resolver_token }}"
           method: GET
           return_content: true
         register: lan_resolver_store_apps
         when: lan_resolver_query_log_app not in (lan_resolver_apps.content | from_json).response.apps | map(attribute='name') | list
         no_log: true

       - name: Resolve the query-log app download URL
         ansible.builtin.set_fact:
           lan_resolver_query_log_app_url: >-
             {{
               ((lan_resolver_store_apps.content | from_json).response.storeApps
                | selectattr('name', 'equalto', lan_resolver_query_log_app)
                | map(attribute='url') | list | first) | default('')
             }}
         when: lan_resolver_store_apps is not skipped

       - name: Assert the query-log app exists in the store
         ansible.builtin.assert:
           that:
             - lan_resolver_query_log_app_url | length > 0
           fail_msg: >-
             '{{ lan_resolver_query_log_app }}' not found in the Technitium app
             store; available names:
             {{ (lan_resolver_store_apps.content | from_json).response.storeApps | map(attribute='name') | list }}
         when: lan_resolver_store_apps is not skipped

       - name: Install the query-log app
         ansible.builtin.uri:
           url: "{{ technitium_api_base }}/apps/downloadAndInstall?name={{ lan_resolver_query_log_app | urlencode }}&url={{ lan_resolver_query_log_app_url | urlencode }}&token={{ lan_resolver_token }}"
           method: POST
           return_content: true
           status_code: [200]
         register: lan_resolver_app_install
         changed_when: true
         failed_when: (lan_resolver_app_install.content | from_json).status | default('') != 'ok'
         when: lan_resolver_store_apps is not skipped
         no_log: true

       # Blocking must be probed from a non-bypassed address: the LXC itself
       # sits in 192.168.20.0/24 (bypassed), so these digs run on the control
       # node, which is on bridgeLocal like a real LAN client.
       - name: Probe blocking from the LAN
         ansible.builtin.command: dig @{{ technitium_ip }} +short doubleclick.net A
         delegate_to: localhost
         register: lan_resolver_block_probe
         check_mode: false
         changed_when: false
         retries: 30
         delay: 10
         until: (lan_resolver_block_probe.stdout | trim) == '0.0.0.0'

       - name: Probe public resolution from the LAN
         ansible.builtin.command: dig @{{ technitium_ip }} +short github.com A
         delegate_to: localhost
         register: lan_resolver_public_probe
         check_mode: false
         changed_when: false
         failed_when: (lan_resolver_public_probe.stdout | trim) | length == 0

       - name: Ask the MikroTik for a router-owned LAN name
         ansible.builtin.command: dig @{{ lan_resolver_router }} +short pve.gibbsgreatly.xyz A
         register: lan_resolver_router_expected
         check_mode: false
         changed_when: false

       - name: Ask Technitium for the same name
         ansible.builtin.command: dig @{{ technitium_ip }} +short pve.gibbsgreatly.xyz A
         register: lan_resolver_router_actual
         check_mode: false
         changed_when: false

       - name: Assert Technitium agrees with the MikroTik for router-owned names
         ansible.builtin.assert:
           that:
             - lan_resolver_router_expected.stdout | trim | length > 0
             - (lan_resolver_router_actual.stdout | trim) == (lan_resolver_router_expected.stdout | trim)
           fail_msg: >-
             Technitium returned '{{ lan_resolver_router_actual.stdout | trim }}'
             for pve.gibbsgreatly.xyz; the MikroTik returned
             '{{ lan_resolver_router_expected.stdout | trim }}'.
         when: not ansible_check_mode
   ```

### lan-dns-03-import-into-deploy

```yaml
id: lan-dns-03-import-into-deploy
title: Import the LAN resolver playbook at the end of deploy-technitium-stack.yml
depends_on: [lan-dns-02-resolver-playbook]

change: >
  Append these three lines to the very end of
  terraform/lxc/ansible/playbooks/deploy-technitium-stack.yml, after the
  existing "Forward the Framework Desktop FQDN to the MikroTik" import, with
  one blank line before them:
  "- name: Configure Technitium as the LAN resolver (docs/lan-dns-technitium/)"
  / "  ansible.builtin.import_playbook: configure-technitium-lan-resolver.yml".
  (Two YAML lines; the first starts with "- name:", the second is indented
  two spaces.) Change nothing else in the file.

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-technitium-stack.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any edit to existing lines of deploy-technitium-stack.yml"

gates:
  - id: syntax-check
    cmd: "bash -c 'cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/deploy-technitium-stack.yml'"
    expect: "exit 0"
    critical: true
  - id: import-is-last
    cmd: "tail -n 1 terraform/lxc/ansible/playbooks/deploy-technitium-stack.yml | grep -q 'import_playbook: configure-technitium-lan-resolver.yml'"
    expect: "exit 0"
    critical: true
  - id: only-additions
    cmd: "test $(git diff -U0 HEAD -- terraform/lxc/ansible/playbooks/deploy-technitium-stack.yml | grep -c '^-[^-]') -eq 0"
    expect: "exit 0"
    critical: true
```

### Operator: apply the resolver config to the primary (pve)

Production mutation — preflight, approval, then run just the standalone
playbook (targeted, not a full `provision.sh` redeploy):

```bash
export TASK_APPROVAL="lan-dns-resolver-primary"
./with-secrets-prod ansible-playbook \
  -i terraform/lxc/environments/pve/technitium-stack/inventory.yml \
  terraform/lxc/ansible/playbooks/configure-technitium-lan-resolver.yml
```

Rollback: `settings/set?forwarders=false&enableBlocking=false` via the
Technitium UI/API restores the pre-plan behavior; the forwarder zones can
be deleted in the UI. Afterwards, spot-check a platform stack that uses
Technitium as its Docker resolver still pulls images (e.g. re-run
`docker pull` of an already-used image on `monitoring-stack`).

### lan-dns-04-verify-primary

```yaml
id: lan-dns-04-verify-primary
title: Verify the primary answers like a Pi-hole, from the LAN
depends_on: [lan-dns-03-import-into-deploy]   # and the operator apply above

change: >
  No file edits. Run the gates from the workstation (on bridgeLocal) and
  record each result in docs/lan-dns-technitium/README.md's hand-back log.

scope:
  allowed_paths:
    - docs/lan-dns-technitium/README.md
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any Technitium API write or playbook run"

gates:
  - id: blocks-ads
    cmd: "test \"$(dig +short @192.168.20.15 doubleclick.net A)\" = 0.0.0.0"
    expect: "exit 0"
    critical: true
  - id: resolves-public
    cmd: "dig @192.168.20.15 github.com A | grep -q 'status: NOERROR'"
    expect: "exit 0"
    critical: true
  - id: lab-zone
    cmd: "test \"$(dig +short @192.168.20.15 traefik.lab.gibbsgreatly.xyz A)\" = 192.168.30.10"
    expect: "exit 0"
    critical: true
  - id: router-owned-name
    cmd: "test \"$(dig +short @192.168.20.15 pve.gibbsgreatly.xyz A)\" = \"$(dig +short @192.168.1.1 pve.gibbsgreatly.xyz A)\""
    expect: "exit 0"
    critical: true
  - id: lan-ptr
    cmd: "dig +short @192.168.20.15 -x 192.168.1.104 | grep -q garuda"
    expect: "exit 0"
    critical: true
  - id: same-verdict-as-pihole
    cmd: "for d in doubleclick.net googleadservices.com ads.yahoo.com; do test \"$(dig +short @192.168.20.15 $d A | head -1)\" = \"$(dig +short @192.168.1.23 $d A | head -1)\" || exit 1; done"
    expect: "exit 0"
    critical: false
```

---

## Phase 2 — Secondary node on pve-tiny

### lan-dns-05-ip-wiring

```yaml
id: lan-dns-05-ip-wiring
title: Wire lab_ip_technitium_tiny through .env and Terraform
depends_on: []

change: >
  (1) In .env, insert immediately after the line starting
  "export LAB_IP_TECHNITIUM=": export LAB_IP_TECHNITIUM_TINY='192.168.20.17'
  followed by two spaces and "# Technitium cluster secondary on pve-tiny (mgmt_seg) -- LAN DNS, docs/lan-dns-technitium/";
  and immediately after the line starting "export TF_VAR_lab_ip_technitium=":
  export TF_VAR_lab_ip_technitium_tiny='192.168.20.17'.
  (2) In terraform/lxc/variables.tf, directly after the closing brace of
  variable "lab_ip_technitium", add a blank line and: variable
  "lab_ip_technitium_tiny" { description = "Technitium cluster secondary
  (pve-tiny) IPv4 address"  type = string  default = "" } formatted like its
  neighbours. (3) In terraform/lxc/main.tf's stack_template_vars, directly
  after the lab_ip_technitium line, add
  lab_ip_technitium_tiny = var.lab_ip_technitium_tiny, then run
  terraform fmt on both .tf files.

scope:
  allowed_paths:
    - .env
    - terraform/lxc/variables.tf
    - terraform/lxc/main.tf
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Changing any existing value in .env"
    - "terraform init/plan/apply"

gates:
  - id: env-vars
    cmd: "test $(grep -cE \"^export (TF_VAR_lab_ip_technitium_tiny|LAB_IP_TECHNITIUM_TINY)='192.168.20.17'\" .env) -eq 2"
    expect: "exit 0"
    critical: true
  - id: tf-wired
    cmd: "grep -q 'variable \"lab_ip_technitium_tiny\"' terraform/lxc/variables.tf && grep -qE '^\\s+lab_ip_technitium_tiny\\s+= var.lab_ip_technitium_tiny$' terraform/lxc/main.tf"
    expect: "exit 0"
    critical: true
  - id: fmt
    cmd: "terraform fmt -check terraform/lxc/main.tf terraform/lxc/variables.tf"
    expect: "exit 0"
    critical: true
```

### lan-dns-06-stack-files

```yaml
id: lan-dns-06-stack-files
title: Create technitium-tiny-stack's stack.yaml, contract, and pve-tiny env dir
depends_on: [lan-dns-05-ip-wiring]

change: >
  Create terraform/lxc/stacks/technitium-tiny-stack/stack.yaml and
  terraform/lxc/stacks/technitium-tiny-stack/STACK_CONTRACT.md with exactly
  the literal content (with its 3-space indent stripped) in "Literal content: technitium-tiny-stack files";
  copy terraform/lxc/environments/pve-tiny/cse-panel-stack/terragrunt.hcl
  byte-for-byte to terraform/lxc/environments/pve-tiny/technitium-tiny-stack/terragrunt.hcl;
  and in terraform/lxc/network/pve-tiny.yaml add, as the last item of
  zones.mgmt_seg.containers, the line
  - "technitium-tiny-stack (VMID 20017) — 192.168.20.17 — LAN DNS cluster secondary, docs/lan-dns-technitium/plan.md"
  indented to match the existing cse-panel-stack item.

scope:
  allowed_paths:
    - terraform/lxc/stacks/technitium-tiny-stack/
    - terraform/lxc/environments/pve-tiny/technitium-tiny-stack/terragrunt.hcl
    - terraform/lxc/network/pve-tiny.yaml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Creating inventory.yml or network-sdn-vars.yml by hand (Terraform generates them)"
    - "terragrunt init/plan/apply"

gates:
  - id: metadata-valid
    cmd: "bash -c '! python3 terraform/lxc/validate-stack-metadata.py --check-contract-docs --check-contract-sections 2>&1 | grep -q technitium-tiny-stack'"
    expect: "exit 0"
    critical: true
  - id: network-yaml-parses
    cmd: "python3 -c \"import yaml;z=yaml.safe_load(open('terraform/lxc/network/pve-tiny.yaml'));assert any('technitium-tiny-stack' in c for c in z['zones']['mgmt_seg']['containers'])\""
    expect: "exit 0"
    critical: true
  - id: terragrunt-copied
    cmd: "cmp terraform/lxc/environments/pve-tiny/cse-panel-stack/terragrunt.hcl terraform/lxc/environments/pve-tiny/technitium-tiny-stack/terragrunt.hcl"
    expect: "exit 0"
    critical: true
```

#### Literal content: technitium-tiny-stack files

`terraform/lxc/stacks/technitium-tiny-stack/stack.yaml`:

   ```yaml
   # Technitium DNS Server — cluster secondary on pve-tiny (mgmt_seg).
   # Second LAN resolver alongside technitium-stack on pve; inherits settings,
   # blocklists and apps through Technitium clustering and the lab/reverse
   # zones through zone transfer. docs/lan-dns-technitium/plan.md.
   hostname: technitium-tiny-stack
   ip_address: "${lab_ip_technitium_tiny}/24"
   gateway: "${lab_gw_mgmt}"
   dns_server: "${lab_gw_mgmt}"
   network:
     zone: mgmt_seg
   vmid: 20017
   cores: 1
   memory: 2048
   swap: 1024
   rootfs_size: 12
   storage_profile: platform-default
   docker_storage_size: "6G"
   template_name: "debian-13.1-2-docker-template.tar.gz"
   tags:
     - technitium-tiny-stack
     - dns
     - core-services
     - infrastructure
     - docker
   # Empty for the same reason as cse-panel-stack: no precedent on pve-tiny
   # for a depends_on entry naming a stack on a different physical node.
   depends_on: []
   provides:
     - service: dns-resolver
       port: 53
       protocol: tcp
     - service: dns-resolver-udp
       port: 53
       protocol: udp
     - service: technitium-cluster-https
       port: 53443
       protocol: tcp
   ansible_playbook: "deploy-technitium-tiny-stack"
   deployment_tier: platform
   portainer_agent: false

   portainer_server_ip: "${lab_ip_portainer}"
   registry_host: "{{ lookup('env', 'LAB_IP_HARBOR') | mandatory('LAB_IP_HARBOR env var is required') }}"
   apt_cacher_host: "${lab_ip_apt_cacher}"
   ```

`terraform/lxc/stacks/technitium-tiny-stack/STACK_CONTRACT.md`:

   ```markdown
   # technitium-tiny-stack — Stack Contract

   ## Purpose

   Second LAN DNS resolver, on `pve-tiny`, so LAN DNS survives `pve` being
   down. Technitium cluster **secondary** of `technitium-stack` (the
   primary, on `pve`). See `docs/lan-dns-technitium/plan.md`.

   ## Network

   | Field | Value |
   |---|---|
   | Node | `pve-tiny` |
   | Zone | `mgmt_seg` |
   | IP | `${lab_ip_technitium_tiny}/24` (`192.168.20.17`) |
   | Gateway | `${lab_gw_mgmt}` |
   | VMID | 20017 |

   ## Inputs

   | Input | Source | Notes |
   |---|---|---|
   | `LAB_IP_TECHNITIUM_TINY` | env var | **Mandatory.** This node's IP |
   | `LAB_IP_TECHNITIUM` | env var | **Mandatory.** The primary's IP (zone-transfer source, cluster primary) |
   | `TECHNITIUM_ADMIN_PASSWORD` | env var (secret) | **Mandatory.** Same admin password as the primary; clustering syncs users from the primary after join |
   | `LAB_DOMAIN` | env var | Defaults to `lab.gibbsgreatly.xyz` |

   ## Provides

   | Service | Port | Protocol | Notes |
   |---|---|---|---|
   | DNS resolver | 53 | UDP + TCP | LAN clients' second resolver (MikroTik DHCP `dns-server`). Serves Secondary copies of the primary's Primary zones |
   | Web console / REST API | 5380 | TCP | Direct by IP only; no Traefik route |
   | Cluster HTTPS | 53443 | TCP | Technitium cluster sync with the primary (self-signed, enabled automatically on cluster join) |

   `stack.yaml` service identifiers: `dns-resolver` (tcp/53), `dns-resolver-udp` (udp/53), `technitium-cluster-https` (tcp/53443).

   ## Dependencies

   - `technitium-stack` (pve) — cluster primary and zone-transfer source.
     Cross-node, so not in `stack.yaml`'s `depends_on`.
   - Harbor (`registry_host`) for the Technitium image pull.
   - `apt-cacher-stack` for package cache during host provisioning.

   ## Persistent State

   | Path | Storage | Contents |
   |---|---|---|
   | Docker named volume `technitium-config` | Docker volume | Not a source of truth: settings/blocklists/apps come from the cluster primary, zones from zone transfer. A rebuild re-joins the cluster and re-transfers zones. |

   ## What Must Not Be Edited Casually

   - Settings, Allowed, Blocked and Apps are read-only here — change them on
     the primary (`configure-technitium-lan-resolver.yml`).
   - `network_mode: host` is deliberate (see the plan's design decisions);
     do not copy it to other stacks.
   - The image tag must equal `deploy-technitium-stack.yml`'s
     `technitium_image_tag` — cluster nodes must run the same version.
   ```

### lan-dns-07-deploy-playbook

```yaml
id: lan-dns-07-deploy-playbook
title: Add deploy-technitium-tiny-stack.yml
depends_on: [lan-dns-06-stack-files]

change: >
  Create terraform/lxc/ansible/playbooks/deploy-technitium-tiny-stack.yml.
  Its first play is a byte-for-byte copy of the "Configure Docker base" play
  (the first play, including its handlers) from deploy-technitium-stack.yml.
  After it, append exactly the literal content (with its 3-space indent stripped) in "Literal content:
  deploy-technitium-tiny-stack.yml (after the Docker base play)".

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-technitium-tiny-stack.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running the playbook"

gates:
  - id: syntax-check
    cmd: "bash -c 'cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/deploy-technitium-tiny-stack.yml'"
    expect: "exit 0"
    critical: true
  - id: same-image-tag
    cmd: "test \"$(grep -h 'technitium_image_tag:' terraform/lxc/ansible/playbooks/deploy-technitium-stack.yml terraform/lxc/ansible/playbooks/deploy-technitium-tiny-stack.yml | sort -u | wc -l)\" -eq 1"
    expect: "exit 0"
    critical: true
```

#### Literal content: deploy-technitium-tiny-stack.yml (after the Docker base play)

   ```yaml
   - name: Deploy Technitium DNS Server (cluster secondary)
     hosts: all
     become: true
     gather_facts: false

     vars:
       technitium_compose_dir: /opt/technitium-stack
       technitium_certs_dir: /opt/technitium-stack/certs
       technitium_combined_ca_bundle: /opt/technitium-stack/certs/combined-ca.crt
       # Must equal deploy-technitium-stack.yml's value: cluster nodes run the
       # same Technitium version.
       technitium_image_tag: "15.2.0"
       effective_registry_host: "{{ lookup('env', 'LAB_FQDN_HARBOR') | default(registry_host, true) | mandatory('LAB_FQDN_HARBOR env var or registry_host inventory var is required') }}"
       lab_domain: "{{ lookup('env', 'LAB_DOMAIN') | default('lab.gibbsgreatly.xyz', true) }}"
       technitium_admin_password: "{{ lookup('env', 'TECHNITIUM_ADMIN_PASSWORD') | mandatory('TECHNITIUM_ADMIN_PASSWORD env var is not set') }}"
       technitium_ip: "{{ lookup('env', 'LAB_IP_TECHNITIUM_TINY') | mandatory('LAB_IP_TECHNITIUM_TINY env var is required') }}"

     tasks:
       - name: Create Technitium compose directory
         ansible.builtin.file:
           path: "{{ technitium_compose_dir }}"
           state: directory
           mode: "0750"

       - name: Write compose secrets env file
         ansible.builtin.copy:
           dest: "{{ technitium_compose_dir }}/.env"
           mode: "0600"
           content: |
             REGISTRY_HOST={{ effective_registry_host }}
             DNS_SERVER_ADMIN_PASSWORD={{ technitium_admin_password }}
         no_log: true

       - name: Create Technitium certs directory
         ansible.builtin.file:
           path: "{{ technitium_certs_dir }}"
           state: directory
           mode: "0755"

       - name: Build Technitium combined CA bundle
         ansible.builtin.shell: |
           set -euo pipefail
           cat /etc/ssl/certs/ca-certificates.crt > {{ technitium_combined_ca_bundle }}
           if [[ -f /usr/local/share/ca-certificates/homelab-root.crt ]]; then
             cat /usr/local/share/ca-certificates/homelab-root.crt >> {{ technitium_combined_ca_bundle }}
           fi
         args:
           executable: /bin/bash
         changed_when: true

       - name: Write Technitium compose definition
         ansible.builtin.copy:
           dest: "{{ technitium_compose_dir }}/docker-compose.yml"
           mode: "0640"
           content: |
             services:
               technitium:
                 image: "{{ effective_registry_host }}/dockerhub/technitium/dns-server:{{ technitium_image_tag }}"
                 container_name: technitium
                 restart: unless-stopped
                 env_file: .env
                 environment:
                   # Hostname part becomes technitium-tiny.cluster.<lab_domain>
                   # when this node joins the cluster.
                   DNS_SERVER_DOMAIN: "technitium-tiny.{{ lab_domain }}"
                   DNS_SERVER_ADMIN_USERNAME: admin
                   DNS_SERVER_PREFER_IPV6: "false"
                   SSL_CERT_FILE: /etc/ssl/certs/combined-ca.crt
                 # network_mode: host -- same single-NIC/single-container
                 # reasoning as technitium-stack (docs/dhcp-refactor/decisions.md
                 # Decision 5); here it also lets clustering register and
                 # serve 53443 on the LXC's real IP. docs/lan-dns-technitium/plan.md.
                 network_mode: host
                 volumes:
                   - technitium-config:/etc/dns
                   - ./certs/combined-ca.crt:/etc/ssl/certs/combined-ca.crt:ro

             volumes:
               technitium-config:
         register: technitium_compose_definition

       - name: Validate Technitium compose configuration
         ansible.builtin.command:
           cmd: docker compose -f "{{ technitium_compose_dir }}/docker-compose.yml" config -q
           chdir: "{{ technitium_compose_dir }}"
         changed_when: false
         when: not ansible_check_mode

       - name: Start Technitium via compose
         community.docker.docker_compose_v2:
           project_src: "{{ technitium_compose_dir }}"
           state: present
           recreate: >-
             {{
               'always'
               if (docker_daemon_config.changed | default(false)
                   or technitium_compose_definition.changed | default(false))
               else 'auto'
             }}
           remove_orphans: true
         when: not ansible_check_mode

       - name: Wait for Technitium web console to respond
         ansible.builtin.uri:
           url: "http://{{ technitium_ip }}:5380/api/user/session/get"  # nosonar: ansible:S5332 — Technitium admin API, private mgmt_seg only
           method: GET
           status_code: [200, 401, 400]
         register: technitium_console_ready
         retries: 30
         delay: 3
         until: technitium_console_ready is success or technitium_console_ready.status in [401, 400]
         when: not ansible_check_mode

       - name: Verify recursive query for github.com
         ansible.builtin.command: dig @{{ technitium_ip }} +short github.com A
         register: technitium_recursion_test
         check_mode: false
         changed_when: false
         retries: 10
         delay: 3
         until: (technitium_recursion_test.stdout | default('')) | length > 0

   - name: Enroll this host as a Wazuh agent
     hosts: all
     become: true
     gather_facts: false
     vars:
       wazuh_agent_fim_paths:
         - /opt/technitium-stack
       wazuh_agent_docker_monitoring_enabled: true
     roles:
       - wazuh_agent

   - name: Enable unattended security updates
     hosts: all
     become: true
     gather_facts: false
     roles:
       - unattended_upgrades

   - name: Replicate the primary's zones to this node (docs/lan-dns-technitium/)
     ansible.builtin.import_playbook: configure-technitium-zone-replication.yml
   ```

### lan-dns-08-replication-playbook

```yaml
id: lan-dns-08-replication-playbook
title: Add configure-technitium-zone-replication.yml
depends_on: [lan-dns-07-deploy-playbook]

change: >
  Create terraform/lxc/ansible/playbooks/configure-technitium-zone-replication.yml
  with exactly the literal content (with its 3-space indent stripped) in "Literal content:
  configure-technitium-zone-replication.yml".

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/configure-technitium-zone-replication.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running the playbook"

gates:
  - id: syntax-check
    cmd: "bash -c 'cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/configure-technitium-zone-replication.yml'"
    expect: "exit 0"
    critical: true
  - id: tiny-deploy-still-parses
    cmd: "bash -c 'cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/deploy-technitium-tiny-stack.yml'"
    expect: "exit 0"
    critical: true
```

#### Literal content: configure-technitium-zone-replication.yml

   ```yaml
   ---
   # Replicates technitium-stack's (primary, pve) zones to technitium-tiny-stack
   # (secondary, pve-tiny). docs/lan-dns-technitium/plan.md, Phase 2.
   #
   # - Primary zones (lab + reverse zones): classic zone transfer + NOTIFY to
   #   Secondary zones on this node. NOT the cluster catalog, because the
   #   cluster would then manage their NS/SOA and deploy-technitium-stack.yml
   #   rewrites both on every run.
   # - Forwarder zones: added to the cluster catalog once the cluster exists
   #   (deploy-technitium-stack.yml never touches Forwarder zones).
   #
   # Runs on the secondary's inventory; the primary's API is reached over
   # mgmt_seg. Imported at the end of deploy-technitium-tiny-stack.yml.

   - name: Replicate primary zones to the secondary
     hosts: all
     become: false
     gather_facts: false

     vars:
       technitium_primary_ip: "{{ lookup('env', 'LAB_IP_TECHNITIUM') | mandatory('LAB_IP_TECHNITIUM env var is required') }}"
       technitium_secondary_ip: "{{ lookup('env', 'LAB_IP_TECHNITIUM_TINY') | mandatory('LAB_IP_TECHNITIUM_TINY env var is required') }}"
       technitium_admin_password: "{{ lookup('env', 'TECHNITIUM_ADMIN_PASSWORD') | mandatory('TECHNITIUM_ADMIN_PASSWORD env var is not set') }}"
       technitium_primary_api: "http://{{ technitium_primary_ip }}:5380/api"  # nosonar: ansible:S5332 — Technitium admin API, private mgmt_seg only
       technitium_secondary_api: "http://{{ technitium_secondary_ip }}:5380/api"  # nosonar: ansible:S5332 — Technitium admin API, private mgmt_seg only
       technitium_cluster_domain: "cluster.{{ lookup('env', 'LAB_DOMAIN') | default('lab.gibbsgreatly.xyz', true) }}"

     tasks:
       - name: Log in to the primary
         ansible.builtin.uri:
           url: "{{ technitium_primary_api }}/user/login?user=admin&pass={{ technitium_admin_password | urlencode }}"
           method: GET
           return_content: true
         register: repl_primary_login
         retries: 10
         delay: 3
         until: repl_primary_login.status == 200
         no_log: true

       - name: Log in to the secondary
         ansible.builtin.uri:
           url: "{{ technitium_secondary_api }}/user/login?user=admin&pass={{ technitium_admin_password | urlencode }}"
           method: GET
           return_content: true
         register: repl_secondary_login
         retries: 10
         delay: 3
         until: repl_secondary_login.status == 200
         no_log: true

       - name: Extract tokens
         ansible.builtin.set_fact:
           repl_primary_token: "{{ (repl_primary_login.content | from_json).token }}"
           repl_secondary_token: "{{ (repl_secondary_login.content | from_json).token }}"
         no_log: true

       - name: List primary zones
         ansible.builtin.uri:
           url: "{{ technitium_primary_api }}/zones/list?token={{ repl_primary_token }}"
           method: GET
           return_content: true
         register: repl_primary_zones_raw
         no_log: true

       # Built-in zones are flagged internal; zones at or under the cluster
       # domain are synced by the cluster itself.
       - name: Select zones to replicate
         ansible.builtin.set_fact:
           repl_primary_zone_names: >-
             {{
               repl_zones
               | selectattr('type', 'equalto', 'Primary')
               | rejectattr('name', 'in', repl_internal_zone_names)
               | map(attribute='name')
               | reject('equalto', technitium_cluster_domain)
               | reject('search', '\.' ~ (technitium_cluster_domain | regex_escape) ~ '$')
               | list
             }}
           repl_forwarder_zone_names: >-
             {{
               repl_zones
               | selectattr('type', 'equalto', 'Forwarder')
               | rejectattr('name', 'in', repl_internal_zone_names)
               | map(attribute='name') | list
             }}
         vars:
           repl_zones: "{{ (repl_primary_zones_raw.content | from_json).response.zones }}"
           repl_internal_zone_names: "{{ repl_zones | selectattr('internal', 'defined') | selectattr('internal') | map(attribute='name') | list }}"

       - name: Read zone-transfer options of each primary zone
         ansible.builtin.uri:
           url: "{{ technitium_primary_api }}/zones/options/get?zone={{ item | urlencode }}&token={{ repl_primary_token }}"
           method: GET
           return_content: true
         register: repl_zone_options
         loop: "{{ repl_primary_zone_names }}"
         no_log: true

       - name: Allow transfer to and notify the secondary
         ansible.builtin.uri:
           url: "{{ technitium_primary_api }}/zones/options/set?zone={{ item.item | urlencode }}&zoneTransfer=UseSpecifiedNetworkACL&zoneTransferNetworkACL={{ technitium_secondary_ip }}&notify=SpecifiedNameServers&notifyNameServers={{ technitium_secondary_ip }}&token={{ repl_primary_token }}"
           method: POST
           return_content: true
           status_code: [200]
         register: repl_zone_options_set
         changed_when: true
         failed_when: (repl_zone_options_set.content | from_json).status | default('') != 'ok'
         loop: "{{ repl_zone_options.results }}"
         loop_control:
           label: "{{ item.item }}"
         when: >-
           (o.zoneTransfer | default('')) != 'UseSpecifiedNetworkACL'
           or (o.zoneTransferNetworkACL | default([]) or []) != [technitium_secondary_ip]
           or (o.notify | default('')) != 'SpecifiedNameServers'
           or (o.notifyNameServers | default([]) or []) != [technitium_secondary_ip]
         vars:
           o: "{{ (item.content | from_json).response }}"
         no_log: true

       - name: List secondary zones
         ansible.builtin.uri:
           url: "{{ technitium_secondary_api }}/zones/list?token={{ repl_secondary_token }}"
           method: GET
           return_content: true
         register: repl_secondary_zones_raw
         no_log: true

       - name: Refuse to shadow a replicated zone with a different local type
         ansible.builtin.assert:
           that:
             - >-
               (repl_secondary_zones_raw.content | from_json).response.zones
               | selectattr('name', 'in', repl_primary_zone_names)
               | rejectattr('type', 'equalto', 'Secondary')
               | list | length == 0
           fail_msg: >-
             The secondary has a non-Secondary zone with the same name as a
             primary zone; delete it on the secondary before re-running.

       - name: Create Secondary zones for missing primary zones
         ansible.builtin.uri:
           url: "{{ technitium_secondary_api }}/zones/create?zone={{ item | urlencode }}&type=Secondary&primaryNameServerAddresses={{ technitium_primary_ip }}&zoneTransferProtocol=Tcp&token={{ repl_secondary_token }}"
           method: POST
           return_content: true
           status_code: [200]
         register: repl_secondary_create
         changed_when: true
         failed_when: (repl_secondary_create.content | from_json).status | default('') != 'ok'
         loop: "{{ repl_primary_zone_names }}"
         when: item not in (repl_secondary_zones_raw.content | from_json).response.zones | map(attribute='name') | list
         no_log: true

       - name: Read cluster state on the primary
         ansible.builtin.uri:
           url: "{{ technitium_primary_api }}/admin/cluster/state?token={{ repl_primary_token }}"
           method: GET
           return_content: true
         register: repl_cluster_state
         no_log: true

       - name: Add Forwarder zones to the cluster catalog
         ansible.builtin.uri:
           url: "{{ technitium_primary_api }}/zones/options/set?zone={{ item | urlencode }}&catalog={{ ('cluster-catalog.' ~ (repl_cluster_state.content | from_json).response.clusterDomain) | urlencode }}&token={{ repl_primary_token }}"
           method: POST
           return_content: true
           status_code: [200]
         register: repl_catalog_set
         changed_when: false
         failed_when: (repl_catalog_set.content | from_json).status | default('') != 'ok'
         loop: "{{ repl_forwarder_zone_names }}"
         when: (repl_cluster_state.content | from_json).response.clusterInitialized | default(false) | bool
         no_log: true

       - name: Compare SOA serials, primary vs secondary
         ansible.builtin.shell: |
           set -euo pipefail
           p=$(dig @{{ technitium_primary_ip }} +short SOA {{ item }} | awk '{print $3}')
           s=$(dig @{{ technitium_secondary_ip }} +short SOA {{ item }} | awk '{print $3}')
           test -n "$p" && test "$p" = "$s"
         args:
           executable: /bin/bash
         register: repl_serial_check
         loop: "{{ repl_primary_zone_names }}"
         changed_when: false
         check_mode: false
         retries: 12
         delay: 10
         until: repl_serial_check.rc == 0
   ```

### Operator: create technitium-tiny-stack on pve-tiny

1. Read-only collision check, then preflight/approval:
   `ping -c1 -W1 192.168.20.17` must fail, and VMID `20017` must not
   appear in pve-tiny's `pct list` (read-only API query through
   `./with-secrets-prod-tiny`, as in the media-stack-lab precedent).
2. Deploy (Terraform creates the LXC, then Ansible runs
   `deploy-technitium-tiny-stack.yml`; the replication import runs too but
   creates nothing cluster-related yet — the catalog task is skipped until
   the cluster exists):
   ```bash
   export TASK_APPROVAL="lan-dns-technitium-tiny-deploy"
   ./with-secrets-prod-tiny scripts/provision.sh --stack technitium-tiny-stack
   ```
   (If `ansible-playbook` inside it hits a blocking-IO error from the
   Bash tool, wrap with `script -qec '…' /dev/null`, as for
   `cse-panel-stack`.)

### Operator: form the cluster (one-time, cluster domain is permanent)

Production mutation on both nodes. Do this from the UIs or with these
exact API calls (tokens from `/api/user/login`; `$PW` =
`TECHNITIUM_ADMIN_PASSWORD` via `./with-secrets-prod bash -c`):

1. On the **primary**, initialize (auto-enables HTTPS 53443 with a
   self-signed cert and renames the node to `<hostname part of its
   current server domain>.cluster.lab.gibbsgreatly.xyz` — likely
   `tech.cluster.lab.gibbsgreatly.xyz`, since the container was first
   started with `DNS_SERVER_DOMAIN=tech.lab.gibbsgreatly.xyz`; check
   Settings > General first if the name matters to you):
   `POST http://192.168.20.15:5380/api/admin/cluster/init?clusterDomain=cluster.lab.gibbsgreatly.xyz&primaryNodeIpAddresses=192.168.20.15&token=$TP`
2. On the **secondary**, join:
   `POST http://192.168.20.17:5380/api/admin/cluster/initJoin?secondaryNodeIpAddresses=192.168.20.17&primaryNodeUrl=https%3A%2F%2F192.168.20.15%3A53443%2F&primaryNodeIpAddress=192.168.20.15&ignoreCertificateErrors=true&primaryNodeUsername=admin&primaryNodePassword=$PW&token=$TS`
   (`ignoreCertificateErrors=true` is the documented option for a
   self-signed primary on a private network.)
3. Confirm Technitium's Authentik OIDC login at
   `https://technitium.lab.gibbsgreatly.xyz` still works (node rename is
   the one change that could plausibly touch it).
4. Re-run the replication playbook so the Forwarder zones join the
   catalog:
   ```bash
   export TASK_APPROVAL="lan-dns-technitium-replication"
   ./with-secrets-prod-tiny ansible-playbook \
     -i terraform/lxc/environments/pve-tiny/technitium-tiny-stack/inventory.yml \
     terraform/lxc/ansible/playbooks/configure-technitium-zone-replication.yml
   ```

Rollback: `POST /api/admin/cluster/secondary/leave` on the secondary, then
`/api/admin/cluster/primary/delete` on the primary. The primary keeps all
its zones and settings either way.

### lan-dns-09-verify-secondary

```yaml
id: lan-dns-09-verify-secondary
title: Verify the secondary answers identically to the primary
depends_on: [lan-dns-08-replication-playbook]   # and the two operator sections above

change: >
  No file edits. Run the gates from the workstation and record results in
  docs/lan-dns-technitium/README.md's hand-back log.

scope:
  allowed_paths:
    - docs/lan-dns-technitium/README.md
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any Technitium API write or playbook run"

gates:
  - id: blocklists-synced
    cmd: "test \"$(dig +short @192.168.20.17 doubleclick.net A)\" = 0.0.0.0"
    expect: "exit 0"
    critical: true
  - id: lab-zone-replicated
    cmd: "test \"$(dig +short @192.168.20.17 traefik.lab.gibbsgreatly.xyz A)\" = 192.168.30.10"
    expect: "exit 0"
    critical: true
  - id: lab-serial-matches
    cmd: "test \"$(dig +short @192.168.20.17 SOA lab.gibbsgreatly.xyz | awk '{print $3}')\" = \"$(dig +short @192.168.20.15 SOA lab.gibbsgreatly.xyz | awk '{print $3}')\""
    expect: "exit 0"
    critical: true
  - id: forwarders-synced
    cmd: "test \"$(dig +short @192.168.20.17 pve.gibbsgreatly.xyz A)\" = \"$(dig +short @192.168.1.1 pve.gibbsgreatly.xyz A)\""
    expect: "exit 0"
    critical: true
  - id: public-over-tcp
    cmd: "dig +tcp @192.168.20.17 github.com A | grep -q 'status: NOERROR'"
    expect: "exit 0"
    critical: true
  - id: cluster-port
    cmd: "curl -sk -o /dev/null -w '%{http_code}' https://192.168.20.17:53443/ | grep -qE '^(200|302|401|404)$'"
    expect: "exit 0"
    critical: false
```

---

## Phase 3 — Point the LAN at Technitium

### lan-dns-10-mikrotik-playbook

```yaml
id: lan-dns-10-mikrotik-playbook
title: Add mikrotik-lan-dns-resolver.yml (cutover + rollback in one playbook)
depends_on: [lan-dns-05-ip-wiring]

change: >
  Create ansible/00-initial-setup/mikrotik-lan-dns-resolver.yml with exactly
  the literal content (with its 3-space indent stripped) in "Literal content: mikrotik-lan-dns-resolver.yml".

scope:
  allowed_paths:
    - ansible/00-initial-setup/mikrotik-lan-dns-resolver.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running the playbook"

gates:
  - id: syntax-check
    cmd: "ansible-playbook --syntax-check -i localhost, ansible/00-initial-setup/mikrotik-lan-dns-resolver.yml"
    expect: "exit 0"
    critical: true
  - id: both-modes
    cmd: "grep -q \"lan_dns_mode | default('technitium')\" ansible/00-initial-setup/mikrotik-lan-dns-resolver.yml && grep -q \"'pihole'\" ansible/00-initial-setup/mikrotik-lan-dns-resolver.yml"
    expect: "exit 0"
    critical: true
```

#### Literal content: mikrotik-lan-dns-resolver.yml

   ```yaml
   ---
   # mikrotik-lan-dns-resolver.yml
   #
   # Chooses which resolvers LAN (bridgeLocal) clients are told to use.
   # docs/lan-dns-technitium/plan.md, Phase 3.
   #
   #   lan_dns_mode=technitium (default): DHCP hands out both Technitium
   #     nodes; IPv6 RA stops advertising DNS (clients resolve over IPv4).
   #   lan_dns_mode=pihole: rollback -- DHCP hands out argon-02 only (the
   #     pre-cutover live value) and RA advertises the Pi-hole ULAs again.
   #
   # Usage (run from the repo root):
   #   ./with-secrets ansible-playbook ansible/00-initial-setup/mikrotik-lan-dns-resolver.yml
   #   ./with-secrets ansible-playbook ansible/00-initial-setup/mikrotik-lan-dns-resolver.yml -e lan_dns_mode=pihole
   #
   # Existing leases keep their old DNS until renewal (MikroTik lease-time is
   # 30m today), so the change reaches every client within ~30 minutes.

   - name: Set the LAN's advertised DNS resolvers
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
       lan_dns_effective_mode: "{{ lan_dns_mode | default('technitium') }}"
       lan_dns_technitium_ips:
         - "{{ lookup('env', 'LAB_IP_TECHNITIUM') | mandatory('LAB_IP_TECHNITIUM env var is required') }}"
         - "{{ lookup('env', 'LAB_IP_TECHNITIUM_TINY') | mandatory('LAB_IP_TECHNITIUM_TINY env var is required') }}"
       lan_dns_modes:
         technitium:
           dhcp_dns_server: "{{ lan_dns_technitium_ips | join(',') }}"
           nd_advertise_dns: "no"
         pihole:
           dhcp_dns_server: "192.168.1.23"
           nd_advertise_dns: "yes"
       lan_dns_target: "{{ lan_dns_modes[lan_dns_effective_mode] }}"
       lan_dns_subnet: "192.168.1.0/24"

     pre_tasks:
       - name: Assert a known mode was requested
         ansible.builtin.assert:
           that:
             - lan_dns_effective_mode in ['technitium', 'pihole']

       - name: Assert MikroTik credentials are set
         ansible.builtin.assert:
           that:
             - mikrotik_password | length > 0
             - mikrotik_user | length > 0

       - name: Refuse to cut over unless both Technitium nodes block and resolve
         ansible.builtin.shell: |
           set -euo pipefail
           test "$(dig +short @{{ item }} doubleclick.net A)" = 0.0.0.0
           dig @{{ item }} github.com A | grep -q 'status: NOERROR'
         args:
           executable: /bin/bash
         loop: "{{ lan_dns_technitium_ips }}"
         changed_when: false
         when: lan_dns_effective_mode == 'technitium'

     tasks:
       - name: Fetch DHCP networks
         ansible.builtin.uri:
           url: "{{ mikrotik_rest_base_url }}/ip/dhcp-server/network"
           method: GET
           user: "{{ mikrotik_user }}"
           password: "{{ mikrotik_password }}"
           force_basic_auth: true
           validate_certs: false  # nosonar: ansible:S4830 — MikroTik self-signed cert; HTTPS traffic still encrypted; private network
           return_content: true
         register: lan_dns_networks
         no_log: true

       - name: Select the bridgeLocal DHCP network
         ansible.builtin.set_fact:
           lan_dns_network: "{{ lan_dns_networks.json | selectattr('address', 'equalto', lan_dns_subnet) | first }}"

       - name: Set the DHCP dns-server option
         ansible.builtin.uri:
           url: "{{ mikrotik_rest_base_url }}/ip/dhcp-server/network/{{ lan_dns_network['.id'] }}"
           method: PATCH
           body_format: json
           body:
             dns-server: "{{ lan_dns_target.dhcp_dns_server }}"
           user: "{{ mikrotik_user }}"
           password: "{{ mikrotik_password }}"
           force_basic_auth: true
           validate_certs: false  # nosonar: ansible:S4830 — MikroTik self-signed cert; HTTPS traffic still encrypted; private network
           status_code: [200]
         changed_when: true
         when: lan_dns_network['dns-server'] | default('') != lan_dns_target.dhcp_dns_server
         no_log: true

       - name: Fetch IPv6 ND entries
         ansible.builtin.uri:
           url: "{{ mikrotik_rest_base_url }}/ipv6/nd"
           method: GET
           user: "{{ mikrotik_user }}"
           password: "{{ mikrotik_password }}"
           force_basic_auth: true
           validate_certs: false  # nosonar: ansible:S4830 — MikroTik self-signed cert; HTTPS traffic still encrypted; private network
           return_content: true
         register: lan_dns_nd
         no_log: true

       - name: Select the bridgeLocal ND entry
         ansible.builtin.set_fact:
           lan_dns_nd_entry: "{{ lan_dns_nd.json | selectattr('interface', 'equalto', 'bridgeLocal') | first }}"

       # The ND entry's dns list (fd00::22,fd00::23) is left in place so the
       # pihole mode only has to flip advertise-dns back on.
       - name: Set RA DNS advertisement
         ansible.builtin.uri:
           url: "{{ mikrotik_rest_base_url }}/ipv6/nd/{{ lan_dns_nd_entry['.id'] }}"
           method: PATCH
           body_format: json
           body:
             advertise-dns: "{{ lan_dns_target.nd_advertise_dns }}"
           user: "{{ mikrotik_user }}"
           password: "{{ mikrotik_password }}"
           force_basic_auth: true
           validate_certs: false  # nosonar: ansible:S4830 — MikroTik self-signed cert; HTTPS traffic still encrypted; private network
           status_code: [200]
         changed_when: true
         when: lan_dns_nd_entry['advertise-dns'] | default('') != lan_dns_target.nd_advertise_dns
         no_log: true

       - name: Re-read both objects
         ansible.builtin.uri:
           url: "{{ mikrotik_rest_base_url }}/{{ item }}"
           method: GET
           user: "{{ mikrotik_user }}"
           password: "{{ mikrotik_password }}"
           force_basic_auth: true
           validate_certs: false  # nosonar: ansible:S4830 — MikroTik self-signed cert; HTTPS traffic still encrypted; private network
           return_content: true
         loop:
           - "ip/dhcp-server/network/{{ lan_dns_network['.id'] }}"
           - "ipv6/nd/{{ lan_dns_nd_entry['.id'] }}"
         register: lan_dns_after
         no_log: true

       - name: Assert the router now advertises the requested resolvers
         ansible.builtin.assert:
           that:
             - lan_dns_after.results[0].json['dns-server'] == lan_dns_target.dhcp_dns_server
             - lan_dns_after.results[1].json['advertise-dns'] == lan_dns_target.nd_advertise_dns
   ```

### Operator: cutover

Preflight/approval (MikroTik is production), then:

```bash
export TASK_APPROVAL="lan-dns-cutover"
./with-secrets ansible-playbook ansible/00-initial-setup/mikrotik-lan-dns-resolver.yml
```

Then renew the workstation's lease (`nmcli device reapply <iface>` or
reconnect) and confirm `resolvectl dns` shows `192.168.20.15
192.168.20.17` and no `fd00::` address; spot-check a phone on WiFi (ads
blocked in a browser, and a LAN name like `nas.gibbsgreatly.xyz`
resolves). **Rollback** at any point:
`./with-secrets ansible-playbook ansible/00-initial-setup/mikrotik-lan-dns-resolver.yml -e lan_dns_mode=pihole`.

### Operator: 7-day soak

Leave argon-02's Pi-hole running untouched. After 7 days, check its
dashboard "Top Clients" / query log: anything still querying it has a
hardcoded DNS server (DHCP no longer hands it out) and needs manual
reconfiguration before retirement. Also skim Technitium's Query Logs app
and the Dashboard for SERVFAIL spikes and user reports of over-blocking;
add allow entries to `configure-technitium-lan-resolver.yml`, not the UI.

### lan-dns-11-docs-after-cutover

```yaml
id: lan-dns-11-docs-after-cutover
title: Record the cutover in router and network docs
depends_on: [lan-dns-10-mikrotik-playbook]   # and the operator cutover

change: >
  In router/desired-config.md: replace the DNS section bullet
  "**DHCP hands out:** 192.168.1.22, 192.168.1.23 (Pi-holes) ✅" with
  "**DHCP hands out:** 192.168.20.15, 192.168.20.17 (Technitium, pve + pve-tiny) — set by ansible/00-initial-setup/mikrotik-lan-dns-resolver.yml, docs/lan-dns-technitium/";
  and replace the IPv6 bullet beginning "**RA DNS:**" with
  "**RA DNS:** not advertised (advertise-dns=no on bridgeLocal); clients resolve over IPv4 via Technitium. The ND dns list fd00::22,fd00::23 is left configured for rollback only."
  Also update the "Upstream" bullet to "DoH via https://1.1.1.1/dns-query"
  (live value per the 2026-09-28 scrape).

scope:
  allowed_paths:
    - router/desired-config.md
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Editing the Static Leases or WiFi sections"

gates:
  - id: dhcp-line
    cmd: "grep -q 'DHCP hands out:\\*\\* 192.168.20.15, 192.168.20.17' router/desired-config.md"
    expect: "exit 0"
    critical: true
  - id: pihole-line-gone
    cmd: "! grep -q 'DHCP hands out:\\*\\* 192.168.1.22' router/desired-config.md"
    expect: "exit 0"
    critical: true
```

---

## Phase 4 — Retire the Pis (after the soak)

### Operator: decommission

1. Power off argon-02 and argon-01 (`sudo poweroff` on each). Keep the SD
   cards for a month as a last-resort rollback.
2. Remove the router's Pi-specific config (production, approval):
   static DHCP leases for `E4:5F:01:0A:56:E1` / `E4:5F:01:F4:A4:88`,
   static DNS entries `argon-01.lan.local` / `argon-02.lan.local` (A and
   AAAA), and the `fd00::22`/`fd00::23` list on the `bridgeLocal` ND entry
   (only now — it was the rollback target until here). After this, the
   `pihole` mode of `mikrotik-lan-dns-resolver.yml` no longer works.

### lan-dns-12-docs-retire

```yaml
id: lan-dns-12-docs-retire
title: Remove the Pi-holes from router and DHCP-refactor docs
depends_on: [lan-dns-11-docs-after-cutover]   # and the operator decommission

change: >
  In router/desired-config.md delete the argon-01 and argon-02 rows from the
  Static Leases table and the ULA addresses table, and delete the line
  beginning "Pi-holes configured as upstream:". In
  docs/dhcp-refactor/bridgelocal-cutover-packet.md delete the argon-01 and
  argon-02 reservation rows (the table then has 6 reservations; change any
  "8-reservation"/"8 reservations" wording in that file to 6). In
  ansible/00-initial-setup/mikrotik-lan-dns-resolver.yml replace the
  "lan_dns_mode=pihole" header comment lines with a single line
  "#   lan_dns_mode=pihole: no longer usable -- Pis retired (docs/lan-dns-technitium/)."

scope:
  allowed_paths:
    - router/desired-config.md
    - docs/dhcp-refactor/bridgelocal-cutover-packet.md
    - ansible/00-initial-setup/mikrotik-lan-dns-resolver.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Removing the pihole entry from lan_dns_modes (keeps history readable)"

gates:
  - id: no-argon-rows
    cmd: "! grep -qE '^\\| *`?argon-0[12]' router/desired-config.md docs/dhcp-refactor/bridgelocal-cutover-packet.md"
    expect: "exit 0"
    critical: true
  - id: playbook-parses
    cmd: "ansible-playbook --syntax-check -i localhost, ansible/00-initial-setup/mikrotik-lan-dns-resolver.yml"
    expect: "exit 0"
    critical: true
```

---

## Phase 5 — DHCP to Technitium (independent track)

The DHCP migration is already fully planned in `docs/dhcp-refactor/`
(Stages A–D done and validated; Stage E cutover packet drafted, Stage F =
7-day soak). **It does not depend on Phases 0–4 and they don't depend on
it.** The only coupling point is the DHCP scope's DNS-server option: it
must hand out whatever the MikroTik hands out at the moment of the DHCP
cutover. Phase 5 can therefore run before, during, or after the DNS
work — but not in the same change window as the Phase 3 cutover, so a
problem is attributable to one change.

### lan-dns-13-dhcp-dns-option

```yaml
id: lan-dns-13-dhcp-dns-option
title: Decouple the DHCP cutover packet's DNS option from the Pi-holes
depends_on: []

change: >
  (1) Append to docs/dhcp-refactor/decisions.md, before the "## Format"
  heading, the literal "Decision 9" section (with its 3-space indent stripped) in "Literal content: DHCP
  Decision 9". (2) In docs/dhcp-refactor/bridgelocal-cutover-packet.md,
  replace the DNS-server option table row's value and source cells
  ("`192.168.1.22`" and its note) with: value "**read live at execution
  time**: the MikroTik `lan` network's current `dns-server` (`192.168.1.23`
  before docs/lan-dns-technitium/ Phase 3, `192.168.20.15,192.168.20.17`
  after)" and source "decisions.md Decision 9"; and in the checklist line
  "DNS-server option handed out is still `192.168.1.22` (the Pi-hole)"
  replace that text with "DNS-server option handed out matches the value
  the MikroTik handed out immediately before cutover (Decision 9)".

scope:
  allowed_paths:
    - docs/dhcp-refactor/decisions.md
    - docs/dhcp-refactor/bridgelocal-cutover-packet.md
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Editing Decisions 1-8"

gates:
  - id: decision-9
    cmd: "grep -q '^## Decision 9: ' docs/dhcp-refactor/decisions.md && test $(grep -n '^## Decision 9: ' docs/dhcp-refactor/decisions.md | cut -d: -f1) -lt $(grep -n '^## Format' docs/dhcp-refactor/decisions.md | cut -d: -f1)"
    expect: "exit 0"
    critical: true
  - id: stale-dns-gone
    cmd: "! grep -q '192.168.1.22' docs/dhcp-refactor/bridgelocal-cutover-packet.md || grep -c '192.168.1.22' docs/dhcp-refactor/bridgelocal-cutover-packet.md | grep -qx 1"
    expect: "exit 0"
    critical: true
```

(The `stale-dns-gone` gate allows one remaining `192.168.1.22` — the
argon-01 reservation row, which `lan-dns-12` removes later if Phase 4
has run.)

#### Literal content: DHCP Decision 9

   ```markdown
   ## Decision 9: DHCP-assigned DNS follows the LAN resolver, not the Pi-holes (supersedes part of Decision 3)

   Context: Decision 3 kept DHCP-assigned DNS on the Pi-holes because
   Technitium's role was scoped to platform-zone authority, and client-LAN
   ad-blocking would have been new, unevaluated scope. `docs/lan-dns-technitium/`
   now takes that scope on explicitly: two clustered Technitium nodes
   (`192.168.20.15` on pve, `192.168.20.17` on pve-tiny) with Pi-hole-style
   blocklists become the LAN resolver, and the Pis are retired. Separately,
   the packet's recorded value (`192.168.1.22`) was already stale: that Pi
   stopped answering DNS and the MikroTik hands out only `192.168.1.23`
   (live, 2026-09-28/29).

   Decision: the Technitium `bridgeLocal` scope's DNS-server option is set,
   at Stage E execution time, to exactly the MikroTik `lan` network's
   `dns-server` value read immediately before cutover — whichever resolver
   migration state the LAN is in then. The DNS migration and the DHCP
   migration stay independently sequenced; this is their only coupling, and
   it is a value read at execution time, not an ordering constraint. They
   must not share a change window.

   Rationale: keeps Stage E a pure "who issues leases" change with no
   resolver change bundled into it (the same like-for-like principle
   Decision 3 applied), while removing the hard-coded Pi-hole assumption
   that the DNS migration makes wrong. Decision 3's other two bullets
   (migrate `bridgeLocal` first; carry the static leases) stand, except the
   two argon reservations drop out once the Pis are retired.
   ```

### Operator: execute DHCP Stage E/F

Follow `docs/dhcp-refactor/plan.md`'s "Immediate next step" and
`bridgelocal-cutover-packet.md` as written, under the production approval
flow. Two items there are still genuinely open and need an operator
decision before the window (recorded in the packet, not decided here):
the scope's domain-name option (`lan` to match MikroTik's current
`add-dns-entries-suffix`, recommended, since Phase 1 already forwards
`lan` to the router and it would simply move to being Technitium-owned)
and the reverse-zone naming for `1.168.192.in-addr.arpa` — note Phase 1
creates that name as a **Forwarder** zone to the router, so the DHCP
scope's reverse zone requires converting it to a Primary zone at Stage E
(delete the forwarder, let the scope create the Primary), and likewise
for `lan`.

**Newly possible follow-on (not planned here):** with
`technitium-tiny-stack` live, dhcp-refactor's "Deferred: multi-instance
DHCP resiliency" option (MikroTik relays to both nodes, Offer Delay Time
on the standby) has its second box. It still carries the caveats recorded
there (DHCP scopes not cluster-synced — though
`configure-technitium-dhcp-scope-via-api.yml` is config-as-code and could
target both; DNS-update gap when the standby issues leases). Revisit
after Stage F as its own decision.

---

## Follow-ups deliberately out of scope

- **Router-path redundancy for `lab.gibbsgreatly.xyz`.** SDN containers
  resolve through the MikroTik, whose `lab-zone-delegate` FWD rule points
  only at `192.168.20.15`. LAN clients are covered by the secondary
  directly; the router path is not. Whether RouterOS FWD `forward-to`
  accepts a list was not verified — check before planning it.
- **Stale router static records.** Many of the ~67 `*.gibbsgreatly.xyz`
  MikroTik statics point at retired hosts (e.g. the old `192.168.1.4`
  reverse proxy). Cleaning them up, or moving LAN host records into a
  Technitium-owned zone, is separate work.
- **`docs/environment-isolation/`** (moving `technitium-stack` itself to
  the per-environment layout) is unchanged and still open.
- **Pi-hole regex / per-client group policy**, if `lan-dns-01` finds any —
  needs the Advanced Blocking app (see the review point after
  `lan-dns-01`).

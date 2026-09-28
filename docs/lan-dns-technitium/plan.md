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
2. **Pis: cold fallback, then retire.** No Pi-hole config is carried
   over — no local records or custom lists need keeping; Technitium gets
   its own blocklists (Phase 2). `argon-02` keeps running Pi-hole
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
5. **Zones sync through the Technitium cluster** (the repo's zone
   automation is made cluster-compatible in Phase 1, rather than working
   around the cluster with zone transfers).
6. **Observability/security on both nodes:** every DNS query goes to
   Graylog in its own index set (30-day retention); Grafana dashboard but
   **no alerting** (platform-wide alerting stays separate future work);
   LAN devices may reach the Technitium IPs on DNS only (operator
   workstation excepted); DNS rebinding protection on.

## Design decisions derived from research (not operator calls)

- **Sync = Technitium clustering, for config and zones.** Technitium
  v14+ clustering (image `15.2.0` is in use) syncs Settings, Allowed,
  Blocked, Apps and Administration from primary to secondary, and every
  zone that is a member of the cluster catalog. So forwarders,
  blocklists, allow/deny lists, the query-log app and all zones are
  configured once, on the primary. Getting zones into the catalog safely
  requires changing how this repo's automation creates zones and handles
  NS/SOA records; that is Phase 1, and it explains why. DHCP is not
  cluster-synced (known upstream gap, already recorded in
  `docs/dhcp-refactor/decisions.md` Decision 4).
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

- **Observability and security reuse the platform's existing paths.**
  node_exporter (TLS, from `lxc_base`), cAdvisor, rsyslog→Graylog and the
  Wazuh agent are what every stack already gets; Technitium adds its
  native Prometheus endpoint (v15.0+, names `queries_total`,
  `blocked_total`, … — read from the v15.2.0 source, the API docs still
  show pre-15.1 names) and the Log Exporter app for per-query logs. The
  one fleet-wide change is `lan-dns-06` (rsyslog forwards RFC 5424
  structured data), which is byte-identical for every existing message.
  Two clean-ups fall out: the monitoring stack's `coredns` scrape job and
  dashboard still pointed at the destroyed `dns-stack`.

## Failover behavior (what "two synced servers" means here)

Both nodes are **full, independent resolvers** — each one forwards over
DoH, applies the same blocklists, and serves the same lab/reverse zones.
Neither proxies through the other at query time. LAN clients get both IPs
from DHCP and fail over on their own (OS resolvers retry the second
server on timeout; many query both).

| Situation | What still works | What doesn't |
|---|---|---|
| pve (primary) down | tiny answers everything: DoH forwarding, blocking, router-forwarded LAN names, and its Secondary copies of the lab/reverse zones (they keep answering until their SOA expire passes without contact — 30 days for `lab.gibbsgreatly.xyz`, whose SOA the deploy playbook sets; the reverse zones use Technitium's default) | Config changes (settings, allow/block lists, apps) — those are only accepted on the primary. Either wait for pve, or promote tiny to primary if pve is gone for good. Containers resolving `lab` via the MikroTik also fail — the router's FWD rule points only at .20.15 (listed in follow-ups) |
| pve-tiny (secondary) down | pve answers everything, exactly as today | nothing client-visible |
| Both down | nothing; rollback is `mikrotik-lan-dns-resolver.yml -e lan_dns_mode=pihole` during the soak | — |

Everything reaches the secondary through Technitium clustering: settings
(DoH forwarders, blocking, blocklist URLs, bypass list), the
Allowed/Blocked lists, installed apps and admin users by config sync; and
every zone (lab, bootstrap, reverse, forwarders) as a cluster catalog
member, which the secondary serves as its own Secondary/SecondaryForwarder
copy. You configure the primary once and the secondary picks it up, so
tiny *does* do DoH and blocklists; it just never gets configured directly.

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
  live before first apply (Phase 3 prose).

---

## Phase 1 — Make zone automation cluster-compatible

On today's standalone server every change in this phase is behavior-
neutral: zones are created exactly as before and NS/SOA are reconciled
exactly as before. The changes only take effect once a Technitium cluster
exists (Phase 3). The rule they implement, read from Technitium's source
(`DnsServerCore/Cluster/ClusterManager.cs` `UpdateClusterRecordsFor`,
`WebServiceZonesApi.cs` record add/update/delete guards, commit
`4323993`, 2026-09-26):

- A Primary zone that is a member of the cluster catalog gets its apex NS
  records set to one per cluster node (each node's server domain) and
  its SOA primary name server set to the primary node's domain. This
  happens when the zone is created with `catalog=`, when an existing
  zone is added to the catalog, and whenever a node joins or leaves.
- For member zones, the API **rejects** adding, deleting or changing
  apex NS records, and rejects SOA updates whose primary name server
  isn't the primary node's domain. So today's deploy playbook would not
  quietly fight the cluster; it would **fail** on every run.
- Member zones inherit the catalog zone's zone-transfer ACL, NOTIFY list
  and TSIG key, and secondaries create their copies automatically. No
  per-zone replication automation is needed.

The repo therefore gets one shared `technitium_zone` role that every zone
creator uses (create, and join the catalog when this server is a cluster
primary). The deploy playbook also stops owning apex NS/SOA once
clustered; it asserts the cluster's values instead of rewriting them.

Zone creators found in the repo and what happens to each:
`deploy-technitium-stack.yml` (bootstrap + lab parity zones) and
`roles/technitium_dns_record` (reverse zones on demand, used by the deploy
playbook and the ai/gaming/pterodactyl DNS-record playbooks) move to the
role; `technitium-framework-forwarder.yml` moves to the role;
`configure-technitium-lan-resolver.yml` (Phase 2) is written against the
role from the start. `configure-technitium-dhcp-scope-via-api.yml` is left
alone: it is a pve-test-vm-only Stage A fixture that routes its API calls
through an SSH hop, and dhcp-refactor Stage E rewrites it for production
anyway (Phase 6 note). The deploy playbook's bootstrap-phase `lab_domain`
Forwarder is also left alone; the parity-zone logic already deletes it
immediately on a cold rebuild.

### lan-dns-02-zone-role

```yaml
id: lan-dns-02-zone-role
title: Add the technitium_zone role
depends_on: []

change: >
  Create terraform/lxc/ansible/roles/technitium_zone/defaults/main.yml and
  terraform/lxc/ansible/roles/technitium_zone/tasks/main.yml with exactly
  the literal content (with its 3-space indent stripped) in "Literal
  content: technitium_zone role".

scope:
  allowed_paths:
    - terraform/lxc/ansible/roles/technitium_zone/
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running any playbook against a host"

gates:
  - id: yaml-parses
    cmd: "python3 -c \"import yaml;[yaml.safe_load(open(f)) for f in ('terraform/lxc/ansible/roles/technitium_zone/defaults/main.yml','terraform/lxc/ansible/roles/technitium_zone/tasks/main.yml')]\""
    expect: "exit 0"
    critical: true
  - id: uses-catalog-and-cluster-state
    cmd: "grep -q 'admin/cluster/state' terraform/lxc/ansible/roles/technitium_zone/tasks/main.yml && grep -q 'zones/options/set' terraform/lxc/ansible/roles/technitium_zone/tasks/main.yml && test $(grep -c 'catalog=' terraform/lxc/ansible/roles/technitium_zone/tasks/main.yml) -eq 2"
    expect: "exit 0"
    critical: true
```

#### Literal content: technitium_zone role

`terraform/lxc/ansible/roles/technitium_zone/defaults/main.yml`:

   ```yaml
   ---
   # technitium_zone defaults -- see tasks/main.yml for the contract.
   technitium_zone_type: Primary
   technitium_zone_forwarder: ""
   technitium_zone_forwarder_protocol: Udp
   ```

`terraform/lxc/ansible/roles/technitium_zone/tasks/main.yml`:

   ```yaml
   ---
   # technitium_zone: ensure one Technitium zone exists and, when this server
   # is a Technitium cluster primary, that it is a member of the cluster
   # catalog -- so every cluster node serves it. This role is the only way
   # automation in this repo should create a Technitium zone.
   #
   # Cluster contract (docs/lan-dns-technitium/plan.md): once a Primary zone
   # is a cluster catalog member, Technitium owns its apex NS records (one per
   # cluster node) and its SOA primary name server, rewrites both whenever a
   # node joins or leaves, and its API rejects edits to them. Callers must
   # never add/delete apex NS records or change the SOA primary name server
   # of a member zone. Zone transfer to secondaries, NOTIFY and TSIG are
   # inherited from the cluster catalog zone.
   #
   # Callers must already be logged in and provide technitium_api_base /
   # technitium_token (same convention as technitium_dns_record).
   #
   # Required var: technitium_zone_name -- the zone's DNS name (reverse zones
   #   as <c>.<b>.<a>.in-addr.arpa, not a CIDR).
   # Optional: technitium_zone_type (Primary | Forwarder),
   #   technitium_zone_forwarder, technitium_zone_forwarder_protocol.
   # Sets fact: technitium_zone_cluster_catalog -- the cluster catalog zone
   #   name, or '' when this server is not a cluster primary.

   - name: Read Technitium cluster state
     ansible.builtin.uri:
       url: "{{ technitium_api_base }}/admin/cluster/state?token={{ technitium_token }}"
       method: GET
       return_content: true
     register: technitium_zone_cluster_state
     no_log: true

   - name: Derive the cluster catalog zone name
     ansible.builtin.set_fact:
       technitium_zone_cluster_catalog: >-
         {{
           ('cluster-catalog.' ~ technitium_zone_state.clusterDomain)
           if (technitium_zone_state.clusterInitialized | default(false) | bool
               and (technitium_zone_state.nodes | default([])
                    | selectattr('state', 'equalto', 'Self')
                    | map(attribute='type') | first | default('')) == 'Primary')
           else ''
         }}
     vars:
       technitium_zone_state: "{{ (technitium_zone_cluster_state.content | from_json).response }}"

   - name: List Technitium zones
     ansible.builtin.uri:
       url: "{{ technitium_api_base }}/zones/list?token={{ technitium_token }}"
       method: GET
       return_content: true
     register: technitium_zone_list
     no_log: true

   - name: Find the existing zone
     ansible.builtin.set_fact:
       technitium_zone_existing: >-
         {{
           (technitium_zone_list.content | from_json).response.zones
           | selectattr('name', 'equalto', technitium_zone_name)
           | list | first | default({})
         }}

   - name: Refuse to reuse a same-named zone of a different type
     ansible.builtin.assert:
       that:
         - technitium_zone_existing | length == 0 or technitium_zone_existing.type == technitium_zone_type
       fail_msg: >-
         Zone {{ technitium_zone_name }} already exists as
         {{ technitium_zone_existing.type | default('?') }}, expected
         {{ technitium_zone_type }}.

   - name: Create the zone
     ansible.builtin.uri:
       url: >-
         {{ technitium_api_base }}/zones/create?zone={{ technitium_zone_name | urlencode }}&type={{ technitium_zone_type
         }}{% if technitium_zone_type == 'Forwarder' %}&protocol={{ technitium_zone_forwarder_protocol }}&forwarder={{ technitium_zone_forwarder | urlencode
         }}&dnssecValidation=false&proxyType=DefaultProxy&initializeForwarder=true{% endif
         %}{% if technitium_zone_cluster_catalog | length > 0 %}&catalog={{ technitium_zone_cluster_catalog | urlencode }}{% endif
         %}&token={{ technitium_token }}
       method: POST
       return_content: true
       status_code: [200]
     register: technitium_zone_create
     changed_when: true
     failed_when: (technitium_zone_create.content | from_json).status | default('') != 'ok'
     when: technitium_zone_existing | length == 0
     no_log: true

   - name: Add the existing zone to the cluster catalog
     ansible.builtin.uri:
       url: "{{ technitium_api_base }}/zones/options/set?zone={{ technitium_zone_name | urlencode }}&catalog={{ technitium_zone_cluster_catalog | urlencode }}&token={{ technitium_token }}"
       method: POST
       return_content: true
       status_code: [200]
     register: technitium_zone_catalog_set
     changed_when: true
     failed_when: (technitium_zone_catalog_set.content | from_json).status | default('') != 'ok'
     when:
       - technitium_zone_existing | length > 0
       - technitium_zone_cluster_catalog | length > 0
       - (technitium_zone_existing.catalog | default('', true)) != technitium_zone_cluster_catalog
     no_log: true
   ```

### lan-dns-03-zone-role-consumers

```yaml
id: lan-dns-03-zone-role-consumers
title: Route technitium_dns_record and the Framework forwarder through technitium_zone
depends_on: [lan-dns-02-zone-role]

change: >
  (1) In terraform/lxc/ansible/roles/technitium_dns_record/tasks/main.yml,
  replace the two tasks "List existing Technitium zones before reverse-zone
  reconciliation" and "Create missing reverse zones for this record set"
  (everything from the first task's "- name:" line up to, not including,
  "- name: Query current A records before publishing") with the first
  literal block in "Literal content: zone-role consumers". (2) In
  terraform/lxc/ansible/playbooks/technitium-framework-forwarder.yml,
  replace the two tasks "List Technitium zones" and "Create conditional
  forwarder zone for the Framework FQDN if absent" (from the first task's
  "- name:" line up to, not including, the comment line "# Every run, not
  only on zone creation") with the second literal block. Strip the 3-space
  indent from both. Change nothing else.

scope:
  allowed_paths:
    - terraform/lxc/ansible/roles/technitium_dns_record/tasks/main.yml
    - terraform/lxc/ansible/playbooks/technitium-framework-forwarder.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Editing the A/PTR record tasks of technitium_dns_record"

gates:
  - id: syntax-dns-record-consumer
    cmd: "bash -c 'cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/configure-ai-stack-dns-records.yml'"
    expect: "exit 0"
    critical: true
  - id: syntax-framework
    cmd: "bash -c 'cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/technitium-framework-forwarder.yml'"
    expect: "exit 0"
    critical: true
  - id: no-direct-zone-create
    cmd: "! grep -q 'zones/create' terraform/lxc/ansible/roles/technitium_dns_record/tasks/main.yml terraform/lxc/ansible/playbooks/technitium-framework-forwarder.yml"
    expect: "exit 0"
    critical: true
```

#### Literal content: zone-role consumers

Replacement in `roles/technitium_dns_record/tasks/main.yml`:

   ```yaml
   # Reverse zones go through technitium_zone so they join the Technitium
   # cluster catalog when this server is a cluster primary.
   - name: Ensure each needed reverse zone exists
     ansible.builtin.include_role:
       name: technitium_zone
     vars:
       technitium_zone_name: >-
         {{ technitium_dns_record_reverse_zone | regex_replace('^(\d+)\.(\d+)\.(\d+)\.0/24$', '\3.\2.\1.in-addr.arpa') }}
     loop: "{{ technitium_dns_record_reverse_zones_needed }}"
     loop_control:
       loop_var: technitium_dns_record_reverse_zone
       label: "{{ technitium_dns_record_reverse_zone }}"
   ```

Replacement in `playbooks/technitium-framework-forwarder.yml`:

   ```yaml
       - name: Ensure the conditional forwarder zone for the Framework FQDN exists
         ansible.builtin.include_role:
           name: technitium_zone
         vars:
           technitium_token: "{{ framework_fwd_token }}"
           technitium_zone_name: "{{ framework_fqdn }}"
           technitium_zone_type: Forwarder
           technitium_zone_forwarder: "{{ framework_forwarder }}"
   ```

### lan-dns-04-deploy-cluster-aware

```yaml
id: lan-dns-04-deploy-cluster-aware
title: Make deploy-technitium-stack.yml cluster-aware
depends_on: [lan-dns-02-zone-role]

change: >
  In terraform/lxc/ansible/playbooks/deploy-technitium-stack.yml make three
  replacements with the literal blocks in "Literal content: cluster-aware
  deploy playbook" (3-space indent stripped): (1) the whole task "Create
  Technitium bootstrap zone if absent" -> block A; (2) the whole task
  "Create Technitium parity zone if absent" -> block B; (3) everything from
  the "- name: Remove unexpected NS records from the parity zone root" line
  up to, not including, "- name: Assert parity-zone record set preserves
  authority records" -> block C (block C contains those same five tasks,
  re-indented inside a block, plus two new tasks). Change nothing else.

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-technitium-stack.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Changing the content of the five re-indented NS/SOA tasks"

gates:
  - id: syntax-check
    cmd: "bash -c 'cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/deploy-technitium-stack.yml'"
    expect: "exit 0"
    critical: true
  - id: only-lab-forwarder-create-left
    cmd: "test $(grep -c '/zones/create?' terraform/lxc/ansible/playbooks/deploy-technitium-stack.yml) -eq 1 && grep '/zones/create?' terraform/lxc/ansible/playbooks/deploy-technitium-stack.yml | grep -q 'type=Forwarder'"
    expect: "exit 0"
    critical: true
  - id: standalone-guard
    cmd: "test $(grep -c \"technitium_zone_cluster_catalog | default('') | length == 0\" terraform/lxc/ansible/playbooks/deploy-technitium-stack.yml) -eq 1 && test $(grep -c \"technitium_zone_cluster_catalog | default('') | length > 0\" terraform/lxc/ansible/playbooks/deploy-technitium-stack.yml) -eq 2"
    expect: "exit 0"
    critical: true
  - id: ns-soa-tasks-preserved
    cmd: "for n in 'Remove unexpected NS records from the parity zone root' 'Publish expected NS record at the parity zone root' 'Derive desired SOA serial for the parity zone' 'Assert parity zone has an SOA record to update' 'Update SOA record at the parity zone root when authority identity differs'; do grep -q \"        - name: $n\" terraform/lxc/ansible/playbooks/deploy-technitium-stack.yml || exit 1; done"
    expect: "exit 0"
    critical: true
```

#### Literal content: cluster-aware deploy playbook

Block A (replaces "Create Technitium bootstrap zone if absent"):

   ```yaml
       - name: Ensure Technitium bootstrap zone exists (and is a cluster catalog member when clustered)
         ansible.builtin.include_role:
           name: technitium_zone
         vars:
           technitium_zone_name: "{{ technitium_bootstrap_zone }}"
   ```

Block B (replaces "Create Technitium parity zone if absent"):

   ```yaml
       - name: Ensure Technitium parity zone exists (and is a cluster catalog member when clustered)
         ansible.builtin.include_role:
           name: technitium_zone
         vars:
           technitium_zone_name: "{{ technitium_generated_zone_name }}"
         when: technitium_parity_zone_enabled | bool
   ```

Block C (replaces the five NS/SOA tasks):

   ```yaml
       # Apex NS records and the SOA primary name server belong to this
       # playbook only while this server is standalone. Once the parity zone
       # is a Technitium cluster catalog member, the cluster sets both (one NS
       # per cluster node; SOA primary = the primary node's domain) and the
       # API rejects edits to them -- so reconcile when standalone, assert
       # when clustered. docs/lan-dns-technitium/plan.md.
       - name: Reconcile parity-zone apex NS and SOA (standalone server only)
         when:
           - technitium_parity_zone_enabled | bool
           - technitium_zone_cluster_catalog | default('') | length == 0
         block:
           - name: Remove unexpected NS records from the parity zone root
             ansible.builtin.uri:
               url: "{{ technitium_api_base }}/zones/records/delete?domain={{ technitium_generated_zone_name | urlencode }}&zone={{ technitium_generated_zone_name | urlencode }}&type=NS&nameServer={{ item.rData.nameServer | urlencode }}&token={{ technitium_token }}"
               method: POST
               status_code: [200]
               return_content: true
             loop: "{{ technitium_existing_parity_ns_records | default([]) }}"
             loop_control:
               label: "{{ item.rData.nameServer }}"
             when:
               - technitium_parity_zone_enabled | bool
               - (item.rData.nameServer | default('')) != technitium_parity_zone_name_server
             failed_when: >-
               (
                 delete_parity_ns_response.content | from_json
               ).status != 'ok'
             register: delete_parity_ns_response
             no_log: true

           - name: Publish expected NS record at the parity zone root
             ansible.builtin.uri:
               url: "{{ technitium_api_base }}/zones/records/add?domain={{ technitium_generated_zone_name | urlencode }}&zone={{ technitium_generated_zone_name | urlencode }}&type=NS&nameServer={{ technitium_parity_zone_name_server | urlencode }}&token={{ technitium_token }}"
               method: POST
               status_code: [200]
               return_content: true
             when: >-
               technitium_parity_zone_enabled | bool and
               (
                 technitium_existing_parity_ns_records | default([])
                 | selectattr('rData.nameServer', 'equalto', technitium_parity_zone_name_server)
                 | list
                 | length == 0
               )
             failed_when: >-
               (
                 publish_parity_ns_response.content | from_json
               ).status != 'ok'
             register: publish_parity_ns_response
             no_log: true

           - name: Derive desired SOA serial for the parity zone
             ansible.builtin.set_fact:
               technitium_parity_zone_soa_serial: >-
                 {{
                   (
                     (
                       technitium_existing_parity_soa_records | first | default({})
                     ).rData.serial | default(1) | int
                   ) + 1
                 }}
             when: technitium_parity_zone_enabled | bool
             no_log: true

           - name: Assert parity zone has an SOA record to update
             ansible.builtin.assert:
               that:
                 - technitium_existing_parity_soa_records | default([]) | length > 0
               fail_msg: >-
                 Technitium parity zone {{ technitium_generated_zone_name }} is
                 missing its root SOA record unexpectedly. Refusing to continue.
             when: technitium_parity_zone_enabled | bool

           - name: Update SOA record at the parity zone root when authority identity differs
             ansible.builtin.uri:
               url: "{{ technitium_api_base }}/zones/records/update?zone={{ technitium_generated_zone_name | urlencode }}&type=SOA&domain={{ technitium_generated_zone_name | urlencode }}&ttl={{ (technitium_existing_parity_soa_records | first).ttl | default(900) }}&disable={{ ((technitium_existing_parity_soa_records | first).disabled | default(false)) | ternary('true', 'false') }}&comments={{ ((technitium_existing_parity_soa_records | first).comments | default('')) | urlencode }}&expiryTtl={{ (technitium_existing_parity_soa_records | first).expiryTtl | default(0) }}&primaryNameServer={{ technitium_parity_zone_name_server | urlencode }}&responsiblePerson={{ technitium_parity_zone_responsible_person | urlencode }}&serial={{ technitium_parity_zone_soa_serial }}&refresh={{ technitium_seed_soa_refresh }}&retry={{ technitium_seed_soa_retry }}&expire={{ technitium_seed_soa_expire }}&minimum={{ technitium_seed_soa_minimum }}&useSerialDateScheme=false&token={{ technitium_token }}"
               method: POST
               status_code: [200]
               return_content: true
             when: >-
               technitium_parity_zone_enabled | bool and
               (
                 technitium_existing_parity_soa_records | default([])
                 | selectattr('rData.primaryNameServer', 'equalto', technitium_parity_zone_name_server)
                 | selectattr('rData.responsiblePerson', 'equalto', technitium_parity_zone_responsible_person)
                 | list
                 | length == 0
               )
             failed_when: >-
               (
                 update_parity_soa_response.content | from_json
               ).status != 'ok'
             register: update_parity_soa_response
             no_log: true

       - name: Read cluster state for the parity-zone authority check
         ansible.builtin.uri:
           url: "{{ technitium_api_base }}/admin/cluster/state?token={{ technitium_token }}"
           method: GET
           return_content: true
         register: technitium_parity_cluster_state
         when:
           - technitium_parity_zone_enabled | bool
           - technitium_zone_cluster_catalog | default('') | length > 0
         no_log: true

       - name: Assert the cluster manages the parity zone's apex NS and SOA
         ansible.builtin.assert:
           that:
             - >-
               technitium_existing_parity_ns_records | map(attribute='rData.nameServer') | map('lower') | sort
               == (technitium_parity_cluster_state.content | from_json).response.nodes | map(attribute='name') | map('lower') | sort
             - >-
               ((technitium_existing_parity_soa_records | first).rData.primaryNameServer | lower)
               == ((technitium_parity_cluster_state.content | from_json).response.dnsServerDomain | lower)
           fail_msg: >-
             {{ technitium_generated_zone_name }} is a cluster catalog member but
             its apex NS/SOA do not match the cluster's nodes -- check the
             Cluster page; re-adding the zone to the catalog makes Technitium
             rewrite them.
         when:
           - technitium_parity_zone_enabled | bool
           - technitium_zone_cluster_catalog | default('') | length > 0
   ```

### lan-dns-05-adopt-zones-playbook

```yaml
id: lan-dns-05-adopt-zones-playbook
title: Add technitium-cluster-adopt-zones.yml and document the cluster contract
depends_on: [lan-dns-02-zone-role]

change: >
  (1) Create terraform/lxc/ansible/playbooks/technitium-cluster-adopt-zones.yml
  with exactly the literal content (with its 3-space indent stripped) in
  "Literal content: technitium-cluster-adopt-zones.yml". (2) In
  terraform/lxc/stacks/technitium-stack/STACK_CONTRACT.md, append this
  bullet as the last item of the "## What Must Not Be Edited Casually"
  section: "- Create Technitium zones only through the `technitium_zone`
  role. Once this server is a Technitium cluster primary, the cluster owns
  every catalog member zone's apex NS records and SOA primary name server
  and the API rejects edits to them; `deploy-technitium-stack.yml`
  reconciles them only while standalone and asserts them when clustered.
  See `docs/lan-dns-technitium/plan.md` Phase 1."

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/technitium-cluster-adopt-zones.yml
    - terraform/lxc/stacks/technitium-stack/STACK_CONTRACT.md
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running the playbook"

gates:
  - id: syntax-check
    cmd: "bash -c 'cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/technitium-cluster-adopt-zones.yml'"
    expect: "exit 0"
    critical: true
  - id: contract-bullet
    cmd: "grep -q 'Create Technitium zones only through the .technitium_zone.' terraform/lxc/stacks/technitium-stack/STACK_CONTRACT.md"
    expect: "exit 0"
    critical: true
```

#### Literal content: technitium-cluster-adopt-zones.yml

   ```yaml
   ---
   # Adds every user-created Primary and Forwarder zone on technitium-stack
   # (the cluster primary) to the Technitium cluster catalog, so the cluster
   # secondary (technitium-tiny-stack) serves all of them.
   # docs/lan-dns-technitium/plan.md.
   #
   # Zones created through the technitium_zone role join the catalog on their
   # own; this catches zones created before the cluster existed (a fresh
   # rebuild, or zones from older playbooks). A no-op on a standalone server.
   # Imported at the end of deploy-technitium-stack.yml.

   - name: Adopt all zones into the Technitium cluster catalog
     hosts: all
     become: false
     gather_facts: false

     vars:
       technitium_ip: "{{ lookup('env', 'LAB_IP_TECHNITIUM') | default(ip_address | default(''), true) | mandatory('LAB_IP_TECHNITIUM env var is required') }}"
       technitium_admin_password: "{{ lookup('env', 'TECHNITIUM_ADMIN_PASSWORD') | mandatory('TECHNITIUM_ADMIN_PASSWORD env var is not set') }}"
       technitium_api_base: "http://{{ technitium_ip }}:5380/api"  # nosonar: ansible:S5332 — Technitium admin API, private mgmt_seg only

     tasks:
       - name: Log in to Technitium API and obtain session token
         ansible.builtin.uri:
           url: "{{ technitium_api_base }}/user/login?user=admin&pass={{ technitium_admin_password | urlencode }}&includeInfo=true"
           method: GET
           return_content: true
         register: adopt_login
         retries: 10
         delay: 3
         until: adopt_login.status == 200
         no_log: true

       - name: Extract Technitium API token
         ansible.builtin.set_fact:
           technitium_token: "{{ (adopt_login.content | from_json).token }}"
         no_log: true

       - name: List Technitium zones
         ansible.builtin.uri:
           url: "{{ technitium_api_base }}/zones/list?token={{ technitium_token }}"
           method: GET
           return_content: true
         register: adopt_zone_list
         no_log: true

       # Built-in zones are flagged internal. The cluster's own zone is already
       # a member; the catalog zone itself has type Catalog and is not listed.
       - name: Select zones to adopt
         ansible.builtin.set_fact:
           adopt_zones: >-
             {{
               adopt_all
               | selectattr('type', 'in', ['Primary', 'Forwarder'])
               | rejectattr('name', 'in', adopt_internal)
               | list
             }}
         vars:
           adopt_all: "{{ (adopt_zone_list.content | from_json).response.zones }}"
           adopt_internal: "{{ adopt_all | selectattr('internal', 'defined') | selectattr('internal') | map(attribute='name') | list }}"

       - name: Ensure each zone is a cluster catalog member
         ansible.builtin.include_role:
           name: technitium_zone
         vars:
           technitium_zone_name: "{{ adopt_zone.name }}"
           technitium_zone_type: "{{ adopt_zone.type }}"
         loop: "{{ adopt_zones }}"
         loop_control:
           loop_var: adopt_zone
           label: "{{ adopt_zone.name }} ({{ adopt_zone.type }})"
   ```

---

## Phase 2 — Make the primary a LAN-grade resolver

No LAN client uses Technitium yet, so this phase has no client-facing
effect. Blocking is bypassed for every SDN subnet, so platform stacks
that resolve through Technitium are unaffected except for the DoH
upstream and the router-forwarded `gibbsgreatly.xyz` view.

### lan-dns-06-rsyslog-structured-data

```yaml
id: lan-dns-06-rsyslog-structured-data
title: Forward RFC 5424 structured data through the rsyslog relay
depends_on: []

change: >
  In terraform/lxc/ansible/roles/rsyslog_forward/templates/log-forwarding.conf.j2,
  in the GraylogForward template string, replace the text
  "%PROCID% - - %msg%" with "%PROCID% - %STRUCTURED-DATA% %msg%", and add
  these two comment lines directly above the "template(" line:
  "# %STRUCTURED-DATA% is '-' when a message has none (identical output to the"
  / "# old literal '- -'); Technitium's Log Exporter puts clientIp etc. there."
  Change nothing else.

scope:
  allowed_paths:
    - terraform/lxc/ansible/roles/rsyslog_forward/templates/log-forwarding.conf.j2
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Changing the MSGID field (the first '-') or any other part of the template"

gates:
  - id: template-updated
    cmd: "grep -q '%PROCID% - %STRUCTURED-DATA% %msg%' terraform/lxc/ansible/roles/rsyslog_forward/templates/log-forwarding.conf.j2 && ! grep -q '%PROCID% - - %msg%' terraform/lxc/ansible/roles/rsyslog_forward/templates/log-forwarding.conf.j2"
    expect: "exit 0"
    critical: true
  - id: single-template-definition
    cmd: "test $(grep -c 'template(name=\"GraylogForward\"' terraform/lxc/ansible/roles/rsyslog_forward/templates/log-forwarding.conf.j2) -eq 1"
    expect: "exit 0"
    critical: true
```

**Correction after Phase 2's deploy (2026-09-29): this step turned out to
be unnecessary for Technitium.** The Log Exporter double-wraps its output
— its formatter builds a full RFC 5424 line (structured data included) and
its syslog sink wraps that whole line as the *message body* of a second
envelope with no structured data — so the fields reach Graylog as text,
and `configure-graylog-dns-queries.yml`'s rule extracts them with regexes.
The change is kept: it is byte-identical for all existing traffic and
already deployed on graylog-stack and technitium-stack, and it makes the
relays transparent for any future sender that does use structured data.
The original reasoning follows.

Why this step exists: the Log Exporter sends the client IP, response type
(`Blocked`, `Cached`, …), qname and answers as RFC 5424 **structured
data**; the message text only carries `QNAME…; RCODE…; ANSWER…`
(`SyslogExportStrategy.cs`). Both rsyslog hops (the Technitium node's
Docker-log relay and graylog-stack's inbound relay) re-emit messages with
the `GraylogForward` template, which hard-coded `- -` for MSGID and
STRUCTURED-DATA — so the fields that make DNS logs useful for security
were being dropped. rsyslog's `%STRUCTURED-DATA%` property is `-` for any
message without structured data, which is every message the fleet sends
today, so their forwarded bytes are unchanged. This is a fleet role, but
it only takes effect on a host when that host is next provisioned; this
plan provisions graylog-stack and both Technitium nodes, and the rest pick
it up whenever they are next deployed.

### lan-dns-07-graylog-dns-queries

```yaml
id: lan-dns-07-graylog-dns-queries
title: Add configure-graylog-dns-queries.yml and import it into deploy-graylog-stack.yml
depends_on: []

change: >
  (1) Create terraform/lxc/ansible/playbooks/configure-graylog-dns-queries.yml
  with exactly the literal content (with its 3-space indent stripped) in
  "Literal content: configure-graylog-dns-queries.yml". (2) Append to the
  very end of terraform/lxc/ansible/playbooks/deploy-graylog-stack.yml, after
  one blank line: "- name: DNS query logs index set, stream and pipeline (docs/lan-dns-technitium/)"
  / "  ansible.builtin.import_playbook: configure-graylog-dns-queries.yml".

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/configure-graylog-dns-queries.yml
    - terraform/lxc/ansible/playbooks/deploy-graylog-stack.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Editing existing lines of deploy-graylog-stack.yml"

gates:
  - id: syntax-standalone
    cmd: "bash -c 'cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/configure-graylog-dns-queries.yml'"
    expect: "exit 0"
    critical: true
  - id: syntax-graylog-deploy
    cmd: "bash -c 'cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/deploy-graylog-stack.yml'"
    expect: "exit 0"
    critical: true
  - id: import-is-last
    cmd: "grep -v '^[[:space:]]*$' terraform/lxc/ansible/playbooks/deploy-graylog-stack.yml | tail -n 1 | grep -q 'import_playbook: configure-graylog-dns-queries.yml'"
    expect: "exit 0"
    critical: true
```

#### Literal content: configure-graylog-dns-queries.yml

   ```yaml
   ---
   # DNS query logs in Graylog (docs/lan-dns-technitium/plan.md, Phase 2).
   #
   # Both Technitium nodes run the Log Exporter app, which sends every query
   # and its answer as RFC 5424 syslog (facility local6) to the node's local
   # rsyslog (127.0.0.1:10514, the Docker-log listener from rsyslog_forward),
   # which relays it to Graylog. This gives that traffic its own index set,
   # with its own retention, so per-query volume can never crowd out other
   # logs: a "DNS Queries" index set + stream, a route-dns-queries rule, and a
   # dns-queries pipeline on the Default Stream. Nothing else in the fleet
   # logs at local6.
   #
   # The Log Exporter double-wraps its output: the message body is itself a
   # complete RFC 5424 line whose structured data ([meta clientIp="..." ...])
   # is plain text by the time it reaches Graylog. The rule therefore extracts
   # the useful fields with regexes into dns_* fields (dns_client_ip,
   # dns_response_type, dns_qname, ...) as well as routing the message.
   #
   # Runs on graylog-stack against its local API. Imported at the end of
   # deploy-graylog-stack.yml; gated on GRAYLOG_DEPLOY_RUNTIME exactly like
   # that playbook's own index-set/stream work. Standalone:
   #   GRAYLOG_DEPLOY_RUNTIME=true ./with-secrets-prod ansible-playbook \
   #     -i terraform/lxc/environments/pve/graylog-stack/inventory.yml \
   #     terraform/lxc/ansible/playbooks/configure-graylog-dns-queries.yml

   - name: Route Technitium DNS query logs into their own Graylog index set
     hosts: all
     become: false
     gather_facts: false

     vars:
       graylog_dns_enabled: "{{ lookup('env', 'GRAYLOG_DEPLOY_RUNTIME') | default('false', true) | bool }}"
       graylog_dns_api: "http://127.0.0.1:9000/api"  # nosonar: ansible:S5332 — internal API on private SDN
       graylog_dns_admin_password: "{{ lookup('env', 'GRAYLOG_ROOT_PASSWORD') | mandatory('GRAYLOG_ROOT_PASSWORD env var is required') }}"
       graylog_dns_title: "DNS Queries"
       graylog_dns_default_stream: "000000000000000000000001"
       graylog_dns_rule_source: |-
         rule "route-dns-queries"
         when
           to_string($message.facility) == "local6"
         then
           let body = to_string($message.message);
           let q = regex("clientIp=\"([^\"]*)\" protocol=\"([^\"]*)\" responseType=\"([^\"]*)\" responseRtt=\"([^\"]*)\" rCode=\"([^\"]*)\"", body, ["dns_client_ip", "dns_protocol", "dns_response_type", "dns_rtt_ms", "dns_rcode"]);
           set_fields(q);
           let n = regex("qName=\"([^\"]*)\" qType=\"([^\"]*)\"", body, ["dns_qname", "dns_qtype"]);
           set_fields(n);
           let a = regex("ANSWER: \\[(.*)\\]\\s*$", body, ["dns_answers"]);
           set_fields(a);
           route_to_stream(id: "{{ graylog_dns_stream_id }}");
           remove_from_stream(id: "{{ graylog_dns_default_stream }}");
         end
       graylog_dns_rule_description: "Extract dns_* fields from Technitium Log Exporter query logs (facility local6) and move them into the DNS Queries stream/index set."

     tasks:
       - name: Check existing Graylog index sets
         ansible.builtin.uri:
           url: "{{ graylog_dns_api }}/system/indices/index_sets"
           method: GET
           url_username: admin
           url_password: "{{ graylog_dns_admin_password }}"
           force_basic_auth: true
           return_content: true
         register: graylog_dns_index_sets
         when: graylog_dns_enabled
         no_log: true

       - name: Create the DNS Queries index set (30 days)
         ansible.builtin.uri:
           url: "{{ graylog_dns_api }}/system/indices/index_sets"
           method: POST
           url_username: admin
           url_password: "{{ graylog_dns_admin_password }}"
           force_basic_auth: true
           headers:
             Content-Type: application/json
             X-Requested-By: ansible
           body_format: json
           body:
             title: "{{ graylog_dns_title }}"
             description: "Every LAN DNS query and answer from the Technitium nodes (Log Exporter app, facility local6). High volume; 30-day retention."
             index_prefix: "gl-dns"
             shards: 1
             replicas: 0
             rotation_strategy_class: "org.graylog2.indexer.rotation.strategies.TimeBasedSizeOptimizingStrategy"
             rotation_strategy:
               type: "org.graylog2.indexer.rotation.strategies.TimeBasedSizeOptimizingStrategyConfig"
               index_lifetime_min: "P25D"
               index_lifetime_max: "P30D"
             retention_strategy_class: "org.graylog2.indexer.retention.strategies.DeletionRetentionStrategy"
             retention_strategy:
               type: "org.graylog2.indexer.retention.strategies.DeletionRetentionStrategyConfig"
               max_number_of_indices: 6
             data_tiering:
               type: "hot_only"
               index_lifetime_min: "P25D"
               index_lifetime_max: "P30D"
             index_analyzer: "standard"
             index_optimization_max_num_segments: 1
             index_optimization_disabled: false
             field_type_refresh_interval: 5000
             use_legacy_rotation: false
             writable: true
           status_code: [200, 201]
           return_content: true
         register: graylog_dns_index_set_create
         when:
           - graylog_dns_enabled
           - (graylog_dns_index_sets.json.index_sets | default([]) | selectattr('title', 'eq', graylog_dns_title) | list | length) == 0
         no_log: true

       - name: Resolve the DNS Queries index set ID
         ansible.builtin.set_fact:
           graylog_dns_index_set_id: >-
             {{
               (graylog_dns_index_sets.json.index_sets | default([])
                | selectattr('title', 'eq', graylog_dns_title) | map(attribute='id') | list | first)
               if (graylog_dns_index_sets.json.index_sets | default([]) | selectattr('title', 'eq', graylog_dns_title) | list | length) > 0
               else graylog_dns_index_set_create.json.id
             }}
         when: graylog_dns_enabled

       - name: Check existing Graylog streams
         ansible.builtin.uri:
           url: "{{ graylog_dns_api }}/streams"
           method: GET
           url_username: admin
           url_password: "{{ graylog_dns_admin_password }}"
           force_basic_auth: true
           return_content: true
         register: graylog_dns_streams
         when: graylog_dns_enabled
         no_log: true

       - name: Create the DNS Queries stream
         ansible.builtin.uri:
           url: "{{ graylog_dns_api }}/streams"
           method: POST
           url_username: admin
           url_password: "{{ graylog_dns_admin_password }}"
           force_basic_auth: true
           headers:
             Content-Type: application/json
             X-Requested-By: ansible
           body_format: json
           body:
             entity:
               title: "{{ graylog_dns_title }}"
               description: "LAN DNS queries from the Technitium nodes."
               index_set_id: "{{ graylog_dns_index_set_id }}"
               matching_type: "AND"
               remove_matches_from_default_stream: false
             share_request: null
           status_code: [200, 201]
           return_content: true
         register: graylog_dns_stream_create
         when:
           - graylog_dns_enabled
           - (graylog_dns_streams.json.streams | default([]) | selectattr('title', 'eq', graylog_dns_title) | list | length) == 0
         no_log: true

       - name: Resolve the DNS Queries stream ID
         ansible.builtin.set_fact:
           graylog_dns_stream_id: >-
             {{
               (graylog_dns_streams.json.streams | default([])
                | selectattr('title', 'eq', graylog_dns_title) | map(attribute='id') | list | first)
               if (graylog_dns_streams.json.streams | default([]) | selectattr('title', 'eq', graylog_dns_title) | list | length) > 0
               else graylog_dns_stream_create.json.stream_id
             }}
         when: graylog_dns_enabled

       # New streams are created paused; resuming is idempotent.
       - name: Resume the DNS Queries stream
         ansible.builtin.uri:
           url: "{{ graylog_dns_api }}/streams/{{ graylog_dns_stream_id }}/resume"
           method: POST
           url_username: admin
           url_password: "{{ graylog_dns_admin_password }}"
           force_basic_auth: true
           headers:
             X-Requested-By: ansible
           status_code: [200, 204]
         when: graylog_dns_enabled
         no_log: true

       - name: Check existing pipeline rules
         ansible.builtin.uri:
           url: "{{ graylog_dns_api }}/system/pipelines/rule"
           method: GET
           url_username: admin
           url_password: "{{ graylog_dns_admin_password }}"
           force_basic_auth: true
           return_content: true
         register: graylog_dns_rules
         when: graylog_dns_enabled
         no_log: true

       - name: Find the existing route-dns-queries rule
         ansible.builtin.set_fact:
           graylog_dns_rule_existing: "{{ graylog_dns_rules.json | default([]) | selectattr('title', 'eq', 'route-dns-queries') | list | first | default({}) }}"
         when: graylog_dns_enabled

       - name: Create the route-dns-queries rule
         ansible.builtin.uri:
           url: "{{ graylog_dns_api }}/system/pipelines/rule"
           method: POST
           url_username: admin
           url_password: "{{ graylog_dns_admin_password }}"
           force_basic_auth: true
           headers:
             Content-Type: application/json
             X-Requested-By: ansible
           body_format: json
           body:
             title: "route-dns-queries"
             description: "{{ graylog_dns_rule_description }}"
             source: "{{ graylog_dns_rule_source }}"
           status_code: [200, 201]
           return_content: true
         register: graylog_dns_rule_create
         failed_when: graylog_dns_rule_create.json.errors | default(none) is not none
         when:
           - graylog_dns_enabled
           - graylog_dns_rule_existing | length == 0
         no_log: true

       # Reconcile on drift, not just existence, so a changed rule reaches the
       # live Graylog on the next run.
       - name: Update the route-dns-queries rule when its source differs
         ansible.builtin.uri:
           url: "{{ graylog_dns_api }}/system/pipelines/rule/{{ graylog_dns_rule_existing.id }}"
           method: PUT
           url_username: admin
           url_password: "{{ graylog_dns_admin_password }}"
           force_basic_auth: true
           headers:
             Content-Type: application/json
             X-Requested-By: ansible
           body_format: json
           body:
             title: "route-dns-queries"
             description: "{{ graylog_dns_rule_description }}"
             source: "{{ graylog_dns_rule_source }}"
           status_code: [200]
           return_content: true
         register: graylog_dns_rule_update
         changed_when: true
         failed_when: graylog_dns_rule_update.json.errors | default(none) is not none
         when:
           - graylog_dns_enabled
           - graylog_dns_rule_existing | length > 0
           - (graylog_dns_rule_existing.source | default('') | trim) != (graylog_dns_rule_source | trim)
         no_log: true

       - name: Check existing pipelines
         ansible.builtin.uri:
           url: "{{ graylog_dns_api }}/system/pipelines/pipeline"
           method: GET
           url_username: admin
           url_password: "{{ graylog_dns_admin_password }}"
           force_basic_auth: true
           return_content: true
         register: graylog_dns_pipelines
         when: graylog_dns_enabled
         no_log: true

       - name: Create the dns-queries pipeline
         ansible.builtin.uri:
           url: "{{ graylog_dns_api }}/system/pipelines/pipeline"
           method: POST
           url_username: admin
           url_password: "{{ graylog_dns_admin_password }}"
           force_basic_auth: true
           headers:
             Content-Type: application/json
             X-Requested-By: ansible
           body_format: json
           body:
             title: "dns-queries"
             description: "Routes Technitium DNS query logs into the DNS Queries stream."
             source: |-
               pipeline "dns-queries"
               stage 0 match either
                 rule "route-dns-queries";
               end
           status_code: [200, 201]
           return_content: true
         register: graylog_dns_pipeline_create
         failed_when: graylog_dns_pipeline_create.json.errors | default(none) is not none
         when:
           - graylog_dns_enabled
           - (graylog_dns_pipelines.json | default([]) | selectattr('title', 'eq', 'dns-queries') | list | length) == 0
         no_log: true

       - name: Resolve the dns-queries pipeline ID
         ansible.builtin.set_fact:
           graylog_dns_pipeline_id: >-
             {{
               (graylog_dns_pipelines.json | default([])
                | selectattr('title', 'eq', 'dns-queries') | map(attribute='id') | list | first)
               if (graylog_dns_pipelines.json | default([]) | selectattr('title', 'eq', 'dns-queries') | list | length) > 0
               else graylog_dns_pipeline_create.json.id
             }}
         when: graylog_dns_enabled

       - name: Read pipeline connections
         ansible.builtin.uri:
           url: "{{ graylog_dns_api }}/system/pipelines/connections"
           method: GET
           url_username: admin
           url_password: "{{ graylog_dns_admin_password }}"
           force_basic_auth: true
           return_content: true
         register: graylog_dns_connections
         when: graylog_dns_enabled
         no_log: true

       - name: Compute pipelines already on the Default Stream
         ansible.builtin.set_fact:
           graylog_dns_default_pipeline_ids: >-
             {{
               graylog_dns_connections.json | default([])
               | selectattr('stream_id', 'eq', graylog_dns_default_stream)
               | map(attribute='pipeline_ids') | list | first | default([])
             }}
         when: graylog_dns_enabled

       # Appends to the existing list -- never replaces it -- so the
       # source-identity-fixups and log-segmentation pipelines stay connected.
       - name: Connect the dns-queries pipeline to the Default Stream
         ansible.builtin.uri:
           url: "{{ graylog_dns_api }}/system/pipelines/connections/to_stream"
           method: POST
           url_username: admin
           url_password: "{{ graylog_dns_admin_password }}"
           force_basic_auth: true
           headers:
             Content-Type: application/json
             X-Requested-By: ansible
           body_format: json
           body:
             stream_id: "{{ graylog_dns_default_stream }}"
             pipeline_ids: "{{ graylog_dns_default_pipeline_ids + [graylog_dns_pipeline_id] }}"
           status_code: [200, 201]
         when:
           - graylog_dns_enabled
           - graylog_dns_pipeline_id not in graylog_dns_default_pipeline_ids
         no_log: true
   ```

### lan-dns-08-resolver-playbook

```yaml
id: lan-dns-08-resolver-playbook
title: Add configure-technitium-lan-resolver.yml
depends_on: [lan-dns-02-zone-role]

change: >
  Create terraform/lxc/ansible/playbooks/configure-technitium-lan-resolver.yml
  with exactly the literal content (with its 3-space indent stripped) in the
  plan section "Literal content: configure-technitium-lan-resolver.yml".

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/configure-technitium-lan-resolver.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running the playbook against any host"

gates:
  - id: syntax-check
    cmd: "bash -c 'cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/configure-technitium-lan-resolver.yml'"
    expect: "exit 0"
    critical: true
  - id: blocklists-present
    cmd: "test $(grep -c 'raw.githubusercontent.com/hagezi/dns-blocklists/main/wildcard/' terraform/lxc/ansible/playbooks/configure-technitium-lan-resolver.yml) -eq 2"
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
   # primary (docs/lan-dns-technitium/plan.md, Phase 2).
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

       # Hagezi Pro (ads/trackers/telemetry, ~230k domains) + Hagezi Threat
       # Intelligence Feeds "mini" (malware/phishing/scam). The full TIF list
       # is ~40MB, too heavy for a 2GB LXC. Both URLs checked 2026-09-29.
       # Plus StevenBlack's unified hosts (Pi-hole's default list): Hagezi
       # deliberately leaves some ad hosts alone (doubleclick.net apex,
       # ad.doubleclick.net, adservice.google.com) that the Pi-holes blocked
       # (operator, 2026-09-29).
       lan_resolver_block_list_urls:
         - "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/wildcard/pro-onlydomains.txt"
         - "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/wildcard/tif.mini-onlydomains.txt"
         - "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts"
       # Exceptions and extra blocks live here, not in the web UI, so a
       # rebuild keeps them. Synced to the secondary via clustering.
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

       # Apps are cluster-synced (install + config), so the secondary gets them
       # too. Rebinding protection and the Log Exporter bypass/skip nothing on
       # their own; the SDN subnets bypass rebinding for the same reason they
       # bypass blocking (platform DNS behavior unchanged).
       lan_resolver_apps:
         - name: "Query Logs (Sqlite)"
           config: null
         - name: "DNS Rebinding Protection"
           config:
             enableProtection: true
             bypassNetworks: "{{ lan_resolver_blocking_bypass }}"
             privateNetworks:
               - 10.0.0.0/8
               - 127.0.0.0/8
               - 172.16.0.0/12
               - 192.168.0.0/16
               - 169.254.0.0/16
               - fc00::/7
               - fe80::/10
             # Legitimately-private public names: the router's split-horizon
             # records, DHCP-generated names, RFC 8375, and Plex's LAN relay.
             privateDomains:
               - home.arpa
               - gibbsgreatly.xyz
               - lan
               - plex.direct
         # Every query + answer to the local rsyslog Docker-log listener, which
         # relays to Graylog (configure-graylog-dns-queries.yml routes it by
         # facility local6 into its own index set).
         - name: "Log Exporter"
           config:
             maxQueueSize: 1000000
             enableEdnsLogging: false
             file:
               path: "./dns_logs.json"
               enabled: false
             http:
               endpoint: "http://localhost:5000/logs"  # nosonar: ansible:S5332 — disabled placeholder required by the app's config schema
               headers: {}
               enabled: false
             syslog:
               address: "127.0.0.1"
               port: 10514
               protocol: "TCP"
               enabled: true

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

       - name: Ensure router forwarder zones exist (cluster catalog members when clustered)
         ansible.builtin.include_role:
           name: technitium_zone
         vars:
           technitium_token: "{{ lan_resolver_token }}"
           technitium_zone_name: "{{ lan_resolver_fwd_zone }}"
           technitium_zone_type: Forwarder
           technitium_zone_forwarder: "{{ lan_resolver_router }}"
         loop: "{{ lan_resolver_forwarder_zones }}"
         loop_control:
           loop_var: lan_resolver_fwd_zone

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
         register: lan_resolver_installed_apps
         no_log: true

       - name: Find apps that are not installed yet
         ansible.builtin.set_fact:
           lan_resolver_missing_apps: >-
             {{
               lan_resolver_apps | map(attribute='name')
               | reject('in', (lan_resolver_installed_apps.content | from_json).response.apps | map(attribute='name') | list)
               | list
             }}

       - name: List store apps
         ansible.builtin.uri:
           url: "{{ technitium_api_base }}/apps/listStoreApps?token={{ lan_resolver_token }}"
           method: GET
           return_content: true
         register: lan_resolver_store_apps
         when: lan_resolver_missing_apps | length > 0
         no_log: true

       - name: Assert every missing app exists in the store
         ansible.builtin.assert:
           that:
             - item in (lan_resolver_store_apps.content | from_json).response.storeApps | map(attribute='name') | list
           fail_msg: "'{{ item }}' not found in the Technitium app store."
         loop: "{{ lan_resolver_missing_apps }}"

       - name: Install missing apps
         ansible.builtin.uri:
           url: "{{ technitium_api_base }}/apps/downloadAndInstall?name={{ item | urlencode }}&url={{ ((lan_resolver_store_apps.content | from_json).response.storeApps | selectattr('name', 'equalto', item) | map(attribute='url') | first) | urlencode }}&token={{ lan_resolver_token }}"
           method: POST
           return_content: true
           status_code: [200]
         register: lan_resolver_app_install
         changed_when: true
         failed_when: (lan_resolver_app_install.content | from_json).status | default('') != 'ok'
         loop: "{{ lan_resolver_missing_apps }}"
         no_log: true

       - name: Read app configs
         ansible.builtin.uri:
           url: "{{ technitium_api_base }}/apps/config/get?name={{ item.name | urlencode }}&token={{ lan_resolver_token }}"
           method: GET
           return_content: true
         register: lan_resolver_app_configs
         loop: "{{ lan_resolver_apps | selectattr('config', 'ne', none) | list }}"
         loop_control:
           label: "{{ item.name }}"
         no_log: true

       - name: Apply app configs that differ
         ansible.builtin.uri:
           url: "{{ technitium_api_base }}/apps/config/set?name={{ item.item.name | urlencode }}&token={{ lan_resolver_token }}"
           method: POST
           body_format: form-urlencoded
           body:
             config: "{{ item.item.config | to_json }}"
           return_content: true
           status_code: [200]
         register: lan_resolver_app_config_set
         changed_when: true
         failed_when: (lan_resolver_app_config_set.content | from_json).status | default('') != 'ok'
         loop: "{{ lan_resolver_app_configs.results }}"
         loop_control:
           label: "{{ item.item.name }}"
         when: >-
           (((item.content | from_json).response.config | default('', true)) or '{}') | from_json
           != item.item.config
         no_log: true

       # Probe domain: googlesyndication.com is itself an entry in Hagezi Pro.
       # Not doubleclick.net -- Hagezi deliberately leaves that apex (and
       # ad.doubleclick.net) unblocked and lists ad subdomains instead.
       # Blocking must be probed from a non-bypassed address: the LXC itself
       # sits in 192.168.20.0/24 (bypassed), so these digs run on the control
       # node, which is on bridgeLocal like a real LAN client.
       - name: Probe blocking from the LAN
         ansible.builtin.command: dig @{{ technitium_ip }} +short googlesyndication.com A
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

       - name: Probe DNS rebinding protection from the LAN
         ansible.builtin.command: dig @{{ technitium_ip }} +short 10.0.0.1.nip.io A
         delegate_to: localhost
         register: lan_resolver_rebind_probe
         check_mode: false
         changed_when: false
         retries: 6
         delay: 10
         until: (lan_resolver_rebind_probe.stdout | trim) | length == 0

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

### lan-dns-09-node-observability

```yaml
id: lan-dns-09-node-observability
title: Add technitium-node-observability.yml (cAdvisor + console logging per node)
depends_on: []

change: >
  (1) Create terraform/lxc/ansible/playbooks/technitium-node-observability.yml
  with exactly the literal content (with its 3-space indent stripped) in
  "Literal content: technitium-node-observability.yml". (2) In
  terraform/lxc/stacks/technitium-stack/STACK_CONTRACT.md, append this
  bullet as the last item of "## What Must Not Be Edited Casually": "-
  Observability: node_exporter (lxc_base, :9100 TLS), cAdvisor
  (/opt/cadvisor, :8080, separate compose project so it never recreates the
  Technitium container), Technitium metrics (`/api/dashboard/metrics/text`,
  token of the `metrics` user), server log to console -> Docker syslog ->
  Graylog, and every DNS query via the Log Exporter app -> Graylog "DNS
  Queries" index set. See `docs/lan-dns-technitium/plan.md`."

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/technitium-node-observability.yml
    - terraform/lxc/stacks/technitium-stack/STACK_CONTRACT.md
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running the playbook"

gates:
  - id: syntax-check
    cmd: "bash -c 'cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/technitium-node-observability.yml'"
    expect: "exit 0"
    critical: true
  - id: separate-compose-project
    cmd: "grep -q 'technitium_obs_cadvisor_dir: /opt/cadvisor' terraform/lxc/ansible/playbooks/technitium-node-observability.yml && grep -q 'loggingType=FileAndConsole' terraform/lxc/ansible/playbooks/technitium-node-observability.yml"
    expect: "exit 0"
    critical: true
  - id: contract-bullet
    cmd: "grep -q '^- Observability: node_exporter' terraform/lxc/stacks/technitium-stack/STACK_CONTRACT.md"
    expect: "exit 0"
    critical: true
```

#### Literal content: technitium-node-observability.yml

   ```yaml
   ---
   # Per-node observability for a Technitium node (technitium-stack or
   # technitium-tiny-stack). docs/lan-dns-technitium/plan.md.
   #
   # - cAdvisor on :8080 for container metrics, as its own compose project
   #   (/opt/cadvisor) so adding or updating it never recreates the Technitium
   #   container. Same image/tag and mounts as every other stack's cAdvisor.
   # - Technitium's server/audit log also to the console, so Docker's syslog
   #   driver ships it to Graylog (Docker Chatter stream) instead of it only
   #   living in a file inside the container. loggingType is a per-node
   #   setting (not cluster-synced), so it is set on each node's own API.
   #
   # node_exporter, rsyslog forwarding and the Wazuh agent come from lxc_base /
   # the deploy playbooks and are not repeated here. Imported at the end of
   # both deploy-technitium-stack.yml and deploy-technitium-tiny-stack.yml.

   - name: Technitium node observability
     hosts: all
     become: true
     gather_facts: false

     vars:
       technitium_obs_registry_host: "{{ lookup('env', 'LAB_FQDN_HARBOR') | default(registry_host, true) | mandatory('LAB_FQDN_HARBOR env var or registry_host inventory var is required') }}"
       technitium_obs_cadvisor_image: "{{ technitium_obs_registry_host }}/ghcr/google/cadvisor:v0.60.5"
       technitium_obs_cadvisor_dir: /opt/cadvisor
       technitium_obs_admin_password: "{{ lookup('env', 'TECHNITIUM_ADMIN_PASSWORD') | mandatory('TECHNITIUM_ADMIN_PASSWORD env var is not set') }}"
       technitium_obs_api: "http://{{ ansible_host }}:5380/api"  # nosonar: ansible:S5332 — Technitium admin API, private mgmt_seg only

     tasks:
       - name: Create cAdvisor compose directory
         ansible.builtin.file:
           path: "{{ technitium_obs_cadvisor_dir }}"
           state: directory
           mode: "0750"

       - name: Write cAdvisor compose definition
         ansible.builtin.copy:
           dest: "{{ technitium_obs_cadvisor_dir }}/docker-compose.yml"
           mode: "0640"
           content: |
             name: cadvisor
             services:
               cadvisor:
                 image: {{ technitium_obs_cadvisor_image }}
                 container_name: cadvisor
                 restart: unless-stopped
                 ports:
                   - "8080:8080"
                 volumes:
                   - /:/rootfs:ro
                   - /var/run:/var/run:ro
                   - /sys:/sys:ro
                   - /var/lib/docker:/var/lib/docker:ro
                   - /etc/machine-id:/etc/machine-id:ro

       - name: Start cAdvisor
         community.docker.docker_compose_v2:
           project_src: "{{ technitium_obs_cadvisor_dir }}"
           state: present
         when: not ansible_check_mode

       - name: Wait for cAdvisor metrics
         ansible.builtin.uri:
           url: "http://{{ ansible_host }}:8080/metrics"  # nosonar: ansible:S5332 — cAdvisor metrics, private mgmt_seg only
           method: GET
           status_code: [200]
         register: technitium_obs_cadvisor_ready
         retries: 20
         delay: 3
         until: technitium_obs_cadvisor_ready is success
         when: not ansible_check_mode

       - name: Log in to this node's Technitium API
         ansible.builtin.uri:
           url: "{{ technitium_obs_api }}/user/login?user=admin&pass={{ technitium_obs_admin_password | urlencode }}"
           method: GET
           return_content: true
         register: technitium_obs_login
         retries: 10
         delay: 3
         until: technitium_obs_login.status == 200
         become: false
         no_log: true

       - name: Read this node's logging setting
         ansible.builtin.uri:
           url: "{{ technitium_obs_api }}/settings/get?token={{ (technitium_obs_login.content | from_json).token }}"
           method: GET
           return_content: true
         register: technitium_obs_settings
         become: false
         no_log: true

       - name: Log to file and console
         ansible.builtin.uri:
           url: "{{ technitium_obs_api }}/settings/set?loggingType=FileAndConsole&token={{ (technitium_obs_login.content | from_json).token }}"
           method: POST
           return_content: true
           status_code: [200]
         register: technitium_obs_logging_set
         changed_when: true
         failed_when: (technitium_obs_logging_set.content | from_json).status | default('') != 'ok'
         when: (technitium_obs_settings.content | from_json).response.loggingType | default('') != 'FileAndConsole'
         become: false
         no_log: true
   ```

### lan-dns-10-import-into-deploy

```yaml
id: lan-dns-10-import-into-deploy
title: Import the resolver, node-observability and zone-adoption playbooks at the end of deploy-technitium-stack.yml
depends_on: [lan-dns-04-deploy-cluster-aware, lan-dns-05-adopt-zones-playbook, lan-dns-08-resolver-playbook, lan-dns-09-node-observability]

change: >
  Append three entries to the very end of
  terraform/lxc/ansible/playbooks/deploy-technitium-stack.yml, after the
  existing "Forward the Framework Desktop FQDN to the MikroTik" import, each
  preceded by one blank line, in this order:
  "- name: Configure Technitium as the LAN resolver (docs/lan-dns-technitium/)"
  / "  ansible.builtin.import_playbook: configure-technitium-lan-resolver.yml";
  "- name: Technitium node observability (docs/lan-dns-technitium/)"
  / "  ansible.builtin.import_playbook: technitium-node-observability.yml";
  "- name: Adopt all zones into the Technitium cluster catalog (docs/lan-dns-technitium/)"
  / "  ansible.builtin.import_playbook: technitium-cluster-adopt-zones.yml".
  Each "import_playbook" line is indented two spaces. Change nothing else.

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
  - id: import-order
    cmd: "test \"$(grep -o 'import_playbook: [a-z-]*.yml' terraform/lxc/ansible/playbooks/deploy-technitium-stack.yml | tail -n 3 | tr '\\n' ' ')\" = 'import_playbook: configure-technitium-lan-resolver.yml import_playbook: technitium-node-observability.yml import_playbook: technitium-cluster-adopt-zones.yml '"
    expect: "exit 0"
    critical: true
```

### Operator: create the Technitium metrics token

The Prometheus endpoint needs an API token. Agents can't write to OpenBao,
so this is yours, once:

1. In the Technitium UI (primary): Administration → Users → **Add User**
   `metrics`, with a long random password you don't keep.
2. Open the user (User Details) and under **Member Of** remove the
   **Everyone** group. Technitium adds every new user to Everyone, which by
   default can view Zones, Cache, Allowed, Blocked, Apps, DNS Client, DHCP
   and **Logs** (the query logs); a metrics token must not carry that.
   Don't tick "Disable User Account" — that would disable its token too.
3. Administration → Permissions → **Dashboard** → Edit → add user
   `metrics` with **View** only. No other section.
4. Administration → Sessions → **Create Token** → Username `metrics`,
   Token Name `victoriametrics`. Copy the token (shown once; API tokens
   don't expire with the session timeout). Clustering later copies the
   user and its token to the secondary.
5. `bao login -method=oidc -no-store`, then write it with
   `scripts/openbao_write.py` into `services/technitium` as field
   `TECHNITIUM_METRICS_TOKEN` (see `docs/reference/secrets-management.md`).
6. Check: `curl -s -H "Authorization: Bearer <token>"
   http://192.168.20.15:5380/api/dashboard/metrics/text | head -3` shows
   `# HELP uptime_seconds …` (an `invalid-token` JSON body means it's wrong),
   and the same token against `/api/zones/list` returns an access-denied
   error rather than a zone list (proves step 2 took).

**Do this before `lan-dns-11` lands**: every environment profile includes
`services/technitium`, and the wrappers fail closed on a manifest field
with no value.

### lan-dns-11-metrics-token-manifest

```yaml
id: lan-dns-11-metrics-token-manifest
title: Declare TECHNITIUM_METRICS_TOKEN in secrets/manifest.json
depends_on: []   # the operator token write above must already be done

change: >
  In secrets/manifest.json, in entries["services/technitium"].fields, add
  "TECHNITIUM_METRICS_TOKEN" as the last element (after
  "TECHNITIUM_OIDC_CLIENT_SECRET"). Keep the file's existing formatting and
  change nothing else.

scope:
  allowed_paths:
    - secrets/manifest.json
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Writing any secret value anywhere"

gates:
  - id: field-declared
    cmd: "python3 -c \"import json;f=json.load(open('secrets/manifest.json'))['entries']['services/technitium']['fields'];assert f==['TECHNITIUM_ADMIN_PASSWORD','TECHNITIUM_OIDC_CLIENT_SECRET','TECHNITIUM_METRICS_TOKEN'],f\""
    expect: "exit 0"
    critical: true
  - id: wrapper-resolves-it
    cmd: "./with-secrets-prod printenv TECHNITIUM_METRICS_TOKEN | grep -qE '.{20,}'"
    expect: "exit 0"
    critical: true
```

### Operator: re-provision graylog-stack

Ansible role change (rsyslog template) + new Graylog config →
`provision.sh` on `pve` under approval. This must happen **before** the
Technitium deploy, so query logs have their index set when they start
flowing:

```bash
export TASK_APPROVAL="lan-dns-graylog"
./with-secrets-prod scripts/provision.sh --stack graylog-stack
```

Then confirm nothing regressed for existing senders: in Graylog, recent
messages from another stack (e.g. `monitoring-stack`) still arrive with the
same `source`/`application_name`, and the new "DNS Queries" stream exists
(empty until Phase 2's Technitium deploy).

### Operator: deploy technitium-stack on pve

Production mutation (Ansible task/role change → `provision.sh` on `pve`
per CLAUDE.md's validation tiers). This one run validates Phase 1's
changes in their **standalone** path (the cluster doesn't exist yet, so
zones must be created and NS/SOA reconciled exactly as before, and the
adopt play is a no-op) and applies the LAN resolver config:

```bash
export TASK_APPROVAL="lan-dns-technitium-primary"
./with-secrets-prod scripts/provision.sh --stack technitium-stack
```

Expect in the recap: no failed tasks, the "Reconcile parity-zone apex NS
and SOA" block running (not skipped), the two cluster-assertion tasks
skipped, and `changed` only for the resolver settings, forwarder zones,
the three apps and their configs, cAdvisor, the logging setting and
node-local rsyslog (structured-data template). The Technitium container
itself is **not** recreated (its compose file is untouched). Rollback: re-run with the previous commit checked out;
resolver settings revert with `settings/set?forwarders=false&enableBlocking=false`
in the Technitium UI/API. Afterwards, spot-check a platform stack that
uses Technitium as its Docker resolver still pulls images (e.g. re-run a
`docker pull` of an already-used image on `monitoring-stack`).

### lan-dns-12-verify-primary

```yaml
id: lan-dns-12-verify-primary
title: Verify the primary answers like a Pi-hole, from the LAN
depends_on: [lan-dns-10-import-into-deploy]   # and the operator deploy above

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
    cmd: "test \"$(dig +short @192.168.20.15 googlesyndication.com A)\" = 0.0.0.0"
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
  - id: rebinding-protection
    cmd: "test -z \"$(dig +short @192.168.20.15 10.0.0.1.nip.io A)\""
    expect: "exit 0"
    critical: true
  - id: split-horizon-still-private
    cmd: "test \"$(dig +short @192.168.20.15 nas.gibbsgreatly.xyz A)\" = \"$(dig +short @192.168.1.1 nas.gibbsgreatly.xyz A)\""
    expect: "exit 0"
    critical: true
  - id: cadvisor-up
    cmd: "curl -s -m 5 -o /dev/null -w '%{http_code}' http://192.168.20.15:8080/metrics | grep -qx 200"
    expect: "exit 0"
    critical: true
  - id: standalone-ns-unchanged
    cmd: "test \"$(dig +short @192.168.20.15 NS lab.gibbsgreatly.xyz)\" = ns1.lab.gibbsgreatly.xyz."
    expect: "exit 0"
    critical: true
```

---

### Operator: confirm DNS logs in Graylog

In Graylog: the "DNS Queries" stream shows messages from `technitium-stack`
within a minute of a lookup from your workstation, and a message has
`dns_client_ip`, `dns_qname`, `dns_response_type`, `dns_rcode` fields
(extracted by the `route-dns-queries` rule). Look up
`googlesyndication.com` and confirm a `dns_response_type: Blocked`
message. Technitium's own server log appears in the "Docker
Chatter" stream as `application_name: docker-technitium`. If the `dns_*`
fields are missing but the message text contains `[meta clientIp=…`, the
rule is the old, route-only version: re-run
`configure-graylog-dns-queries.yml` (it updates the rule on drift).

---

## Phase 3 — Secondary node on pve-tiny

### lan-dns-13-ip-wiring

```yaml
id: lan-dns-13-ip-wiring
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

### lan-dns-14-stack-files

```yaml
id: lan-dns-14-stack-files
title: Create technitium-tiny-stack's stack.yaml, contract, and pve-tiny env dir
depends_on: [lan-dns-13-ip-wiring]

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
   # blocklists, apps and every zone through Technitium clustering.
   # docs/lan-dns-technitium/plan.md.
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
   | `LAB_IP_TECHNITIUM` | env var | Informational: the cluster primary's IP (cluster join is an operator step, not automated) |
   | `TECHNITIUM_ADMIN_PASSWORD` | env var (secret) | **Mandatory.** Same admin password as the primary; clustering syncs users from the primary after join |
   | `LAB_DOMAIN` | env var | Defaults to `lab.gibbsgreatly.xyz` |

   ## Provides

   | Service | Port | Protocol | Notes |
   |---|---|---|---|
   | DNS resolver | 53 | UDP + TCP | LAN clients' second resolver (MikroTik DHCP `dns-server`). Serves cluster-synced copies of every zone on the primary |
   | Web console / REST API | 5380 | TCP | Direct by IP only; no Traefik route |
   | Cluster HTTPS | 53443 | TCP | Technitium cluster sync with the primary (self-signed, enabled automatically on cluster join) |

   `stack.yaml` service identifiers: `dns-resolver` (tcp/53), `dns-resolver-udp` (udp/53), `technitium-cluster-https` (tcp/53443).

   ## Dependencies

   - `technitium-stack` (pve) — cluster primary; source of all config and zones.
     Cross-node, so not in `stack.yaml`'s `depends_on`.
   - Harbor (`registry_host`) for the Technitium image pull.
   - `apt-cacher-stack` for package cache during host provisioning.

   ## Persistent State

   | Path | Storage | Contents |
   |---|---|---|
   | Docker named volume `technitium-config` | Docker volume | Not a source of truth: settings, blocklists, apps and zones all come from the cluster primary. A rebuild re-joins the cluster (operator step) and re-syncs. |

   ## Observability and Security

   Same as `technitium-stack`: node_exporter (:9100, TLS + basic auth, from
   `lxc_base`), cAdvisor (:8080, `/opt/cadvisor`), Technitium metrics
   (`/api/dashboard/metrics/text` on :5380, cluster-synced `metrics` token),
   syslog + Docker logs + Technitium server log to Graylog, every DNS query
   via the cluster-synced Log Exporter app to Graylog's "DNS Queries" index
   set, Wazuh agent (FIM on `/opt/technitium-stack`, Docker monitoring),
   unattended upgrades, GVM scanning (mgmt_seg), and LAN access limited to
   DNS by `mikrotik-firewall-technitium-lan.yml`. Dashboard: Grafana
   "Technitium DNS".

   ## What Must Not Be Edited Casually

   - Settings, Allowed, Blocked and Apps are read-only here — change them on
     the primary (`configure-technitium-lan-resolver.yml`).
   - `network_mode: host` is deliberate (see the plan's design decisions);
     do not copy it to other stacks.
   - The image tag must equal `deploy-technitium-stack.yml`'s
     `technitium_image_tag` — cluster nodes must run the same version.
   ```

### lan-dns-15-deploy-playbook

```yaml
id: lan-dns-15-deploy-playbook
title: Add deploy-technitium-tiny-stack.yml
depends_on: [lan-dns-14-stack-files, lan-dns-09-node-observability]

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
  - id: imports-node-observability
    cmd: "grep -v '^[[:space:]]*$' terraform/lxc/ansible/playbooks/deploy-technitium-tiny-stack.yml | tail -n 1 | grep -q 'import_playbook: technitium-node-observability.yml'"
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

   - name: Technitium node observability (docs/lan-dns-technitium/)
     ansible.builtin.import_playbook: technitium-node-observability.yml

   ```

### Operator: create technitium-tiny-stack on pve-tiny

`provision.sh` never runs Terraform — it only runs Ansible against the
inventory that `terragrunt apply` generates — so creation is two commands
(the same pattern `docs/ai-stacks-pve-tiny/` used on this node):

1. Read-only checks: `terragrunt plan` (on the read-only allowlist) must
   show 5 to add, 0 to change/destroy, CT 20017 on pve-tiny at
   192.168.20.17 on `tvmgmt`; `ping -c1 -W1 192.168.20.17` must fail; and
   VMID 20017 must not exist on pve-tiny (`pct list` on the node — the
   pve-tiny secrets profile has no read-only API token, so this is an
   operator check).
   ```bash
   ./with-secrets-prod-tiny terragrunt plan --working-dir terraform/lxc/environments/pve-tiny/technitium-tiny-stack -no-color
   ```
2. Create and start the CT (also attaches it to the SDN vnet and writes
   `inventory.yml`/`network-sdn-vars.yml` in the env dir):
   ```bash
   export TASK_APPROVAL="lan-dns-technitium-tiny-deploy"
   ./with-secrets-prod-tiny terragrunt apply --working-dir terraform/lxc/environments/pve-tiny/technitium-tiny-stack
   ```
3. Deploy Technitium (Ansible: Docker base, Technitium, Wazuh, unattended
   upgrades, node observability; it has no zones until it joins the
   cluster). Edge reconcile and Portainer registration skip on pve-tiny:
   ```bash
   ./with-secrets-prod-tiny scripts/provision.sh --stack technitium-tiny-stack
   unset TASK_APPROVAL
   ```
   (If `ansible-playbook` inside it hits a blocking-IO error, wrap with
   `script -qec '…' /dev/null`, as for `cse-panel-stack`.)

### Operator: form the cluster (one-time, cluster domain is permanent)

Production mutation on both nodes. Do this from the UIs or with these
exact API calls (tokens from `/api/user/login`; `$PW` =
`TECHNITIUM_ADMIN_PASSWORD` via `./with-secrets-prod bash -c`):

1. On the **primary**, initialize (auto-enables HTTPS 53443 with a
   self-signed cert and renames the node to
   `tech.cluster.lab.gibbsgreatly.xyz` — its server domain is
   `tech.lab.gibbsgreatly.xyz`, confirmed live 2026-09-29):
   `POST http://192.168.20.15:5380/api/admin/cluster/init?clusterDomain=cluster.lab.gibbsgreatly.xyz&primaryNodeIpAddresses=192.168.20.15&token=$TP`
2. On the **secondary**, join:
   `POST http://192.168.20.17:5380/api/admin/cluster/initJoin?secondaryNodeIpAddresses=192.168.20.17&primaryNodeUrl=https%3A%2F%2F192.168.20.15%3A53443%2F&primaryNodeIpAddress=192.168.20.15&ignoreCertificateErrors=true&primaryNodeUsername=admin&primaryNodePassword=$PW&token=$TS`
   (`ignoreCertificateErrors=true` is the documented option for a
   self-signed primary on a private network.)
3. Confirm Technitium's Authentik OIDC login at
   `https://technitium.lab.gibbsgreatly.xyz` still works (node rename is
   the one change that could plausibly touch it).
4. Adopt every existing zone into the cluster catalog (Technitium then
   rewrites each Primary zone's apex NS to both nodes and its SOA primary
   to the primary node, and the secondary pulls copies):
   ```bash
   export TASK_APPROVAL="lan-dns-technitium-adopt-zones"
   ./with-secrets-prod ansible-playbook \
     -i terraform/lxc/environments/pve/technitium-stack/inventory.yml \
     terraform/lxc/ansible/playbooks/technitium-cluster-adopt-zones.yml
   ```
5. Prove the **clustered** path of the deploy playbook: re-run
   `./with-secrets-prod scripts/provision.sh --stack technitium-stack`
   (same approval). Expect the standalone NS/SOA block skipped and "Assert
   the cluster manages the parity zone's apex NS and SOA" passing, with no
   failed tasks. A failure here means Phase 1 missed a writer; stop
   before Phase 4.

Rollback: `POST /api/admin/cluster/secondary/leave` on the secondary, then
`/api/admin/cluster/primary/delete` on the primary. The primary keeps all
its zones and settings either way.

### lan-dns-16-monitoring-scrape-dashboard

```yaml
id: lan-dns-16-monitoring-scrape-dashboard
title: Scrape both Technitium nodes and replace the CoreDNS dashboard
depends_on: [lan-dns-13-ip-wiring, lan-dns-11-metrics-token-manifest]

change: >
  In terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml make the
  three replacements in "Literal content: monitoring scrape changes" (each
  "find" block replaced by its "replace" block; 3-space indent stripped),
  delete terraform/lxc/stacks/monitoring-stack/dashboards/coredns.json, and
  create terraform/lxc/stacks/monitoring-stack/dashboards/technitium.json
  with exactly the literal JSON in "Literal content: technitium.json".

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml
    - terraform/lxc/stacks/monitoring-stack/dashboards/coredns.json
    - terraform/lxc/stacks/monitoring-stack/dashboards/technitium.json
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Changing any other scrape job"

gates:
  - id: syntax-check
    cmd: "bash -c 'cd terraform/lxc/ansible && ansible-playbook --syntax-check -i localhost, playbooks/deploy-monitoring-stack.yml'"
    expect: "exit 0"
    critical: true
  - id: coredns-gone
    cmd: "! grep -q 'job_name: coredns' terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml && test ! -e terraform/lxc/stacks/monitoring-stack/dashboards/coredns.json"
    expect: "exit 0"
    critical: true
  - id: technitium-targets
    cmd: "grep -q 'job_name: technitium' terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml && test $(grep -c 'LAB_IP_TECHNITIUM_TINY' terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml) -eq 3"
    expect: "exit 0"
    critical: true
  - id: dashboard-valid
    cmd: "python3 -c \"import json;d=json.load(open('terraform/lxc/stacks/monitoring-stack/dashboards/technitium.json'));assert d['uid']=='technitium' and len(d['panels'])==12\""
    expect: "exit 0"
    critical: true
```

#### Literal content: monitoring scrape changes

Find (node_exporter job, last entry):

   ```yaml
                   - targets: ["{{ lookup('env', 'LAB_IP_OPENBAO') }}:9100"]
                     labels: {stack: openbao-stack}
   ```

Replace with:

   ```yaml
                   - targets: ["{{ lookup('env', 'LAB_IP_OPENBAO') }}:9100"]
                     labels: {stack: openbao-stack}
                   - targets: ["{{ lookup('env', 'LAB_IP_TECHNITIUM') }}:9100"]
                     labels: {stack: technitium-stack}
                   - targets: ["{{ lookup('env', 'LAB_IP_TECHNITIUM_TINY') | mandatory('LAB_IP_TECHNITIUM_TINY env var is required') }}:9100"]
                     labels: {stack: technitium-tiny-stack}
   ```

Find (cadvisor job, last entry):

   ```yaml
                   - targets: ["{{ lookup('env', 'LAB_IP_MEDIA_STACK_LAB') }}:8080"]
                     labels: {stack: media-stack-lab}
   ```

Replace with:

   ```yaml
                   - targets: ["{{ lookup('env', 'LAB_IP_MEDIA_STACK_LAB') }}:8080"]
                     labels: {stack: media-stack-lab}
                   - targets: ["{{ lookup('env', 'LAB_IP_TECHNITIUM') }}:8080"]
                     labels: {stack: technitium-stack}
                   - targets: ["{{ lookup('env', 'LAB_IP_TECHNITIUM_TINY') | mandatory('LAB_IP_TECHNITIUM_TINY env var is required') }}:8080"]
                     labels: {stack: technitium-tiny-stack}
   ```

Find (the dead CoreDNS job):

   ```yaml
               - job_name: coredns
                 scrape_interval: 15s
                 static_configs:
                   - targets:
                       - "{{ lookup('env', 'LAB_IP_DNS') }}:9153"
   ```

Replace with:

   ```yaml
               # Technitium's native Prometheus endpoint (v15.0+). Needs an API
               # token of the Technitium user "metrics" (Dashboard: View only);
               # clustering syncs users and tokens, so one token serves both
               # nodes. Replaces the coredns job (dns-stack destroyed
               # 2026-09-08). docs/lan-dns-technitium/plan.md.
               - job_name: technitium
                 scrape_interval: 15s
                 scheme: http
                 metrics_path: /api/dashboard/metrics/text
                 authorization:
                   credentials: "{{ lookup('env', 'TECHNITIUM_METRICS_TOKEN') | mandatory('TECHNITIUM_METRICS_TOKEN env var is required') }}"
                 static_configs:
                   - targets: ["{{ lookup('env', 'LAB_IP_TECHNITIUM') }}:5380"]
                     labels: {stack: technitium-stack, node: pve}
                   - targets: ["{{ lookup('env', 'LAB_IP_TECHNITIUM_TINY') | mandatory('LAB_IP_TECHNITIUM_TINY env var is required') }}:5380"]
                     labels: {stack: technitium-tiny-stack, node: pve-tiny}
   ```

#### Literal content: technitium.json

   ```json
   {"annotations": {"list": []}, "description": "Technitium DNS cluster (technitium-stack on pve, technitium-tiny-stack on pve-tiny): liveness, query outcomes, blocking, cache, and host/container resources. docs/lan-dns-technitium/plan.md", "editable": true, "graphTooltip": 1, "id": null, "links": [], "refresh": "1m", "schemaVersion": 38, "tags": ["lab", "technitium", "dns"], "templating": {"list": []}, "time": {"from": "now-24h", "to": "now"}, "timepicker": {}, "timezone": "browser", "title": "Technitium DNS", "uid": "technitium", "version": 1, "panels": [
     {"id": 1, "type": "stat", "title": "Node up", "datasource": {"type": "prometheus", "uid": "VictoriaMetrics"}, "gridPos": {"h": 5, "w": 6, "x": 0, "y": 0}, "targets": [{"refId": "A", "expr": "up{job=\"technitium\"}", "legendFormat": "{{node}}"}], "fieldConfig": {"defaults": {"unit": "none", "thresholds": {"mode": "absolute", "steps": [{"color": "red", "value": null}, {"color": "green", "value": 1}]}, "mappings": [{"type": "value", "options": {"0": {"text": "DOWN"}, "1": {"text": "UP"}}}]}, "overrides": []}, "options": {"colorMode": "background", "graphMode": "none", "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": false}, "textMode": "value_and_name"}},
     {"id": 2, "type": "stat", "title": "Blocked (last 1h)", "datasource": {"type": "prometheus", "uid": "VictoriaMetrics"}, "gridPos": {"h": 5, "w": 6, "x": 6, "y": 0}, "targets": [{"refId": "A", "expr": "sum(increase(blocked_total{job=\"technitium\"}[1h])) / clamp_min(sum(increase(queries_total{job=\"technitium\"}[1h])), 1)", "legendFormat": "blocked"}], "fieldConfig": {"defaults": {"unit": "percentunit", "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": null}]}, "decimals": 1}, "overrides": []}, "options": {"colorMode": "background", "graphMode": "none", "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": false}, "textMode": "value_and_name"}},
     {"id": 3, "type": "stat", "title": "Cache hits (last 1h)", "datasource": {"type": "prometheus", "uid": "VictoriaMetrics"}, "gridPos": {"h": 5, "w": 6, "x": 12, "y": 0}, "targets": [{"refId": "A", "expr": "sum(increase(cached_total{job=\"technitium\"}[1h])) / clamp_min(sum(increase(queries_total{job=\"technitium\"}[1h])), 1)", "legendFormat": "cached"}], "fieldConfig": {"defaults": {"unit": "percentunit", "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": null}]}, "decimals": 1}, "overrides": []}, "options": {"colorMode": "background", "graphMode": "none", "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": false}, "textMode": "value_and_name"}},
     {"id": 4, "type": "stat", "title": "SERVFAIL (last 1h)", "datasource": {"type": "prometheus", "uid": "VictoriaMetrics"}, "gridPos": {"h": 5, "w": 6, "x": 18, "y": 0}, "targets": [{"refId": "A", "expr": "sum(increase(server_failure_total{job=\"technitium\"}[1h])) / clamp_min(sum(increase(queries_total{job=\"technitium\"}[1h])), 1)", "legendFormat": "servfail"}], "fieldConfig": {"defaults": {"unit": "percentunit", "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": null}, {"color": "orange", "value": 0.01}, {"color": "red", "value": 0.05}]}, "decimals": 2}, "overrides": []}, "options": {"colorMode": "background", "graphMode": "none", "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": false}, "textMode": "value_and_name"}},
     {"id": 5, "type": "timeseries", "title": "Queries/s by node", "datasource": {"type": "prometheus", "uid": "VictoriaMetrics"}, "gridPos": {"h": 8, "w": 12, "x": 0, "y": 5}, "targets": [{"refId": "A", "expr": "sum by (node) (rate(queries_total{job=\"technitium\"}[5m]))", "legendFormat": "{{node}}"}], "fieldConfig": {"defaults": {"unit": "reqps", "color": {"mode": "palette-classic"}, "custom": {"lineWidth": 1, "fillOpacity": 10}}, "overrides": []}, "options": {"legend": {"calcs": ["mean", "max"], "displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}}},
     {"id": 6, "type": "timeseries", "title": "Responses/s by outcome", "datasource": {"type": "prometheus", "uid": "VictoriaMetrics"}, "gridPos": {"h": 8, "w": 12, "x": 12, "y": 5}, "targets": [{"refId": "A", "expr": "sum(rate(no_error_total{job=\"technitium\"}[5m]))", "legendFormat": "NOERROR"}, {"refId": "B", "expr": "sum(rate(nx_domain_total{job=\"technitium\"}[5m]))", "legendFormat": "NXDOMAIN"}, {"refId": "C", "expr": "sum(rate(server_failure_total{job=\"technitium\"}[5m]))", "legendFormat": "SERVFAIL"}, {"refId": "D", "expr": "sum(rate(refused_total{job=\"technitium\"}[5m]))", "legendFormat": "REFUSED"}, {"refId": "E", "expr": "sum(rate(blocked_total{job=\"technitium\"}[5m]))", "legendFormat": "blocked"}, {"refId": "F", "expr": "sum(rate(dropped_total{job=\"technitium\"}[5m]))", "legendFormat": "dropped"}], "fieldConfig": {"defaults": {"unit": "reqps", "color": {"mode": "palette-classic"}, "custom": {"lineWidth": 1, "fillOpacity": 10}}, "overrides": []}, "options": {"legend": {"calcs": ["mean", "max"], "displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}}},
     {"id": 7, "type": "timeseries", "title": "Answer source/s", "datasource": {"type": "prometheus", "uid": "VictoriaMetrics"}, "gridPos": {"h": 8, "w": 12, "x": 0, "y": 13}, "targets": [{"refId": "A", "expr": "sum(rate(authoritative_total{job=\"technitium\"}[5m]))", "legendFormat": "authoritative"}, {"refId": "B", "expr": "sum(rate(recursive_total{job=\"technitium\"}[5m]))", "legendFormat": "recursive (DoH upstream)"}, {"refId": "C", "expr": "sum(rate(cached_total{job=\"technitium\"}[5m]))", "legendFormat": "cache"}], "fieldConfig": {"defaults": {"unit": "reqps", "color": {"mode": "palette-classic"}, "custom": {"lineWidth": 1, "fillOpacity": 10}}, "overrides": []}, "options": {"legend": {"calcs": ["mean", "max"], "displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}}},
     {"id": 8, "type": "timeseries", "title": "Blocked/s by node", "datasource": {"type": "prometheus", "uid": "VictoriaMetrics"}, "gridPos": {"h": 8, "w": 12, "x": 12, "y": 13}, "targets": [{"refId": "A", "expr": "sum by (node) (rate(blocked_total{job=\"technitium\"}[5m]))", "legendFormat": "{{node}}"}], "fieldConfig": {"defaults": {"unit": "reqps", "color": {"mode": "palette-classic"}, "custom": {"lineWidth": 1, "fillOpacity": 10}}, "overrides": []}, "options": {"legend": {"calcs": ["mean", "max"], "displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}}},
     {"id": 9, "type": "timeseries", "title": "LXC memory used", "datasource": {"type": "prometheus", "uid": "VictoriaMetrics"}, "gridPos": {"h": 8, "w": 12, "x": 0, "y": 21}, "targets": [{"refId": "A", "expr": "node_memory_MemTotal_bytes{job=\"node_exporter\",stack=~\"technitium.*\"} - node_memory_MemAvailable_bytes{job=\"node_exporter\",stack=~\"technitium.*\"}", "legendFormat": "{{stack}}"}], "fieldConfig": {"defaults": {"unit": "bytes", "color": {"mode": "palette-classic"}, "custom": {"lineWidth": 1, "fillOpacity": 10}}, "overrides": []}, "options": {"legend": {"calcs": ["mean", "max"], "displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}}},
     {"id": 10, "type": "timeseries", "title": "Technitium container memory (cAdvisor)", "datasource": {"type": "prometheus", "uid": "VictoriaMetrics"}, "gridPos": {"h": 8, "w": 12, "x": 12, "y": 21}, "targets": [{"refId": "A", "expr": "container_memory_working_set_bytes{job=\"cadvisor\",stack=~\"technitium.*\",name=\"technitium\"}", "legendFormat": "{{stack}}"}], "fieldConfig": {"defaults": {"unit": "bytes", "color": {"mode": "palette-classic"}, "custom": {"lineWidth": 1, "fillOpacity": 10}}, "overrides": []}, "options": {"legend": {"calcs": ["mean", "max"], "displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}}},
     {"id": 11, "type": "timeseries", "title": "LXC CPU busy", "datasource": {"type": "prometheus", "uid": "VictoriaMetrics"}, "gridPos": {"h": 8, "w": 12, "x": 0, "y": 29}, "targets": [{"refId": "A", "expr": "1 - avg by (stack) (rate(node_cpu_seconds_total{job=\"node_exporter\",stack=~\"technitium.*\",mode=\"idle\"}[5m]))", "legendFormat": "{{stack}}"}], "fieldConfig": {"defaults": {"unit": "percentunit", "color": {"mode": "palette-classic"}, "custom": {"lineWidth": 1, "fillOpacity": 10}}, "overrides": []}, "options": {"legend": {"calcs": ["mean", "max"], "displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}}},
     {"id": 12, "type": "timeseries", "title": "Uptime", "datasource": {"type": "prometheus", "uid": "VictoriaMetrics"}, "gridPos": {"h": 8, "w": 12, "x": 12, "y": 29}, "targets": [{"refId": "A", "expr": "uptime_seconds{job=\"technitium\"}", "legendFormat": "{{node}}"}], "fieldConfig": {"defaults": {"unit": "s", "color": {"mode": "palette-classic"}, "custom": {"lineWidth": 1, "fillOpacity": 10}}, "overrides": []}, "options": {"legend": {"calcs": ["mean", "max"], "displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}}}
   ]}
   ```

### Operator: re-provision monitoring-stack

After the cluster exists (so the secondary has the synced `metrics`
token):

```bash
export TASK_APPROVAL="lan-dns-monitoring"
./with-secrets-prod scripts/provision.sh --stack monitoring-stack
```

### lan-dns-17-verify-secondary

```yaml
id: lan-dns-17-verify-secondary
title: Verify the secondary answers identically to the primary
depends_on: [lan-dns-15-deploy-playbook]   # and the two operator sections above

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
    cmd: "test \"$(dig +short @192.168.20.17 googlesyndication.com A)\" = 0.0.0.0"
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
  - id: cluster-owns-lab-ns
    cmd: "test $(dig +short @192.168.20.17 NS lab.gibbsgreatly.xyz | grep -c '\\.cluster\\.lab\\.gibbsgreatly\\.xyz\\.$') -eq 2"
    expect: "exit 0"
    critical: true
  - id: reverse-zone-synced
    cmd: "dig +short @192.168.20.17 -x 192.168.30.10 | grep -q '^traefik\\.lab\\.gibbsgreatly\\.xyz\\.$'"
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

### lan-dns-18-verify-observability

```yaml
id: lan-dns-18-verify-observability
title: Verify both nodes are scraped (Technitium, node_exporter, cAdvisor)
depends_on: [lan-dns-16-monitoring-scrape-dashboard, lan-dns-17-verify-secondary]   # and the monitoring-stack re-provision

change: >
  No file edits. Run the gates from the workstation and record results in
  docs/lan-dns-technitium/README.md's hand-back log.

scope:
  allowed_paths:
    - docs/lan-dns-technitium/README.md
  forbidden_actions:
    - "Any change outside allowed_paths"

gates:
  - id: technitium-job-up
    cmd: "curl -s -m 10 http://192.168.20.12:8428/api/v1/query --data-urlencode 'query=sum(up{job=\"technitium\"})' | python3 -c \"import sys,json;r=json.load(sys.stdin)['data']['result'];assert r and float(r[0]['value'][1])==2,r\""
    expect: "exit 0"
    critical: true
  - id: node-exporter-up
    cmd: "curl -s -m 10 http://192.168.20.12:8428/api/v1/query --data-urlencode 'query=sum(up{job=\"node_exporter\",stack=~\"technitium.*\"})' | python3 -c \"import sys,json;r=json.load(sys.stdin)['data']['result'];assert r and float(r[0]['value'][1])==2,r\""
    expect: "exit 0"
    critical: true
  - id: cadvisor-up
    cmd: "curl -s -m 10 http://192.168.20.12:8428/api/v1/query --data-urlencode 'query=sum(up{job=\"cadvisor\",stack=~\"technitium.*\"})' | python3 -c \"import sys,json;r=json.load(sys.stdin)['data']['result'];assert r and float(r[0]['value'][1])==2,r\""
    expect: "exit 0"
    critical: true
  - id: queries-counted
    cmd: "curl -s -m 10 http://192.168.20.12:8428/api/v1/query --data-urlencode 'query=count(queries_total{job=\"technitium\"})' | python3 -c \"import sys,json;r=json.load(sys.stdin)['data']['result'];assert r and float(r[0]['value'][1])==2,r\""
    expect: "exit 0"
    critical: true
```

### Operator: security and ops checklist (both nodes)

- **Wazuh:** both `technitium-stack` and `technitium-tiny-stack` show as
  **active** agents in the Wazuh dashboard (the primary was enrolled in the
  2026-08-29 pilot; tiny enrolls via its deploy playbook — mgmt_seg →
  `192.168.40.15:1514/1515` is already allowed at the MikroTik).
- **Graylog:** "DNS Queries" has messages from **both** hosts with
  `dns_*` fields (the Log Exporter config is cluster-synced; each node
  ships via its own rsyslog).
- **Grafana:** the "Technitium DNS" dashboard shows both nodes UP; the old
  "CoreDNS" dashboard is gone.
- **GVM:** `192.168.20.17` appears in the next scheduled mgmt_seg scan
  report (the scan scope is the whole `192.168.20.0/24`; nothing to add).
- **Backups:** the pve-tiny PBS backup job includes VMID `20017` (if the
  job lists VMIDs rather than "all", add it), and pve's job still covers
  `20015`. Read-only check through `./with-secrets-prod-tiny python3`
  against `/cluster/backup`.
- **NetBox:** the next `netbox-populate` run lists `technitium-tiny-stack`
  (it syncs from Proxmox; no manual entry).
- **Harbor:** the `technitium/dns-server:15.2.0` and cAdvisor images are
  pulled through Harbor's proxy cache, so they are in its vulnerability
  scans already; check the dashboard for Critical findings on either.

### Operator: failover drill (before the LAN depends on it)

Prove the table in "Failover behavior" rather than assume it. With
approval, on pve: `pct exec 20015 -- docker stop technitium`, then from
the workstation re-run `lan-dns-17`'s gates against `192.168.20.17` —
blocking, `traefik.lab.gibbsgreatly.xyz`, `pve.gibbsgreatly.xyz` and
`github.com` must all still answer. Then
`pct exec 20015 -- docker start technitium` and confirm the primary's
Cluster page shows the secondary `Connected`. Nothing on the LAN uses
either node yet, so the drill has no client impact; the router's `lab`
FWD rule does briefly lose its target, so keep it short (under a
minute) and do it outside CI runs.

---

## Phase 4 — Point the LAN at Technitium

### lan-dns-19-mikrotik-playbook

```yaml
id: lan-dns-19-mikrotik-playbook
title: Add mikrotik-lan-dns-resolver.yml (cutover + rollback in one playbook)
depends_on: [lan-dns-13-ip-wiring]

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
   # docs/lan-dns-technitium/plan.md, Phase 4.
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
           test "$(dig +short @{{ item }} googlesyndication.com A)" = 0.0.0.0
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

### lan-dns-20-mikrotik-firewall-lan

```yaml
id: lan-dns-20-mikrotik-firewall-lan
title: Add mikrotik-firewall-technitium-lan.yml (LAN may reach Technitium on DNS only)
depends_on: [lan-dns-13-ip-wiring]

change: >
  Create ansible/00-initial-setup/mikrotik-firewall-technitium-lan.yml with
  exactly the literal content (with its 3-space indent stripped) in
  "Literal content: mikrotik-firewall-technitium-lan.yml".

scope:
  allowed_paths:
    - ansible/00-initial-setup/mikrotik-firewall-technitium-lan.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Running the playbook"

gates:
  - id: syntax-check
    cmd: "ansible-playbook --syntax-check -i localhost, ansible/00-initial-setup/mikrotik-firewall-technitium-lan.yml"
    expect: "exit 0"
    critical: true
  - id: drop-is-new-only
    cmd: "grep -q 'connection-state: new' ansible/00-initial-setup/mikrotik-firewall-technitium-lan.yml && grep -q 'technitium_lan_workstation: \"192.168.1.104\"' ansible/00-initial-setup/mikrotik-firewall-technitium-lan.yml"
    expect: "exit 0"
    critical: true
```

#### Literal content: mikrotik-firewall-technitium-lan.yml

   ```yaml
   ---
   # mikrotik-firewall-technitium-lan.yml
   #
   # Once the whole LAN uses Technitium (docs/lan-dns-technitium/plan.md,
   # Phase 4), LAN devices may reach the two Technitium nodes on DNS only.
   # The operator workstation keeps full access (Ansible SSH, 5380 admin UI,
   # 53443 cluster UI); normal admin goes through
   # https://technitium.lab.gibbsgreatly.xyz (Traefik + Authentik OIDC).
   # Scoped to the two Technitium IPs via an address list, so no other
   # bridgeLocal -> mgmt_seg access changes. The drop only matches NEW
   # connections, so return traffic is never affected.
   #
   # Usage (run from the repo root):
   #   ./with-secrets ansible-playbook ansible/00-initial-setup/mikrotik-firewall-technitium-lan.yml
   #   ./with-secrets ansible-playbook ansible/00-initial-setup/mikrotik-firewall-technitium-lan.yml -e technitium_lan_state=absent   # rollback

   - name: Restrict LAN access to the Technitium nodes to DNS
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
       technitium_lan_effective_state: "{{ technitium_lan_state | default('present') }}"
       technitium_lan_list: "technitium-dns"
       technitium_lan_comment_prefix: "technitium-lan:"
       technitium_lan_ips:
         - "{{ lookup('env', 'LAB_IP_TECHNITIUM') | mandatory('LAB_IP_TECHNITIUM env var is required') }}"
         - "{{ lookup('env', 'LAB_IP_TECHNITIUM_TINY') | mandatory('LAB_IP_TECHNITIUM_TINY env var is required') }}"
       technitium_lan_subnet: "192.168.1.0/24"
       technitium_lan_workstation: "192.168.1.104"
       # Order matters: accepts first, drop last. Each is inserted before the
       # first existing forward drop/reject, which preserves this order.
       technitium_lan_rules:
         - chain: forward
           action: accept
           src-address: "{{ technitium_lan_subnet }}"
           dst-address-list: "{{ technitium_lan_list }}"
           protocol: udp
           dst-port: "53"
           comment: "technitium-lan: LAN to Technitium DNS udp/53"
         - chain: forward
           action: accept
           src-address: "{{ technitium_lan_subnet }}"
           dst-address-list: "{{ technitium_lan_list }}"
           protocol: tcp
           dst-port: "53"
           comment: "technitium-lan: LAN to Technitium DNS tcp/53"
         - chain: forward
           action: accept
           src-address: "{{ technitium_lan_workstation }}"
           dst-address-list: "{{ technitium_lan_list }}"
           comment: "technitium-lan: operator workstation (garuda) full access"
         - chain: forward
           action: drop
           src-address: "{{ technitium_lan_subnet }}"
           dst-address-list: "{{ technitium_lan_list }}"
           connection-state: new
           comment: "technitium-lan: LAN default-deny to Technitium (admin via technitium.lab)"

     pre_tasks:
       - name: Assert MikroTik credentials are set
         ansible.builtin.assert:
           that:
             - mikrotik_password | length > 0
             - mikrotik_user | length > 0

       - name: Assert a known state was requested
         ansible.builtin.assert:
           that:
             - technitium_lan_effective_state in ['present', 'absent']

     tasks:
       - name: Read firewall address lists
         ansible.builtin.uri:
           url: "{{ mikrotik_rest_base_url }}/ip/firewall/address-list"
           method: GET
           user: "{{ mikrotik_user }}"
           password: "{{ mikrotik_password }}"
           force_basic_auth: true
           validate_certs: false  # nosonar: ansible:S4830 — MikroTik self-signed cert; HTTPS traffic still encrypted; private network
           return_content: true
         register: technitium_lan_address_lists
         no_log: true

       - name: Read firewall filter rules
         ansible.builtin.uri:
           url: "{{ mikrotik_rest_base_url }}/ip/firewall/filter"
           method: GET
           user: "{{ mikrotik_user }}"
           password: "{{ mikrotik_password }}"
           force_basic_auth: true
           validate_certs: false  # nosonar: ansible:S4830 — MikroTik self-signed cert; HTTPS traffic still encrypted; private network
           return_content: true
         register: technitium_lan_filters
         no_log: true

       - name: Add missing address-list entries
         ansible.builtin.uri:
           url: "{{ mikrotik_rest_base_url }}/ip/firewall/address-list/add"
           method: POST
           user: "{{ mikrotik_user }}"
           password: "{{ mikrotik_password }}"
           force_basic_auth: true
           validate_certs: false  # nosonar: ansible:S4830 — MikroTik self-signed cert; HTTPS traffic still encrypted; private network
           body_format: json
           body:
             list: "{{ technitium_lan_list }}"
             address: "{{ item }}"
             comment: "{{ technitium_lan_comment_prefix }} Technitium DNS node"
           status_code: [200, 201]
         loop: "{{ technitium_lan_ips }}"
         when:
           - technitium_lan_effective_state == 'present'
           - >-
             technitium_lan_address_lists.json
             | selectattr('list', 'equalto', technitium_lan_list)
             | selectattr('address', 'equalto', item) | list | length == 0
         no_log: true

       - name: Find the first forward drop/reject rule for ordered insertion
         ansible.builtin.set_fact:
           technitium_lan_anchor: >-
             {{
               (technitium_lan_filters.json
                 | selectattr('chain', 'defined') | selectattr('chain', 'equalto', 'forward')
                 | selectattr('action', 'defined') | selectattr('action', 'in', ['drop', 'reject'])
                 | list) | first | default({})
             }}

       - name: Add missing rules
         ansible.builtin.uri:
           url: "{{ mikrotik_rest_base_url }}/ip/firewall/filter/add"
           method: POST
           user: "{{ mikrotik_user }}"
           password: "{{ mikrotik_password }}"
           force_basic_auth: true
           validate_certs: false  # nosonar: ansible:S4830 — MikroTik self-signed cert; HTTPS traffic still encrypted; private network
           body_format: json
           body: >-
             {{
               item | combine({'place-before': technitium_lan_anchor['.id']})
               if technitium_lan_anchor != {} else item
             }}
           status_code: [200, 201]
         loop: "{{ technitium_lan_rules }}"
         loop_control:
           label: "{{ item.comment }}"
         when:
           - technitium_lan_effective_state == 'present'
           - >-
             technitium_lan_filters.json
             | selectattr('comment', 'defined')
             | selectattr('comment', 'equalto', item.comment) | list | length == 0
         no_log: true

       - name: Remove filter entries (rollback)
         ansible.builtin.uri:
           url: "{{ mikrotik_rest_base_url }}/ip/firewall/filter/{{ item['.id'] }}"
           method: DELETE
           user: "{{ mikrotik_user }}"
           password: "{{ mikrotik_password }}"
           force_basic_auth: true
           validate_certs: false  # nosonar: ansible:S4830 — MikroTik self-signed cert; HTTPS traffic still encrypted; private network
           status_code: [200, 204]
         loop: "{{ technitium_lan_filters.json | selectattr('comment', 'defined') | selectattr('comment', 'match', technitium_lan_comment_prefix) | list }}"
         loop_control:
           label: "{{ item.comment }}"
         when: technitium_lan_effective_state == 'absent'
         no_log: true

       - name: Remove address-list entries (rollback)
         ansible.builtin.uri:
           url: "{{ mikrotik_rest_base_url }}/ip/firewall/address-list/{{ item['.id'] }}"
           method: DELETE
           user: "{{ mikrotik_user }}"
           password: "{{ mikrotik_password }}"
           force_basic_auth: true
           validate_certs: false  # nosonar: ansible:S4830 — MikroTik self-signed cert; HTTPS traffic still encrypted; private network
           status_code: [200, 204]
         loop: "{{ technitium_lan_address_lists.json | selectattr('comment', 'defined') | selectattr('comment', 'match', technitium_lan_comment_prefix) | list }}"
         loop_control:
           label: "{{ item.comment }}"
         when: technitium_lan_effective_state == 'absent'
         no_log: true

       - name: Re-read firewall filter rules
         ansible.builtin.uri:
           url: "{{ mikrotik_rest_base_url }}/ip/firewall/filter"
           method: GET
           user: "{{ mikrotik_user }}"
           password: "{{ mikrotik_password }}"
           force_basic_auth: true
           validate_certs: false  # nosonar: ansible:S4830 — MikroTik self-signed cert; HTTPS traffic still encrypted; private network
           return_content: true
         register: technitium_lan_filters_after
         no_log: true

       - name: Assert the rules are in the requested state and correctly ordered
         ansible.builtin.assert:
           that:
             - (technitium_lan_forward | length) == ((technitium_lan_rules | length) if technitium_lan_effective_state == 'present' else 0)
             - technitium_lan_effective_state == 'absent' or (technitium_lan_forward | last).action == 'drop'
         vars:
           technitium_lan_forward: >-
             {{
               technitium_lan_filters_after.json | selectattr('comment', 'defined')
               | selectattr('comment', 'match', technitium_lan_comment_prefix) | list
             }}

       - name: DNS still answers from this workstation
         ansible.builtin.shell: |
           set -euo pipefail
           dig @{{ item }} github.com A | grep -q 'status: NOERROR'
           dig +tcp @{{ item }} github.com A | grep -q 'status: NOERROR'
         args:
           executable: /bin/bash
         loop: "{{ technitium_lan_ips }}"
         changed_when: false
         when: technitium_lan_effective_state == 'present'
   ```

### Operator: cutover

Preflight/approval (MikroTik is production), then — access lockdown
first, so no LAN device ever reaches the admin ports of a server it has
just been told to use:

```bash
export TASK_APPROVAL="lan-dns-cutover"
./with-secrets ansible-playbook ansible/00-initial-setup/mikrotik-firewall-technitium-lan.yml
./with-secrets ansible-playbook ansible/00-initial-setup/mikrotik-lan-dns-resolver.yml
```

Check the lockdown from a phone on WiFi: `http://192.168.20.15:5380` must
time out, while DNS works and `https://technitium.lab.gibbsgreatly.xyz`
still loads (through Traefik, not the blocked port). Rollback for the
lockdown alone: the same playbook with `-e technitium_lan_state=absent`.

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

### lan-dns-21-docs-after-cutover

```yaml
id: lan-dns-21-docs-after-cutover
title: Record the cutover in router and network docs
depends_on: [lan-dns-19-mikrotik-playbook]   # and the operator cutover

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

## Phase 5 — Retire the Pis (after the soak)

### Operator: decommission

1. Power off argon-02 and argon-01 (`sudo poweroff` on each). Keep the SD
   cards for a month as a last-resort rollback.
2. Remove the router's Pi-specific config (production, approval):
   static DHCP leases for `E4:5F:01:0A:56:E1` / `E4:5F:01:F4:A4:88`,
   static DNS entries `argon-01.lan.local` / `argon-02.lan.local` (A and
   AAAA), and the `fd00::22`/`fd00::23` list on the `bridgeLocal` ND entry
   (only now — it was the rollback target until here). After this, the
   `pihole` mode of `mikrotik-lan-dns-resolver.yml` no longer works.

### lan-dns-22-docs-retire

```yaml
id: lan-dns-22-docs-retire
title: Remove the Pi-holes from router and DHCP-refactor docs
depends_on: [lan-dns-21-docs-after-cutover]   # and the operator decommission

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

## Phase 6 — DHCP to Technitium (independent track)

The DHCP migration is already fully planned in `docs/dhcp-refactor/`
(Stages A–D done and validated; Stage E cutover packet drafted, Stage F =
7-day soak). **It does not depend on Phases 0–4 and they don't depend on
it.** The only coupling point is the DHCP scope's DNS-server option: it
must hand out whatever the MikroTik hands out at the moment of the DHCP
cutover. Phase 6 can therefore run before, during, or after the DNS
work — but not in the same change window as the Phase 4 cutover, so a
problem is attributable to one change.

### lan-dns-23-dhcp-dns-option

```yaml
id: lan-dns-23-dhcp-dns-option
title: Decouple the DHCP cutover packet's DNS option from the Pi-holes
depends_on: []

change: >
  (1) Append to docs/dhcp-refactor/decisions.md, before the "## Format"
  heading, the literal "Decision 9" section (with its 3-space indent stripped) in "Literal content: DHCP
  Decision 9". (2) In docs/dhcp-refactor/bridgelocal-cutover-packet.md,
  replace the DNS-server option table row's value and source cells
  ("`192.168.1.22`" and its note) with: value "**read live at execution
  time**: the MikroTik `lan` network's current `dns-server` (`192.168.1.23`
  before docs/lan-dns-technitium/ Phase 4, `192.168.20.15,192.168.20.17`
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
argon-01 reservation row, which `lan-dns-22` removes later if Phase 5
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
`add-dns-entries-suffix`, recommended, since Phase 2 already forwards
`lan` to the router and it would simply move to being Technitium-owned)
and the reverse-zone naming for `1.168.192.in-addr.arpa` — note Phase 2
creates that name as a **Forwarder** zone to the router, so the DHCP
scope's reverse zone requires converting it to a Primary zone at Stage E
(delete the forwarder, let the scope create the Primary), and likewise
for `lan`.

When Stage E adapts `configure-technitium-dhcp-scope-via-api.yml` for the
production `bridgeLocal` scope, its zone creation must go through the
`technitium_zone` role (Phase 1), so the scope's forward and reverse zones
join the cluster catalog and DHCP-driven A/PTR records reach the
secondary like every other zone.

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
- **Alerting.** None exists anywhere on the platform; this plan adds
  dashboards only (operator, 2026-09-29). Obvious first rules once a
  contact point exists: `up{job="technitium"} == 0` for 5m, SERVFAIL ratio
  above 5%, no `blocked_total` increase for 24h (blocklists failed to
  load).
- **pve-tiny has no read-only Proxmox API token** in its secrets profile
  (only the automation token), so read-only checks against pve-tiny can't
  follow CLAUDE.md's read-only-token rule. Adding `PROXMOX_READONLY_TOKEN_ID`
  / `_SECRET` to `hosts/pve-tiny` (and the profile) would fix that.

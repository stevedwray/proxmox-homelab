# Plan: reverse DNS (PTR) for Technitium A records

Status: **ready to execute** -- researched, all literal content below has been
applied to real copies of the target files and validated (syntax-check,
ansible-lint, `python3 -m unittest`, `ruff`) before being written into this
plan. See `README.md` for the current per-step status and hand-backs.

## Design decisions (operator-approved)

1. **Shared-IP PTR ownership**: when multiple A records share one IP (every
   browser-routed hostname behind Traefik shares `LAB_IP_PROXY`), the PTR for
   that IP belongs to the record that is genuinely that IP's owner --
   proxy-stack's own `traefik` record. Every other record sharing the IP gets
   `ptr: false`. This is not a special case bolted on top; it's the general
   rule (see decision 2's tiebreak order) applied to the group that happens to
   be biggest.
2. **Mechanism**: one shared Ansible role (`technitium_dns_record`) is the
   only code that ever calls Technitium's `zones/records/add` for an A or PTR
   record. All three existing DNS-record call sites (the edge-manifest
   bootstrap/parity-zone publish in `deploy-technitium-stack.yml`, and the two
   ad-hoc `configure-*-dns-records.yml` playbooks) are refactored onto it.
   This also fixes the pre-existing drift between them (one used `GET` +
   `overwrite=true`, the other `POST` + idempotency-check) by standardizing on
   the safer, already-proven `POST` + query-before-add pattern.
3. **Scope**: reverse zones are created automatically (on demand, from
   whichever record set is actually being published) for every /24 that owns
   at least one `ptr: true` record -- in practice `mgmt_seg` (192.168.20.0/24),
   `edge_seg` (192.168.30.0/24), `infra_seg` (192.168.40.0/24), the AI-services
   subnet (192.168.50.0/24), and `game_seg` (192.168.60.0/24). No hardcoded
   subnet list exists anywhere; the role derives the reverse zone from each
   qualifying record's own IP.

## A real design finding from validating this plan (read before touching bootstrap-zone code)

`deploy-technitium-stack.yml` publishes records into **two** zones on every
run: the short-lived `tech.<domain>` **bootstrap zone** (parity/validation
only, never authoritative) and the real production **parity zone**
(`<domain>`, e.g. `lab.gibbsgreatly.xyz`). Both zones' `dns`/`traefik`/etc.
records point at the *same physical IPs* -- just under two different forward
names. A PTR record is one name per IP, so if both zones tried to own PTRs
for those IPs, whichever published second would either silently fight the
first or create two competing PTR records for one address.

**Resolution**: only the parity zone (the real production namespace) creates
PTR records. Every bootstrap-zone record is `ptr: false`, unconditionally.
This is already reflected in the literal content below -- do not "fix" it by
setting any bootstrap-zone record's `ptr: true`.

## Steps

### dns-reverse-01-shared-role

```yaml
id: dns-reverse-01-shared-role
title: Create the shared technitium_dns_record Ansible role
depends_on: []

change: >
  Create terraform/lxc/ansible/roles/technitium_dns_record/defaults/main.yml
  with exactly this content:

    ---
    technitium_dns_record_records: []

  Create terraform/lxc/ansible/roles/technitium_dns_record/tasks/main.yml
  with exactly this content:

    ---
    # technitium_dns_record: idempotently publish one or more Technitium A
    # records, and (where the record's own IP is uniquely owned by it) a
    # matching PTR record in the appropriate /24 reverse zone.
    #
    # Callers must already be logged in to the Technitium API and provide
    # technitium_api_base / technitium_token (this role never logs in itself,
    # matching every existing call site's own login task).
    #
    # Required var: technitium_dns_record_records -- list of:
    #   - name: <label, e.g. "dns">
    #     zone: <forward zone this record is published in, e.g. "tech.lab.gibbsgreatly.xyz">
    #     ip: <IPv4 address, e.g. "192.168.20.15">
    #     ptr: <bool -- true only for the ONE record that should own the
    #           reverse (PTR) entry for this IP. When two or more records
    #           share the same IP (e.g. every browser-routed hostname behind
    #           Traefik), exactly one of them must set ptr: true and the
    #           rest must set ptr: false -- PTR is one name per IP, it
    #           cannot represent every A record pointing at that IP.>
    #
    # Assumes every record's IP falls in a /24 subnet (true for every SDN VLAN
    # segment this repo defines -- see docs/design/network.md); the reverse
    # zone is derived from the IP's first three octets.

    - name: Determine distinct /24 reverse zones needed for this record set
      ansible.builtin.set_fact:
        technitium_dns_record_reverse_zones_needed: >-
          {{
            technitium_dns_record_records
            | selectattr('ptr', 'equalto', true)
            | map(attribute='ip')
            | map('regex_replace', '^(\d+\.\d+\.\d+)\.\d+$', '\1.0/24')
            | unique
            | list
          }}

    - name: List existing Technitium zones before reverse-zone reconciliation
      ansible.builtin.uri:
        url: "{{ technitium_api_base }}/zones/list?token={{ technitium_token }}"
        method: GET
        return_content: true
      register: technitium_dns_record_zone_list
      no_log: true

    - name: Create missing reverse zones for this record set
      ansible.builtin.uri:
        url: "{{ technitium_api_base }}/zones/create?zone={{ item | urlencode }}&type=Primary&token={{ technitium_token }}"
        method: POST
        status_code: [200]
      loop: "{{ technitium_dns_record_reverse_zones_needed }}"
      loop_control:
        label: "{{ item }}"
      when: >-
        (item | regex_replace('^(\d+)\.(\d+)\.(\d+)\.0/24$', '\3.\2.\1.in-addr.arpa'))
        not in ((technitium_dns_record_zone_list.content | from_json).response.zones | map(attribute='name') | list)
      no_log: true

    - name: Query current A records before publishing
      ansible.builtin.uri:
        url: "{{ technitium_api_base }}/zones/records/get?zone={{ item.zone }}&domain={{ item.name }}.{{ item.zone }}&listZone=false&token={{ technitium_token }}"
        method: GET
        return_content: true
      loop: "{{ technitium_dns_record_records }}"
      loop_control:
        label: "{{ item.name }}.{{ item.zone }}"
      register: technitium_dns_record_existing_a
      retries: 10
      delay: 2
      until: technitium_dns_record_existing_a is not failed
      no_log: true

    - name: Publish A records
      ansible.builtin.uri:
        url: "{{ technitium_api_base }}/zones/records/add?domain={{ item.item.name }}.{{ item.item.zone }}&zone={{ item.item.zone }}&type=A&ipAddress={{ item.item.ip }}&token={{ technitium_token }}"
        method: POST
        status_code: [200]
        return_content: true
      loop: "{{ technitium_dns_record_existing_a.results }}"
      loop_control:
        label: "{{ item.item.name }}.{{ item.item.zone }} -> {{ item.item.ip }}"
      when: >-
        (item.content | from_json).response.records
        | selectattr('type', 'equalto', 'A')
        | selectattr('rData.ipAddress', 'equalto', item.item.ip)
        | list
        | length == 0
      failed_when: >-
        (technitium_dns_record_publish_a.content | from_json).status != 'ok'
      register: technitium_dns_record_publish_a
      no_log: true

    - name: Query current PTR records before publishing
      ansible.builtin.uri:
        url: >-
          {{ technitium_api_base }}/zones/records/get?zone={{ item.ip | regex_replace('^(\d+)\.(\d+)\.(\d+)\.\d+$', '\3.\2.\1.in-addr.arpa') }}&domain={{ item.ip | regex_replace('^(\d+)\.(\d+)\.(\d+)\.(\d+)$', '\4.\3.\2.\1.in-addr.arpa') }}&listZone=false&token={{ technitium_token }}
        method: GET
        return_content: true
      loop: "{{ technitium_dns_record_records | selectattr('ptr', 'equalto', true) | list }}"
      loop_control:
        label: "{{ item.ip }} -> {{ item.name }}.{{ item.zone }}"
      register: technitium_dns_record_existing_ptr
      retries: 10
      delay: 2
      until: technitium_dns_record_existing_ptr is not failed
      no_log: true

    - name: Publish PTR records
      ansible.builtin.uri:
        url: >-
          {{ technitium_api_base }}/zones/records/add?domain={{ item.item.ip | regex_replace('^(\d+)\.(\d+)\.(\d+)\.(\d+)$', '\4.\3.\2.\1.in-addr.arpa') }}&zone={{ item.item.ip | regex_replace('^(\d+)\.(\d+)\.(\d+)\.\d+$', '\3.\2.\1.in-addr.arpa') }}&type=PTR&ptrName={{ item.item.name }}.{{ item.item.zone }}&token={{ technitium_token }}
        method: POST
        status_code: [200]
        return_content: true
      loop: "{{ technitium_dns_record_existing_ptr.results }}"
      loop_control:
        label: "{{ item.item.ip }} -> {{ item.item.name }}.{{ item.item.zone }}"
      when: >-
        (item.content | from_json).response.records
        | selectattr('type', 'equalto', 'PTR')
        | selectattr('rData.ptrName', 'equalto', item.item.name ~ '.' ~ item.item.zone)
        | list
        | length == 0
      failed_when: >-
        (technitium_dns_record_publish_ptr.content | from_json).status != 'ok'
      register: technitium_dns_record_publish_ptr
      no_log: true

  Do not add a login task to this role -- every existing call site already
  logs in itself and passes technitium_api_base/technitium_token in.

scope:
  allowed_paths:
    - terraform/lxc/ansible/roles/technitium_dns_record/
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Adding a login/token task to this role"
    - "Any provision.sh / ansible-playbook run against a real host -- syntax/lint only in this step"

gates:
  - id: yaml-loads
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/ansible/roles/technitium_dns_record/tasks/main.yml'))\""
    expect: "exit 0"
    critical: true
  - id: role-lints-clean
    cmd: "ansible-lint terraform/lxc/ansible/roles/technitium_dns_record"
    expect: "exit 0 (0 failures; line-length/var-naming warnings are pre-existing repo-wide warn_list entries in .ansible-lint, not new failures)"
    critical: true
```

### dns-reverse-02-render-edge-ptr-logic

```yaml
id: dns-reverse-02-render-edge-ptr-logic
title: Add PTR-ownership assignment to render-edge-technitium.py
depends_on: []

change: >
  Edit terraform/lxc/render-edge-technitium.py with these exact changes:

  1. Change the dataclasses import line from:

       from dataclasses import asdict, dataclass

     to:

       from dataclasses import asdict, dataclass, replace

  2. Change the RenderedRecord and GeneratedRecord dataclasses from:

       @dataclass(frozen=True)
       class RenderedRecord:
           name: str
           ip: str
           host: str
           source: str


       @dataclass(frozen=True)
       class GeneratedRecord:
           host: str
           ttl: str
           target: str
           manifest: str

     to:

       @dataclass(frozen=True)
       class RenderedRecord:
           name: str
           ip: str
           host: str
           source: str
           stack: str | None = None
           ptr: bool = False


       @dataclass(frozen=True)
       class GeneratedRecord:
           host: str
           ttl: str
           target: str
           manifest: str
           stack: str

  3. Change _manifest_routes_for_generation and _generated_record_from_route
     (and their one call site in _collect_generated_records) from:

       def _manifest_routes_for_generation(
           manifest_path: Path,
           issues: list[RenderIssue],
       ) -> list[dict[str, object]]:
           document = load_manifest(manifest_path)
           if not isinstance(document, dict):
               issues.append(RenderIssue(code="TDR100", message="manifest top-level must be a mapping", manifest=str(manifest_path)))
               return []

           spec = document.get("spec")
           if not isinstance(spec, dict):
               issues.append(RenderIssue(code="TDR101", message="manifest spec must be a mapping", manifest=str(manifest_path)))
               return []

           routes = spec.get("routes")
           if not isinstance(routes, list):
               issues.append(RenderIssue(code="TDR102", message="manifest spec.routes must be a list", manifest=str(manifest_path)))
               return []

           return [route for route in routes if isinstance(route, dict)]


       def _generated_record_from_route(route: dict[str, object], manifest_path: Path) -> GeneratedRecord | None:
           dns = route.get("dns")
           if not isinstance(dns, dict) or dns.get("enabled") is not True:
               return None

           host = str(route.get("host", "")).strip().rstrip(".")
           if not host:
               return None

           return GeneratedRecord(
               host=host,
               ttl=str(dns.get("ttl", "")).strip(),
               target=str(dns.get("target", "")).strip(),
               manifest=str(manifest_path),
           )


       def _collect_generated_records(
           manifest_paths: list[Path],
           issues: list[RenderIssue],
       ) -> tuple[GeneratedRecord, ...]:
           records: list[GeneratedRecord] = []
           host_index: dict[str, str] = {}

           for manifest_path in sorted(manifest_paths):
               for route in _manifest_routes_for_generation(manifest_path, issues):
                   record = _generated_record_from_route(route, manifest_path)
                   if record is None:
                       continue

     to:

       def _manifest_routes_for_generation(
           manifest_path: Path,
           issues: list[RenderIssue],
       ) -> tuple[str, list[dict[str, object]]]:
           document = load_manifest(manifest_path)
           if not isinstance(document, dict):
               issues.append(RenderIssue(code="TDR100", message="manifest top-level must be a mapping", manifest=str(manifest_path)))
               return "", []

           spec = document.get("spec")
           if not isinstance(spec, dict):
               issues.append(RenderIssue(code="TDR101", message="manifest spec must be a mapping", manifest=str(manifest_path)))
               return "", []

           routes = spec.get("routes")
           if not isinstance(routes, list):
               issues.append(RenderIssue(code="TDR102", message="manifest spec.routes must be a list", manifest=str(manifest_path)))
               return "", []

           metadata = document.get("metadata")
           stack = str(metadata.get("stack", "")).strip() if isinstance(metadata, dict) else ""

           return stack, [route for route in routes if isinstance(route, dict)]


       def _generated_record_from_route(route: dict[str, object], manifest_path: Path, stack: str) -> GeneratedRecord | None:
           dns = route.get("dns")
           if not isinstance(dns, dict) or dns.get("enabled") is not True:
               return None

           host = str(route.get("host", "")).strip().rstrip(".")
           if not host:
               return None

           return GeneratedRecord(
               host=host,
               ttl=str(dns.get("ttl", "")).strip(),
               target=str(dns.get("target", "")).strip(),
               manifest=str(manifest_path),
               stack=stack,
           )


       def _collect_generated_records(
           manifest_paths: list[Path],
           issues: list[RenderIssue],
       ) -> tuple[GeneratedRecord, ...]:
           records: list[GeneratedRecord] = []
           host_index: dict[str, str] = {}

           for manifest_path in sorted(manifest_paths):
               stack, routes = _manifest_routes_for_generation(manifest_path, issues)
               for route in routes:
                   record = _generated_record_from_route(route, manifest_path, stack)
                   if record is None:
                       continue

     Use the manifest's own metadata.stack field (not the manifest file's
     directory name) -- directory-name inference is wrong for manifests
     that don't live at stacks/<stack>/edge.yaml, including this repo's own
     test fixtures under docs/provisioning-refactor/fixtures/.

  4. In _render_records_from_seed, change the generated-record construction
     and the function's final two lines from:

       rendered_records.append(
           RenderedRecord(name=label, ip=generated.target, host=generated.host, source="generated")
       )

       rendered_records.sort(key=lambda record: record.host)
       return origin, tuple(rendered_records)

     to:

       rendered_records.append(
           RenderedRecord(
               name=label,
               ip=generated.target,
               host=generated.host,
               source="generated",
               stack=generated.stack,
           )
       )

       rendered_records.sort(key=lambda record: record.host)
       return origin, _assign_ptr_ownership(tuple(rendered_records))


       def _assign_ptr_ownership(records: tuple[RenderedRecord, ...]) -> tuple[RenderedRecord, ...]:
           """Pick exactly one PTR owner per distinct IP.

           A PTR record is one name per IP, so when multiple A records share an
           IP (every browser-routed hostname behind Traefik shares LAB_IP_PROXY,
           for instance) only one of them can own the reverse entry. Preference
           order: the record generated from proxy-stack's own edge.yaml (that
           IP is genuinely proxy-stack's), else the record named "dns" (covers
           the dns/ns1 pair sharing LAB_IP_TECHNITIUM), else the
           alphabetically-first name in the group -- deterministic, so re-runs
           never flip which name owns an existing PTR.
           """
           by_ip: dict[str, list[RenderedRecord]] = {}
           for record in records:
               by_ip.setdefault(record.ip, []).append(record)

           ptr_owners: set[RenderedRecord] = set()
           for group in by_ip.values():
               proxy_owned = [r for r in group if r.stack == "proxy-stack"]
               dns_named = [r for r in group if r.name == "dns"]
               if proxy_owned:
                   ptr_owners.add(proxy_owned[0])
               elif dns_named:
                   ptr_owners.add(dns_named[0])
               else:
                   ptr_owners.add(min(group, key=lambda r: r.name))

           return tuple(replace(record, ptr=(record in ptr_owners)) for record in records)

  5. Change _records_payload's records list from:

       "records": [{"name": record.name, "ip": record.ip} for record in records],

     to:

       "records": [
           {"name": record.name, "ip": record.ip, "ptr": record.ptr} for record in records
       ],

scope:
  allowed_paths:
    - terraform/lxc/render-edge-technitium.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Changing RenderResult.to_dict()'s own records/generated_records serialization -- that's diagnostic --json CLI output, not the zone-records.json payload, and is out of scope"

gates:
  - id: existing-tests-still-pass
    cmd: "cd /home/steve/git/proxmox-homelab && python3 -m unittest terraform.lxc.test_render_edge_technitium -v"
    expect: "exit 0, all 4 pre-existing tests OK (dns-reverse-03's new test is not added yet in this step)"
    critical: true
  - id: ruff-clean
    cmd: "cd /home/steve/git/proxmox-homelab && ruff check terraform/lxc/render-edge-technitium.py"
    expect: "All checks passed! / exit 0"
    critical: true
```

### dns-reverse-03-render-edge-ptr-test

```yaml
id: dns-reverse-03-render-edge-ptr-test
title: Add a unit test for PTR ownership across a shared-IP collision
depends_on: [dns-reverse-02-render-edge-ptr-logic]

change: >
  In terraform/lxc/test_render_edge_technitium.py, insert this new test
  method immediately before the existing test_rejects_duplicate_generated_records
  method (same class, same indentation level):

    def test_ptr_owner_is_proxy_stack_for_shared_browser_ip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            seed = tmp / "seed.zone"
            output_records = tmp / "records.json"
            seed.write_text(
                """$ORIGIN lab.gibbsgreatly.xyz.
    $TTL 5m
    @ IN NS ns1.lab.gibbsgreatly.xyz.
    ns1 IN A 10.57.1.13
    """,
                encoding="utf-8",
            )

            result = render_technitium_dry_run(
                manifest_paths=[
                    VALID_DIR / "traefik-dashboard.yaml",
                    VALID_DIR / "grafana.yaml",
                    VALID_DIR / "authentik.yaml",
                ],
                seed_zone_path=seed,
                output_records_path=output_records,
            )

        self.assertTrue(result.ok)
        ptr_map = {record.name: record.ptr for record in result.records}
        # traefik-dashboard.yaml/grafana.yaml/authentik.yaml all target the
        # same LAB_IP_PROXY (10.57.2.10, set module-wide above) -- only the
        # record generated from proxy-stack's own manifest may own the PTR.
        self.assertTrue(ptr_map["traefik"])
        self.assertFalse(ptr_map["grafana"])
        self.assertFalse(ptr_map["auth"])
        # dns/ns1 both sit on LAB_IP_TECHNITIUM (a placeholder in this
        # source-mode test) -- "dns" is the deterministic tiebreak owner.
        self.assertTrue(ptr_map["dns"])
        self.assertFalse(ptr_map["ns1"])

  Note authentik.yaml's route host is auth.lab.gibbsgreatly.xyz (label
  "auth", not "authentik") -- use ptr_map["auth"], not ptr_map["authentik"],
  or the test will KeyError.

scope:
  allowed_paths:
    - terraform/lxc/test_render_edge_technitium.py
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Modifying any existing test method"

gates:
  - id: full-suite-passes
    cmd: "cd /home/steve/git/proxmox-homelab && python3 -m unittest terraform.lxc.test_render_edge_technitium -v"
    expect: "exit 0, 5 tests OK including test_ptr_owner_is_proxy_stack_for_shared_browser_ip"
    critical: true
  - id: ruff-clean
    cmd: "cd /home/steve/git/proxmox-homelab && ruff check terraform/lxc/test_render_edge_technitium.py"
    expect: "All checks passed! / exit 0"
    critical: true
```

### dns-reverse-04-bootstrap-zone-wiring

```yaml
id: dns-reverse-04-bootstrap-zone-wiring
title: Wire the bootstrap-zone A-record publish onto technitium_dns_record
depends_on: [dns-reverse-01-shared-role]

change: >
  In terraform/lxc/ansible/playbooks/deploy-technitium-stack.yml, replace the
  technitium_seed_records list (in the "Bootstrap Technitium zone" play's
  vars: block) from:

      # Seed record set for the short-lived Technitium bootstrap zone. This
      # intentionally mirrors CoreDNS's current browser-routed vs breakglass
      # split so we can validate Technitium independently before it owns the
      # live LAB_DOMAIN zone.
      technitium_seed_records:
        - { name: "dns", ip: "{{ lookup('env', 'LAB_IP_TECHNITIUM') }}" }
        - { name: "ns1", ip: "{{ lookup('env', 'LAB_IP_TECHNITIUM') }}" }
        - { name: "traefik", ip: "{{ lookup('env', 'LAB_IP_PROXY') | mandatory('LAB_IP_PROXY env var is required') }}" }
        - { name: "authentik", ip: "{{ lookup('env', 'LAB_IP_PROXY') | mandatory('LAB_IP_PROXY env var is required') }}" }
        - { name: "step-ca", ip: "{{ lookup('env', 'LAB_IP_STEP_CA') | mandatory('LAB_IP_STEP_CA env var is required') }}" }
        - { name: "monitoring", ip: "{{ lookup('env', 'LAB_IP_MONITORING') | mandatory('LAB_IP_MONITORING env var is required') }}" }
        - { name: "grafana", ip: "{{ lookup('env', 'LAB_IP_PROXY') | mandatory('LAB_IP_PROXY env var is required') }}" }
        - { name: "portainer", ip: "{{ lookup('env', 'LAB_IP_PROXY') | mandatory('LAB_IP_PROXY env var is required') }}" }
        - { name: "harbor", ip: "{{ lookup('env', 'LAB_IP_PROXY') | mandatory('LAB_IP_PROXY env var is required') }}" }
        - { name: "netbox", ip: "{{ lookup('env', 'LAB_IP_PROXY') | mandatory('LAB_IP_PROXY env var is required') }}" }
        - { name: "authentik-int", ip: "{{ lookup('env', 'LAB_IP_AUTHENTIK') | mandatory('LAB_IP_AUTHENTIK env var is required') }}" }
        - { name: "authentik-bg", ip: "{{ lookup('env', 'LAB_IP_AUTHENTIK') | mandatory('LAB_IP_AUTHENTIK env var is required') }}" }
        - { name: "harbor-bg", ip: "{{ lookup('env', 'LAB_IP_HARBOR') | mandatory('LAB_IP_HARBOR env var is required') }}" }
        - { name: "monitoring-bg", ip: "{{ lookup('env', 'LAB_IP_MONITORING') | mandatory('LAB_IP_MONITORING env var is required') }}" }
        - { name: "netbox-bg", ip: "{{ lookup('env', 'LAB_IP_NETBOX') | mandatory('LAB_IP_NETBOX env var is required') }}" }
        - { name: "portainer-bg", ip: "{{ lookup('env', 'LAB_IP_PORTAINER') | mandatory('LAB_IP_PORTAINER env var is required') }}" }
        - { name: "proxy-bg", ip: "{{ lookup('env', 'LAB_IP_PROXY') | mandatory('LAB_IP_PROXY env var is required') }}" }

  to:

      # Seed record set for the short-lived Technitium bootstrap zone. This
      # intentionally mirrors CoreDNS's current browser-routed vs breakglass
      # split so we can validate Technitium independently before it owns the
      # live LAB_DOMAIN zone.
      #
      # ptr is always false here: this zone shares physical IPs with the real
      # parity zone below (same LAB_IP_* addresses under a different, non-
      # authoritative tech.<domain> name), and a PTR record can only point at
      # one name per IP. The parity zone -- the real production namespace --
      # is what owns reverse DNS for these addresses; see technitium_dns_record
      # role docs for why.
      technitium_seed_records:
        - { name: "dns", zone: "{{ technitium_bootstrap_zone }}", ip: "{{ lookup('env', 'LAB_IP_TECHNITIUM') }}", ptr: false }
        - { name: "ns1", zone: "{{ technitium_bootstrap_zone }}", ip: "{{ lookup('env', 'LAB_IP_TECHNITIUM') }}", ptr: false }
        - { name: "traefik", zone: "{{ technitium_bootstrap_zone }}", ip: "{{ lookup('env', 'LAB_IP_PROXY') | mandatory('LAB_IP_PROXY env var is required') }}", ptr: false }
        - { name: "authentik", zone: "{{ technitium_bootstrap_zone }}", ip: "{{ lookup('env', 'LAB_IP_PROXY') | mandatory('LAB_IP_PROXY env var is required') }}", ptr: false }
        - { name: "step-ca", zone: "{{ technitium_bootstrap_zone }}", ip: "{{ lookup('env', 'LAB_IP_STEP_CA') | mandatory('LAB_IP_STEP_CA env var is required') }}", ptr: false }
        - { name: "monitoring", zone: "{{ technitium_bootstrap_zone }}", ip: "{{ lookup('env', 'LAB_IP_MONITORING') | mandatory('LAB_IP_MONITORING env var is required') }}", ptr: false }
        - { name: "grafana", zone: "{{ technitium_bootstrap_zone }}", ip: "{{ lookup('env', 'LAB_IP_PROXY') | mandatory('LAB_IP_PROXY env var is required') }}", ptr: false }
        - { name: "portainer", zone: "{{ technitium_bootstrap_zone }}", ip: "{{ lookup('env', 'LAB_IP_PROXY') | mandatory('LAB_IP_PROXY env var is required') }}", ptr: false }
        - { name: "harbor", zone: "{{ technitium_bootstrap_zone }}", ip: "{{ lookup('env', 'LAB_IP_PROXY') | mandatory('LAB_IP_PROXY env var is required') }}", ptr: false }
        - { name: "netbox", zone: "{{ technitium_bootstrap_zone }}", ip: "{{ lookup('env', 'LAB_IP_PROXY') | mandatory('LAB_IP_PROXY env var is required') }}", ptr: false }
        - { name: "authentik-int", zone: "{{ technitium_bootstrap_zone }}", ip: "{{ lookup('env', 'LAB_IP_AUTHENTIK') | mandatory('LAB_IP_AUTHENTIK env var is required') }}", ptr: false }
        - { name: "authentik-bg", zone: "{{ technitium_bootstrap_zone }}", ip: "{{ lookup('env', 'LAB_IP_AUTHENTIK') | mandatory('LAB_IP_AUTHENTIK env var is required') }}", ptr: false }
        - { name: "harbor-bg", zone: "{{ technitium_bootstrap_zone }}", ip: "{{ lookup('env', 'LAB_IP_HARBOR') | mandatory('LAB_IP_HARBOR env var is required') }}", ptr: false }
        - { name: "monitoring-bg", zone: "{{ technitium_bootstrap_zone }}", ip: "{{ lookup('env', 'LAB_IP_MONITORING') | mandatory('LAB_IP_MONITORING env var is required') }}", ptr: false }
        - { name: "netbox-bg", zone: "{{ technitium_bootstrap_zone }}", ip: "{{ lookup('env', 'LAB_IP_NETBOX') | mandatory('LAB_IP_NETBOX env var is required') }}", ptr: false }
        - { name: "portainer-bg", zone: "{{ technitium_bootstrap_zone }}", ip: "{{ lookup('env', 'LAB_IP_PORTAINER') | mandatory('LAB_IP_PORTAINER env var is required') }}", ptr: false }
        - { name: "proxy-bg", zone: "{{ technitium_bootstrap_zone }}", ip: "{{ lookup('env', 'LAB_IP_PROXY') | mandatory('LAB_IP_PROXY env var is required') }}", ptr: false }

  Then, later in the same play, replace the two tasks named
  "Query current A records in the bootstrap zone" and "Publish A records to
  the bootstrap zone" (the ansible.builtin.uri task pair immediately after
  the "Assert effective record set preserves bootstrap authority records"
  task) with this single task:

      - name: Publish bootstrap-zone A records via technitium_dns_record
        ansible.builtin.include_role:
          name: technitium_dns_record
        vars:
          technitium_dns_record_records: "{{ technitium_records }}"

  Leave the "Determine bootstrap record source" task (technitium_records:
  "{{ technitium_seed_records }}") and the "Assert effective record set..."
  task immediately before it unchanged -- both still work as-is since `name`
  is still a field on every record.

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-technitium-stack.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Setting ptr: true on any technitium_seed_records entry -- see the plan's design-finding note"
    - "Touching the parity-zone play -- that is dns-reverse-05"
    - "Any provision.sh / ansible-playbook run against a real host -- syntax-check only in this step"

gates:
  - id: syntax-check
    cmd: "cd /home/steve/git/proxmox-homelab && ANSIBLE_CONFIG=terraform/lxc/ansible/ansible.cfg ansible-playbook --syntax-check terraform/lxc/ansible/playbooks/deploy-technitium-stack.yml"
    expect: "exit 0 (a pre-existing ansible.builtin.apt_repository deprecation warning from the unrelated wazuh_agent role is expected output, not a failure)"
    critical: true
```

### dns-reverse-05-parity-zone-wiring

```yaml
id: dns-reverse-05-parity-zone-wiring
title: Wire the parity-zone A-record publish onto technitium_dns_record, with PTR verification
depends_on: [dns-reverse-01-shared-role, dns-reverse-02-render-edge-ptr-logic, dns-reverse-04-bootstrap-zone-wiring]

change: >
  In terraform/lxc/ansible/playbooks/deploy-technitium-stack.yml (same file
  as dns-reverse-04, applied after it), make three changes to the
  "Bootstrap Technitium zone" play:

  1. In the "Assert generated Technitium zone payload shape" task, change:

       - name: Assert generated Technitium zone payload shape
         ansible.builtin.assert:
           that:
             - technitium_generated_zone_payload is mapping or technitium_generated_zone_payload is sequence
             - technitium_generated_zone_payload is not string
             - technitium_generated_zone_records is sequence
             - technitium_generated_zone_records is not string
           fail_msg: >-
             technitium_generated_zone_src must contain either a JSON array of
             `{name, ip}` records or an object with `zone` and `records`.
         when: technitium_generated_zone_enabled | bool

     to:

       - name: Assert generated Technitium zone payload shape
         ansible.builtin.assert:
           that:
             - technitium_generated_zone_payload is mapping or technitium_generated_zone_payload is sequence
             - technitium_generated_zone_payload is not string
             - technitium_generated_zone_records is sequence
             - technitium_generated_zone_records is not string
             - >-
               technitium_generated_zone_records
               | selectattr('ptr', 'defined')
               | list | length == technitium_generated_zone_records | length
           fail_msg: >-
             technitium_generated_zone_src must contain either a JSON array of
             `{name, ip, ptr}` records or an object with `zone` and `records`.
             Every record needs a `ptr` field -- regenerate it with the current
             render-edge-technitium.py, which always includes one.
         when: technitium_generated_zone_enabled | bool

  2. Replace the two tasks named "Query current A records in the parity zone"
     and "Publish A records to the parity zone" with these two tasks:

       - name: Build parity-zone record set for technitium_dns_record
         ansible.builtin.set_fact:
           technitium_generated_zone_records_with_zone: >-
             {{
               technitium_generated_zone_records
               | map('combine', {'zone': technitium_generated_zone_name})
               | list
             }}
         when: technitium_parity_zone_enabled | bool

       - name: Publish parity-zone A and PTR records via technitium_dns_record
         ansible.builtin.include_role:
           name: technitium_dns_record
         vars:
           technitium_dns_record_records: "{{ technitium_generated_zone_records_with_zone }}"
         when: technitium_parity_zone_enabled | bool

  3. Immediately after the "Assert parity-zone authority query returns
     expected IP" task (the last task in this play, right before the
     following "Enroll this host as a Wazuh agent" play header), add these
     two new tasks:

       - name: Verify reverse lookup for the proxy IP resolves to its PTR owner
         ansible.builtin.shell: >
           dig @{{ technitium_ip }} +short -x {{ lookup('env', 'LAB_IP_PROXY') }}
         register: technitium_parity_ptr_test
         args:
           executable: /bin/bash
         check_mode: false
         changed_when: false
         retries: 10
         delay: 2
         until: (technitium_parity_ptr_test.stdout | default('')) | length > 0
         when: technitium_parity_zone_enabled | bool

       - name: Assert reverse lookup for the proxy IP names the expected PTR owner
         ansible.builtin.assert:
           that:
             - (technitium_parity_ptr_test.stdout | trim) == ('traefik.' ~ technitium_generated_zone_name ~ '.')
           fail_msg: >-
             Reverse lookup for {{ lookup('env', 'LAB_IP_PROXY') }} did not
             return traefik.{{ technitium_generated_zone_name }} -- check which
             record technitium_dns_record_records marked ptr: true for this IP.
         when:
           - technitium_parity_zone_enabled | bool
           - not ansible_check_mode

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-technitium-stack.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Touching the bootstrap-zone play -- that was dns-reverse-04"
    - "Any provision.sh / ansible-playbook run against a real host -- syntax-check only in this step"

gates:
  - id: syntax-check
    cmd: "cd /home/steve/git/proxmox-homelab && ANSIBLE_CONFIG=terraform/lxc/ansible/ansible.cfg ansible-playbook --syntax-check terraform/lxc/ansible/playbooks/deploy-technitium-stack.yml"
    expect: "exit 0 (a pre-existing ansible.builtin.apt_repository deprecation warning from the unrelated wazuh_agent role is expected output, not a failure)"
    critical: true
```

### dns-reverse-06-ai-stack-playbook

```yaml
id: dns-reverse-06-ai-stack-playbook
title: Refactor configure-ai-stack-dns-records.yml onto technitium_dns_record
depends_on: [dns-reverse-01-shared-role]

change: >
  Replace the full content of
  terraform/lxc/ansible/playbooks/configure-ai-stack-dns-records.yml with
  exactly this:

    # Add direct-backend Technitium A records (and their PTR records) for
    # llm-gpu-stack/comfyui-stack, matching the existing
    # <service>-bg.lab.gibbsgreatly.xyz convention used by every other backend
    # service (authentik-bg, harbor-bg, netbox-bg, etc.) -- a direct pointer to
    # the container's own IP, independent of Traefik routing.
    #
    # Deliberately NOT adding the plain <service>.lab.gibbsgreatly.xyz name
    # (which resolves to Traefik/edge_seg) -- neither stack has a Traefik
    # route configured yet (Phase 2, not done), so that name would be
    # misleading until it does.
    ---
    - name: Add Technitium A/PTR records for llm-gpu-stack/comfyui-stack backends
      hosts: localhost
      connection: local
      gather_facts: false

      vars:
        technitium_ip: "{{ lookup('env', 'LAB_IP_TECHNITIUM') | default('192.168.20.15', true) }}"
        technitium_admin_password: "{{ lookup('env', 'TECHNITIUM_ADMIN_PASSWORD') | mandatory('TECHNITIUM_ADMIN_PASSWORD env var is not set') }}"
        technitium_api_base: "http://{{ technitium_ip }}:5380/api" # nosonar: ansible:S5332 -- Technitium admin API, private mgmt_seg only
        lab_domain: "{{ lookup('env', 'LAB_DOMAIN') | default('lab.gibbsgreatly.xyz', true) }}"
        ai_stack_dns_records:
          - { name: "llm-gpu-stack-bg", zone: "{{ lab_domain }}", ip: "192.168.50.10", ptr: true }
          - { name: "comfyui-stack-bg", zone: "{{ lab_domain }}", ip: "192.168.50.11", ptr: true }

      tasks:
        - name: Log in to Technitium
          ansible.builtin.uri:
            url: "{{ technitium_api_base }}/user/login?user=admin&pass={{ technitium_admin_password | urlencode }}&includeInfo=true"
            method: GET
            return_content: true
          register: technitium_login
          no_log: true
          until: technitium_login.status == 200
          retries: 3
          delay: 5

        - name: Extract session token
          ansible.builtin.set_fact:
            technitium_token: "{{ (technitium_login.content | from_json).token }}"
          no_log: true

        - name: Publish AI-stack backend A and PTR records via technitium_dns_record
          ansible.builtin.include_role:
            name: technitium_dns_record
          vars:
            technitium_dns_record_records: "{{ ai_stack_dns_records }}"

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/configure-ai-stack-dns-records.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any provision.sh / ansible-playbook run against a real host -- syntax-check only in this step"

gates:
  - id: syntax-check
    cmd: "cd /home/steve/git/proxmox-homelab && ANSIBLE_CONFIG=terraform/lxc/ansible/ansible.cfg ansible-playbook --syntax-check terraform/lxc/ansible/playbooks/configure-ai-stack-dns-records.yml"
    expect: "exit 0"
    critical: true
```

### dns-reverse-07-gaming-stack-playbook

```yaml
id: dns-reverse-07-gaming-stack-playbook
title: Refactor configure-gaming-stack-dns-records.yml onto technitium_dns_record
depends_on: [dns-reverse-01-shared-role]

change: >
  Replace the full content of
  terraform/lxc/ansible/playbooks/configure-gaming-stack-dns-records.yml with
  exactly this:

    # Add Technitium A records (and a PTR record for the canonical name) for
    # gaming-stack-lab's direct game-port services, matching the game_seg
    # convention: gaming-stack.lab.gibbsgreatly.xyz and
    # foreverworld.lab.gibbsgreatly.xyz both point straight at the container's
    # own IP, not through Traefik (game protocols aren't HTTP). Both names
    # share one IP, so only gaming-stack -- the canonical container identity --
    # owns the PTR; foreverworld is an alias and cannot also own it (PTR is one
    # name per IP).
    #
    # These were mistakenly added to the retired CoreDNS zone instead
    # (terraform/lxc/ansible/files/coredns-lab.zone) when gaming-stack-lab was
    # first scaffolded. CoreDNS has not been the live production DNS delegate
    # target since the 2026-07-05 Technitium cutover
    # (docs/dns-refactor/production-cutover-packet.md) -- this playbook is the
    # correction, following the same pattern as
    # configure-ai-stack-dns-records.yml.
    ---
    - name: Add Technitium A/PTR records for gaming-stack-lab
      hosts: localhost
      connection: local
      gather_facts: false

      vars:
        technitium_ip: "{{ lookup('env', 'LAB_IP_TECHNITIUM') | mandatory('LAB_IP_TECHNITIUM env var is required') }}"
        technitium_admin_password: "{{ lookup('env', 'TECHNITIUM_ADMIN_PASSWORD') | mandatory('TECHNITIUM_ADMIN_PASSWORD env var is not set') }}"
        technitium_api_base: "http://{{ technitium_ip }}:5380/api" # nosonar: ansible:S5332 -- Technitium admin API, private mgmt_seg only
        lab_domain: "{{ lookup('env', 'LAB_DOMAIN') | default('lab.gibbsgreatly.xyz', true) }}"
        gaming_stack_dns_records:
          - { name: "gaming-stack", zone: "{{ lab_domain }}", ip: "192.168.60.10", ptr: true }
          - { name: "foreverworld", zone: "{{ lab_domain }}", ip: "192.168.60.10", ptr: false }

      tasks:
        - name: Log in to Technitium
          ansible.builtin.uri:
            url: "{{ technitium_api_base }}/user/login?user=admin&pass={{ technitium_admin_password | urlencode }}&includeInfo=true"
            method: GET
            return_content: true
          register: technitium_login
          no_log: true
          until: technitium_login.status == 200
          retries: 3
          delay: 5

        - name: Extract session token
          ansible.builtin.set_fact:
            technitium_token: "{{ (technitium_login.content | from_json).token }}"
          no_log: true

        - name: Publish gaming-stack-lab A and PTR records via technitium_dns_record
          ansible.builtin.include_role:
            name: technitium_dns_record
          vars:
            technitium_dns_record_records: "{{ gaming_stack_dns_records }}"

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/configure-gaming-stack-dns-records.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any provision.sh / ansible-playbook run against a real host -- syntax-check only in this step"

gates:
  - id: syntax-check
    cmd: "cd /home/steve/git/proxmox-homelab && ANSIBLE_CONFIG=terraform/lxc/ansible/ansible.cfg ansible-playbook --syntax-check terraform/lxc/ansible/playbooks/configure-gaming-stack-dns-records.yml"
    expect: "exit 0"
    critical: true
```

### dns-reverse-08-stack-contract-doc

```yaml
id: dns-reverse-08-stack-contract-doc
title: Document the ptr field and reverse-zone auto-creation in STACK_CONTRACT.md
depends_on: [dns-reverse-01-shared-role]

change: >
  In terraform/lxc/stacks/technitium-stack/STACK_CONTRACT.md, in the
  "Generated Artifacts" section, after the existing bullet that starts
  "A pre-publish guard (equivalent to CoreDNS's stage..." and before the
  "## What May Depend on This Stack" heading, add this new bullet:

    - Every A record published via the technitium_dns_record role (both the
      parity-zone publish above and the two ad-hoc
      configure-ai-stack-dns-records.yml / configure-gaming-stack-dns-records.yml
      playbooks) carries a `ptr` flag. Where `ptr: true`, the role also
      creates (on demand, per /24) the matching reverse
      (`<n>.<n>.<n>.in-addr.arpa`) zone and a PTR record. Because a PTR
      record is one name per IP, only one record per shared IP may set
      `ptr: true` -- see terraform/lxc/ansible/roles/technitium_dns_record/tasks/main.yml
      for the exact contract. The short-lived bootstrap zone (tech.<domain>)
      never sets ptr: true, since it shares physical IPs with this parity
      zone and PTR ownership must not be contested between them.

scope:
  allowed_paths:
    - terraform/lxc/stacks/technitium-stack/STACK_CONTRACT.md
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Rewording or removing any existing bullet in this section"

gates:
  - id: bullet-present
    cmd: "grep -q 'technitium_dns_record role' terraform/lxc/stacks/technitium-stack/STACK_CONTRACT.md"
    expect: "exit 0"
    critical: true
```

## Not a step -- operator-run validation and promotion

Per this repo's Validation Tiers (CLAUDE.md), this is an Ansible task/role
change: the real gate is `scripts/provision.sh --stack technitium-stack` on
`pve-test-vm`, not something any step above runs. After all steps land and
their hand-backs are recorded in `README.md`:

1. On the `feat/dns-reverse-records` (or similarly named) branch, the
   operator runs `./with-secrets scripts/provision.sh --stack
   technitium-stack` against `pve-test-vm` (confirm target first per
   CLAUDE.md's Execution Guardrails). This exercises the real bootstrap-zone
   and parity-zone publish, including the new PTR/reverse-zone tasks and the
   new `dig -x` verification tasks added in dns-reverse-05.
2. The operator re-runs `terraform/lxc/reconcile-edge.py --apply --json`
   (or however the current Approved Deploy Order regenerates
   `zone-records.json`) so the parity zone actually carries `ptr` fields
   before the provision.sh run in step 1, since `render-edge-technitium.py`
   is what produces them.
3. The operator runs the two ad-hoc playbooks
   (`configure-ai-stack-dns-records.yml`, `configure-gaming-stack-dns-records.yml`)
   against `pve-test-vm` and spot-checks a `dig -x` for one AI-stack backend
   IP and for `192.168.60.10` (gaming-stack/foreverworld) to confirm only
   `gaming-stack` owns that PTR.
4. Once `pve-test-vm` validation passes, promote to `stable` per the branch
   model, then to `main` after a successful incremental deploy on `pve`
   (technitium-stack only -- this doesn't touch Authentik/Traefik routing,
   so the narrower per-stack tier applies, not a full teardown).

This validation run, the reconcile-edge.py invocation, and the branch
promotion are not step blocks above because they mutate a real host
(`pve-test-vm`) -- exactly the "first mutation of shared/production
infrastructure" case `docs/agent-design/step-packet-schema.md` reserves for
an operator's own judgment in the moment, not a pre-written spec.

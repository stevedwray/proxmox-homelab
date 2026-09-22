# nextcloud-stack plan

Written with `.github/prompts/plan-change.prompt.md`, following
`docs/agent-design/step-packet-schema.md`. Intended to be executed with
`.github/prompts/implement-step.prompt.md`. See [README.md](README.md) for
decisions, research, and what's still genuinely open.

**Not a priority right now** — this plan exists so the work is ready to
pick up, not to be run immediately.

Several things below are genuinely not step blocks, and are written as
plain operator/prose instructions instead: running `scaffold-stack.sh`
(`nextcloud-02`), the live deploy against `pve` under the production
approval flow (`nextcloud-06`), and most of Phase 3 (Pangolin exposure,
monitoring, security — control-plane/credential-creating actions per
`/home/steve/git/oci/docs/repeatable-operations.md`'s own stated policy).

---

## Phase 1 — stack, zone, storage, SSO

### Step: nextcloud-01-create-apps-seg-zone

```yaml
id: nextcloud-01-create-apps-seg-zone
title: Create apps_seg SDN zone (VLAN 120, 192.168.120.0/24) and its firewall policies
depends_on: []

change: >
  VLAN 90 was this step's original choice but is already live as
  test_dhcp_seg (terraform/lxc/network/pve-test-vm.yaml, tvdhcp,
  192.168.90.0/24 — the switch labels it "dhcp_test", confirmed present
  on the physical trunk 2026-09-23). pve-test-vm is nested inside pve
  and shares its physical NIC/trunk (see the ai_seg zone comment in
  pve.yaml for the same reasoning applied to VLAN 50), so reusing 90
  here would collide. Re-check terraform/lxc/network/*.yaml for
  `vlan_tag:` values before executing this step in case another zone
  has since claimed 120 — as of 2026-09-23 (after nextcloud-P3-01
  claimed 110) every tag 10 through 110 is spoken for, so 120 is next.

  Insert this exact block into terraform/lxc/network/pve.yaml in the
  zones: section, immediately after the media_seg zone block (search for
  "gateway: \"192.168.80.1\"" then "snat: false" to find its end):

    # apps_seg — General application services (VLAN 120, 192.168.120.0/24)
    apps_seg:
      description: General application services — Nextcloud (nextcloud-stack)
      type: sdn_vnet
      bridge: tvapps
      firewall: false
      sdn:
        zone: tvapps
        zone_type: vlan
        bridge: vmbr0
        nodes:
          - pve
        vnet: tvapps
        vlan_tag: 120
        alias: pve apps segment
        subnet: "192.168.120.0/24"
        gateway: "192.168.120.1"
        snat: false

  In the members section (search for "media_seg:" under the second
  occurrence, near "media-stack-lab (VMID 80010)"), insert immediately
  after that block:

    apps_seg:
      description: General application services — Nextcloud, additive alongside existing zones
      attachment: apps_seg
      containers:
        - "nextcloud-stack (VMID 120010) — 192.168.120.10"

  In the policies: section, insert these six rules immediately before the
  final existing rule in the file (the "media-stack-lab node_exporter TLS
  cert issuance from step-ca" rule, description ending "targeting the
  deny rule." — insert after that rule, i.e. at the end of the policies
  list). Image pulls (Harbor) and apt packages (apt-cacher) do NOT need
  their own rules here — both are already covered by the existing
  `from: all_zones, to: infra_seg, ports: [80, 443, 3142]` rule
  ("All zones and LAN to Harbor and apt-cacher") elsewhere in this file,
  which apps_seg inherits automatically once it exists as a zone:

    - from: edge_seg
      to: apps_seg
      protocol: tcp
      ports: [8080]
      description: Traefik to Nextcloud web UI (nextcloud-stack)
    - from: apps_seg
      to: mgmt_seg
      protocol: tcp
      ports: [9443]
      description: nextcloud-stack to Authentik for OIDC
    - from: apps_seg
      to: 192.168.30.10
      protocol: tcp
      ports: [443]
      description: >-
        nextcloud-stack to Traefik on 443, for two distinct reasons:
        (1) user_oidc's server-to-server OIDC token exchange -- media-
        stack-lab found live (2026-09-04) that this goes out via edge_seg,
        not direct to mgmt_seg:9443, applying that lesson from the start;
        (2) docker pull against Harbor's FQDN (LAB_FQDN_HARBOR, routed
        through Traefik) -- the direct-IP path to Harbor on infra_seg
        fails TLS (see reference_registry_host_vs_fqdn_harbor: bare-IP
        docker login gets "connection refused" on 443, confirmed live
        twice). Both reasons share the same from/to/port so one rule
        covers both.
    - from: apps_seg
      to: 192.168.20.14
      protocol: tcp
      ports: [514]
      description: nextcloud-stack rsyslog forwarding to Graylog
    - from: apps_seg
      to: 192.168.20.11
      protocol: tcp
      ports: [443]
      description: nextcloud-stack node_exporter TLS cert issuance from step-ca
    - from: apps_seg
      to: default
      protocol: all
      ports: []
      description: Explicit deny — apps_seg has no other reachability beyond the above plus internet egress

  Do NOT add a greenbone-stack scan-reach rule in this step. Per
  docs/greenbone-stack/network-scan-rollout-plan.md, widening
  greenbone-stack's (pentest_seg) reach into a new zone is a deliberate,
  separately-called-out action ("treat with the same seriousness CLAUDE.md
  gives production credential mutations"), not something to fold into a
  routine zone-creation PR. nextcloud-01b below handles it as its own
  explicit step, scoped by source = greenbone-stack's own IP only,
  matching that doc's existing pattern.

scope:
  allowed_paths:
    - terraform/lxc/network/pve.yaml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any terragrunt apply / SDN apply -- validation only in this step"

gates:
  - id: yaml-syntax
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/network/pve.yaml'))\""
    expect: "exit 0"
    critical: true
```

### Step: nextcloud-01b-greenbone-scan-reach

**Not a step block — this is the deliberate security-scan widening
`docs/greenbone-stack/network-scan-rollout-plan.md` requires be called
out explicitly, not folded into nextcloud-01's routine zone-creation
diff.** Follow that doc's own process for adding a new zone to GVM's
scan reach, which as of this plan's writing is: add a firewall rule
scoped by *source = greenbone-stack's own IP*
(`${lab_ip_greenbone}`, canonical `192.168.70.11`), not blanket
`pentest_seg`, into `apps_seg` for discovery-scan reach (ICMP + the
common TCP/UDP discovery ports that doc's Phase 1 already defines for
other zones — copy its exact rule shape rather than reinventing one
here), and register `192.168.120.0/24` in whatever GVM target/task
config that doc's Phase 1 established for the other SDN zones (`game_seg`,
`media_seg`, etc.). Read `network-scan-rollout-plan.md` in full before
doing this — it has real, hard-won specifics (in-interface matching over
src-address matching, rule ordering against the default-deny, IoT/consumer
gear sensitivity to `Full and fast` scans) that a from-scratch attempt
would silently miss. This step should land as its own follow-up plan
step once nextcloud-01/02 are actually deployed and `192.168.120.10` is a
real, reachable host — scanning a zone with nothing live in it yet has
no value and risks a stale/wrong target definition.

### Step: nextcloud-02-scaffold-stack-request

**Not a step block — operator/local-model prose instruction, not
`implement-step` work.** `scaffold-stack.sh` internally depends on tools
outside a bounded execution loop (same reason `media-lab-02` was written
as prose, not a step — see `docs/agent-design/step-packet-schema.md`
"Reuse `scaffold-stack.sh`... but not as a step block").

1. Confirm the current stable Nextcloud image tag (check
   `hub.docker.com/r/nextcloud/server/tags` — pin the specific version,
   e.g. `nextcloud:30-apache`, not `latest`). Fill it into the
   `compose_requirements` block below before use.
2. Copy `terraform/lxc/stacks/stack-request.example.yaml` to
   `terraform/lxc/stacks/nextcloud-stack/stack-request.yaml` and replace
   its contents with the literal content below (image tag filled in per
   step 1).
3. Run `terraform/lxc/scaffold-stack.sh nextcloud-stack` from the repo
   root.
4. Delete `terraform/lxc/stacks/nextcloud-stack/stack-request.yaml` once
   scaffolding succeeds (or keep it as a record of intent — either is
   fine per the example file's own guidance).

```yaml
stack_yaml:
  hostname: nextcloud-stack
  ip_address: "192.168.120.10/24"
  gateway: "192.168.120.1"
  dns_server: "192.168.120.1"
  vmid: 90010
  cores: 4
  memory: 4096
  swap: 1024
  rootfs_size: 12
  storage_profile: platform-default
  docker_storage_size: "15G"
  template_name: "debian-13.1-2-docker-template.tar.gz"
  tags:
    - docker
    - nextcloud
    - storage
    - apps
  depends_on: []
  provides:
    - service: nextcloud
      port: 8080
      protocol: tcp
  ansible_playbook: deploy-nextcloud-stack
  deployment_tier: apps
  portainer_agent: true
  apt_cacher_host: "${lab_ip_apt_cacher}"

  # Dedicated data volume for Nextcloud's actual file storage, separate
  # from rootfs/docker-storage — same pattern as harbor-stack's
  # extra_mount for registry blobs.
  extra_mount_path: "/var/lib/nextcloud-data"
  extra_mount_size: "200G"
  extra_mount_profile: durable-zfs
  extra_mount:
    logical_name: nextcloud-data
    path: /var/lib/nextcloud-data
    size: "200G"
    profile: durable-zfs
    backup_policy: include
    resize_control_plane: operational
    mutation_policy: grow-only

compose_requirements: |
  Three services: nextcloud (app), postgres (db), redis (cache/locking).

  nextcloud service:
  - Image: ${REGISTRY_HOST}/dockerhub/nextcloud:<PINNED_TAG> (Harbor
    pull-through). IMPORTANT: REGISTRY_HOST here must resolve to
    LAB_FQDN_HARBOR (harbor.${LAB_DOMAIN}), NOT LAB_IP_HARBOR. Both
    netbox-stack and media-stack-lab's cadvisor service copied the bare-IP
    var by mistake and got "connection refused" on 443 at pull time --
    see reference_registry_host_vs_fqdn_harbor and nextcloud-02b below,
    which sets REGISTRY_HOST correctly in the playbook's environment
    before "docker compose up" runs.
  - container_name: nextcloud-stack-app
  - depends_on: postgres (condition: service_healthy), redis (condition:
    service_healthy)
  - ports: "8080:80" only (container listens on 80 internally; host side
    matches the provides: port 8080 in stack_yaml above)
  - environment: POSTGRES_HOST=postgres, POSTGRES_DB=nextcloud,
    POSTGRES_USER=nextcloud, POSTGRES_PASSWORD=${NEXTCLOUD_DB_PASSWORD},
    REDIS_HOST=redis, REDIS_HOST_PASSWORD=${NEXTCLOUD_REDIS_PASSWORD},
    NEXTCLOUD_ADMIN_USER=admin, NEXTCLOUD_ADMIN_PASSWORD=${NEXTCLOUD_ADMIN_PASSWORD},
    NEXTCLOUD_TRUSTED_DOMAINS=nextcloud.${LAB_DOMAIN},
    OVERWRITEPROTOCOL=https, TRUSTED_PROXIES=${LAB_IP_PROXY}
  - volumes: named volume nextcloud-app-data for /var/www/html (app code
    + config), bind mount /var/lib/nextcloud-data (the extra_mount path
    above) to /var/www/html/data (actual user files)
  - restart: unless-stopped
  - healthcheck: test against http://localhost/status.php, start_period
    120s, interval 15s, timeout 5s, retries 5

  postgres service:
  - Image: ${REGISTRY_HOST}/dockerhub/postgres:16-alpine
  - container_name: nextcloud-stack-db
  - environment: POSTGRES_DB=nextcloud, POSTGRES_USER=nextcloud,
    POSTGRES_PASSWORD=${NEXTCLOUD_DB_PASSWORD}
  - volumes: named volume nextcloud-db-data for /var/lib/postgresql/data
  - healthcheck: pg_isready -U nextcloud, interval 10s, timeout 5s,
    retries 5
  - restart: unless-stopped

  redis service:
  - Image: ${REGISTRY_HOST}/dockerhub/redis:7-alpine
  - container_name: nextcloud-stack-redis
  - command: redis-server --requirepass ${NEXTCLOUD_REDIS_PASSWORD}
  - healthcheck: redis-cli -a ${NEXTCLOUD_REDIS_PASSWORD} ping, interval
    10s, timeout 5s, retries 5
  - restart: unless-stopped

  Top-level volumes: block declaring nextcloud-app-data and
  nextcloud-db-data as named Docker volumes (not bind mounts — only the
  data directory is a bind mount, to the extra_mount path).

compose_forbidden: |
  a custom top-level networks: block, the "latest" image tag on any
  service, a cron container in this first pass (Nextcloud's background
  jobs can run via AJAX/webcron initially — add a dedicated cron
  container as a later, separate step once the base stack is validated,
  not bundled into first deploy), any hardcoded password (everything
  password-shaped must be a ${VAR} sourced from SOPS via with-secrets,
  same as NETBOX_DB_PASSWORD/NETBOX_REDIS_PASSWORD elsewhere).

contract_facts: |
  - Purpose: self-hosted file storage / sync, initial use case is a
    durable landing point for reports/docs from other lab projects
    (deep-research, CyberSecEval) — see docs/reporting-platform/
  - Zone: apps_seg (VLAN 120, new zone — see nextcloud-01)
  - IP: 192.168.120.10/24
  - Gateway: 192.168.120.1
  - VMID: 90010
  - Provides: nextcloud, port 8080, protocol tcp
  - Dependencies: none at deploy time; Authentik must already be live
    for OIDC wiring (nextcloud-05) to succeed
  - Persistent state: /var/www/html (app+config, named volume,
    docker_storage-backed), /var/www/html/data (user files, bind-mounted
    to the durable-zfs extra_mount at /var/lib/nextcloud-data),
    postgres data (named volume)
  - Nothing depends on this stack yet (deep-research/CyberSecEval
    ingestion is Phase 2, not yet wired)
  - What must not be edited casually: NEXTCLOUD_TRUSTED_DOMAINS and
    TRUSTED_PROXIES must stay correct or Nextcloud will reject all
    requests through Traefik with a "untrusted domain" error
  - Playbook: deploy-nextcloud-stack, docker_base + portainer_agent
    roles plus a compose file, plus post-install occ bootstrap tasks
    (see nextcloud-04)
  - Implementation files: terraform/lxc/stacks/nextcloud-stack/stack.yaml
    (new), terraform/lxc/stacks/nextcloud-stack/terragrunt.hcl (new),
    terraform/lxc/stacks/nextcloud-stack/docker-compose.yml (new),
    terraform/lxc/stacks/nextcloud-stack/inventory.yml (generated by
    terragrunt apply, do not hand-edit),
    terraform/lxc/ansible/playbooks/deploy-nextcloud-stack.yml (new)
```

### Step: nextcloud-02b-fix-registry-host-resolution

```yaml
id: nextcloud-02b-fix-registry-host-resolution
title: Resolve REGISTRY_HOST to Harbor's FQDN (not IP) before docker compose up
depends_on: [nextcloud-02-scaffold-stack-request]

change: >
  scaffold-stack.sh generates
  terraform/lxc/ansible/playbooks/deploy-nextcloud-stack.yml from
  compose_requirements using the minecraft-stack exemplar's shape (copy
  compose file to the target, "docker compose config" check, "docker
  compose up -d"). That generated playbook has no REGISTRY_HOST
  resolution of its own -- add one, modeled exactly on
  deploy-media-stack-lab.yml's docker_registry_host var (NOT
  netbox-stack's registry_host field, which resolves to the broken bare
  IP -- see reference_registry_host_vs_fqdn_harbor).

  Add this to the playbook's vars: block, alongside
  nextcloud_stack_fqdn_authentik (added by nextcloud-04):

    docker_registry_host: "{{ lookup('env', 'LAB_FQDN_HARBOR') | default('harbor.' ~ (lookup('env', 'LAB_DOMAIN') | default('lab.gibbsgreatly.xyz', true)), true) }}"

  Then add `environment: {REGISTRY_HOST: "{{ docker_registry_host }}"}`
  to the generated "docker compose up -d" task (the
  `ansible.builtin.command: cmd: docker compose up -d` task scaffold-stack.sh
  produces) and to the "docker compose config" validation task, so
  Compose's own ${REGISTRY_HOST} interpolation resolves to the FQDN at
  both validate and run time, not just whatever happens to be in the
  ambient shell environment.

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-nextcloud-stack.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any ansible-playbook run against pve or pve-test-vm in this step -- syntax-check only"

gates:
  - id: syntax-check
    cmd: "ansible-playbook --syntax-check terraform/lxc/ansible/playbooks/deploy-nextcloud-stack.yml"
    expect: "exit 0"
    critical: true
  - id: no-bare-ip-var
    cmd: "grep -q 'LAB_IP_HARBOR' terraform/lxc/ansible/playbooks/deploy-nextcloud-stack.yml && echo FAIL || echo OK"
    expect: "OK"
    critical: true
```

### Step: nextcloud-02c-add-monitoring-scrape-targets

**Not a step block against nextcloud-stack's own files — this edits a
different, already-running stack's deploy playbook
(`deploy-monitoring-stack.yml`), which needs its own scope/gate/deploy
treatment, not nextcloud-stack's.** VictoriaMetrics scrape targets are a
fully manual static list (`terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml`
lines 183-264 as of this plan's writing) — there is no NetBox-driven
auto-discovery for metrics despite NetBox tracking the host. Add two
entries there, matching the existing `media-stack-lab` entries exactly:

    - targets: ["{{ lookup('env', 'LAB_IP_NEXTCLOUD_STACK') }}:9100"]
      labels: {stack: nextcloud-stack}

  (under job_name: node_exporter, and the equivalent under job_name:
  cadvisor on port 8080 if a cadvisor sidecar is later added to
  nextcloud-stack's compose — not in the first pass per
  compose_forbidden above, so skip the cadvisor entry for now).

This requires redeploying `monitoring-stack` itself
(`scripts/provision.sh --stack monitoring-stack` against `pve`, under the
production approval flow — Ansible task/role change tier per CLAUDE.md's
Validation Tiers table) to pick up the new scrape target. Sequence this
after nextcloud-stack is actually live (so `LAB_IP_NEXTCLOUD_STACK`
resolves to a real, reachable host) rather than before.

### Step: nextcloud-03-add-secrets-placeholders

```yaml
id: nextcloud-03-add-secrets-placeholders
title: Document required new SOPS secret keys for nextcloud-stack
depends_on: [nextcloud-02-scaffold-stack-request]

change: >
  This step does NOT edit terraform/secrets.common.enc.yaml directly —
  SOPS-encrypted edits are an operator-only action per CLAUDE.md
  (Security and analysis... / Production Credential Controls: edit with
  `SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops
  terraform/secrets.common.enc.yaml`, never decrypted into a plaintext
  file, never edited by an agent). Instead, add this exact subsection to
  docs/nextcloud-stack/README.md immediately under its "Still genuinely
  open" heading, as a checklist the operator runs once before
  nextcloud-06:

    ## New SOPS secrets required before first deploy

    Add these keys to `terraform/secrets.common.enc.yaml` via
    `SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt sops terraform/secrets.common.enc.yaml`
    before running nextcloud-06:

    - `TF_VAR_nextcloud_db_password` — Postgres password for the
      nextcloud DB user
    - `TF_VAR_nextcloud_redis_password` — Redis auth password
    - `TF_VAR_nextcloud_admin_password` — initial Nextcloud admin
      account password
    - `NEXTCLOUD_OIDC_CLIENT_ID` — Authentik OIDC client id (also
      referenced by discover-authentik-edge.py, see nextcloud-05)
    - `NEXTCLOUD_OIDC_CLIENT_SECRET` — Authentik OIDC client secret

scope:
  allowed_paths:
    - docs/nextcloud-stack/README.md
  forbidden_actions:
    - "Any edit to terraform/secrets.common.enc.yaml or any *.enc.yaml file"
    - "Any edit outside allowed_paths"

gates:
  - id: no-secrets-file-touched
    cmd: "git diff --name-only | grep -v 'docs/nextcloud-stack/README.md' | grep -q . && echo FAIL || echo OK"
    expect: "OK"
    critical: true
```

### Step: nextcloud-04-occ-oidc-bootstrap-tasks

```yaml
id: nextcloud-04-occ-oidc-bootstrap-tasks
title: Add occ-based user_oidc bootstrap tasks to the generated deploy playbook
depends_on: [nextcloud-02-scaffold-stack-request]

change: >
  After nextcloud-02 generates
  terraform/lxc/ansible/playbooks/deploy-nextcloud-stack.yml, append these
  tasks to its tasks: list (after the existing "Start ... via docker
  compose" / wait_for-style tasks scaffold-stack.sh generates, following
  the minecraft-stack exemplar's shape in
  terraform/lxc/stacks/stack-request.example.yaml):

    - name: Install user_oidc app in Nextcloud
      ansible.builtin.command:
        cmd: docker exec nextcloud-stack-app php occ app:install user_oidc
      register: occ_install_user_oidc
      changed_when: "'already installed' not in occ_install_user_oidc.stderr"
      failed_when: >-
        occ_install_user_oidc.rc != 0 and
        'already installed' not in occ_install_user_oidc.stderr
      when: not ansible_check_mode

    - name: Register Authentik as an OIDC provider
      ansible.builtin.command:
        cmd: >-
          docker exec nextcloud-stack-app php occ user_oidc:provider
          authentik
          --clientid="{{ lookup('env', 'NEXTCLOUD_OIDC_CLIENT_ID') | mandatory('NEXTCLOUD_OIDC_CLIENT_ID env var is not set') }}"
          --clientsecret="{{ lookup('env', 'NEXTCLOUD_OIDC_CLIENT_SECRET') | mandatory('NEXTCLOUD_OIDC_CLIENT_SECRET env var is not set') }}"
          --discoveryuri="https://{{ nextcloud_stack_fqdn_authentik }}/application/o/edge-nextcloud-stack-nextcloud/.well-known/openid-configuration"
          --unique-uid=0
      register: occ_register_provider
      changed_when: "'Provider added' in occ_register_provider.stdout"
      failed_when: >-
        occ_register_provider.rc != 0 and
        'already exists' not in occ_register_provider.stderr
      when: not ansible_check_mode

  Add nextcloud_stack_fqdn_authentik to the playbook's vars: block,
  matching media-stack-lab's own pattern exactly:

    nextcloud_stack_fqdn_authentik: "{{ lookup('env', 'LAB_FQDN_AUTHENTIK') | default('authentik.' ~ (lookup('env', 'LAB_DOMAIN') | default('lab.gibbsgreatly.xyz', true)), true) }}"

  NOTE (see README.md "Still genuinely open"): the exact `occ
  user_oidc:provider` flag set (`--unique-uid`, discovery-uri-based vs
  manual endpoint flags) has not been validated against a live
  instance — confirm against the actual pinned Nextcloud version's
  `occ user_oidc:provider --help` output before treating this step's
  gate as sufficient proof it works end to end.

scope:
  allowed_paths:
    - terraform/lxc/ansible/playbooks/deploy-nextcloud-stack.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any ansible-playbook run against pve or pve-test-vm in this step -- syntax-check only"

gates:
  - id: syntax-check
    cmd: "ansible-playbook --syntax-check terraform/lxc/ansible/playbooks/deploy-nextcloud-stack.yml"
    expect: "exit 0"
    critical: true
```

### Step: nextcloud-05-authentik-oidc-route

```yaml
id: nextcloud-05-authentik-oidc-route
title: Register nextcloud-stack's OIDC route in the Authentik edge reconciler and add its EdgeManifest
depends_on: [nextcloud-02-scaffold-stack-request]

change: >
  In terraform/lxc/discover-authentik-edge.py, add one entry to each of
  the two existing dicts (immediately after the
  ("media-stack-lab", "immich") entries, matching their exact tuple
  shape):

  In OIDC_ROUTE_CLIENT_IDS (around line 51):
    ("nextcloud-stack", "nextcloud"): ("NEXTCLOUD_OIDC_CLIENT_ID", "nextcloud"),

  In OIDC_ROUTE_CLIENT_SECRETS (around line 62):
    ("nextcloud-stack", "nextcloud"): "NEXTCLOUD_OIDC_CLIENT_SECRET",

  Then create terraform/lxc/stacks/nextcloud-stack/edge.yaml with this
  exact content, modeled on media-stack-lab/edge.yaml:

    apiVersion: homelab.gibbsgreatly.xyz/v1alpha1
    kind: EdgeManifest
    metadata:
      name: nextcloud-stack-edge
      stack: nextcloud-stack
      annotations:
        repo.auth.oidc.client_id_env: NEXTCLOUD_OIDC_CLIENT_ID
        repo.auth.oidc.client_secret_env: NEXTCLOUD_OIDC_CLIENT_SECRET
    spec:
      routes:
        - name: nextcloud
          host: nextcloud.${LAB_DOMAIN}
          backend:
            type: url
            url: http://${LAB_IP_NEXTCLOUD_STACK}:8080
          dns:
            enabled: true
            target: ${LAB_IP_PROXY}
            ttl: 5m
          tls:
            resolver: letsencrypt
          auth:
            mode: oidc

scope:
  allowed_paths:
    - terraform/lxc/discover-authentik-edge.py
    - terraform/lxc/stacks/nextcloud-stack/edge.yaml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any reconcile-authentik-edge.py run against pve in this step -- discovery/validation only"

gates:
  - id: python-syntax
    cmd: "python3 -m py_compile terraform/lxc/discover-authentik-edge.py"
    expect: "exit 0"
    critical: true
  - id: yaml-syntax
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/stacks/nextcloud-stack/edge.yaml'))\""
    expect: "exit 0"
    critical: true
```

### Step: nextcloud-06-deploy-and-validate

**Not a step block — production deploy, operator approval flow.**
`scripts/provision.sh --stack nextcloud-stack` is a mutating,
Ansible-backed deploy against `pve`. Per CLAUDE.md's Validation Tiers
table, "Ansible task or role changes" (which a brand-new stack's first
deploy is) validate directly on `pve` under the production approval
flow, not on `pve-test-vm`. Before running this:

1. Confirm all SOPS secrets from nextcloud-03's checklist are set.
2. Preflight Summary to the operator: target = `pve`, mutating, exact
   objects = new `apps_seg` SDN zone/vnet/firewall rules (from
   nextcloud-01) + new `nextcloud-stack` LXC + its Docker Compose stack,
   out-of-scope = everything else.
3. Wait for explicit operator "Proceed."
4. `export TASK_APPROVAL="nextcloud-stack-first-deploy"` then
   `./with-secrets-prod scripts/provision.sh --stack nextcloud-stack`.
5. Verify per CLAUDE.md's Stack Service Types convention: `curl` to
   Nextcloud's HTTP port — add a row for `nextcloud-stack` there
   (`curl -f http://192.168.120.10:8080/status.php`) once this step
   actually runs, since the table doesn't have one yet.
6. After-Action Summary to the operator per the standard flow.

---

## Phase 2 — reports ingestion (deep-research, same node only)

**Deliberately narrow.** Per README.md, CyberSecEval's `pve-tiny` push is
out of scope until `docs/reporting-platform/plan.md` Phase 3 (cross-node
ingestion) lands. This phase only covers `deep-research` (`pve`,
`ai-services-stack`, `ai_seg`, same node as `nextcloud-stack`).

### Step: nextcloud-P2-01-research-push-hook

**Not a step block yet — research needed before this can be written as
literal content.** Before authoring a real step:

1. Read `docs/reporting-platform/plan.md`'s Phase 1 (the `deep-research`
   adopter work) and the actual `deep-research` code path that writes
   `reports/deep-research/<run-id>/{report.md,manifest.json}` to find
   exactly where a post-write hook belongs.
2. Decide: does `deep-research` push via a WebDAV PUT immediately after
   writing each run's `report.md`/`manifest.json`, or does a small
   separate sync script poll `reports/deep-research/` and push new run
   directories to Nextcloud on an interval? Prefer the former if
   `deep-research`'s run-completion code path is a single identifiable
   function; prefer the latter if it isn't, to avoid coupling Nextcloud
   availability to `deep-research`'s own run success/failure.
3. Per `docs/reporting-platform/CONVENTION.md`'s security expectations,
   this needs its own scoped Nextcloud app password / WebDAV credential
   — never a shared or admin credential, and scoped to a
   `deep-research`-only folder in Nextcloud, not full account access.
4. Confirm `apps_seg` firewall reachability from `ai_seg` (a new rule:
   `from: ai_seg, to: apps_seg, protocol: tcp, ports: [8080]` — not yet
   added anywhere in this plan; add it to nextcloud-01's policy block,
   or as its own follow-up step, once the push direction is confirmed).

Once these are resolved, write `nextcloud-P2-02-...` as a real step
block with literal file paths and exact content, following the same
literal-vs-constrained discipline as Phase 1 above.

---

## Phase 3 — Pangolin exposure, monitoring, and security

**Basis:** a separate, already-existing repo, `/home/steve/git/oci`,
designs the OCI-hosted Pangolin edge and its home-side connector in
detail (`docs/pangolin-architecture-plan.md`,
`docs/newt-vlan-design-plan.md`,
`docs/pangolin-observability-and-graylog-plan.md`). The OCI instance
itself hasn't changed since that design was written (operator-confirmed
2026-09-23), so this plan treats it as the current, authoritative design
— not stale — and does not re-derive it. This phase adapts that design
to `nextcloud-stack` as the concrete driver, rather than inventing a
separate exposure mechanism.

**Correction to this plan's own earlier framing:** `nextcloud-stack`'s
README originally said Pangolin exposure would eventually reach
`apps_seg:8080` directly. That is wrong per
`pangolin-observability-and-graylog-plan.md`: Newt gets an allow rule
only to lab Traefik (`edge_seg`), never to the application zone/port
directly — "this keeps the connector policy stable as services move
behind the edge proxy and prevents a published resource from becoming a
general LAN route." Traefik remains the single ingress control point for
both LAN and Pangolin-sourced traffic.

**Shared infrastructure, not nextcloud-specific.** The connector VLAN,
the Traefik source-aware split, and OCI-side monitoring/logging all
benefit every future Pangolin-published service (Pentagi is the OCI
repo's own documented first pilot), not just nextcloud-stack. This phase
builds that shared infrastructure with nextcloud-stack as the first
concrete service riding on it — subsequent services reuse it rather than
repeating this phase.

### Step: nextcloud-P3-01-create-connector-seg-zone

**DONE, live on `pve` as of 2026-09-23** — file committed
(`a24d0f94`) and SDN objects applied via `pvesh` under the production
approval flow (task `nextcloud-P3-01-connector-seg-sdn-apply`).
Verified: zone `tvnewt`, vnet `tvnewt` tag 110, subnet
`192.168.110.0/24`/gw `192.168.110.1` all present via `pvesh get`, and
`vmbr0.110` UP on the host. Kept below as a record of what ran, with
one real deviation from the original text: `apps_seg` (from
`nextcloud-01`) didn't exist yet when this ran — Phase 1 is still not
built — so the block was anchored after `ai_seg` instead. Re-anchor
after `apps_seg` only if this step is ever re-run from scratch on a
host where Phase 1 already landed first.

```yaml
id: nextcloud-P3-01-create-connector-seg-zone
title: Create connector_seg SDN zone for the Newt connector (VLAN 110, 192.168.110.0/24)
depends_on: []

change: >
  VLAN 100 was this step's original choice but is already live as
  cse_seg (terraform/lxc/network/pve-tiny.yaml, 192.168.100.0/24,
  confirmed present on the physical switch trunk 2026-09-23) — using it
  again here would collide on the shared trunk. Every VLAN tag already
  in use across terraform/lxc/network/*.yaml as of 2026-09-23 is 10, 20,
  30, 40, 50, 60, 70, 80, 90, 100; this step takes the next free tag,
  110. Re-check terraform/lxc/network/*.yaml for `vlan_tag:` values
  before executing this step, in case another zone has claimed 110 in
  the meantime.

  Insert this exact block into terraform/lxc/network/pve.yaml in the
  zones: section, immediately after the apps_seg zone block added by
  nextcloud-01 (search for "gateway: \"192.168.120.1\"" then "snat: false"
  to find its end) — or, if apps_seg doesn't exist yet (Phase 1 not
  built), anchor after ai_seg instead (search for
  "gateway: \"${lab_gw_ai}\"" then "snat: false"), as was actually done
  2026-09-23:

    # connector_seg — Newt connector for OCI Pangolin edge (VLAN 110, 192.168.110.0/24)
    connector_seg:
      description: Newt connector for the OCI Pangolin edge (see /home/steve/git/oci) — reaches only lab Traefik, nothing else
      type: sdn_vnet
      bridge: tvnewt
      firewall: false
      sdn:
        zone: tvnewt
        zone_type: vlan
        bridge: vmbr0
        nodes:
          - pve
        vnet: tvnewt
        vlan_tag: 110
        alias: pve connector segment
        subnet: "192.168.110.0/24"
        gateway: "192.168.110.1"
        snat: false

  In the members section, insert immediately after apps_seg's member block:

    connector_seg:
      description: Newt connector — minimal host, no unrelated workloads, per newt-vlan-design-plan.md
      attachment: connector_seg
      containers:
        - "newt-connector (VMID 110010) — 192.168.110.10"

  In the policies: section, insert these two rules at the end of the
  policies list (after apps_seg's explicit-deny rule from nextcloud-01).
  This is deliberately narrower than newt-vlan-design-plan.md's generic
  matrix: that doc's DNS/internet-egress rows aren't needed as explicit
  east-west rules in this repo's existing pattern (MikroTik is the
  gateway for every zone, and internet egress is already implied by
  every other zone's own "explicit deny" rule wording, e.g. apps_seg's
  "no other reachability beyond the above plus internet egress" —
  confirm this reading against MikroTik's actual default-forward policy
  before treating it as proven, not just inferred from file comments).
  The one genuinely new east-west permission this connector needs is
  reach to lab Traefik — nowhere else:

    - from: connector_seg
      to: 192.168.30.11
      protocol: tcp
      ports: [443]
      description: >-
        Newt connector to pangolin-proxy ONLY (192.168.30.11, edge_seg)
        — a second, dedicated Traefik instance created by nextcloud-P3-03
        that serves only the explicit subset of routes opted into
        Pangolin. This is deliberately NOT 192.168.30.10 (the main,
        LAN-facing Traefik that fronts everything else) — connector_seg
        has no network path to it at all, by construction, not by
        per-router policy. Per pangolin-observability-and-graylog-plan.md:
        "Newt does NOT receive a direct allow rule to the [application]
        address... this keeps the connector policy stable as services
        move behind the edge proxy." Do not add a connector_seg ->
        apps_seg (or any other app zone, or the main Traefik) rule even
        for a single, specific service.
    - from: connector_seg
      to: default
      protocol: all
      ports: []
      description: Explicit deny — connector_seg has no other reachability beyond lab Traefik plus internet egress

  Do NOT add a connector_seg -> Graylog rule in this step. Per
  pangolin-observability-and-graylog-plan.md, OCI log delivery to Graylog
  is a separate, not-yet-implemented piece (see nextcloud-P3-05) that
  would need its own dedicated-ingestion-port rule, added only once that
  path is actually built — adding it speculatively now would open a path
  to nothing.

scope:
  allowed_paths:
    - terraform/lxc/network/pve.yaml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Any terragrunt apply / SDN apply -- validation only in this step"
    - "Any rule granting connector_seg reach to apps_seg, the main Traefik (192.168.30.10), or any zone other than 192.168.30.11"

gates:
  - id: yaml-syntax
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/network/pve.yaml'))\""
    expect: "exit 0"
    critical: true
  - id: no-direct-app-zone-rule
    cmd: "grep -A3 'from: connector_seg' terraform/lxc/network/pve.yaml | grep -q 'to: apps_seg' && echo FAIL || echo OK"
    expect: "OK"
    critical: true
  - id: no-main-traefik-rule
    cmd: "grep -A3 'from: connector_seg' terraform/lxc/network/pve.yaml | grep -q '192.168.30.10' && echo FAIL || echo OK"
    expect: "OK"
    critical: true
```

### Step: nextcloud-P3-02-newt-host-deploy

**Not a step block yet — depends on nextcloud-P3-01 being deployed and
validated first**, and on a decision this plan defers rather than
defaults: `newt-vlan-design-plan.md` Phase 1 calls for "choose the Newt
host and its VLAN/subnet" as an explicit inventory-check step, and its
own transitional option (a locked-down `mgmt_seg` LXC) versus a
dedicated `connector_seg` host (what nextcloud-P3-01 above assumes) is
listed as one of `pangolin-observability-and-graylog-plan.md`'s own
"Open decisions." This plan takes the dedicated-VLAN option as the
target (matching both OCI docs' stated preference), but the actual Newt
install — enrollment credentials, minimal host provisioning, no
unrelated workloads per the design — is a credential-creating
control-plane action, not local-model-executable file content. Scaffold
it as a minimal LXC in `connector_seg` (192.168.110.10, per
nextcloud-P3-01) the same way other stacks are scaffolded, but treat
Newt's own enrollment (`repeatable-operations.md`: "install Newt with
the site enrollment credentials... remain control-plane or
home-network operations") as an operator action using the already-issued
`lab` site's credentials — never generate or store new ones in this
repo.

### Step: nextcloud-P3-03-pangolin-proxy-stack

**Decision locked in (2026-09-23, operator-confirmed): Option B — a
second, dedicated Traefik instance, not a second entrypoint on the
shared one.** `pangolin-observability-and-graylog-plan.md` documented
three isolation options; the entrypoint-on-shared-instance option was
rejected in favor of physical separation: a compromised or misconfigured
Newt host gets no network path to anything except this second Traefik's
own, deliberately narrow dynamic config, rather than relying on
`render-edge-traefik.py` always getting per-route entrypoint assignment
right as more services get added. This is shared platform work (benefits
every future Pangolin-published service — cse-panel, deep-research, and
others — not just nextcloud-stack), scoped larger than nextcloud-stack
alone; nextcloud-stack is the first concrete service riding on it.

```yaml
id: nextcloud-P3-03-pangolin-proxy-stack
title: Scaffold a second, dedicated Traefik instance (pangolin-proxy) for Pangolin-published routes only
depends_on: [nextcloud-P3-01-create-connector-seg-zone]

change: >
  Scaffold a new stack, pangolin-proxy, in edge_seg alongside the
  existing Traefik (same zone, same firewall reachability to Authentik --
  see edge_seg -> mgmt_seg:9443 "Traefik forward-auth to Authentik",
  already covers this new instance for free with no new rule needed).

  stack.yaml facts: hostname pangolin-proxy, ip_address 192.168.30.11/24,
  gateway 192.168.30.1 (edge_seg's existing gateway), vmid 30011, zone
  edge_seg, tags [docker, traefik, pangolin, edge], provides
  (pangolin-proxy-https, port 443, protocol tcp), deployment_tier apps,
  apt_cacher_host "${lab_ip_apt_cacher}".

  Compose: a single Traefik service, same pinned image/digest as the
  main proxy-stack's traefik_image (see group_vars-equivalent pin in
  this repo's own proxy-stack role -- read it directly rather than
  assuming it matches, images drift independently per stack). Static
  config (traefik.yml): entryPoints has only `websecure` (:443) -- no
  `web`/:80 redirect entrypoint is needed since Pangolin already
  terminates the public-facing TLS leg; this instance's :443 only needs
  to be reachable from connector_seg, never from the internet or the
  LAN directly. providers.file watching a `/etc/traefik/dynamic/`
  directory, same pattern as the main proxy-stack. certificatesResolvers:
  reuse the same Let's Encrypt account/Cloudflare DNS-01 challenge
  pattern as the main proxy-stack's `letsencrypt` resolver (same
  CF_DNS_API_TOKEN, separate acme.json storage since this is a distinct
  Traefik process/container).

  Dynamic config: write dynamic/authentik.yml as an EXACT copy of the
  main proxy-stack's shared Authentik middleware block (same
  `proxy_lab_fqdn_authentik_internal` address, same
  authResponseHeaders) -- see nextcloud-P3-03b for why this needs its
  own copy rather than being shared.

  Per-route dynamic config files are NOT written by this step -- they
  come from EdgeManifests via a new renderer target (nextcloud-P3-03c),
  starting empty (this stack, by itself, publishes nothing).

scope:
  allowed_paths:
    - terraform/lxc/stacks/pangolin-proxy/
    - terraform/lxc/ansible/playbooks/deploy-pangolin-proxy.yml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "Adding a web/:80 entrypoint or any route that is not explicitly opted into Pangolin publishing"
    - "Any terragrunt apply or live deploy in this step -- scaffold and syntax-check only"

gates:
  - id: syntax-check
    cmd: "ansible-playbook --syntax-check terraform/lxc/ansible/playbooks/deploy-pangolin-proxy.yml"
    expect: "exit 0"
    critical: true
```

### Step: nextcloud-P3-03b-duplicate-authentik-middleware

```yaml
id: nextcloud-P3-03b-duplicate-authentik-middleware
title: Confirm pangolin-proxy's forwardAuth middleware is a real, working duplicate, not a shared reference
depends_on: [nextcloud-P3-03-pangolin-proxy-stack]

change: >
  The main proxy-stack's forwardAuth middleware
  (terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml, "Write shared
  Authentik middleware config" task) calls
  https://{{ proxy_lab_fqdn_authentik_internal }}:9443/outpost.goauthentik.io/auth/traefik
  -- an internal-only hostname (LAB_FQDN_AUTHENTIK_INTERNAL, default
  authentik-int.<domain>) that resolves directly to Authentik, not
  through either Traefik. This means pangolin-proxy's own copy of this
  middleware (written by nextcloud-P3-03 above) works identically and
  needs no new firewall rule -- confirm this live once both stacks
  exist: the same outpost call from a second, independent Traefik
  process, same edge_seg -> mgmt_seg:9443 reachability.

  Live-verify (not assumed): that authentik-int.<domain> actually
  resolves to Authentik's real IP from edge_seg (not through Traefik --
  a routing loop would be a real, silent failure mode: pangolin-proxy
  calling out through itself or the main Traefik to reach Authentik).

scope:
  allowed_paths: []
  forbidden_actions:
    - "Any file edit in this step -- verification only, against a live pangolin-proxy + proxy-stack + authentik-stack"

gates:
  - id: dns-resolves-directly
    cmd: "dig +short authentik-int.${LAB_DOMAIN} | grep -qE '^[0-9]' && echo OK || echo FAIL"
    expect: "OK"
    critical: true
```

### Step: nextcloud-P3-03c-edgemanifest-pangolin-opt-in

**Not a step block yet — genuinely open, needs a short design pass
before it's literal.** `render-edge-traefik.py` currently renders every
EdgeManifest route into the main proxy-stack's single dynamic config
directory (confirmed by reading it — one output target, no branching on
destination). It needs a second output path for routes that opt into
Pangolin publishing. Two real design questions to resolve before writing
this as a step:

1. **Same route, two hostnames, or two separate route entries?** A
   service published both on the LAN (`nextcloud.${LAB_DOMAIN}`) and via
   Pangolin (`nextcloud.pan.gibbsgreatly.xyz`) could be modeled as one
   EdgeManifest route with a `pangolin.public_host:` field (one router
   rendered twice, once per Traefik instance, different Host rule each
   time), or as two separate route entries in the same EdgeManifest.
   Prefer the former — it keeps one source of truth for backend URL/auth
   mode per service, rather than two entries that can drift out of sync.
2. **OIDC redirect_uris need a second entry.** `discover-authentik-edge.py`
   computes each OIDC route's expected `redirect_uris` from its `host:`
   field alone (`_oidc_redirect_uris`, confirmed by reading it) and
   reconciles Authentik's provider config to match exactly. A
   Pangolin-published OIDC route (not nextcloud initially, since
   nextcloud-04/05 use `forwardAuth`-free `occ user_oidc` wiring directly
   against Authentik rather than this repo's `forwardAuth`/OIDC
   EdgeManifest path — but relevant for any future OIDC-mode route, e.g.
   openwebui) needs the reconciler taught to add both hostnames'
   callback URLs to the same provider, not just the LAN one. Confirm
   which of nextcloud's own auth paths (occ user_oidc vs this repo's
   EdgeManifest OIDC path) actually applies before assuming this affects
   nextcloud-stack directly.

Once resolved, write the real step: extend `render-edge-traefik.py` and
the `EdgeManifest` CRD-equivalent schema, add the LAN-vs-Pangolin source-
policy regression tests from `pangolin-observability-and-graylog-plan.md`
(every LAN-approved service still works from the LAN; an unpublished
service fails through Pangolin even when its hostname is supplied — this
is now trivially true by construction under Option B, since
pangolin-proxy's dynamic config simply has no router for it; a request
from the connector subnet cannot reach a route by changing its Host
header — also true by construction, since connector_seg has no network
path to the main Traefik at all under nextcloud-P3-01's rule).

### Step: nextcloud-P3-04-nextcloud-pangolin-route

**Depends on nextcloud-P3-03c landing first.** Once the EdgeManifest
Pangolin opt-in mechanism exists, add a `pangolin` block to
`terraform/lxc/stacks/nextcloud-stack/edge.yaml`'s `nextcloud` route
(alongside the existing internal LAN route added by nextcloud-05),
publishing `nextcloud.pan.gibbsgreatly.xyz` via pangolin-proxy (not the
main Traefik) — matching
`pangolin-observability-and-graylog-plan.md`'s service onboarding
contract table (dedicated `*.pan.gibbsgreatly.xyz` hostname, distinct
resource/route names so an operator can tell which policy layer rejected
a request, lab Traefik as the target — never the container directly).
Not written as literal content yet since it depends on P3-03c's
not-yet-decided schema shape. Also confirm at this point which of
nextcloud's two auth paths is actually live (occ user_oidc direct
against Authentik, from nextcloud-04/05, vs this repo's EdgeManifest
`forwardAuth`/OIDC path) — nextcloud-P3-03c's redirect_uri concern only
applies if the EdgeManifest OIDC path is the one in use.

### Step: nextcloud-P3-05-pangolin-resource-and-lab-site

**Not a step block — control-plane, credential/policy-creating action,
same category `repeatable-operations.md` explicitly reserves for manual
operation: "should be automated only after the target API workflow is
confirmed, because those steps create credentials and access policy."**
Once nextcloud-P3-04's route exists:

1. Create the Pangolin resource via the Integration API
   (`https://api.gibbsgreatly.xyz/v1`), site `lab` (already created and
   enrolled per `repeatable-operations.md`), targeting the new Pangolin
   Traefik entrypoint/route for nextcloud, not the container directly.
2. Require SSO and MFA by default (no anonymous bypass), per
   `pangolin-architecture-plan.md` and the service onboarding contract.
3. Assign a dedicated access group, not the owner account, per
   `pangolin-architecture-plan.md` Phase 3.
4. Decide whether to keep Nextcloud's own Authentik OIDC login active in
   addition to Pangolin's gate (defense in depth, the same call
   `pangolin-observability-and-graylog-plan.md` makes for Pentagi as "an
   administrative or AI service") — Nextcloud holds real user files, so
   default to keeping both layers unless a documented decision says
   otherwise.
5. Run the public-edge security tests from
   `pangolin-observability-and-graylog-plan.md`'s "Public-edge security
   tests" section against `nextcloud.pan.gibbsgreatly.xyz`: clean-browser
   and unauthorized-account access, MFA, certificate hostname, secure
   redirects/cookies, uploads (Nextcloud is upload-heavy — this is a real
   functional risk, not a formality), idle/long-request timeouts, and
   confirm the home service is unreachable directly from the internet.
6. Confirm the rollback path works: disabling the Pangolin resource,
   then disabling the Traefik route, each independently blocks access.

### Step: nextcloud-P3-06-oci-monitoring-and-logging

**Not a step block — this is `pangolin-observability-and-graylog-plan.md`'s
own Phases 0–5, not re-derived here.** That plan's own "Purpose and
current state" section says explicitly: "No infrastructure changes are
authorized by this document. First verify the live Graylog input,
address, TLS mode, and firewall contract" — i.e. even its own Phase 0
hasn't been done yet as of this plan's writing. Before nextcloud-stack
is published via Pangolin, at minimum confirm:

- OCI compute/network/cost metrics are collected read-only via OCI
  Monitoring/Usage APIs (no public monitoring endpoint, no home VLAN
  route to OCI).
- Pangolin/Traefik/Gerbil/Newt logs and metrics ship to the existing
  Graylog service via a private Pangolin machine-client resource through
  site `lab` — never a public Graylog port, never Newt reaching Graylog
  UI/API/SSH directly (only a dedicated ingestion port, if/when this
  lands — see nextcloud-P3-01's note on why that firewall rule isn't
  added yet).
- Grafana dashboards exist for the Pangolin edge (Traefik rate/latency/
  5xx, certificate expiry, Newt online state) and alert on: Pangolin/
  Gerbil down, Newt offline, no expected logs for 10 minutes, certificate
  expiry under 21 days, and OCI cost spikes.
- The acceptance tests in that doc's own "Acceptance tests" section pass:
  no public monitoring/Graylog port open, revoking the machine credential
  breaks only log delivery, Newt reaches only approved destinations.

This is shared OCI-edge infrastructure, not specific to nextcloud-stack
— treat it as its own workspace under `/home/steve/git/oci` (that repo
already has the design; it just hasn't been executed), and treat
nextcloud-stack's Pangolin publish (nextcloud-P3-05) as blocked on at
minimum the logging path existing, so a compromised or misbehaving
public-facing Nextcloud instance is actually observable and its access
logs actually land somewhere reviewable.

### Step: nextcloud-P3-07-oci-hardening-and-wazuh

**Not a step block — points at a full, detailed, executable plan
written in the `oci` repo itself** (that repo has no local-model
step-packet tooling, so it isn't written as fenced YAML steps the way
this repo's plans are):
[`/home/steve/git/oci/docs/hardening-and-wazuh-plan.md`](../../../oci/docs/hardening-and-wazuh-plan.md).
Covers, in five phases: SSH/NSG lockdown (OCI Bastion, removing direct
SSH exposure), OS baseline hardening (unattended security upgrades, a
host firewall mirroring the NSG allow-list, minimal installed
packages), a Wazuh agent enrolled with a credential **unique to the OCI
host** (manager-side pre-registration via `manage_agents`, never the
shared `WAZUH_AGENT_AUTHD_PASSWORD` every other agent uses — so a
compromise of this internet-facing host can't be used to enroll rogue
agents or interfere with the rest of the fleet's trust), OCI-native VCN
Flow Logs/Audit logs as a control-plane-level signal an attacker with
root on the instance can't suppress, and shipping Pangolin's own
backups off-host to Object Storage. That plan is self-contained and
executable on its own — this step exists only to record the dependency:
**nextcloud-P3-05 (Pangolin publish) should be treated as blocked on
that plan's Phase 1 (SSH/NSG) and Phase 3 (Wazuh agent) at minimum**,
same reasoning as nextcloud-P3-06 for logging.

The one piece of that plan that is proxmox-homelab's own file, not
oci's, is the firewall rule granting `connector_seg` reach to
`wazuh-stack`'s event port. Write it as its own step, additive to
nextcloud-P3-01's policy block:

```yaml
id: nextcloud-P3-07b-connector-wazuh-firewall-rule
title: Add connector_seg -> wazuh-stack:1514 firewall rule (Wazuh agent events only, not enrollment)
depends_on: [nextcloud-P3-01-create-connector-seg-zone]

change: >
  Insert this rule into terraform/lxc/network/pve.yaml's policies:
  section, immediately before connector_seg's existing explicit-deny
  rule (added by nextcloud-P3-01, description starting "Explicit deny —
  connector_seg has no other reachability..."):

    - from: connector_seg
      to: 192.168.40.15
      protocol: tcp
      ports: [1514]
      description: >-
        Newt connector (via a private Pangolin resource, not a direct
        public route -- see /home/steve/git/oci/docs/hardening-and-wazuh-plan.md
        Phase 3.3) to wazuh-stack's agent-events port only. Deliberately
        NOT port 1515 (enrollment): the oci-pangolin agent's client.keys
        is provisioned out-of-band per that plan's Step 3.1/3.2, so this
        connector never needs, and should never be granted, a route to
        the enrollment port at all.

  IMPORTANT — verify against MikroTik's live state before assuming this
  file is a complete picture: wazuh-stack's existing agents
  (proxy-stack, authentik-stack, technitium-stack, pve itself) already
  have working 1514/1515 rules that were applied directly to MikroTik
  and never mirrored back into this file (confirmed --
  docs/wazuh-stack/README.md documents this explicitly, and this file
  has zero existing 1514/1515/192.168.40.15 references despite 6 live
  agents). Cross-check the live MikroTik ruleset, not just this file,
  before treating this step as sufficient on its own.

scope:
  allowed_paths:
    - terraform/lxc/network/pve.yaml
  forbidden_actions:
    - "Any change outside allowed_paths"
    - "A rule granting connector_seg reach to wazuh-stack port 1515 (enrollment)"
    - "Any terragrunt apply / SDN apply / MikroTik change in this step -- file edit and syntax gate only"

gates:
  - id: yaml-syntax
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/network/pve.yaml'))\""
    expect: "exit 0"
    critical: true
  - id: no-enrollment-port
    cmd: "grep -A3 'from: connector_seg' terraform/lxc/network/pve.yaml | grep -q '1515' && echo FAIL || echo OK"
    expect: "OK"
    critical: true
```

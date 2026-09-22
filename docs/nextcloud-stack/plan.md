# nextcloud-stack plan

Written with `.github/prompts/plan-change.prompt.md`, following
`docs/agent-design/step-packet-schema.md`. Intended to be executed with
`.github/prompts/implement-step.prompt.md`. See [README.md](README.md) for
decisions, research, and what's still genuinely open.

**Not a priority right now** — this plan exists so the work is ready to
pick up, not to be run immediately.

Two things below are genuinely not step blocks, and are written as plain
operator/prose instructions instead: running `scaffold-stack.sh`
(`nextcloud-02`) and the live deploy against `pve` under the production
approval flow (`nextcloud-06`).

---

## Phase 1 — stack, zone, storage, SSO

### Step: nextcloud-01-create-apps-seg-zone

```yaml
id: nextcloud-01-create-apps-seg-zone
title: Create apps_seg SDN zone (VLAN 90, 192.168.90.0/24) and its firewall policies
depends_on: []

change: >
  Insert this exact block into terraform/lxc/network/pve.yaml in the
  zones: section, immediately after the media_seg zone block (search for
  "gateway: \"192.168.80.1\"" then "snat: false" to find its end):

    # apps_seg — General application services (VLAN 90, 192.168.90.0/24)
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
        vlan_tag: 90
        alias: pve apps segment
        subnet: "192.168.90.0/24"
        gateway: "192.168.90.1"
        snat: false

  In the members section (search for "media_seg:" under the second
  occurrence, near "media-stack-lab (VMID 80010)"), insert immediately
  after that block:

    apps_seg:
      description: General application services — Nextcloud, additive alongside existing zones
      attachment: apps_seg
      containers:
        - "nextcloud-stack (VMID 90010) — 192.168.90.10"

  In the policies: section, insert these six rules immediately before the
  final existing rule in the file (the "media-stack-lab node_exporter TLS
  cert issuance from step-ca" rule, description ending "targeting the
  deny rule." — insert after that rule, i.e. at the end of the policies
  list):

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
        nextcloud-stack (user_oidc) to Authentik via Traefik for OIDC
        token exchange. media-stack-lab found live (2026-09-04) that an
        OIDC client's server-to-server token exchange goes out via
        edge_seg on 443, not direct to mgmt_seg:9443 — applying that
        lesson here from the start rather than rediscovering it.
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
  ip_address: "192.168.90.10/24"
  gateway: "192.168.90.1"
  dns_server: "192.168.90.1"
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
    pull-through, matching netbox-stack's ${REGISTRY_HOST}/dockerhub/...
    prefix convention — not a bare dockerhub reference).
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
  - Zone: apps_seg (VLAN 90, new zone — see nextcloud-01)
  - IP: 192.168.90.10/24
  - Gateway: 192.168.90.1
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
   (`curl -f http://192.168.90.10:8080/status.php`) once this step
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

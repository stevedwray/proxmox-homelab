# immich-stack plan

Written with `.github/prompts/plan-change.prompt.md`, following
`docs/agent-design/step-packet-schema.md`. Intended to be executed with
`.github/prompts/implement-step.prompt.md`, one step at a time, in Laguna's
`Repo Tools` Copilot agent mode (or any local model in that role).

## Research this plan is based on

- Real, current upstream Immich compose facts (fetched from
  `github.com/immich-app/immich/main/docker/docker-compose.yml`, not
  recalled from memory, since this becomes real deployed infrastructure):
  four services -- `immich-server` (`ghcr.io/immich-app/immich-server`,
  port 2283, depends on redis+database), `immich-machine-learning`
  (`ghcr.io/immich-app/immich-machine-learning`, ML inference, its own
  `model-cache` volume), `redis` (actually `valkey/valkey:9`,
  digest-pinned), `database` (`ghcr.io/immich-app/postgres:14-
  vectorchord0.4.3-pgvectors0.2.0`, digest-pinned -- **not** vanilla
  postgres/pgvector; Immich's vector-search feature requires this specific
  fork).
- Precedent: `docs/stack-lifecycle-refactor/stage-10-minecraft-exemplar.md`
  -- same "author a `stack-request.yaml`, then run `scaffold-stack.sh`"
  split, and the same deliberate choice to defer an SDN zone / Portainer
  registration for a first pass rather than scope-creep a first exemplar.
- Zone precedent: this repo's user-facing app stacks (`torrent-stack`,
  `media-stack`, `gaming-stack`) are legacy LAN-bridge LXCs with no SDN
  zone; `docs/application-migration/` sketches per-app VLANs
  (`media_seg` etc.) that were never actually created. Immich would be the
  first new app-tier stack since that gap was identified.

## Decisions (resolved 2026-08-25)

- **Zone**: new `media_seg` zone, VLAN 80, `192.168.80.0/24`, gateway
  `192.168.80.1` -- follows the existing +10 zone-numbering pattern in
  `network/pve.yaml` (10/20/30/40/50/60/70 already taken; `game_seg` at
  VLAN 60 exists but is scoped to gaming, not photos). This is genuinely
  new SDN scope, not a stack-request.yaml field -- see step `immich-00`
  below.
- **Storage**: NFS, not local `docker_storage_size`. Real, already-live
  precedent: `media-stack`'s Jellyfin container bind-mounts
  `/nas-media/...` straight from a NAS export
  (`terraform/lxc/stacks/media-stack/jellyfin-docker-compose.yml`). That
  mount is **not** Terraform/Ansible-managed anywhere in this repo --
  confirmed by search, it's manual host-level setup done once. So
  "confirm the NAS export is mounted on the target LXC" is a real
  prerequisite for immich-01, the same way the historical Jellyfin
  migration task (`docs/plan/tasks/06-app-stacks-05-migrate-jellyfin.md`)
  listed it as a checklist item, not something `scaffold-stack.sh` can
  set up.

## Step: immich-00-create-media-seg-zone

Real Terraform/SDN/MikroTik work, not a stack-request.yaml field, and not
a step a local model should attempt -- creating a zone touches shared
network config and needs the operator's normal review, not a
`Repo Tools`/Laguna session. Included here only so the plan is complete
and the dependency is explicit.

```yaml
id: immich-00-create-media-seg-zone
title: Create media_seg SDN zone (VLAN 80, 192.168.80.0/24)
model_hint: frontier
depends_on: []

change: >
  Add a media_seg zone to terraform/lxc/network/pve.yaml following the
  existing zone blocks' exact shape (see infra_seg/ai_seg/game_seg for
  the pattern: zone/vnet/subnet/gateway declaration plus the VLAN
  comment header). VLAN 80, subnet 192.168.80.0/24, gateway
  192.168.80.1. Add the matching MikroTik trunk/VLAN interface and any
  cross-zone firewall rules immich-stack will need (at minimum: LAN ->
  media_seg reachability for the workstation; consult existing zone
  rules for the exact shape). This is additive-only (new zone, no
  changes to existing zones/rules) -- CLAUDE.md's validation tier for
  that is apply, then scripts/provision.sh --stack <name> against 1-2
  existing stacks in adjacent zones to confirm no regression, not a
  full teardown cycle.

scope:
  allowed_paths:
    - terraform/lxc/network/pve.yaml
  forbidden_actions:
    - "Modifying any existing zone's subnet, gateway, or firewall rule"
    - "Applying directly against pve without going through this repo's normal branch/validate/promote workflow first"

gates:
  - id: terragrunt-plan-shows-only-additions
    cmd: "./with-secrets terragrunt --working-dir terraform/lxc/stacks run --all plan"
    expect: "plan shows only new resources for media_seg -- zero changes/deletions to any existing zone"
    critical: true
```

---

## Step: immich-01-stack-request

```yaml
id: immich-01-stack-request
title: Author stack-request.yaml for immich-stack
model_hint: frontier
depends_on: [immich-00-create-media-seg-zone]

change: >
  Create terraform/lxc/stacks/immich-stack/stack-request.yaml (copy
  terraform/lxc/stacks/stack-request.example.yaml as the starting shape).
  Fill stack_yaml with: hostname immich-stack, ip_address
  "192.168.80.10/24" (candidate in the new media_seg zone -- confirm free
  via pct list/ping before applying), gateway "192.168.80.1", dns_server
  "192.168.80.1", vmid 80010 (candidate, following this repo's
  zone-prefixed VMID convention e.g. ai_seg's 50011/50012/50013), cores 4,
  memory 4096 (machine-learning inference needs headroom beyond
  Minecraft's 2048), docker_storage_size "20G" (base OS + images +
  Postgres/model-cache only -- the photo library itself is NFS, not local
  storage), deployment_tier apps, ansible_playbook deploy-immich-stack,
  portainer_agent false (deferred, matching minecraft-stack's first-pass
  choice), provides: [{service: immich, port: 2283, protocol: tcp}].
  Fill compose_requirements with the literal four-service compose content
  below, adapted: container_name prefixed immich-stack-<service>, restart
  unless-stopped to match this repo's convention rather than upstream's
  bare `always`, model-cache as a named Docker volume (matches upstream),
  but UPLOAD_LOCATION bind-mounted from an NFS-backed host path (e.g.
  /nas-media/immich-photos) rather than a Docker volume, matching
  media-stack's existing /nas-media/ Jellyfin pattern -- NOT a size
  chosen on the LXC's own docker_storage_size.
  Fill compose_forbidden with: a custom top-level networks: block,
  exposing the database or redis ports externally, using a plain
  postgres/pgvector image instead of the pinned
  ghcr.io/immich-app/postgres:14-vectorchord0.4.3-pgvectors0.2.0 image
  (Immich's vector search requires that specific fork), storing
  UPLOAD_LOCATION as a Docker named volume instead of the NFS bind mount.
  Fill contract_facts following STACK_CONTRACT.template.md's sections,
  noting: zone is media_seg (VLAN 80), nothing depends on this stack,
  prerequisite that /nas-media/immich-photos (or chosen path) is already
  NFS-mounted on the LXC before first compose up (not IaC-managed --
  manual, same as media-stack's own NAS mount), Implementation files
  section listing the five new paths under
  terraform/lxc/stacks/immich-stack/ and
  terraform/lxc/ansible/playbooks/deploy-immich-stack.yml as not existing
  yet.

scope:
  allowed_paths:
    - terraform/lxc/stacks/immich-stack/stack-request.yaml
  forbidden_actions:
    - "Running scaffold-stack.sh -- that's step immich-02"
    - "Any terragrunt or provision.sh command"
    - "Mounting or modifying the NFS export itself"

gates:
  - id: stack-request-exists
    cmd: "test -f terraform/lxc/stacks/immich-stack/stack-request.yaml"
    expect: "exit 0"
    critical: true
  - id: stack-request-parses
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/stacks/immich-stack/stack-request.yaml'))\""
    expect: "exit 0"
    critical: true
  - id: no-docker-storage-inflation
    cmd: "grep -q 'docker_storage_size: \"20G\"' terraform/lxc/stacks/immich-stack/stack-request.yaml"
    expect: "exit 0"
    critical: false
```

## Step: immich-02-scaffold

```yaml
id: immich-02-scaffold
title: Run the stack scaffolder against stack-request.yaml
model_hint: local
depends_on: [immich-01-stack-request]

change: >
  Run terraform/lxc/scaffold-stack.sh immich-stack. Do not author
  stack.yaml, docker-compose.yml, STACK_CONTRACT.md, terragrunt.hcl, or
  the playbook by hand -- the scaffolder's own five narrow sub-agents do
  that, gated by its own validators between each. Your job is only to run
  it and report the outcome.

scope:
  allowed_paths:
    - terraform/lxc/stacks/immich-stack/
  forbidden_actions:
    - "Hand-editing any of the five generated files if the scaffolder fails partway -- report which validator failed instead"
    - "Any terragrunt or provision.sh command"

gates:
  - id: scaffold-exits-clean
    cmd: "terraform/lxc/scaffold-stack.sh immich-stack"
    expect: "exit 0"
    critical: true
```

---

## Not covered by this plan (deliberately, matching the minecraft-stack precedent)

- Confirming the candidate IP/VMID are actually free (read-only check, do
  before `terragrunt apply`) -- media_seg is brand new so VMID collision
  is unlikely, but the check is still owed.
- Confirming `/nas-media/immich-photos` (or whatever path is chosen) is
  actually exported from the NAS and mounted on the target LXC before
  first `docker compose up` -- manual, not IaC-managed, same gap as
  media-stack's own Jellyfin mount.
- `terragrunt plan`/`apply` for both the new zone (immich-00) and the
  stack itself, `provision.sh --stack immich-stack`, and health-check
  validation -- real infrastructure steps, stay manual/operator-run, same
  as every prior exemplar in this repo.
- Traefik/Authentik SSO exposure -- not decided yet; Immich has its own
  user accounts, so whether it sits behind Authentik at all is an open
  question, not assumed.
- Backup strategy for the photo library and Postgres data -- a real gap
  for anything holding irreplaceable personal data, not addressed here.

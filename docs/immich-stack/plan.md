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

## Open decisions -- step 1 is not ready to run until these are answered

These are genuine judgment calls, not something to default silently (that
is exactly the failure mode `stage-10-minecraft-exemplar.md` flags: don't
let a model invent an SDN zone or a size on its own):

1. **Zone**: plain LAN bridge (`vmbr0`), matching every existing app-tier
   stack including the minecraft-stack precedent, or a new dedicated
   zone (e.g. `media_seg`) given Immich holds real personal photo data,
   unlike a Minecraft world? Plain LAN is the consistent, lower-scope
   default; a dedicated zone is more defensible for something holding
   real personal data but is new scope this plan doesn't build.
2. **Photo library size**: `docker_storage_size` / the `UPLOAD_LOCATION`
   volume needs a real number from the operator (how many GB of photos,
   plus headroom) -- there is no safe default to invent here.

Until both are answered, step `immich-01` below is a template with those
two fields marked `<<NEEDS OPERATOR INPUT>>`, not literal ready-to-run
content.

---

## Step: immich-01-stack-request

```yaml
id: immich-01-stack-request
title: Author stack-request.yaml for immich-stack
model_hint: frontier
depends_on: []

change: >
  Create terraform/lxc/stacks/immich-stack/stack-request.yaml (copy
  terraform/lxc/stacks/stack-request.example.yaml as the starting shape).
  Fill stack_yaml with: hostname immich-stack, ip_address
  "192.168.1.61/24" (candidate -- not yet confirmed free; check via
  `pct list` / ping before applying, same as minecraft-stack's own
  candidate-IP caveat), gateway "192.168.1.1", dns_server "192.168.1.1",
  vmid 171 (candidate, same caveat), cores 4, memory 4096 (machine-learning
  inference needs headroom beyond Minecraft's 2048), docker_storage_size
  "<<NEEDS OPERATOR INPUT: photo library size + headroom>>",
  deployment_tier apps, ansible_playbook deploy-immich-stack,
  portainer_agent false (deferred, matching minecraft-stack's first-pass
  choice), provides: [{service: immich, port: 2283, protocol: tcp}].
  Fill compose_requirements with the literal four-service compose content
  below (adapted: container_name prefixed immich-stack-<service>, restart
  unless-stopped to match this repo's convention rather than upstream's
  bare `always`, volumes as named Docker volumes declared in a top-level
  volumes: block rather than bind mounts, per this repo's established
  pattern -- not a relative bind mount).
  Fill compose_forbidden with: a custom top-level networks: block,
  exposing the database or redis ports externally, using a plain
  postgres/pgvector image instead of the pinned
  ghcr.io/immich-app/postgres:14-vectorchord0.4.3-pgvectors0.2.0 image
  (Immich's vector search requires that specific fork).
  Fill contract_facts following STACK_CONTRACT.template.md's sections,
  explicitly noting: zone decision still open (see plan's "Open
  decisions"), nothing depends on this stack, Implementation files section
  listing the five new paths under terraform/lxc/stacks/immich-stack/ and
  terraform/lxc/ansible/playbooks/deploy-immich-stack.yml as not existing
  yet.

scope:
  allowed_paths:
    - terraform/lxc/stacks/immich-stack/stack-request.yaml
  forbidden_actions:
    - "Running scaffold-stack.sh -- that's step immich-02"
    - "Any terragrunt or provision.sh command"

gates:
  - id: stack-request-exists
    cmd: "test -f terraform/lxc/stacks/immich-stack/stack-request.yaml"
    expect: "exit 0"
    critical: true
  - id: stack-request-parses
    cmd: "python3 -c \"import yaml; yaml.safe_load(open('terraform/lxc/stacks/immich-stack/stack-request.yaml'))\""
    expect: "exit 0"
    critical: true
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
  before `terragrunt apply`).
- `terragrunt plan`/`apply`, `provision.sh --stack immich-stack`, and
  health-check validation -- real infrastructure steps, stay manual/
  operator-run, same as every prior exemplar in this repo.
- Traefik/Authentik SSO exposure -- not decided yet; Immich has its own
  user accounts, so whether it sits behind Authentik at all is an open
  question, not assumed.
- A dedicated `media_seg` SDN zone -- deferred pending the zone decision
  above; cheap to add later under CLAUDE.md's additive-SDN tier if chosen.
- Backup strategy for the photo library and Postgres data -- a real gap
  for anything holding irreplaceable personal data, not addressed here.

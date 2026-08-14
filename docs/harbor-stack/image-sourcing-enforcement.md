# Harbor Image Sourcing — Findings & Enforcement Plan

## Purpose

This document is a separate track from `docs/harbor-stack/README.md` (which
covers Harbor scan convergence, monitoring, and dashboards — already largely
complete). This track covers a different question:

> Does every container image actually get pulled through Harbor, and can
> that be *enforced* rather than left to convention?

Triggered by an operator observation: `harbor.lab` (the live `pve`
production Harbor) shows only 12 artifacts, far fewer than expected if every
deployed stack were routing its pulls through Harbor's proxy-cache projects.

Transient investigation notes, if any accumulate while this plan is worked,
belong under `docs/harbor-stack/artifacts/` (git-ignored) per
`docs/workflow/documentation-workspaces.md`. This file holds only durable
conclusions and the plan itself.

## Status (2026-08-14)

**Stage A and Stage B are complete and merged into this branch** (11
commits on `task/harbor-image-sourcing-enforcement`). All ten stacks with
real violations are fixed and, where they can be deployed on pve-test-vm,
live-validated there. See Findings 5–8 below for what implementation
turned up beyond the original four findings, and the Decisions Log for
what got fixed vs. deliberately deferred. Stage C and Stage D are not yet
started.

## Verified Findings (2026-08-14)

### Finding 1 — Several stacks/roles hardcode direct upstream pulls

Confirmed by grepping every `image:` reference under `terraform/lxc/ansible/`
(playbooks and roles) — not just `terraform/lxc/stacks/`, see Finding 2 for
why that distinction matters.

| Stack / role | Image(s) | Reference | Status |
|---|---|---|---|
| `portainer-stack` | `portainer/portainer-ce`, `gcr.io/cadvisor/cadvisor` | `deploy-portainer-stack.yml:99,111` | ✅ fixed, live-validated |
| `proxy-stack` (Traefik) | `traefik:{{version}}`, `gcr.io/cadvisor/cadvisor` | `deploy-proxy-stack.yml:57,231` | ✅ fixed, live-validated |
| `monitoring-stack` | `gcr.io/cadvisor/cadvisor` + an unguarded task actively stripping the other 3 (see Finding 7) | `deploy-monitoring-stack.yml:80,557` | ✅ fixed, live-validated |
| `technitium-stack` | `technitium/dns-server` | `deploy-technitium-stack.yml:118` | ✅ fixed, live-validated |
| `minecraft-wildworks` (`gaming-stack-lab`, **`pve`-production only**) | `itzg/minecraft-server`, `itzg/mc-monitor`, `ghcr.io/google/cadvisor` | `deploy-minecraft-wildworks.yml:15-17` | ✅ code fixed, offline-validated only — **live deployment on hold indefinitely, operator directive: do not touch the live Minecraft server** |
| `docker_socket_proxy` role — shared sidecar, **6 consumers** (authentik, harbor, monitoring, netbox, portainer, proxy) | `tecnativa/docker-socket-proxy:latest` | `roles/docker_socket_proxy/defaults/main.yml:4` | ✅ fixed, live-validated on all 4 currently-enabled consumers deployed on pve-test-vm |
| `harbor-stack` itself (cadvisor sidecar) | `gcr.io/cadvisor/cadvisor` | `deploy-harbor-stack.yml:230` | ✅ fixed, live-validated — turned out *not* to be a real bootstrap exception, see Finding 5's note below |
| `authentik-stack` (found via Finding 6, not this table originally) | `postgres:16-alpine`, `redis:alpine`, `gcr.io/cadvisor/cadvisor` | `stacks/authentik-stack/docker-compose.yml:8,20,96` | ✅ fixed, live-validated; also fixed `authentik_registry_host`'s IP-on-non-pve special case |
| `netbox-stack` (found via Finding 6) | `gcr.io/cadvisor/cadvisor` | `stacks/netbox-stack/docker-compose.yml:151` | ✅ fixed, live-validated |
| `test-docker` (found via Finding 6) | `traefik/whoami`, `nginx:alpine` | `stacks/test-docker/docker-compose.yml:3,10` | ✅ fixed, not live-validated (not currently deployed) |
| `docker-socket-proxy-test` (found via Finding 6) | `nginx:stable-alpine`, `traefik/whoami`, `redis:alpine` | `stacks/docker-socket-proxy-test/docker-compose.yml:5,10,15` | ✅ fixed, not live-validated (not currently deployed) |
| `harness-target` (found via Finding 6) | hardcodes `harbor.lab.gibbsgreatly.xyz` literally, not `${REGISTRY_HOST}` | `stacks/harness-target/docker-compose.yml:5,12` | ✅ confirmed intentional, no fix — see Finding 8 |

Stacks confirmed correctly routed through `{{ *_registry_host }}` → Harbor
from the start: `ai-services-stack`, `graylog-stack`, `greenbone-stack`,
`pentagi-stack`.

`app_stack` role / `deploy-stack.yml` was in an earlier pass of this table
(hardcoded `nginx:alpine` placeholder) — **dropped after confirming it has
zero live consumers.** Audited every `stack.yaml`'s `ansible_playbook` field
in the repo; none point at `deploy-stack`. It's scaffolding intended for a
future `torrent-stack`/`media-stack` legacy migration
(`docs/application-migration/`) that hasn't started. No fix needed until
that migration is actually picked up.

**Environment-scoping note on `gaming-stack-lab`:** its `stack.yaml`
requests `memory: 24576` (24 GB). pve-test-vm is a 16 GB laptop, total —
this stack cannot fit there, full stop, not a policy choice. It is
deliberately `pve`-production-only and does not and should not exist on
pve-test-vm, even temporarily. This changes how it gets validated in
Stage B — see the Test & Verification Plan.

### Finding 2 — The CI gate meant to catch this only checks the wrong directory

`.github/workflows/validate.yml:50-67` (`harbor-image-policy` job) greps for
direct upstream registry references, but only under `terraform/lxc/stacks/`.
Every violation in Finding 1 lives under `terraform/lxc/ansible/playbooks/`
or `terraform/lxc/ansible/roles/`, which the grep never touches. This scope
was written into the job's originating task packet
(`docs/plan/tasks/05-supply-chain-05-harbor-image-policy.md`, "Out of
Scope: Scanning `ansible/` ... files") — a deliberate scope choice at the
time that has since become a blind spot, since it's `ansible/` where every
real `image:` line actually lives. **The job has been reporting clean the
entire time regardless of the violations in Finding 1.**

### Finding 3 — No forced re-pull path, so even correctly-routed stacks go stale in Harbor

`docs/harbor-stack/README.md:171-172` already documents that "after a fresh
Harbor rebuild, proxy-cache artifacts do not exist until something pulls
them through Harbor." Checked every stack's Compose pull behavior:

- `greenbone-stack` sets `pull: always` (`deploy-greenbone-stack.yml:510`)
- `graylog-stack` runs an explicit `docker compose pull` before `up`
  (`deploy-graylog-stack.yml:328-345`)
- **Every other stack** (monitoring, netbox, portainer, authentik
  conditionally, ai-services, pentagi's post-build step, etc.) relies on
  Compose's default pull policy, which only pulls an image if it is not
  already present locally on that container's Docker daemon.

So a stack that is correctly Harbor-routed in its compose file still will
not refresh (or re-register) its image in Harbor on a normal
`provision.sh`/redeploy pass, once the image is already cached on that LXC —
the container keeps running fine, but Harbor stops seeing it. Two memory
records (Harbor `admin` password recovered via direct DB write on
2026-07-31; CI robot credential found stale against live Harbor on
2026-07-26) are consistent with Harbor's own backing store having been reset
more recently than several long-running stacks were last recreated — which
would explain a sparse artifact count independent of Finding 1.

### Finding 4 — Docker is not configured to route or enforce Harbor at all; it works by convention only

Grepped every `daemon.json` template and every `registry-mirrors` /
`insecure-registries` reference in the repo:

- `docker_base` role (`terraform/lxc/ansible/roles/docker_base/templates/daemon.json.j2`)
  has a `registry-mirrors` block wired to a `docker_registry_mirror`
  variable, gated by `enable_registry_mirror` (defaults to `false`).
  **`enable_registry_mirror` is never set to `true` anywhere in the repo**,
  and `docker_registry_mirror` is never defined anywhere outside that one
  role file. This is dead/unfinished scaffolding — not active on any host.
- Every other `daemon.json` write across the repo (netbox, ci-runner,
  pentagi, portainer, monitoring, technitium, graylog, authentik,
  greenbone, ...) only sets `insecure-registries` pointing at Harbor's own
  hostname — that just tells Docker "it's OK to talk to Harbor over plain
  HTTP." It does not redirect or intercept pulls aimed anywhere else.

**Confirms the operator's suspicion directly: nothing forces a pull through
Harbor today.** Every image that does go through Harbor does so purely
because the compose file's `image:` string is spelled out as
`{{ registry_host }}/project/name:tag` by convention. Any compose file
(including all seven in Finding 1), any manually-run `docker pull`, or any
future stack author who forgets the prefix bypasses Harbor with zero
friction and zero detection (per Finding 2).

There is also a real technical ceiling on how far the *existing dormant*
`registry-mirrors` mechanism could go even if turned on: Docker Engine's
`registry-mirrors` daemon setting only ever applies to Docker Hub pulls, and
it requires the mirror to serve images unprefixed at its API root
(`GET /v2/<repo>/manifests/<tag>` on the mirror host directly). Harbor's
proxy-cache is project-scoped (`/v2/dockerhub/<repo>/...`), so **Harbor
cannot be plugged in directly as a `registry-mirrors` target** — that config
shape only works against a plain `registry:2` mirror pointed at Docker Hub,
which is a different piece of software than what's deployed. This matters
for the plan below.

### Finding 5 — The real reason most pulls through Harbor were failing: FQDN vs. raw IP

Discovered while live-validating the very first Stage B fix
(`portainer-stack`) on pve-test-vm: a pull against Harbor's raw container IP
(`LAB_IP_HARBOR`) fails outright, every time, regardless of
`insecure-registries`. Root cause, confirmed via nginx access logs and
direct curl:

- Harbor's `external_url` (`terraform/lxc/ansible/roles/harbor_installer/templates/harbor.yml.j2`)
  is deliberately HTTPS, terminated by Traefik — Harbor's own nginx only
  ever serves plain HTTP internally (`http.port`, no `https:` block; the
  template's own comment says so explicitly).
- Harbor's registry always answers a pull's initial `401` with
  `WWW-Authenticate: Bearer realm="<external_url scheme+host>/service/token"`
  — regardless of which host/port the client actually connected to.
- A client pulling against the raw IP (`192.168.40.110`, plain HTTP, works
  fine for the initial request) gets handed back an **HTTPS** token realm,
  which Harbor doesn't serve on that IP at all (TLS lives at Traefik, not
  Harbor) — the token fetch fails with `connection refused` on port 443,
  and the whole pull fails.
- Pulling against Harbor's **FQDN** (`LAB_FQDN_HARBOR`, routed through
  Traefik, real TLS) works end-to-end: the realm URL matches the host the
  client already successfully connected to.

This is why some Finding 1 fixes needed a second pass: several playbooks
had a `docker_registry_host`/`*_registry_host` var that resolved to
`LAB_IP_HARBOR` rather than `LAB_FQDN_HARBOR` (`portainer-stack`,
`proxy-stack`, `harbor-stack`'s own cadvisor sidecar, and
`authentik-stack`'s `authentik_registry_host`, which explicitly used the IP
on every environment except `pve`). All four now prefer
`LAB_FQDN_HARBOR`, matching the convention already used correctly by
`ai-services-stack`/`graylog-stack`/`pentagi-stack`/`monitoring-stack`/
`netbox-stack`. **Every stack fixed in this pass now confirmed pulling
successfully through Harbor's FQDN, live, on pve-test-vm** — this is
strong direct evidence for what was actually suppressing Harbor's artifact
count, on top of Findings 1–4.

### Finding 6 — The corrected CI check surfaced real violations Finding 1 missed

Testing Stage A's widened check against the live repo (before fixing
anything) surfaced more than Finding 1's original table:

- **`authentik-stack`'s `docker-compose.yml`**: its own header comment
  claimed "All images are routed through Harbor proxy cache" — but
  `postgresql` (`postgres:16-alpine`) and `redis` (`redis:alpine`) were
  hardcoded directly the whole time, alongside the same `gcr.io/cadvisor`
  bypass every other stack had. Missed by the original Finding 1 pass
  because that grep was scoped to `terraform/lxc/ansible/`, not
  `terraform/lxc/stacks/*/docker-compose.yml` — the same class of
  directory-scope blind spot as Finding 2 itself.
- **`netbox-stack`'s `docker-compose.yml`**: same `gcr.io/cadvisor` bypass,
  same reason it was missed.
- **`test-docker` and `docker-socket-proxy-test`**: both disposable/test-tier
  stacks had every image hardcoded, with no `REGISTRY_HOST` substitution
  wired in at all (not even the plumbing existed).
- **`docker_socket_proxy`'s own template** (`roles/docker_socket_proxy/templates/docker-compose.yml.j2`)
  wasn't scanned at all — the check's `--include` list only covered
  `*.yml`/`*.yaml`, not `*.j2`.
- A pure line-level check also cannot distinguish a good indirected
  `*_image:` var (`{{ vm_image }}`, correctly Harbor-routed) from a bad one
  (`{{ minecraft_server_image }}`, hardcoded upstream) without resolving
  the var's own definition — the widened check now does this (one hop,
  same file or that role's `defaults/main.yml`), which is what actually
  caught `minecraft-wildworks`'s three images despite their `image:` lines
  looking like normal Jinja references.

All of the above are now fixed (see Decisions Log) except `test-docker`/
`docker-socket-proxy-test`, which got the code fix but not live validation
(neither is currently deployed on pve-test-vm).

### Finding 7 — `monitoring-stack` was *actively* stripping its own correct Harbor routing, every run

Discovered live: after fixing `monitoring-stack`'s cadvisor line, its other
three images (`vm_image`, `grafana_image`, `harbor_findings_exporter_image`
— already correctly Harbor-routed in code) were still running old, plain
upstream images on pve-test-vm. Root cause was not Finding 3's staleness —
it was active, ongoing sabotage:
`terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml`'s "Rewrite
compose images to use upstream Docker Hub (dependency-tolerant mode)" task
had **no `when:` clause**, unlike every sibling task in the same
DNS-fallback block (`resolv.conf` backup, `/etc/hosts` entry, temporary
public DNS), which all correctly gate on `monitoring_dns_fallback_needed`.
This one — the consequential one — ran unconditionally on *every single
deploy*, regex-stripping the Harbor prefix from every `/dockerhub/` image
in the rendered compose file regardless of whether Harbor was actually
reachable. Fixed by adding the missing `when:` guard; grepped the rest of
the repo for the same `dependency-tolerant`/`Rewrite compose images`
pattern — it's isolated to this one file, not copy-pasted elsewhere.

### Finding 8 — `harness-target` hardcodes production's Harbor FQDN literally (confirmed intentional)

`terraform/lxc/stacks/harness-target/docker-compose.yml` routes its two
images through `harbor.lab.gibbsgreatly.xyz` — a literal, hardcoded
hostname, not `${REGISTRY_HOST}`. That's `pve` production's Harbor FQDN;
on pve-test-vm (where `harness-target` is actually deployed, per live
inventory) this doesn't route through the local Harbor at all. **Confirmed
intentional by the operator (2026-08-15):** it only ever *pulls* (read-only)
through prod Harbor's proxy cache — never mutates it — which is an
accepted design choice, not a bug. Excluded from the CI check's enforcement
scope permanently, not pending further input.

### Finding 9 — `TF_WORKSPACE` gap for pve-test-vm (fixed, cross-referenced)

Found and fixed during the pre-implementation methodology smoke test, not
this plan's own investigation, but directly relevant to it: `.env.pve-test-vm`
never set `TF_WORKSPACE`, so any ad hoc `terragrunt plan`/`apply` against
pve-test-vm silently operated against the wrong, empty Terraform workspace.
Fixed (`export TF_WORKSPACE='pve-test-vm'`, matching `.env.pve`/
`.env.pve-framework`'s existing pattern) and verified: `apt-cacher-stack`'s
container resource now shows zero diff instead of a phantom full recreate.

## Assessment of the Operator's Target State

Restating the position to respond to it point by point:

1. The structural bypass was intended to be temporary.
2. End state: literally every container image should go through Harbor.
3. Harbor itself should re-pull images through itself where possible.
4. There should be a non-destructive process to re-pull images through
   Harbor.
5. Docker should be forced, where possible, to go through Harbor.
6. End state: Harbor becomes a container image firewall — direct pulls
   blocked.

| # | Realistic as stated? | Assessment |
|---|---|---|
| 1 | Yes | Confirmed — `STACK_CONTRACT.md` already states this as current design intent, not aspirational. The 7 violations in Finding 1 are drift, not by-design exceptions (except the harbor-stack bootstrap sidecar). |
| 2 | Yes, with one narrow exception | Achievable to a very high percentage. The one genuine exception: Harbor's own bootstrap sidecar image, which by definition cannot be pulled through a Harbor that doesn't exist yet on a fresh rebuild. This should be documented as a permanent, tiny, accepted exception rather than something to eliminate — see Stage B. Locally-built images (e.g. `mcp-utility-stack`'s `cve-mcp-server`, built not pulled) need a different mechanism — push the built image *into* Harbor after building, not "pull through" it — same end result (scannable in Harbor), different plumbing. |
| 3 | Not literally, but achievable in spirit | Harbor's proxy-cache is passive: it only refreshes an artifact when a client (Docker/skopeo) makes a request through it. Harbor does not have a built-in "go re-fetch my own cached images" scheduler. What's achievable — and what actually delivers the outcome wanted — is an external, scheduled job that walks the known image list and re-requests each one through Harbor. Framed correctly this *is* "Harbor re-pulling itself" from an operator's point of view, even though the trigger lives outside Harbor. |
| 4 | Yes, this is the right ask | Fully non-destructive: `docker pull`/`docker compose pull`/`skopeo copy` never touch a running container unless followed by a recreate. A scheduled refresh job is safe by construction. |
| 5 | Partially — real ceiling exists | Docker's only native "force via daemon config" mechanism (`registry-mirrors`) exists in this repo already, is dormant, and **only covers Docker Hub, with silent fallback to the origin if the mirror is unreachable or missing the image** — it is not a hard block, and it cannot be pointed at Harbor as deployed (see Finding 4's last paragraph) without adding a second, small mirror component in front of Harbor's `dockerhub` project. It also does nothing for `ghcr.io`, `quay.io`, `gcr.io` — those have no Docker-Engine-native mirror concept at all. So "force Docker" as a *daemon-config* mechanism tops out well short of "every registry, no fallback." |
| 6 | Not via Docker config; yes via network egress | A true firewall — direct pulls fail rather than silently succeeding — is a network-layer control, not a Docker-daemon setting: block outbound to `docker.io`/`ghcr.io`/`quay.io`/`registry.k8s.io`/`gcr.io` at the SDN/firewall boundary for the zones that run these stacks, with a narrow allow-rule for Harbor's own host (which still needs real upstream egress to do the proxy-cache fill on a cache miss). This repo already has the right primitive for this (VLAN zones, MikroTik as L3 gateway — see `[[project_sdn_vlan_design]]`), so it's feasible, but it is a genuinely higher-risk, higher-blast-radius change than anything else in this plan: per this repo's own Validation Tiers, modifying an existing zone/cross-zone rule requires a full teardown cycle before promotion, and a firewall misconfiguration here breaks *all* image pulls platform-wide, including Harbor's own cache-fill path if the allow-rule is wrong. This should be a later, separate, carefully-staged piece of work — not bundled with the cheaper routing/CI fixes below — and should launch in **log/monitor mode before hard-deny**, so any remaining bypass gets caught by evidence instead of an outage. |

**Net critique:** the direction is sound and mostly achievable with the tools already in this repo. The one place to recalibrate is item 5/6 — "force Docker" via daemon config is a dead end past Docker Hub; the actual enforcement point for a real "image firewall" is the network boundary, which is a bigger and separately-gated change. Treat routing/CI/re-pull fixes (cheap, safe, fast) and network enforcement (expensive, risky, slow) as two different phases, not one.

## Design Principles

- Every stack-owned compose file spells out `{{ *_registry_host }}/project/...`
  for every image it pulls from an upstream registry — no exceptions once
  Harbor exists and is reachable.
- The one accepted, permanent exception is Harbor's own bootstrap
  dependency on its first-ever cold start (chicken-and-egg); it must
  self-heal to Harbor-routed on the very next reconciliation pass once
  Harbor is up (see Stage B).
- Locally-built images (no upstream pull) get pushed into a Harbor project
  post-build, not left unscanned.
- The CI gate must scan every location an `image:` line can actually live —
  no directory-scoped blind spots.
- Cache refresh must be non-destructive: refreshing Harbor's copy of an
  image must never restart or recreate a running container as a side
  effect.
- Enforcement is layered and staged: fix what's cheap and safe first
  (routing + CI + re-pull), treat network-level blocking as a distinct,
  higher-validation-tier phase attempted only after the cheap layer is
  clean and has run log-only for a observation period.

## Target State

- `terraform/lxc/ansible/` contains zero `image:` lines that reference an
  upstream registry directly, except the one documented harbor-stack
  bootstrap exception.
- `harbor-image-policy` in CI scans `terraform/lxc/ansible/` (playbooks and
  roles) in addition to `terraform/lxc/stacks/`, and fails loudly with
  file:line output on any violation.
- A scheduled, non-destructive job re-pulls every known in-use image through
  Harbor on a regular cadence, independent of whether any stack has been
  redeployed recently, so Harbor's scan data reflects what's actually
  running.
- Docker Hub pulls specifically use the existing (currently dormant)
  registry-mirror scaffolding as defense-in-depth, understood explicitly as
  "faster / cached," not as the enforcement mechanism.
- A follow-on, separately-validated phase adds network-layer egress
  restriction so direct pulls to known upstream registries fail outright
  from every zone except Harbor's own — launched in log-only mode first.

## Staged Remediation Plan

### Stage A — Close the CI blind spot

Goal: make the existing policy check actually see the real violations.

Work:
- Extend `harbor-image-policy` in `.github/workflows/validate.yml` to also
  grep `terraform/lxc/ansible/playbooks/` and `terraform/lxc/ansible/roles/`
  (in addition to the current `terraform/lxc/stacks/` scope).
- Keep the existing exclusion for `.terragrunt-cache/` and comment lines.
- Add a narrowly-scoped, explicit allowlist exception for the one
  documented harbor-stack bootstrap line, so the job can go strict
  everywhere else without a permanent false failure.

Verification:
- Run the extended grep locally against current `main` — it should surface
  every row in Finding 1's table (except the allowlisted bootstrap line).
- CI job fails on a deliberately reintroduced test violation, passes once
  reverted.

Exit criteria: CI would have caught every violation in Finding 1 had this
scope existed at the time.

### Stage B — Eliminate the structural bypasses

Goal: every stack in Finding 1's table routes through Harbor.

Work, per stack:
- `portainer-stack`, `proxy-stack`, `monitoring-stack`: rewrite direct
  `gcr.io/cadvisor/cadvisor` (and `traefik`, `portainer/portainer-ce`)
  references to `{{ *_registry_host }}/gcr/cadvisor/cadvisor` /
  `.../dockerhub/library/traefik` / `.../dockerhub/portainer/portainer-ce`,
  matching the pattern already used correctly by `pentagi-stack` and
  `graylog-stack` for the same cadvisor image.
- `technitium-stack`: route `technitium/dns-server` through
  `{{ *_registry_host }}/dockerhub/technitium/dns-server`.
- `minecraft-wildworks` (`pve`-only, see environment-scoping note above):
  route all three images (`itzg/minecraft-server`, `itzg/mc-monitor`,
  `ghcr.io/google/cadvisor`) through their respective `dockerhub`/`ghcr`
  Harbor projects. Code change and validation approach are otherwise
  identical to the other stacks in this list — only *where* it gets tested
  differs, since it cannot be deployed on pve-test-vm at all. See the Test
  & Verification Plan.
- `docker_socket_proxy` role: this is a single-file fix
  (`roles/docker_socket_proxy/defaults/main.yml`) that cascades correctly
  to all 6 stacks that consume the role, since they all pull the default
  from the role rather than overriding it locally — highest leverage, single
  fix.
- `harbor-stack` bootstrap sidecar: add a post-deploy reconciliation task
  to `deploy-harbor-stack.yml` — once Harbor's own health check passes,
  pull `{{ registry_host }}/gcr/cadvisor/cadvisor:vX` once (cache-filling
  it into Harbor), and change the running definition so **every subsequent
  provisioning pass** (including future rebuilds) uses the Harbor-routed
  reference. The very first cold-start of a from-scratch Harbor remains the
  one legitimate direct pull in the whole repo; everything after that,
  including this same image, converges to Harbor-routed.
- `mcp-utility-stack` (`cve-mcp-server`, locally built): add a post-build
  `docker push` step targeting a dedicated non-proxy Harbor project (its own
  code comment already anticipated this — "no other consumer yet, so a
  dedicated Harbor project/robot account isn't warranted" — revisit that
  call now that the goal is comprehensive coverage, not minimal footprint).

Verification: re-run Stage A's extended CI grep — zero unallowlisted
violations. Deploy each touched stack on pve-test-vm per this repo's normal
Ansible-role-change validation tier
(`scripts/provision.sh --stack <name>` on pve-test-vm) and confirm the
container starts using the Harbor-routed image.

Exit criteria: Finding 1's table is empty except the one documented
bootstrap exception.

### Stage C — Non-destructive scheduled re-pull / rescan job

Goal: Harbor's artifact/scan state reflects what's actually running, not
just what happened to be freshly deployed recently.

Work:
- Build a small, stateless job (natural extension of the cache-fill logic
  already proven in
  `terraform/lxc/ansible/roles/harbor_postconfigure/files/harbor_scan_smoke.py`)
  that:
  - reads a manifest of currently in-use `{{ registry_host }}/project/repo:tag`
    references (ideally generated from the same source Stage A's CI check
    scans, so the two never drift apart)
  - for each, runs a plain `docker pull` / `skopeo copy` through Harbor —
    never touches a running container, never recreates anything
  - relies on Harbor's existing `auto_scan` proxy-project metadata (already
    converged per `docs/harbor-stack/README.md` Stage 1) to trigger a fresh
    Trivy scan on the refreshed artifact
- Run it on a schedule (systemd timer) on **`ci-runner-01`** — decided.
  It already has a proven, live network/Docker-client path to Harbor
  (`depends_on: harbor-stack`, `registry_host` wired, Docker daemon already
  configured to reach Harbor), so the job runs as a normal outside client
  with no new firewall path needed. Harbor's own LXC was the alternative but
  is comparatively RAM-constrained (2 GB) and already runs Harbor's core,
  DB, jobservice, and Trivy — adding a repeating pull loop there would
  compete with the thing it's trying to refresh. `ci-runner-01` exists on
  both `pve` and pve-test-vm (`192.168.10.63` / `192.168.10.163`), so this
  is testable on pve-test-vm before touching production.
- Follow the same systemd-timer pattern already used in this repo by
  `terraform/lxc/ansible/roles/portainer_backup/tasks/main.yml` rather than
  inventing a new one.
- Cadence: start daily; revisit after observing real refresh volume and
  Trivy scan load.

Verification:
- Run manually once against pve-test-vm; confirm Harbor's `push_time`
  updates for a known artifact and no container restarts.
- Confirm the job tolerates an empty/cold Harbor (first run after a
  rebuild) without failing, consistent with the rebuild-safety rule already
  established for the Stage 2 smoke check in `docs/harbor-stack/README.md`.

Exit criteria: a stack that hasn't been redeployed in weeks still shows a
recent scan timestamp in Harbor.

### Stage D — Docker Hub registry-mirror as defense-in-depth (not enforcement)

Goal: use the existing dormant scaffolding for what it's actually good for.

Work:
- Either (a) finish wiring `docker_base`'s `registry-mirrors` config against
  a small dedicated `registry:2` pull-through-cache instance configured
  with Harbor's `dockerhub` project as its remote (the shape Docker's
  daemon-level mirror protocol actually expects), or (b) explicitly retire
  the dormant scaffolding if the value isn't judged worth a second moving
  part.
- Document clearly, wherever this lands, that this mechanism is a
  performance/redundancy nicety for Docker Hub pulls only, silently falls
  back to the origin on miss, and is not a substitute for Stage A/B's
  routing correctness or Stage E's enforcement.

Exit criteria: either the mirror is live and documented as opportunistic
caching only, or the dead code is removed with that decision recorded here.

### Stage E — Network-layer image firewall (separate, later, higher-risk phase)

Goal: direct pulls to known upstream registries actually fail from
everywhere except Harbor's own egress path — the literal "firewall"
outcome.

Work:
- Add an SDN/firewall rule blocking outbound to `docker.io`, `ghcr.io`,
  `quay.io`, `gcr.io`, `registry.k8s.io` from the zones that run Docker
  workloads, with a narrow allow carve-out for Harbor's own host (which
  needs real upstream egress for proxy-cache fills).
- **Launch in log-only/monitor mode first.** Let it run for an observation
  window and review logged attempts before switching to hard deny — this
  is the only way to catch a Stage B miss or a not-yet-known consumer
  without an outage.
- Only after a clean observation window, flip to hard deny.

Validation tier: this is a change to existing SDN/firewall rules per this
repo's own Validation Tiers table — **full teardown cycle on pve-test-vm
required before promotion past `stable`**, not the lighter-weight tier used
for Stages A–D. Do not bundle this stage's rollout with A–D's.

Exit criteria: a deliberate direct-pull test from a non-Harbor host inside
an affected zone fails; the same pull through Harbor succeeds; Harbor's own
cache-fill path is unaffected.

## Test & Verification Plan

This work is Ansible/CI/automation-shaped, not "additive Terraform" — so the
default rule applies throughout: **everything is implemented and validated
on pve-test-vm first.** Production `pve` is only touched after pve-test-vm
passes, and only under this repo's full Production Credential Controls
approval flow (preflight summary → operator says "Proceed" → `TASK_APPROVAL`
set → `./with-secrets-prod` → after-action summary) — no standing approval,
each stage's production rollout is its own ask.

**The one exception is `gaming-stack-lab`/`minecraft-wildworks`**, which
cannot be deployed on pve-test-vm at all (24 GB requested vs. 16 GB total
available) — its test path is split into an offline/dry-run half on
pve-test-vm-or-local plus a narrowly-scoped, approved production validation,
detailed under Stage B below. No other stack in this plan has this
restriction.

Suggested branch: cut a dedicated `task/harbor-image-sourcing-enforcement`
branch from current HEAD when implementation starts, separate from
`feat/gaming-stack-lab-foundation` — this is a distinct concern from the
gaming-stack lab work, even though one of its fixes (`minecraft-wildworks`'s
image lines) touches the same compose file.

### Stage A — CI grep scope

No live host touched; this only changes a GitHub Actions workflow file.

1. Run the widened grep locally against the current repo — confirm it
   lists every row in Finding 1's table.
2. Push the branch with the CI fix applied but *before* fixing the actual
   violations — confirm the job goes red in GitHub Actions listing the real
   files, not just locally. This proves the check would have caught them.
3. Apply Stage B's fixes, push again, confirm the job goes green.
4. Confirm the harbor-stack bootstrap allowlist line does not itself trip
   the check.

Pass condition: job is red before Stage B, green after, and never flags the
one documented bootstrap exception.

### Stage B — per-stack image routing fixes

**Standard stacks** (`portainer-stack`, `proxy-stack`, `monitoring-stack`,
`technitium-stack`, and the 6 `docker_socket_proxy` consumers):

1. `./with-secrets bash -c 'echo $TF_VAR_proxmox_node'` — confirm it prints
   `pve-test-vm` before touching anything (per CLAUDE.md's Execution
   Guardrails).
2. `./with-secrets scripts/provision.sh --stack <name> --check` (dry run).
3. `./with-secrets scripts/provision.sh --stack <name>` (live).
4. `docker inspect <container> --format '{{.Config.Image}}'` — confirm the
   running container's image string is the Harbor-prefixed one, not the old
   upstream reference.
5. Confirm the artifact actually landed in pve-test-vm's Harbor (its
   project/repository list shows the new image).
6. Run the stack's documented health check per CLAUDE.md's Stack Service
   Types table (HTTP health endpoint, systemd unit, or `dig` as
   appropriate).
7. Re-run `provision.sh` a second time — confirm it's a no-op (idempotency),
   not a repeated recreate.
8. For `docker_socket_proxy` specifically: since one role-default change
   cascades to 6 stacks, repeat steps 2–7 for **each of the 6** individually
   — a stack that locally overrides the role default would silently not
   pick up the fix, and that's exactly the kind of drift worth catching
   here rather than assuming the cascade is clean.

Rollback condition (any standard stack): if `provision.sh` fails, the
post-change health check fails, or Harbor doesn't show the new artifact —
revert the `image:` line, redeploy, confirm health restored, and stop; don't
proceed to the next stack until root-caused.

**`minecraft-wildworks` / `gaming-stack-lab`** (the pve-only exception):
**Step 1 is done. Steps 2–4 are on hold indefinitely — operator directive
(2026-08-15): do not touch the live Minecraft server.** Left documented
below for if/when that changes, not as a live plan.

1. Offline check first, no live host anywhere: `ansible-playbook
   deploy-minecraft-wildworks.yml --syntax-check`, plus a template-render
   check (e.g. `ansible -m debug` against the relevant vars, or a dry
   `--check` run if a suitable target exists) confirming the three `image:`
   Jinja expressions resolve to the correct Harbor-prefixed strings. No
   container of any kind gets created on pve-test-vm for this stack.
2. Live validation happens only on `pve`, scoped narrowly to this one
   change, under the full approval flow: preflight names the target
   (`pve`), states it's mutating, lists the exact objects (the 3 image
   references in `deploy-minecraft-wildworks.yml`), and states everything
   else as out of scope. Wait for "Proceed" before running anything.
3. Roll out during a low-traffic window — this is a live game server,
   players may be connected.
4. Same post-change checks as the standard stacks (image string, Harbor
   artifact, container health) but run against `pve` under
   `./with-secrets-prod`, not `./with-secrets`.

Explicitly not doing: standing up a temporary/disposable clone of
`gaming-stack-lab` on pve-test-vm to get a pre-prod live test. That would
recreate the exact "exists on pve-test-vm" state that's been ruled out, even
if torn down right after. Flagging this as a deliberate choice, not an
oversight — say the word if you'd actually prefer that tradeoff.

### Stage C — `ci-runner-01` re-pull job

1. Confirm pve-test-vm's `ci-runner-01` is up (`192.168.10.163`).
2. First run the job manually (not via timer) against pve-test-vm's Harbor
   with a small known image list.
3. **Core non-destructive check:** capture `docker inspect --format
   '{{.State.StartedAt}}'` for every target container immediately before
   and after the job runs — must be byte-identical. This is the concrete
   proof the refresh never touches a running container.
4. Confirm Harbor's `push_time`/scan timestamp for each pulled image
   updates.
5. Confirm it tolerates a cold/empty Harbor without erroring (convenient to
   test right after a pve-test-vm Harbor rebuild, if one happens to be
   scheduled anyway).
6. Only after manual runs are clean, enable the systemd timer, let one real
   scheduled firing happen unattended, repeat checks 3–5 against that run.
7. Promote to `pve`'s `ci-runner-01` only after the pve-test-vm timer has
   run cleanly, unattended, at least once.

### Stage D — registry-mirror decision

- If finishing the mirror: stand up the small `registry:2` companion on
  pve-test-vm, point `docker_base`'s mirror config at it, confirm a Docker
  Hub pull is cached/faster on repeat, and confirm it falls back cleanly to
  the origin when the mirror is deliberately stopped.
- If retiring: confirm removing the dead scaffolding doesn't change
  `docker_base` behavior anywhere (`docker_base_configure_mirror` was
  always `false` in practice) — a syntax-check is sufficient, no host
  validation needed.

### Stage E — network-layer image firewall

Reiterating from the assessment above: this is a change to an existing
SDN/firewall rule set, so it carries this repo's **full teardown cycle on
pve-test-vm** validation tier — not the lighter tier used for A–D, and not
bundled with A–D's rollout.

1. Deploy the block rule in **log-only/monitor mode** first.
2. Observe for an agreed window; review logged direct-pull attempts from
   every zone the rule covers.
3. Only after a clean window with no unexpected direct-pull traffic, flip
   to hard deny.
4. Explicit pass/fail test: from a host inside the blocked zone, a direct
   `docker pull ubuntu` fails; the same pull via
   `{{ registry_host }}/dockerhub/library/ubuntu` succeeds; Harbor's own
   outbound cache-fill pull (needed to serve that second pull) is
   unaffected.
5. Full teardown/rebuild cycle on pve-test-vm passes with the rule active
   before this is eligible for promotion past `stable`.

### Promotion path (all stages)

`task/harbor-image-sourcing-enforcement` → validate on pve-test-vm per the
checks above → merge to `stable` → incremental deploy + smoke test on `pve`
→ merge `stable` → `main`. Stages A–D are similar risk and can likely be
batched into one branch/PR. Stage E stays on its own branch and its own
promotion pass given the higher validation tier and blast radius.

## Verification Matrix

| Stage | Primary verification | Pass condition |
|---|---|---|
| A | extended CI grep run against current `main`/branch | surfaces every known Finding 1 violation; clean once Stage B lands |
| B (standard stacks) | `scripts/provision.sh --stack <name>` on pve-test-vm per touched stack | container starts using Harbor-routed image; Stage A grep clean |
| B (`minecraft-wildworks`) | offline syntax/template check only | image strings resolve correctly offline; **live rollout on hold indefinitely per operator directive, not attempted** |
| C | manual run + unattended scheduled run on pve-test-vm's `ci-runner-01` | Harbor artifact timestamp refreshes; container `StartedAt` unchanged; tolerates cold/empty Harbor |
| D | mirror reachability + fallback check, or removal commit | mirror documented as opportunistic-only, or scaffolding removed |
| E | direct-pull test from blocked zone vs. Harbor-routed pull, full teardown cycle | direct fails, Harbor-routed succeeds, Harbor cache-fill unaffected, teardown cycle passed |

## Out of Scope (this document)

- Harbor scan-policy convergence, dashboards, findings exporter — already
  covered by `docs/harbor-stack/README.md`.
- Kubernetes-style admission control (not applicable — this platform is
  Docker Compose on LXC, not Kubernetes).
- Content trust / image signing (Cosign) — a separate supply-chain control,
  not a sourcing-enforcement one.
- Rotating the Harbor CI robot credential mismatch tracked separately
  (`[[project_harbor_ci_robot_credential_mismatch]]`).

## Decisions Log

- `app_stack` role / `deploy-stack.yml`: confirmed zero live consumers,
  dropped from scope (2026-08-14).
- Stage C execution host: `ci-runner-01`, decided (2026-08-14).
- `*_registry_host` vars repo-wide: standardized on preferring
  `LAB_FQDN_HARBOR` over `registry_host`/`LAB_IP_HARBOR` in every stack
  touched this pass, per Finding 5 (2026-08-14).
- `harness-target`'s hardcoded-hostname bug (Finding 8): confirmed
  intentional by the operator — it only ever pulls (read-only) through
  prod Harbor's proxy cache, never mutates it. Permanently excluded from
  the CI check, no fix needed (2026-08-15).
- `minecraft-wildworks`'s production rollout: operator confirmed **do not
  touch the live Minecraft server** — `gaming-stack-lab` is intentionally
  `pve`-only due to pve-test-vm's RAM ceiling, and that's staying that way.
  The code fix (Stage B, already committed) stays as prepared-but-not-
  deployed; there is no live rollout planned or pending (2026-08-15).
- `harbor-stack`'s cadvisor sidecar: confirmed *not* a genuine bootstrap
  exception (Harbor is already up by the time that play runs) — fixed like
  every other stack, CI allowlist for it removed (2026-08-14).
- 11 commits landed on `task/harbor-image-sourcing-enforcement`: the
  TF_WORKSPACE fix, the Stage A CI rewrite, and one commit per stack fixed
  in Stage B. Not yet pushed to `origin` or merged to `stable`.

## Open Questions for Operator

- Stage E is intentionally scoped as a later, separate effort — confirm
  that's the right sequencing before any network/firewall work is
  scheduled, given its full-teardown-cycle validation cost.
- Ready to start Stage C (scheduled re-pull job) and/or Stage D
  (registry-mirror finish-or-retire decision) now, or hold here?

Resolved (2026-08-15): `harness-target`'s hardcoded hostname (confirmed
intentional, no fix) and `minecraft-wildworks`'s production rollout (not
happening — do not touch the live Minecraft server; the code fix stays
committed but undeployed indefinitely). See Decisions Log.

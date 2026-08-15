# Harbor Stack Plan

## Purpose

This document plans the Harbor scanning and monitoring work that is still missing
from the current implementation. The plan is intentionally aligned to:

- the Harbor deployment code that already exists in this repo
- the live Harbor state verified on `pve` on 2026-05-31
- the teardown/rebuild model used by this repo
- discrete stages that can be implemented, verified, and promoted independently

The immediate goals are:

1. ensure Harbor actually scans proxy-cached images after a fresh deploy
2. make that behavior verifiable after teardown/rebuild
3. expose that state in Grafana without relying on the Harbor UI

Working note:

- transient handoff, handback, evidence, and scratch material for this
  workstream belongs under `docs/harbor-stack/artifacts/`
- that directory is local-only and git-ignored

## Open Investigation — Proxy-Cache Artifact Registration Gap (2026-08-15)

Triggered by `image-sourcing-enforcement.md`'s rollout: after confirming every
in-use image actually routes through Harbor, checked whether Harbor was
actually scanning all of them. It isn't.

**Confirmed at the database level** (`SELECT repository_name, count(*) FROM
artifact GROUP BY repository_name` against `harbor-db`'s own Postgres): on
`pve`, only the `dockerhub` project (native `docker-hub` adapter type) and
`pentagi` (push-based, not proxy-cache at all) have any artifact rows.
`gcr`, `ghcr`, `quay`, `greenbone` — all using the generic `docker-registry`
adapter type — have **zero** artifact rows despite real, successful pulls
(`pull_count` climbing, and for `greenbone` specifically, 1.8GB of real blob
storage consumed). Trivy never scans what Harbor never registers as an
artifact.

Ruled out, with direct evidence for each:
- **Not a registry-adapter-type limitation** in the "some registries just
  don't work" sense — see the corrected root cause below.
- **Not a multi-arch/OCI-image-index issue** — `dockerhub/library/postgres`
  (which scans fine) is also an OCI image index, same media type as the
  broken `greenbone` repos.
- **Not Harbor version, component health, quota, or system-level config** —
  both instances run identical v2.14.3, `pve`'s `/api/v2.0/health` reports
  every component healthy, quotas are unlimited on both, and a full
  `/api/v2.0/configurations` diff between the two instances showed no
  functional difference.
- **Not stale runtime state** — restarted `harbor-core` on `pve` and forced
  a genuinely fresh (non-cached) pull afterward; still zero DB rows at that
  point.
- **Not an environment difference between `pve` and pve-test-vm at all** —
  see below. This was the working hypothesis for a while and was wrong;
  corrected the same day once tested directly.

**Root cause, confirmed (2026-08-15, final).** Debug logging on `pve`'s
`harbor-core` (temporarily enabled via the normal `harbor_installer` role
path, reverted after) showed a working `dockerhub` pull running through
`controller/proxy/local.go` (full artifact-registration flow: blob checks,
manifest `PUT`, `PUSH_ARTIFACT` event, Trivy trigger, `SCANNING_COMPLETED`)
versus a broken `gcr` pull running through a different path,
`controller/proxy/controller.go:216` ("manifest list cache"), which logged
almost nothing and triggered no scan — even though the `docker pull` itself
succeeded a second later. That narrowed *where* the gap was, but not why
pve-test-vm appeared unaffected for the same adapter type.

Testing that directly resolved it: **pulling a genuinely new tag that
neither Harbor instance had ever seen** (`gcr/cadvisor/cadvisor:v0.55.1`,
vs. the long-standing `v0.49.1` every stack actually uses) produced an
identical result on **both** `pve` and pve-test-vm — a real artifact gets
created, and Trivy scans it successfully (`scan_status: Success`, real
severity data) within seconds. **The artifact is just never tagged.**
Confirmed Harbor deliberately disallows fixing this by hand: `POST
.../artifacts/{digest}/tags` on a proxy-cache project returns `405
METHOD_NOT_ALLOWED`, `"the operation isn't supported for a proxy cache
project"` — tag creation for proxy-cache pulls is meant to happen
automatically as part of the pull-through flow, and for the generic
`docker-registry` adapter type, that automatic step doesn't fire.

So: **there is no environment difference.** `gcr/cadvisor/cadvisor:v0.49.1`
looking "fine" earlier was misleading — it was tagged once, long enough ago
to predate whatever changed, and every pull since (by any of the 6+ stacks
using it) has been silently creating fresh untagged, invisible-by-default
artifacts that genuinely were scanned, just impossible to find by tag.
`repo.artifact_count` does correctly count untagged artifacts (confirmed:
went from `0` to `1` after the `v0.55.1` test pull), so the original "zero
artifacts" finding for these projects, before any of today's test pulls,
was accurate — this isn't a case of the scans existing all along and just
being hidden from view.

One more wrinkle found the same way: every project has a **daily retention
schedule** (`0 0 0 * * *`, confirmed via `/api/v2.0/schedules`) — retention
policies commonly prune untagged artifacts, so even a scan that *does*
happen via a fresh pull may not survive past the next retention run, since
nothing (no tag) protects it from cleanup. Not confirmed to actually delete
these specific artifacts (would need to observe across a retention cycle),
but it's a second reason not to treat "it got scanned once" as durable
coverage.

**Upgrade to Harbor 2.15.2 tested directly on pve-test-vm (2026-08-15) —
does not fix it, and is a one-way door.** Online research surfaced a real,
matching upstream issue
([goharbor/harbor#17135](https://github.com/goharbor/harbor/issues/17135),
["Proxy cache isn't tagging images"](https://knowledge.broadcom.com/external/article/398201/proxy-cache-isnt-tagging-images.html))
and a stated fix landing in Harbor 2.15 (2.15.0 shipped its own unrelated
proxy-cache regression, fixed in
[2.15.1](https://github.com/goharbor/harbor/issues/23025); 2.15.2 is
current). Worth testing directly rather than trusting the changelog:

- Upgraded pve-test-vm's `harbor-stack` to v2.15.2 (the role's own
  idempotency check only looks at whether *any* installer is already
  extracted, not whether it's the *requested* version — had to remove
  `/opt/harbor/harbor` first, leaving `/var/lib/harbor`'s actual data
  volume untouched, to force a genuine re-download).
- All 8 components came up healthy; the Docker Hub/Cloudflare health-check
  issue that originally forced the 2.14.3 downgrade did **not** resurface
  (the `harbor_postconfigure` fix removing Docker Hub credentials from that
  check is apparently still sufficient).
- **The live bug is not fixed.** Pulled two more genuinely fresh tags
  (`v0.54.1`, `v0.52.1`) after the upgrade — both still registered
  **untagged**, identical to pre-upgrade behavior. What Harbor 2.15's
  migration actually does is a **one-time backfill of tags on artifacts
  that already existed at upgrade time** (confirmed: the earlier
  pre-upgrade `v0.55.1` untagged artifact acquired a tag, under a new
  digest, right after the upgrade) — it does not fix the live
  registration path for anything pulled afterward.
- **Attempting to revert to 2.14.3 broke Harbor outright.** `harbor-db`'s
  schema had moved forward, and — unexpectedly — Harbor 2.15.2 replaced
  Redis with Valkey as the cache backend; 2.14.3's older `redis-photon`
  image couldn't read the now-Valkey-formatted data. Both `redis` and
  `harbor-jobservice` crash-looped, `harbor-core` never went healthy
  (`502` for the full 300s retry window). Recovered by moving forward to
  2.15.2 again (not backward) — full health restored within a minute.
  **Conclusion: upgrading past 2.14.3 is a one-way door on this Harbor
  install** — don't attempt it against `pve` without accepting that a
  rollback isn't a safe option if something else goes wrong.
- **Net result:** pve-test-vm's `harbor-stack` is now genuinely running
  v2.15.2, diverged from the repo's committed `harbor_installer_version:
  "2.14.3"` default. Not yet reconciled either direction — an open decision
  (adopt 2.15.2 as the new default given it's a strict improvement even
  though it doesn't fix this specific bug, or document pve-test-vm's state
  as a deliberate, called-out test-only divergence) rather than something
  to silently drift on.

**Fix options, reassessed with both the confirmed root cause and the
upgrade test:**
- **Pull-then-push job** (recommended), extending the existing
  `harbor_repull` role (`terraform/lxc/ansible/roles/harbor_repull/`) to
  explicitly `docker push` affected images into a plain, non-proxy-cache
  project — mirrors the `pentagi` project's already-proven-working pattern,
  which never touches the proxy-cache tag-creation step at all. The clearly
  right option now: it's the only one confirmed to actually work, on the
  Harbor version actually in use, without a risky one-way upgrade.
- **Harbor native Replication** — same weaker assessment as before, now
  reinforced: the 2.15.2 test confirms the underlying tag-creation code is
  broken regardless of Harbor version, so there's no reason to expect
  Replication (which still relies on that same tag-creation step) fares any
  better.
- **Upgrading Harbor** is no longer a live option for fixing this
  specifically — confirmed not to work, and confirmed to be a one-way
  migration. Might still be worth doing *eventually* for its own reasons
  (newer Harbor, Valkey instead of Redis), but as a separate, deliberately
  staged decision — not a fix for this bug, and not safe to attempt on
  `pve` without accepting the rollback risk demonstrated here.
- Filing this as an upstream Harbor bug (confirmed still present in 2.15.2,
  generic `docker-registry` proxy-cache adapter fails to tag on the
  "manifest list cache" code path — existing issue #17135 predates 2.15 and
  wasn't actually closed by it) is worth doing independent of which local
  fix gets picked.

**Version divergence, decided (2026-08-15):** adopting 2.15.2 deliberately
rather than reverting pve-test-vm back to 2.14.3. Reasoning: the one-way
Redis/Valkey boundary is inherent to crossing 2.14→2.15, not something that
gets easier by waiting — it'll be forced eventually by some future
CVE/security fix that only ships in 2.15+, so taking it now, tested, on a
deliberate schedule beats taking it later under pressure. Once on 2.15.2,
the *next* bump (whenever the proxy-cache tagging bug is actually fixed
upstream) is an ordinary forward move, not a second one-way door. The
residual cost is real but narrow: no cheap revert below 2.15 if something
unrelated surfaces later — accepted, not eliminated. Repo default
(`harbor_installer_version` in
`terraform/lxc/ansible/roles/harbor_installer/defaults/main.yml`) bumped to
`"2.15.2"` to match.

**Validation approach for this change, also decided (2026-08-15):** not a
full teardown cycle. A Harbor version bump that doesn't change what
consumers pull/push against has a narrower blast radius than
Authentik/Traefik — a Harbor outage doesn't break stacks that are already
running (their images are already resident locally), it only blocks new
pulls/deploys/scans. `CLAUDE.md`'s Validation Tiers table now has a
dedicated row for this: `scripts/provision.sh --stack harbor-stack` on
pve-test-vm, then the same for 1–2 stacks that actually pull through it
(one native-adapter project, one proxy-cache project) to confirm no
regression. Full platform teardown stays reserved for changes that would
actually break something currently running.

**Rollout complete (2026-08-15).** `pve` and pve-test-vm both confirmed
running `v2.15.2-a97e7b83`, all 8 components healthy on both
(`/api/v2.0/health`). Scoped validation (this section, above) ran clean on
pve-test-vm: `harbor-stack` itself, plus `portainer-stack` (dockerhub/
native-adapter consumer) and `netbox-stack` (gcr/proxy-cache consumer via
its cAdvisor sidecar), all redeployed and smoke-tested with `failed=0`.

**Real recurrence of the idempotency bug, worth fixing at the source.**
The first `pve` upgrade attempt reported a clean `changed=4` run but
`systeminfo` still showed `v2.14.3` afterward — the exact
role-level idempotency-check gap from lessons-learned #10, reproducing on
a second, independent environment exactly as that lesson predicted. Fixed
the same way (remove `/opt/harbor/harbor` scaffold, re-run — `changed=7`
the second time, version genuinely moved). Since this has now recurred
across both environments this same change touched, it's no longer just a
one-off gotcha to remember — the role's "Check if Harbor installer has
already been extracted" task should compare the extracted version against
`harbor_installer_version` and force re-extraction on a mismatch, instead
of relying on an operator remembering to blow away the scaffold by hand.
**Fixed (2026-08-15)** — see lessons-learned.md #10 for the version-marker
mechanism and how it was validated on pve-test-vm without any risk to the
running install.

**Idempotency fix rolled to `pve` (2026-08-15).** Same outcome as
pve-test-vm: marker missing on first run (`changed=7`, safe same-version
reinstall, marker written), second run a true no-op. Version and health
unchanged (`v2.15.2-a97e7b83`, all 8 components healthy).

**Scan-coverage gap actually fixed (2026-08-15).** Implemented the
pull-then-push extension to `harbor_repull`
(`terraform/lxc/ansible/roles/harbor_repull/`): a new plain, non-proxy-cache
`mirror` project (created by `harbor_postconfigure`), and a project-scoped
push robot provisioned entirely by `harbor_repull`'s own tasks (unique
generated name, secret written only to `ci-runner-01`, no SOPS round-trip —
deliberately avoids the kind of drift already seen with the shared
`robot$ci-runner` credential, see
[[project_harbor_ci_robot_credential_mismatch]]). After each successful
pull through a proxy-cache project (everything except `dockerhub`, whose
native adapter already tags correctly), `harbor_repull.py` now also
`docker tag`s and pushes the same image into `mirror/<original-path>` —
the exact push flow `pentagi` already proves works, since it never touches
the broken tag-creation code path at all.

Validated on pve-test-vm with a real manual trigger of the systemd
service: 16/16 pulls succeeded, 3/3 mirror pushes succeeded (the two
`ghcr` and one `gcr` entries currently in the manifest). Confirmed at the
API level, not just a clean run — `mirror/gcr/cadvisor/cadvisor` came back
tagged (`v0.49.1`) with `scan_status: Success` and real severity data,
where the same image via the proxy-cache path has zero tagged artifacts.
Gracefully degrades to pull-only if the mirror credential isn't
provisioned yet (e.g. a rebuild before `harbor_repull` has run once).

**Rolled out to `pve` and closed out (2026-08-15).** `harbor_postconfigure`
created the `mirror` project on `pve`; `harbor_repull`'s push robot
provisioned the same way on `ci-runner-01`. A real repull run against
`pve` confirmed 16/16 pulls and 16/16 mirror pushes — every currently
manifest-tracked image, including `dockerhub` entries (see below).

**dockerhub included too, not skipped.** The original assumption that
dockerhub's native adapter always tags correctly didn't survive contact
with a full production audit: `grafana-oss`, `victoria-metrics`, `traefik`,
and `portainer-ce` all turned up as a single untagged artifact despite
using the "safe" adapter. Root cause not fully chased down (retention's
tag_selectors likely can't protect an artifact that loses its tag for any
reason, regardless of adapter), but the fix already built is
adapter-agnostic — `harbor_repull_mirror_skip_projects` now defaults to
empty, mirroring everything.

**Full vulnerability audit run against `pve`'s Harbor, all 61 artifacts
across 8 projects.** Two images are deliberately vulnerable (pentest
targets) and now carry a Harbor-native CVE allowlist — `dockerhub`
(`vulhub/struts2`, 257 CVE IDs) and `pentagi` (`kali-linux-fixed`, 131 CVE
IDs) — each list hand-cross-checked against every other image sharing that
project first, since Harbor's allowlist has no per-repository granularity.
Everything else got a real upstream-version check; full findings, fix
targets, and the allowlist rationale are in the published report.

**Next steps, in order:**
1. Expand `manifest.txt` — it's still v1 scope (confirmed live tags for a
   subset of stacks only, e.g. `itzg/minecraft-server` and
   `portainer/agent` aren't tracked yet). Every image actually in use
   should be in this manifest for scan coverage to be complete, not just
   tracked.
2. Work through the fix/upgrade list from the audit report, starting with
   `goauthentik/server`/`ldap` (highest Critical count, core auth infra)
   and `cadvisor` (already confirmed pullable at a newer tag, low-risk
   sidecar — good first one to actually execute).
3. Optional, independent of the above: file the upstream Harbor bug
   report (issue #17135 predates 2.15 and evidently wasn't fixed by it —
   worth an update/new issue with this session's specific findings:
   `controller/proxy/controller.go:216`, confirmed still broken in
   2.15.2). Explicitly declined for this session — the operator doesn't
   want it filed.

**Security finding from this investigation, already fixed:** ad-hoc
`ansible -m shell -a "..."` commands against a target host get their fully
expanded command line (including any interpolated secret) logged via
syslog and forwarded to Graylog — `HARBOR_DB_PASSWORD` was exposed this way
during this investigation. Rotated on both `pve` and pve-test-vm (shared
value in `terraform/secrets.common.enc.yaml`) same day; both Harbor
instances redeployed and verified healthy afterward. See
[lessons-learned.md](lessons-learned.md) for the safe pattern
(`environment:`/`args: stdin:` + `no_log: true`) verified to actually
prevent this leak, empirically tested with a dummy value before use on the
real password.

## Verified Current State

### Code state

The current repo already does the following:

- installs Harbor with embedded Trivy enabled via `./prepare --with-trivy`
- enables Harbor metrics on `:9090/metrics`
- creates proxy-cache projects for `dockerhub`, `ghcr`, `quay`, and `lscr`
- attempts to configure global scan behavior in
  `terraform/lxc/ansible/roles/harbor_postconfigure/tasks/main.yml`
- scrapes Harbor metrics from the monitoring stack

Relevant files:

- `terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml`
- `terraform/lxc/ansible/roles/harbor_installer/defaults/main.yml`
- `terraform/lxc/ansible/roles/harbor_installer/templates/harbor.yml.j2`
- `terraform/lxc/ansible/roles/harbor_postconfigure/defaults/main.yml`
- `terraform/lxc/ansible/roles/harbor_postconfigure/tasks/main.yml`
- `terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml`
- `terraform/lxc/stacks/harbor-stack/STACK_CONTRACT.md`

### Live stack state on `pve` as of 2026-05-31

Verified through `./with-secrets-prod` plus read-only Harbor API calls:

- Harbor is healthy and responds to `/api/v2.0/ping`
- the default scanner is `Trivy`
- `Trivy` is registered and not disabled
- Harbor metrics are live on `:9090/metrics`
- Harbor is caching proxy artifacts successfully
- the `dockerhub` proxy project currently exposes cached artifacts for
  `library/alpine`
- platform artifacts for that cached image now expose populated
  `scan_overview` data after a real OCI-client cache-fill through Harbor's
  external registry URL
- the live `scanAll` schedule endpoint accepts a 6-field cron, not the 5-field
  cron previously configured in code
- existing proxy-cache projects now expose `metadata.auto_scan: "true"` after
  reconciliation
- a direct authenticated registry manifest GET is not sufficient on its own to
  materialize a new proxy-cache artifact in Harbor's project API
- a real OCI client pull through Harbor's external registry URL does
  materialize the proxy-cache artifact and is the correct verification path

This means the current system is now in a better state than the original gap
assessment:

- scanner installation is present
- proxy cache is present
- scan-policy convergence is proven on live `pve`
- rebuild-safe scan verification is proven on live `pve`
- observability plumbing is still only partially present

### Current implementation status in repo

The repo now contains validated remediation work:

- Stage 0 is complete in docs
- Stage 1 is implemented and validated on live `pve` in
  `terraform/lxc/ansible/roles/harbor_postconfigure/`:
  - proxy-cache project creation now requests `metadata.auto_scan=true`
  - existing proxy-cache projects are reconciled to `metadata.auto_scan=true`
  - scan-all scheduling now uses `/api/v2.0/system/scanAll/schedule`
  - the default cron is now the 6-field form Harbor accepted live
  - the role reads the schedule back and fails if Harbor does not persist it
- Stage 2 is implemented and validated on live `pve` in
  `terraform/lxc/ansible/roles/harbor_postconfigure/files/harbor_scan_smoke.py`:
  - API and registry endpoints are handled separately
  - OCI cache-fill uses Harbor's external registry URL
  - `skopeo` is preferred over daemon-dependent `docker pull`
  - TLS verification can be relaxed for the smoke path when the controller does
    not yet trust Harbor's external certificate chain
  - manifest-list aware selection now prefers a real `linux/amd64` child image
    when Harbor does not retain a clean tagged parent artifact
- Stage 3 is implemented and validated on live `pve` in
  `terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml`:
  - Harbor metrics are scraped as separate `harbor-exporter`, `harbor-core`,
    `harbor-registry`, and `harbor-jobservice` jobs
  - VictoriaMetrics reports all four Harbor jobs as `up` after deploy
- Stage 4 is implemented in
  `terraform/lxc/stacks/monitoring-stack/dashboards/harbor-operations.json`:
  - Grafana provisions a Harbor Operations dashboard
  - the dashboard covers component health, queue state, proxy-cache inventory,
    core API traffic, registry traffic, and jobservice throughput
- Stage 5 is implemented and validated on live `pve`:
  - a first-pass findings exporter is deployed with `monitoring-stack`
  - VictoriaMetrics can query repository-level scan coverage and severity metrics
  - Grafana provisions a Harbor Scan Coverage dashboard from those metrics
  - the findings exporter also serves a live detailed CVE feed at
    `/findings.json`
  - Grafana provisions a Harbor CVE Inventory dashboard backed by the
    `Harbor Findings` datasource
  - the exporter currently covers:
    - proxy-cache repositories only
    - repository state (`scanned`, `unscanned`, `stale`, `error`)
    - last scan timestamp
    - severity totals by repository
    - detailed CVE rows derived from Harbor vulnerability additions payloads
  - Harbor alerting and dashboard refinement are still future work

The main remaining work is no longer Harbor scan convergence or basic Harbor
operations visibility. It is Harbor alerting and later refinement of findings
coverage and dashboard usability over time.

## Main Gaps

1. The first-pass findings exporter, scan-coverage dashboard, and CVE inventory
  dashboard are live, and the exporter serves detailed CVE rows from Harbor at
  `/findings.json`. The remaining work is refinement of that dashboard rather
  than first-time wiring.

2. Harbor alerting is still missing for Trivy/component health, queue buildup,
   scan failure patterns, exporter refresh problems, and stale/unscanned
   findings coverage.

3. Detailed CVE rows should not be forced into Prometheus labels. They need a
   separate Harbor-derived feed that Grafana can render as a table without
   exploding metric cardinality.

4. The first-pass exporter is repository-level only; later work may still need
   digest-level or tag-level refinement if repository aggregation proves too
   coarse for operations.

5. Harbor-related docs now reflect the current metrics state, and they need to
   stay aligned with implementation as the remaining alerting and dashboard
   refinement work lands.

## Design Principles

The implementation should follow these rules:

- no manual Harbor UI steps are required after a rebuild
- all durable Harbor behavior is applied by code or verified drift-safe API calls
- post-deploy validation must distinguish "Trivy is up" from "artifacts are scanned"
- each stage must have a clear verification command and pass/fail condition
- teardown/rebuild must tolerate loss of the Trivy cache
- the plan must not depend on Harbor preserving runtime-only state across rebuilds

## Rebuild Constraints

These constraints matter for the plan:

- Harbor registry/config loss is not acceptable in teardown planning
- Trivy cache loss is acceptable
- after a fresh Harbor rebuild, proxy-cache artifacts do not exist until something
  pulls them through Harbor
- therefore, scan verification must include a deterministic post-deploy cache-fill
  step using one or more small pinned images
- a registry manifest GET alone is not enough for cache-fill on the current live
  Harbor behavior; the verification path needs a real pull/copy client
- the verification image set must be small, stable, and acceptable to keep cached

Recommended verification artifacts:

- `dockerhub/library/alpine:<pinned>`
- optionally one multi-arch image and one single-arch image to catch manifest-list
  behavior separately

## Target State

After this work is complete:

- `deploy-harbor-stack.yml` configures Harbor so scan policy survives every rebuild
- a post-deploy Harbor smoke check proves:
  - Trivy is healthy
  - proxy projects exist
  - scan policy is present
  - a pinned test artifact is cached
  - that artifact eventually exposes non-empty scan data
- monitoring scrapes Harbor exporter/core/registry/jobservice metrics separately
- Grafana exposes a Harbor dashboard for component health, queue state, and scan
  activity
- Grafana also exposes scan coverage for cached artifacts, not just Harbor process
  health

## Staged Plan

### Stage 0 - Baseline And Evidence

Goal:
Capture and codify the live mismatch before changing behavior.

Changes:

- create this `docs/harbor-stack/` doc set
- update Harbor-related stale notes in `docs/monitoring-stack/design.md`
- record the verified current state and the exact drift:
  - scanner healthy
  - artifacts cached
  - scan policy absent or unreadable in live config
  - artifact vulnerability data empty

Verification:

- no code behavior change yet
- doc review only

Exit criteria:

- repo contains a current Harbor plan that matches both code and live state

### Stage 1 - Make Harbor Scan Policy Converge Reliably

Goal:
Ensure Harbor post-configuration writes scan settings in a way that Harbor actually
persists and exposes after a rebuild.

Files likely touched:

- `terraform/lxc/ansible/roles/harbor_postconfigure/tasks/main.yml`
- `terraform/lxc/ansible/roles/harbor_postconfigure/defaults/main.yml`
- possibly a new helper script if raw API payload shaping becomes easier to test that
  way

Work:

- inspect the Harbor API contract for global scan settings and update the role so it
  uses the payload Harbor actually persists
- use the Harbor schedule endpoint with the 6-field cron format that live `pve`
  accepted
- add an explicit read-back assertion after the write
- fail the play if Harbor accepts the request but does not expose the expected state
- define the drift behavior for existing proxy-cache projects that do not expose
  `metadata.auto_scan`:
  - either reconcile them in code
  - or fail loudly with a clear remediation message
- keep the role idempotent

Important note:

- do not treat HTTP 200 alone as success
- success means the subsequent GET shows the expected scan configuration
- success also means expected proxy-cache projects expose the intended metadata, or
  the role clearly fails rather than silently proceeding

Verification:

- run `deploy-harbor-stack.yml` against a Harbor instance
- verify:
  - scanner list contains healthy default `Trivy`
  - schedule write uses a 6-field cron
  - schedule read-back contains the expected scan policy
  - expected proxy-cache projects either expose `metadata.auto_scan=true` or the
    role fails with evidence
  - no role task silently "succeeds" while leaving `scan_all_policy` empty

Exit criteria:

- Harbor post-config converges on live `pve` without false-green success
- Harbor scan policy read-back passes
- Harbor proxy-project scan-related metadata is either reconciled or treated as a
  hard failure

### Stage 2 - Add Rebuild-Safe Harbor Smoke Verification

Goal:
Prove after every rebuild that Harbor can scan proxy-cached artifacts, not just start
its containers.

Files likely touched:

- `terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml`
- a new script under `scripts/` or `terraform/lxc/`
- possibly `docs/teardown-test/` runbook references

Work:

- add a read-only Harbor verification routine that runs after post-config
- run the cache-fill step from a host that has a real OCI client path such as
  `docker`, `crane`, or `skopeo`
- the routine should:
  - confirm `/api/v2.0/ping`
  - confirm healthy default scanner
  - confirm proxy projects exist
  - pull or copy a pinned verification image through Harbor using the OCI client
    path above
  - poll Harbor for artifact state until timeout
  - verify non-empty scan data appears for the cached artifact

Implementation detail:

- a plain Harbor manifest GET is not an acceptable cache-fill mechanism for this
  stage because it did not materialize a new proxy-cache artifact on live `pve`
- use Harbor API queries that handle nested repository names and manifest-list
  artifacts correctly
- where a parent manifest list points to a child platform image, verification must
  inspect the child digest if Harbor does not attach the scan result to the parent
  immediately

Recommended verification output:

- repository name
- parent digest
- child digest if present
- whether `scan_overview` is populated
- whether vulnerabilities endpoint returns non-empty content
- elapsed wait time

Verification:

- run after normal Harbor deploy on live `pve`
- run again after a clean Harbor rebuild
- verify the verification image is absent before cache-fill when testing rebuild
  behavior from a clean Harbor state

Exit criteria:

- a fresh Harbor instance can be proven to progress from:
  - no cached test artifact
  - to cached artifact created by a real OCI pull/copy path
  - to populated scan result

### Stage 3 - Expand Harbor Monitoring Scrapes

Goal:
Expose enough Harbor metrics to build useful dashboards and alerts.

Files likely touched:

- `terraform/lxc/ansible/playbooks/deploy-monitoring-stack.yml`
- `docs/monitoring-stack/design.md`

Work:

- replace or augment the single generic `harbor` scrape job with separate jobs for:
  - Harbor exporter
  - Harbor core
  - Harbor registry
  - Harbor jobservice
- use Harbor's `comp` query parameter where appropriate
- preserve the existing Harbor metrics endpoint configuration in the installer role

Verification:

- VictoriaMetrics target list shows all Harbor scrape jobs as `up`
- jobservice metrics appear, not just top-level exporter metrics
- registry metrics appear, not just top-level exporter metrics

Exit criteria:

- Grafana can query Harbor component metrics beyond `harbor_up`

### Stage 4 - Build Harbor Operations Dashboard

Goal:
Give operators a useful Harbor dashboard even before artifact-level scan coverage is
fully exported.

Files likely touched:

- `terraform/lxc/stacks/monitoring-stack/dashboards/harbor-operations.json`
- possibly Grafana alert provisioning files if alerts are added at the same time

Dashboard contents:

- Harbor overall health
- component up/down for core, registry, jobservice, Trivy
- proxy project counts, repository counts, artifact counts, pull counts
- task queue size and queue latency
- registry request rate and storage action timing
- jobservice throughput and failure counts where available

Verification:

- dashboard auto-provisions with the monitoring stack
- panels render from live Harbor metrics without manual datasource changes

Exit criteria:

- operators can see Harbor runtime health and activity from Grafana

### Stage 5 - Export Artifact Scan Coverage For Grafana

Goal:
Expose the scan information Harbor metrics do not currently provide directly.

Rationale:

- native Harbor Prometheus metrics are good for process health and queue behavior
- they are not enough to answer "which cached artifacts are still unscanned?"

Files likely touched:

- a new lightweight exporter script, likely deployed with the monitoring stack
- monitoring scrape config
- a new dashboard such as
  `terraform/lxc/stacks/monitoring-stack/dashboards/harbor-scan-coverage.json`
- possibly a small env file or secret-injection path for Harbor API credentials

Work:

- build a small exporter that queries Harbor API and emits Prometheus metrics
- keep the first version intentionally narrow:
  - proxy-cache projects only
  - read-only Harbor API calls only
  - stdlib Python if practical
  - no database or local persistence
  - one scrape endpoint, one polling loop, one in-memory snapshot
- deploy it with the monitoring stack so the exporter remains:
  - stateless
  - rebuild-safe
  - close to VictoriaMetrics
  - easy to restart independently of Harbor

Recommended architecture:

- runtime location:
  - run the exporter as a small service on `monitoring-stack`
  - preferred first implementation: a Compose service using a stock Python image
    and a mounted script, rather than building a custom image
- listener:
  - expose a simple `/metrics` HTTP endpoint on a dedicated internal port such as
    `:9414`
- polling model:
  - background refresh every 5 minutes
  - serve the last complete successful snapshot to Prometheus scrapes
  - expose exporter self-health so stale data is obvious
- source of truth:
  - Harbor artifact APIs and vulnerability additions APIs
  - do not scrape Harbor UI HTML or depend on manual CSV exports
- auth:
  - first implementation may use Harbor admin credentials already available via
    SOPS if that is the only API path proven to work
  - treat dedicated least-privilege Harbor credentials as a hardening follow-up,
    not as a blocker to the first usable exporter

Recommended exporter metric set:

- exporter health:
  - `harbor_findings_exporter_up`
  - `harbor_findings_exporter_last_refresh_success_timestamp_seconds`
  - `harbor_findings_exporter_last_refresh_duration_seconds`
  - `harbor_findings_exporter_refresh_errors_total`
- coverage metrics:
  - `harbor_findings_artifacts_total{project=...,state=...}`
  - states should start as:
    - `scanned`
    - `unscanned`
    - `error`
    - `stale`
  - `stale` should mean "artifact exists, but scan timestamp is older than the
    configured freshness window"
- artifact-level presence metrics:
  - `harbor_findings_artifact_info{project=...,repository=...,tag=...,digest=...,state=...} 1`
  - keep this to proxy-cache artifacts only so cardinality stays acceptable for a
    homelab-scale deployment
- vulnerability totals:
  - `harbor_findings_vulnerabilities_total{project=...,repository=...,severity=...}`
  - severities should start as:
    - `Critical`
    - `High`
    - `Medium`
    - `Low`
    - `Unknown`
- scan timing:
  - `harbor_findings_artifact_last_scan_timestamp_seconds{project=...,repository=...,tag=...,digest=...}`

Recommended exporter logic:

- enumerate only the known proxy-cache projects:
  - `dockerhub`
  - `ghcr`
  - `quay`
  - `lscr`
- for each repository in those projects:
  - list artifacts with `with_scan_overview=true`
  - ignore placeholder entries that do not represent a usable platform image when
    a better scan-bearing child artifact exists
  - reuse the Stage 2 selection rule:
    - prefer tagged parent artifact if Harbor exposes it cleanly
    - otherwise prefer `linux/amd64`
    - otherwise prefer any artifact that already carries `scan_overview`
- determine state per artifact:
  - `scanned` if `scan_overview` exists or vulnerability additions are non-empty
  - `unscanned` if artifact exists but no scan result is present
  - `error` if Harbor returns a non-retryable API error for that artifact
  - `stale` if scan data exists but the last scan time is older than the
    configured freshness threshold
- derive severity totals from Harbor's vulnerability payload if present
- publish only the last coherent snapshot; do not stream partially refreshed data

Recommended configuration knobs:

- `HARBOR_API_URL`
- `HARBOR_API_USERNAME`
- `HARBOR_API_PASSWORD`
- `HARBOR_FINDINGS_PROJECTS`
- `HARBOR_FINDINGS_REFRESH_INTERVAL_SECONDS`
- `HARBOR_FINDINGS_SCAN_STALE_AFTER_SECONDS`
- `HARBOR_FINDINGS_LISTEN_ADDRESS`
- `HARBOR_FINDINGS_LISTEN_PORT`

Recommended implementation stages:

- Stage 5a - exporter skeleton:
  - add the exporter process
  - emit only self-health metrics
  - scrape it from VictoriaMetrics
- Stage 5b - coverage metrics:
  - add project/repository enumeration
  - emit `scanned` / `unscanned` / `error`
- Stage 5c - severity metrics:
  - parse vulnerability payloads
  - emit `harbor_findings_vulnerabilities_total`
- Stage 5d - scan coverage dashboard:
  - build `harbor-scan-coverage.json`
  - provision it with Grafana and validate live panels
  - highlight unscanned, stale, and critical-heavy repositories
- Stage 5e - detailed CVE listing feed:
  - extend the findings exporter with a JSON findings feed
  - validate the feed live against Harbor proxy-cache data on `pve`
  - wire the feed into Grafana as a first-pass CVE inventory table

Recommended first dashboard contents:

- exporter health and last successful refresh
- scanned vs unscanned vs stale artifact counts by project
- repositories with the most critical findings
- repositories with missing scan results
- oldest stale scan timestamps

Detailed CVE listing design:

- keep detailed CVE rows out of Prometheus metrics
- extend the findings exporter with a second read-only data feed for current
  findings, separate from `/metrics`
- preferred first shape:
  - `/findings.json` or `/findings.ndjson` served by the existing
    `harbor-findings-exporter`
  - one row per finding on the selected representative artifact
  - rows derived directly from Harbor's vulnerability additions payload
- preferred dashboard integration:
  - add a Grafana JSON-capable datasource path for the detailed feed
  - keep VictoriaMetrics as the datasource for aggregate panels
  - use the JSON-capable datasource only for CVE table panels
- if Grafana plugin installation proves undesirable, fall back to a generated
  report artifact served from `monitoring-stack`, but keep that as a secondary
  option behind the exporter-hosted JSON feed

Recommended detailed finding fields:

- `project`
- `repository`
- `tag`
- `digest`
- `artifact_push_time`
- `scan_completed_at`
- `scanner`
- `cve_id`
- `severity`
- `package`
- `installed_version`
- `fixed_version`
- `link`
- short `description` or summary text if Harbor provides it

Recommended detailed listing behavior:

- keep scope to the known proxy-cache projects in the first version
- emit only the representative artifact already selected by the exporter for
  each repository unless later operations prove that digest-level expansion is
  necessary
- deduplicate by `(project, repository, digest, package, cve_id)` so the table
  does not double-count the same finding
- sort findings by severity and scan time in the rendered dashboard view
- keep the exporter stateless; the JSON feed should be generated from the same
  in-memory snapshot used for Prometheus metrics
- publish only the last coherent successful snapshot; do not mix old metrics
  with partial new CVE rows

Cardinality guardrails:

- keep Stage 5 focused on proxy-cache artifacts only
- do not emit per-CVE metrics in the first version
- do not emit both repository- and digest-level severity series unless the
  dashboard clearly needs both
- prefer repository-level severity totals for most panels

Rebuild/teardown behavior:

- the exporter must tolerate Harbor starting empty after rebuild
- an empty Harbor cache should produce valid zero or `unscanned` metrics, not
  exporter failure
- no exporter state should be persisted across rebuilds
- the exporter should converge automatically after the Stage 2 smoke artifact is
  repopulated

Verification:

- Stage 5a:
  - exporter `/metrics` responds
  - VictoriaMetrics target is `up`
- Stage 5b:
  - exporter metrics show non-zero cached artifact count
  - sampled unscanned artifacts appear correctly during validation
- Stage 5c:
  - severity totals are non-zero for a known vulnerable proxy-cached artifact
  - totals broadly match Harbor API payload summaries for spot-checked artifacts
- Stage 5d:
  - Grafana dashboard auto-provisions
  - operators can identify unscanned or stale repositories without using Harbor UI
  - live `pve` validation confirms the dashboard is provisioned in Grafana
  - aggregate severity totals and stale coverage are queryable over time

- Stage 5e:
  - detailed CVE feed responds with current findings rows
  - Grafana provisions a first-pass CVE inventory table backed by that feed
  - operators can answer:
    - which CVEs are currently present?
    - which repository/tag/digest carries them?
    - which packages and fixed versions are involved?

Exit criteria:

- Grafana can show actual scan coverage, not just Harbor process health
- operators can answer:
  - which cached repositories are unscanned?
  - which cached repositories have critical findings?
  - which scan results are stale?
  - which individual CVEs are currently present on cached representative artifacts?

### Stage 6 - Alerting And Teardown Integration

Goal:
Make Harbor scanning regressions visible during normal operations and rebuild drills.

Files likely touched:

- Grafana alert provisioning
- teardown/rebuild health gate docs or scripts

Alerts to add:

- Trivy component down
- Harbor jobservice down
- scan coverage below threshold
- unscanned cached artifacts older than threshold
- repeated scan task failures if exposed
- findings exporter refresh stale or failed
- detailed CVE feed unavailable when aggregate metrics still scrape successfully

Teardown/rebuild gate additions:

- Harbor smoke check must pass before Harbor is considered rebuilt
- monitoring validation should include Harbor scrape targets and Harbor dashboards

Exit criteria:

- rebuild acceptance includes Harbor scan validation, not only Harbor API health

## Verification Matrix

| Stage | Primary verification | Pass condition |
|---|---|---|
| 0 | doc review | plan matches code and live state |
| 1 | Harbor config read-back | 6-field schedule persists and proxy-project scan metadata converges or fails loudly |
| 2 | Harbor smoke test with pinned artifact | real OCI cache-fill creates artifact and scan data appears within timeout |
| 3 | VictoriaMetrics targets | Harbor component scrape jobs are `up` |
| 4 | Grafana dashboard provisioning | Harbor operations panels render live data |
| 5 | exporter metrics | unscanned vs scanned cached artifacts are measurable |
| 6 | alerts plus rebuild gate | Harbor scan regressions fail visible checks |

## Recommended Implementation Order

Implement in this order:

1. Stage 0
2. Stage 1
3. Stage 2
4. Stage 3
5. Stage 4
6. Stage 5
7. Stage 6

Reason:

- there is no point building a dashboard before scan policy and scan verification are
  trustworthy
- there is no point trusting a rebuild before the verification path itself is coded
- there is no point calling Stage 2 complete until the cache-fill transport is a
  real OCI client path rather than a manifest-only probe

## Notes For Production Checks

When checking production Harbor:

- use `./with-secrets-prod`, not `./with-secrets`
- prefer read-only commands allowed by the production wrapper
- in this repo, `./with-secrets-prod python3 ...` is the most reliable read-only path
  for Harbor API inspection

This matters because `bash -lc curl ...` is currently classified by the wrapper as
approval-gated, even when the underlying request is read-only.

## Out Of Scope

This plan does not include:

- replacing embedded Trivy with an external scanner
- full CI supply-chain redesign
- Harbor content trust / Cosign policy enforcement changes
- broad Harbor project taxonomy changes unrelated to scan reliability
- whether every platform image actually gets routed through Harbor in the
  first place, and whether that routing can be enforced rather than left to
  convention — see
  [docs/harbor-stack/image-sourcing-enforcement.md](image-sourcing-enforcement.md)
  (durable gotchas from that work: [lessons-learned.md](lessons-learned.md))

Those can be planned later once Harbor scan coverage is reliable and visible.

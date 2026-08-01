# Current State — Checkpoint 2026-08-02

Status: **Steps 1–6 done and validated on `pve-test-vm`. Not promoted.**
Branch: `task/ai-services-migration` (cut from `feat/mcp-utility-stack` per
plan.md's "Getting started" section). Nothing has touched `pve` or
`framework` yet — this checkpoint exists so a fresh session can pick up
cleanly before Step 7 (promote to `stable`, deploy to `pve`).

## Live state right now

- **`ai-services-stack` LXC**: VMID `50013`, `192.168.50.111/24`, `ai_seg`
  zone, running on `pve-test-vm`. Created via `terragrunt apply`;
  `terraform/lxc/environments/pve/ai-services-stack/` exists (terragrunt.hcl
  only) but has **not** been applied — nothing exists on `pve` yet.
- **OpenWebUI + SearXNG**: deployed via `scripts/provision.sh --stack
  ai-services-stack`, containers up and healthy. Data (chat history, users,
  SearXNG settings) migrated from `framework`'s real
  `/mnt/container-storage/{openwebui,searxng}-data` into this LXC's Docker
  named volumes (`ai-services-openwebui-data`, `ai-services-searxng-data`)
  before first start — not a fresh install.
- **MikroTik firewall**: 5 new rules live on the one shared physical router
  (affects `pve` and `pve-test-vm` simultaneously, same subnet):
  `edge_seg→ai_seg:8081`, `ai_seg→framework:8080,11434`,
  `ai_seg→edge_seg:443`, `192.168.50.111→internet:80`, and
  `ai_seg→192.168.20.110(Authentik):443` (added later — see the OIDC section
  below). The `internet:80` rule is IP-scoped to the `pve-test-vm` instance
  specifically — **must be re-run with `pve`'s `LAB_IP_AI_SERVICES` after
  promotion**; the other four are subnet/zone-wide or reference Authentik's
  fixed IP and already cover both nodes. Independently verified via the
  router's own read-only REST API, not just by trusting the ansible
  playbook's exit code.
- **Traefik edge route**: live and correct. `openwebui.test.gibbsgreatly.xyz`
  → `192.168.50.111:8081`, published via `terraform/lxc/reconcile-edge.py`
  (see the OIDC section below for why this needed a manual, scoped run).
- **`framework`**: completely untouched. Still running `llamacpp-router`,
  `ollama`, `comfyui`, and the original `openwebui`/`searxng` containers
  side by side. `openwebui.lab.gibbsgreatly.xyz` (production domain) still
  points at `framework`'s original deployment — the edge route has not
  been repointed (that's Step 7).

## What's been validated on `pve-test-vm`, and how

- **Model discovery over the new cross-subnet path**: confirmed live —
  OpenWebUI's own container reaches `framework.gibbsgreatly.xyz:8080`
  (llamacpp-router, 15 real models) and `:11434` (Ollama, 17 real models)
  through the new firewall rule, using an FQDN (not a raw IP — see
  lessons-learned).
- **Real chat completion**: Ollama returned a real completion in 1.8s.
  llamacpp-router's completion for one specific 30B model timed out at
  240s, but this was reproduced identically calling *directly from a
  workstation, bypassing `ai_seg` entirely* — it's a pre-existing
  `framework`-side characteristic (a llama-swap model cold-load), not
  something this migration broke. Not investigated further here.
- **SearXNG RAG search**: OpenWebUI's own container successfully calls
  `searxng:8080` internally and gets real results — the same integration
  class that was broken for PentAGI's SearXNG this session, confirmed
  working here. This validated the *network path* (`ai_seg` → `searxng`
  container), not the *quality* of results — see bug 11 below, found
  afterward when the operator reported real queries coming back empty.
- **No regression to `mcp-utility-stack`**: the live `pve` instance still
  responds correctly (`406`, one of its documented-healthy codes). The
  `pve-test-vm` instance being unreachable is pre-existing — it was
  deliberately stopped after its own promotion to `pve` on 2026-08-01
  (`git show 4fe9bab9`), unrelated to this work.
- **OIDC login: fully working end-to-end, confirmed live** (real redirect
  to a real Authentik login page, `200`, `<title>authentik</title>`).
  Getting here took three separate real bugs, not one platform limitation
  — an earlier version of this checkpoint wrongly concluded OIDC "can't be
  validated on pve-test-vm" and deferred it to promotion; that was wrong,
  caught and corrected the same session:
  1. Authentik's *public* edge route (`authentik.${LAB_DOMAIN}`) does use
     the `letsencrypt` resolver, which is LE **staging** on `pve-test-vm`
     — genuinely untrusted, this part of the original diagnosis was
     correct. But the fix isn't "wait for pve" — this platform already has
     a working pattern for exactly this (see `docs/step-ca-implementation/
     internal-tls-consumer-matrix.md`): route backend-only OIDC calls
     through `authentik-int.${LAB_DOMAIN}` instead, a step-ca-issued
     direct-TLS endpoint in `mgmt_seg`, already proven for
     Grafana/Portainer. Switched `OPENID_PROVIDER_URL` to it.
  2. That needed a new `ai_seg → 192.168.20.110 (Authentik):443` firewall
     rule — the first cross-zone rule into `mgmt_seg` from a contained
     zone; nothing existing needed one since Grafana/Portainer already
     live inside `mgmt_seg` itself.
  3. Even with the right endpoint and firewall rule, OpenWebUI's actual
     OAuth library (`authlib`, via `httpx`) still failed TLS verification
     — `httpx` ignores the container's system CA trust store entirely and
     loads its own bundled `certifi` package file. Confirmed by reading
     the real traceback down through `authlib → httpx_client → httpx →
     httpcore`, not by guessing. Fixed by bind-mounting the LXC host's
     already-trusted CA bundle onto `certifi`'s file path too, not just
     the system location.
  4. Separately, **the edge route to the new LXC had never actually been
     published to Traefik at all.** `scripts/provision.sh --stack
     ai-services-stack` (used for every deploy this session) explicitly
     skips edge/DNS/Authentik-app reconciliation in single-stack mode
     (`"SKIP edge reconcile: single-stack mode (activate-edge phase
     handles this)"`) — that phase is part of the full teardown-cycle
     tooling, not something `--stack` runs implicitly. Traefik was
     silently still routing the test hostname to something stale, which
     is what made bugs 1–3 so confusing to diagnose (fixing the app-side
     config produced no visible change at all, because requests through
     the public hostname were never reaching the new container's
     corrected code). Fixed by running
     `terraform/lxc/reconcile-edge.py --apply` scoped to just this stack's
     manifest (the full run crashes on unrelated stale `comfyui-stack`
     scaffolding, a pre-existing gap, not touched here), then pushing the
     generated Traefik config via `deploy-proxy-stack.yml` — the exact
     steps `reconcile_all_edge()` in `provision.sh` performs, just scoped
     manually.
  See `docs/design/lessons-learned.md`'s Authentik section for the durable
  version of all four findings.

## Real bugs found and fixed during implementation

These were live, reproducible failures hit while actually running things —
not theoretical:

1. **Stale addressing/port bugs in the old `pve-framework`-era
   `stack.yaml`/`edge.yaml`** — already described in plan.md's own
   "Addressing" section; fixed as part of Step 1.
2. **`ai_seg` has no route to Harbor's raw `infra_seg` IP.** It's a
   deliberately contained zone (like `pentest_seg`), confirmed by a live
   `docker pull` timeout. Fixed by switching to `harbor.${LAB_DOMAIN}`
   (routed via Traefik/`edge_seg`), matching `deploy-pentagi-stack.yml`'s
   already-proven pattern for the other contained zone. No new firewall
   rule needed — reuses the `ai_seg→edge_seg:443` rule OIDC also needs.
3. **`lxc_base` role's CA-install task has a hardcoded relative-path
   assumption** (`{{ playbook_dir }}/../../../../certs/...`, correct only
   for playbooks 4 directories deep under
   `terraform/lxc/ansible/playbooks/`). The data-migration playbook lives
   at `ansible/00-initial-setup/` (2 deep) — reusing the role silently
   resolved outside the repo and skipped CA install with no error. Fixed
   by writing correctly-pathed CA-trust tasks directly in the migration
   playbook rather than reusing the role from the wrong depth.
4. **`ansible.builtin.fetch` is a poor choice for large files** — it uses
   `slurp` internally (base64-encodes the whole file through Ansible's
   JSON channel). An ~845MB real tarball took 18+ minutes and never
   finished; switching to `ansible.posix.synchronize` (rsync) dropped the
   same transfer to 2m38s total.
5. **A real, previously-missing firewall rule the plan didn't anticipate**:
   `ai_seg→edge_seg:443`, needed because both `authentik.${LAB_DOMAIN}`
   (OIDC) and `llm.${LAB_DOMAIN}` (LM Studio) resolve via DNS to Traefik's
   `edge_seg` IP, not `mgmt_seg`. Found via live verification before
   deploying, not after a failure.
6. **`network/pve.yaml`'s documented `ai_seg` egress rule didn't match
   live reality.** Docs described a narrow FQDN allowlist; the actual
   live MikroTik rule is a flat `192.168.50.0/24 → !192.168.0.0/16:443`
   accept for the whole subnet, with zero address-lists configured.
   Found by reading the router's own state via its read-only REST API
   before extending it, not by trusting the docs. Corrected the docs to
   match reality rather than perpetuating the wrong description.
7. **`pve.yaml`'s `ai_seg` zone doc said "no pve-local containers yet"** —
   stale; `mcp-utility-stack` has been live on `pve` since 2026-08-01
   (`git show 4fe9bab9`). Fixed inline since it directly contradicted a
   change being made in the same block.
8. **`scripts/provision.sh --stack <name>` never reconciles Traefik/DNS/
   Authentik-app config for that stack.** Every deploy this session used
   `--stack ai-services-stack`, so the new LXC's edge route was never
   actually published — Traefik kept routing the public test hostname to
   something stale the whole time. See the OIDC section above; fixed by
   running `terraform/lxc/reconcile-edge.py --apply` scoped to this
   stack's manifest directly, then pushing the result via
   `deploy-proxy-stack.yml`, replicating what `provision.sh`'s full
   (non-`--stack`) mode does automatically.
9. **`authlib`'s real HTTP client (`httpx`) doesn't use the container's
   system CA trust store at all** — it loads its own bundled `certifi`
   file exclusively. A bind-mount that correctly fixed `urllib`/`aiohttp`
   TLS verification left `authlib`'s actual OIDC discovery fetch still
   failing, silently, with no visible symptom besides the wrong redirect
   target. Fixed by also mounting the trusted bundle onto `certifi`'s
   path.
10. **Authentik's public edge route uses LE staging on `pve-test-vm`
    (expected, documented) — but the correct response isn't "defer OIDC
    validation to `pve`", it's "use the internal `authentik-int` endpoint
    like Grafana/Portainer already do."** An earlier pass at this exact
    problem wrongly concluded OIDC was unfixable pre-promotion; corrected
    the same session once the actual internal-TLS consumer pattern was
    pointed out. Needed a new `ai_seg → mgmt_seg` firewall rule (the first
    of its kind — see rule 8 in the firewall list above).
11. **OpenWebUI's web search kept failing with `404: No results found`
    even though the SearXNG network path (bug/validation above) was fine.**
    Root-caused live: SearXNG's default engine set for `general` queries
    includes `duckduckgo`/`duckduckgo web` (TCP connect timeout to
    `html.duckduckgo.com` — reproduced from a separate workstation on the
    same WAN uplink, so a real network-path issue, not an `ai_seg`
    firewall gap) and `google cse`/`startpage`/`brave`/`qwant`/`yahoo`/
    `presearch` (all reachable but bot-detect/CAPTCHA a self-hosted
    SearXNG's scraped requests). None of these fail fast — they eat the
    full per-engine timeout every query, so a real answer from a working
    engine still arrives too late. This isn't something the migration
    broke; `framework`'s original deployment has the same stock
    `use_default_settings: true` config and would show the same behavior
    under real use, it just hadn't been stress-tested there. Fixed by
    disabling the broken/blocked engines and enabling two confirmed
    working ones (`mwmbl`, `searchmysite`) via an idempotent
    `ansible.builtin.blockinfile` task against the SearXNG data volume's
    `settings.yml` — survives both fresh deploys and a settings file
    migrated in from `framework`. See
    `docs/design/lessons-learned.md`'s SearXNG section.

See `docs/design/lessons-learned.md` for the durable, generalized version
of these — this file is the migration-specific record.

## Next steps

1. Promote `task/ai-services-migration` → `stable` per the normal branch
   model (needs the appropriate validation tier — this counts as
   Docker-Compose-stack-tier, already satisfied by the validation above).
2. Incremental deploy to `pve` (Step 7): `terragrunt apply` in
   `terraform/lxc/environments/pve/ai-services-stack/`, re-run the
   data-migration playbook against `pve`'s instance, re-run
   `mikrotik-firewall-ai-services-stack.yml` with `pve`'s
   `LAB_IP_AI_SERVICES` for the `:80` rule (the other 4 rules already
   cover both nodes), **run `terraform/lxc/reconcile-edge.py --apply`
   scoped to `ai-services-stack/edge.yaml` and push via
   `deploy-proxy-stack.yml`** (don't rely on `provision.sh --stack` alone
   — see the OIDC section above for why), repoint the
   `openwebui.${LAB_DOMAIN}` edge route. This is a production mutation —
   needs the `with-secrets-prod` approval flow per CLAUDE.md.
3. OIDC login already confirmed working end-to-end on `pve-test-vm` (see
   above) — on `pve` it should work the same way, just verify the
   production Authentik app/provider exist post-reconcile.
4. Step 8: decommission `openwebui`/`searxng` on `framework` after a soak
   period, not immediately.
5. Open question still unresolved from plan.md: whether the operator wants
   real auth added to llamacpp-router's `:8080` now that it's a formal
   cross-zone dependency. Not blocking.
6. Unrelated pre-existing gap noticed, not fixed here: `comfyui-stack`'s
   Authentik proxy provider fails `reconcile-edge.py --apply` with
   `400: Internal host cannot be empty when forward auth is disabled` —
   blocks any *full* (non-scoped) edge reconcile run. Worth a look
   separately since it'll keep blocking full reconciliation for every
   future stack until fixed.

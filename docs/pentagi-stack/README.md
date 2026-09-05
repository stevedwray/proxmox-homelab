# PentAGI Stack

Workspace for deploying [PentAGI](https://github.com/vxcontrol/pentagi) — an
autonomous AI pentesting-agent platform — as `pentagi-stack`, a Debian LXC on
`pve-test-vm`, driving local Ollama/SearXNG on `framework.gibbsgreatly.xyz`
(the Framework Desktop — bare-metal Ubuntu 26, not Proxmox) and exposing its
web UI through Traefik.

Status: **Phase 0 through 3 are fully done.** `pentagi-stack` (VMID `70010`,
`192.168.70.110`, renumbered 2026-07-26 -- see below) is up, all four containers healthy. `pentagi.test.gibbsgreatly.xyz`
resolves (DNS pushed via **Technitium**, the actual live DNS server on
`pve-test-vm` — not CoreDNS, despite some legacy naming in this repo),
routes through Traefik, and Authentik forward-auth gates it correctly.
Operator has logged in through Authentik and changed PentAGI's default
`admin@pentagi.com`/`admin` password — confirmed independently via real
`/api/v1/graphql` traffic in PentAGI's own logs from the operator's
workstation, all `200`.

**Phase 4 Test 1 passed, 2026-07-26** — direct Assistant tool call, clean
single execution, no embedding/provider errors:

```
PENTAGI_TOOL_TEST_OK
Linux 0108c373 ... x86_64 GNU/Linux
```

Not with the model originally configured, though — see below. Test 2
(agent delegation) and Test 3 (scoped Metasploitable 2 flow) were deferred by
operator choice — Test 1 was judged sufficient internal validation to move on.

**Production (`pve`) deployment done and verified, 2026-07-26.** Same stack
shape as `pve-test-vm`, on the shared `pentest_seg` zone (VLAN 70) at its
canonical IP `192.168.70.10` (freed by renumbering `pve-test-vm`'s instance to
`.110` — see Phase 0). `https://pentagi.lab.gibbsgreatly.xyz/` resolves,
routes through Traefik, and returns Authentik's forward-auth `302`, matching
the `pve-test-vm` signature exactly. New MikroTik rule needed:
`pentest_seg → 192.168.30.10` (pve's own Traefik IP) for Harbor pulls — the
same "Harbor is reached via Traefik, not its own IP" gotcha as before, just
re-hit on the production router. **Real mistake made and caught by the
operator**: DNS was initially pushed to `dns-stack`/CoreDNS on `pve` — per
`docs/dns-refactor/README.md`, CoreDNS was cut over to **Technitium**
(`192.168.20.15`) as the live authoritative delegate on `pve` back in Phase 3
of that workspace, and is now rollback-only. Fixed by rendering/publishing
the record through `render-edge-technitium.py` + `deploy-technitium-stack.yml`
instead. Lesson: check which DNS backend is *actually* authoritative for a
target environment before assuming `dns-stack`/CoreDNS is live, even on
`pve` — this workspace's own `pve-test-vm` notes already called this out for
the test environment, but the lesson wasn't generalized to "check this again
for every environment," including production.

**Model correction, 2026-07-26 — real, PentAGI-specific evidence beat the
repo-wide policy.** `PRIMARY_MODEL` was `llama-3.3-70b-instruct:q4_k_m` per
Decision 12 (a real, evidence-based ban on Qwen — but for VSCode/Copilot/
Continue's *own* tool-calling integration). It passed a simple direct
`/api/chat` preflight cleanly, then failed **consistently** against
PentAGI's actual runtime prompts in live Test 1 attempts — three
independent retry cycles, every one `The model produced output that does
not match the expected peg-native format`, PentAGI's own reflector
fallback unable to recover either. The operator's own prior hands-on
PentAGI testing had already found the real answer, preserved in
`docs/pentagi-stack/original/pentagi/.env` (gitignored — real secrets):
`qwen3.6-35b-a3b-ud:q4_k_m`. Switched to it, redeployed, retested — passed
cleanly on the first real attempt. **Lesson that generalizes**: a simple
single-tool preflight test validates basic API mechanics, not a real
application's actual prompt complexity — treat Phase 4's live test as the
real acceptance gate for model choice, Phase 2 as necessary but not
sufficient.

**Security fix, same session**: found and fixed a `.gitignore` bug where
the blanket `!.env` negation (meant only for this repo's own root `.env`)
was unignoring *any* file literally named `.env` anywhere in the tree —
including the operator's original PentAGI install directory, which
contains real plaintext secrets (Langfuse S3/Redis credentials, scraper
auth). Re-ignored that directory and its tarball specifically.

**Infrastructure incident during Phase 4 Test 1 (2026-07-26), found and
resolved — not a PentAGI/pentagi-stack bug.** Test 1's first tool call
stalled with no GPU activity on `framework.gibbsgreatly.xyz`. Root cause:
`pve-test-vm`'s external USB drive (a Samsung PSSD T7, backing the
`infrastructure` ZFS pool that `pentagi-stack`'s own rootfs lives on) was
hitting repeated UAS (USB Attached SCSI) resets every 1–3 minutes
(`dmesg`: `uas_eh_device_reset_handler`), stalling I/O enough to explain
the stuck image pull, high load average, and intermittent SSH timeouts —
a known recurring issue with this drive, not related to any of this
workspace's own changes. Operator shut down `pve-test-vm`, reseated the
USB connection, and restarted it — all pools reported healthy afterward,
`pentagi-stack`'s containers auto-restarted cleanly (`unless-stopped`),
PentAGI's API confirmed responding again. Worth remembering: **when
diagnosing something on `pve-test-vm` that looks like it could be a
container issue but shows high load with no single hot process and
intermittent SSH stalls, check `dmesg` on `pve-test-vm` itself for USB
errors before assuming it's the stack's own problem.**

[plan.md](./plan.md) is the phased plan this was executed against — kept
up to date with what actually happened, not just what was designed.

**Phase 0 done (2026-07-26)** — MikroTik trunk tagging (§0.1), the Proxmox
SDN zone (§0.2, `tvpent` — note: had to be renamed from the originally
planned `tvpentest`, since Proxmox SDN zone names are capped at 8
characters), and the `pentagi-stack` Terraform/Ansible stack itself (§0.3)
were all built and applied live via `terragrunt apply` (5 resources added,
0 changed, 0 destroyed — clean additive-only run). Full containment was
applied at the MikroTik, going beyond every other zone on this router,
which a live check found has no actual east-west isolation today despite
the documented "default-deny" intent — worth a follow-up pass across those
zones at some point, separate from this workspace.

**Phase 1 done (2026-07-26)** — PentAGI deployed via templated `.env` +
vendored, Harbor-rewritten `docker-compose.yml`, no interactive installer.
Two real bugs were found and fixed live, both worth remembering:

1. **Harbor is reached through Traefik (`edge_seg`, `192.168.30.110`), not
   at its own `infra_seg` IP.** `harbor.${LAB_DOMAIN}` resolves to Traefik's
   address, so the zone's containment needed a `pentest_seg → edge_seg`
   rule, not just `→ infra_seg`. All four image pulls timed out for ~15
   minutes before this was caught — a real gap in the original zone design,
   not a hypothetical one. (A related, easy-to-repeat mistake: the fix rule
   was first added *after* the zone's deny-all catch-all in the MikroTik's
   rule order, so it silently didn't fire until moved — the same ordering
   trap Decision 4 already warned about for `ai_seg`.)
2. **`PENTAGI_POSTGRES_PASSWORD` must be URL-safe.** It's embedded directly
   into PentAGI's `DATABASE_URL` connection string via plain Compose
   variable substitution, which can't URL-encode it. A `base64`-generated
   secret containing `/` broke Go's URL parser (`invalid port ... after
   host`), putting `pentagi` into a restart loop even though every
   container had started. Generate this one with `openssl rand -hex 24`
   (alphanumeric only), not `-base64`. Since `pgvector`'s data volume bakes
   the password in at first `initdb`, fixing this after the fact also
   requires wiping `pentagi-stack_pentagi-postgres-data` and letting it
   reinitialize — safe here since nothing real was in it yet.

Also confirmed along the way: `llama-3.3-70b-instruct:q4_k_m`/`:q3_k_m` are
live on `framework.gibbsgreatly.xyz`'s Ollama, and `forwardAuth`'s Authentik
reconciliation is fully automated (a shared forward-auth outpost, no manual
Authentik object needed) — both were open questions in the original plan,
now resolved.

**Phase 2 done (2026-07-26)** — provider/tool-calling preflight, all
checks passed:

- `llama-3.3-70b-instruct:q4_k_m` produces clean, structured tool calls via
  Ollama's own `/api/chat` — **the load-bearing check the whole model
  policy hinged on**, since Decision 12's Qwen-vs-Llama evidence came from
  VSCode/Copilot/Continue, never from Ollama's native tool-calling API
  directly. Confirmed here, not just inherited as a strong prior.
- Embedding (`nomic-embed-text:latest`, 768 dimensions), Docker-network
  reachability to both Ollama and SearXNG, and full GPU residency at
  131072 context (`size_vram` == `size`, no CPU offload) all confirmed.
- **One caveat, not a blocker**: SearXNG's `format=json` works, but most of
  its underlying engines (`brave`, `google cse`, `startpage`,
  `duckduckgo`) were rate-limited/CAPTCHA'd at test time — a pre-existing
  operational state on `framework.gibbsgreatly.xyz`, unrelated to this
  deployment. Worth rechecking before trusting SearXNG results in Phase 4.

## Read in this order

1. [plan.md](./plan.md) — the phased deployment plan: SDN zone + Terraform
   stack scaffolding → install PentAGI (templated `.env`, no interactive
   installer) → provider/tool-calling preflight → Traefik + Authentik
   forward-auth → layered validation → operations/backups → worker-node
   isolation. Each phase has concrete tasks and acceptance criteria.
2. [lessons-learned.md](./lessons-learned.md) — checkpoint from the
   validation-testing phase that followed deployment: eight fixes to a
   private PentAGI fork, infrastructure changes, what broke and why, and
   the llama.cpp migration findings. The active deployment uses Qwen3.6 for
   every role, including `adviser`; it does not use `gpt-oss-120b`.
3. [model-recommendations.md](./model-recommendations.md) — role-by-role
   model recommendations from the separate eval-battery project's full
   BFCL/GPQA/IFEval/CyberSecEval/RepoBench/SWE-rebench results, including
   a real open question this doc's own "adviser" evidence never
   settled: whether `gpt-oss-120b` actually earns its cost over
   Qwen3.6-35B alone.
4. [model-ab-test-plan.md](./model-ab-test-plan.md) — staged, controlled
   model-comparison plan using the PVE `pentest_seg` harness. It begins with
   minimal tool calls before any vulnerability validation.
5. [upstream-control.md](./upstream-control.md) — the isolated, true-upstream
   PentAGI control on PVE used to distinguish upstream behaviour from the
   private patched deployment.

## Upgrade baseline (2026-08-18)

The private fork at `/home/steve/git/pentagi`, branch
`fix/lab-lessons-learned`, is already based on upstream PentAGI `v2.1.0`
plus 15 local commits (`fe772720678f06f48e03f9311a1810fcfa499b52`). Those
commits contain the eight validation-derived fixes plus the CVE-MCP and
GVM-bridge tools. An upstream rebase is therefore not part of this update.

The lab deployment currently runs
`harbor.lab.gibbsgreatly.xyz/pentagi/pentagi-fixed:latest` with Docker image
ID `sha256:deb4365c1ab62bc001b0f25bbe4b3f39378ea383bc2132a1c379b03afefe06f8`
(captured from VMID 70010 on 2026-08-18). This local Docker image/config ID
is **not** the pin. Its verified registry manifest digest is
`harbor.lab.gibbsgreatly.xyz/pentagi/pentagi-fixed@sha256:685f638482fa43139a08f46396e863cc3ebc585486f9184fc747d9292102c914`;
the deployment playbook pins that exact artifact. Rebuild from `fe77272` only
when an image change is required, then capture and promote its new manifest
digest explicitly.

## Vanilla-upstream companion on the same LXC (2026-08-19)

For quick "browse and click through the real vanilla upstream UI" testing —
lighter weight than the isolated [upstream control](./upstream-control.md),
which deliberately has no Traefik route by design — `pentagi-stack`'s own
LXC (`192.168.70.10`) now also carries a second, separate compose project at
`/opt/pentagi-upstream-vanilla`, laid down by
`deploy-pentagi-upstream-vanilla-companion.yml`. It's the same byte-for-byte
upstream Compose file as the isolated control, its own `.env`/data volume so
neither install's state touches the other, and `PENTAGI_LISTEN_IP`/
`PENTAGI_LISTEN_PORT`/`SERVER_USE_SSL=false` set to the exact same
`192.168.70.10:8443` the real lab route already targets — so switching to it
needs **zero** Traefik/DNS/Authentik changes; the existing
`pentagi.lab.gibbsgreatly.xyz` route and its Authentik forward-auth gate
just keep working, unchanged, no matter which install answers behind it.

**Only one can run at a time** — upstream's own Compose file hardcodes fixed
container names (`pentagi`, `pgvector`, `scraper`, `pgexporter`), so both
projects can't hold them simultaneously. Switching is a manual
`docker compose down` (on whichever is active, to free the names — data
volumes are untouched) followed by `docker compose up -d` (on the other):

```bash
# Switch lab -> vanilla upstream
ssh root@192.168.70.10 'cd /opt/pentagi-stack && docker compose down'
ssh root@192.168.70.10 'cd /opt/pentagi-upstream-vanilla && docker compose up -d'

# Switch back, vanilla -> lab
ssh root@192.168.70.10 'cd /opt/pentagi-upstream-vanilla && docker compose down'
ssh root@192.168.70.10 'cd /opt/pentagi-stack && docker compose up -d'
```

Login is identical to the real lab instance from the browser's point of
view — same URL, same Authentik SSO gate. Behind that gate, PentAGI's own
login is whichever install is currently up: the lab one uses its
already-changed password, the vanilla one is untouched
(`admin@pentagi.com`/`admin`).

An earlier attempt in this session gave the vanilla control its own
permanent Traefik/DNS/Authentik route (a separate hostname pointing at
`pentagi-upstream-control`'s own LXC) — fully reverted, unused. Kept the
isolated control exactly as originally designed (loopback-only, no edge
route) for the A/B test harness in
[model-ab-test-plan.md](./model-ab-test-plan.md); this same-LXC companion is
purely for quick manual browsing.

## Key facts up front

- **Target host: `pve-test-vm`**, not `pve` — not a production node, so no
  `TASK_APPROVAL` flow applies to this build. Promotion past `stable` onto a
  production node is a separate, later decision.
- **New dedicated SDN zone required**: `pentest_seg` (VLAN 70,
  `192.168.70.0/24`) — none of `pve-test-vm`'s existing zones
  (`build_seg`/`mgmt_seg`/`edge_seg`/`infra_seg`) are a semantic fit for a
  workload holding a Docker socket with root-equivalent reach over its own
  containers, following the same precedent as `ai_seg` on `pve-framework`.
  **Blocked on operator action**: the MikroTik and `pve-test-vm`'s trunk
  port both need VLAN 70 tagged before any Terraform SDN work can proceed.
- **No interactive installer needed.** PentAGI is a plain
  `docker-compose.yml` + `.env` app under the hood (confirmed directly from
  `vxcontrol/pentagi`'s own repo) — the console-driven setup is just a
  convenience wrapper. The Ansible role templates the `.env` and runs
  `docker compose up -d` directly.
- **Harbor + apt-cacher, like every other stack.** Images are rewritten
  through Harbor's `dockerhub`/`quay` proxy-cache projects (matching
  `graylog-stack`/`monitoring-stack`); apt-cacher is automatic via the
  shared `lxc_base` role, no PentAGI-specific work needed.
- **Traefik yes, Authentik native-OIDC no.** PentAGI's own login only
  supports Google/GitHub OAuth (confirmed from its Go source — no generic
  OIDC client exists in the app itself), so it can't be a native-OIDC party
  the way OpenWebUI/Grafana/Portainer are. The plan uses Traefik's
  `forwardAuth` mode (Authentik's forward-auth middleware) to gate the UI
  at the edge instead — PentAGI's own login stays as defense-in-depth
  behind that gate, not the primary control. **Confirmed (2026-07-26)**:
  `reconcile-authentik-edge.py` already fully automates `forwardAuth` —
  a shared forward-auth outpost serves every such route, with its own
  Proxy Provider reconciliation and live endpoint-serving checks. No
  manual Authentik object needs to be hand-created.
- **Model policy**: `PRIMARY_MODEL` is `llama-3.3-70b-instruct:q4_k_m`, not
  the Qwen models used in earlier hands-on PentAGI testing — `decisions.md`
  Decision 12 is an evidence-based ban on Qwen for reliable structured tool
  calls. **Confirmed (2026-07-26)**: this exact tag (and `:q3_k_m`) is
  already pulled and live on `framework.gibbsgreatly.xyz`'s Ollama. Decision
  12's tool-calling evidence is from VSCode/Copilot/Continue, though, not
  PentAGI's own provider calibration — Phase 2's tool-call preflight is
  still the first direct confirmation either way, not a formality.
  **Superseded, same day** — see "Model correction, 2026-07-26" above:
  `llama-3.3-70b-instruct` failed PentAGI's real Test 1 three times and
  was replaced with `qwen3.6-35b-a3b-ud:q4_k_m`, which is what's actually
  live now. See [model-recommendations.md](./model-recommendations.md)
  for the independent eval-battery evidence backing that choice, plus
  recommendations for the other roles (`adviser`, `coder`).
- **Lab-target network scoping is by destination IP, not by port.** A real
  pentest needs open-ended port enumeration against an authorized target,
  so `pentest_seg`'s cross-zone policy for `LAB_TARGET` allows the full
  port range to that one host specifically, rather than a fixed allowlist
  the way `infra_seg`/`mgmt_seg`'s policies work for known application ports.

## Related documentation

- `docs/framework-integration/decisions.md` — Decision 4 (dedicated SDN
  zones for new workload classes), Decision 8 (Authentik integration
  pattern, native OIDC vs. forward-auth), Decision 12 (Qwen tool-calling
  ban, Llama-3.3-70B-Instruct as the proven alternative).
- `docs/framework-ubuntu/plan.md` §0 — current, live facts about
  `framework.gibbsgreatly.xyz` (the Framework Desktop): three Ollama/
  llama.cpp/LM Studio backends, `ai-services-stack` (OpenWebUI + SearXNG),
  all independently verified.
- `docs/framework-ubuntu/local-ai-development.md` — **PentestGPT is a
  different, already-validated tool** (2026-07-24), running client-side on
  the operator's workstation against the same Ollama endpoint. Don't
  confuse it with PentAGI (this workspace) — PentAGI is a much heavier,
  server-side deployment with its own Docker-socket-holding control plane.
- `terraform/lxc/stacks/ai-services-stack/`,
  `terraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml` — the
  closest existing example of this repo's Docker-stack + Harbor + Traefik +
  Authentik conventions; `pentagi-stack` follows the same shape wherever
  PentAGI's own constraints (no native OIDC, needs a Docker socket) don't
  force a difference.
- `CLAUDE.md` — branch model, validation tiers, and production credential
  controls this plan follows (`pve-test-vm` is not production-gated;
  promotion past `stable` would be).

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
- **MikroTik firewall**: 4 new rules live on the one shared physical router
  (affects `pve` and `pve-test-vm` simultaneously, same subnet):
  `edge_seg→ai_seg:8081`, `ai_seg→framework:8080,11434`,
  `ai_seg→edge_seg:443`, and `192.168.50.111→internet:80` (this last one is
  IP-scoped to the `pve-test-vm` instance specifically — **must be re-run
  with `pve`'s `LAB_IP_AI_SERVICES` after promotion**, the other three are
  subnet/zone-wide and already cover both nodes). Independently verified
  via the router's own read-only REST API, not just by trusting the
  ansible playbook's exit code.
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
  working here.
- **No regression to `mcp-utility-stack`**: the live `pve` instance still
  responds correctly (`406`, one of its documented-healthy codes). The
  `pve-test-vm` instance being unreachable is pre-existing — it was
  deliberately stopped after its own promotion to `pve` on 2026-08-01
  (`git show 4fe9bab9`), unrelated to this work.
- **OIDC — config confirmed correct, interactive login blocked by a
  pve-test-vm-only platform limitation, not a bug here.** See
  lessons-learned.md's Authentik section: Authentik's own edge route on
  `pve-test-vm` uses the standard `letsencrypt` resolver (not the
  `step-ca`-backed one Harbor gets), so its cert there is Let's Encrypt
  **staging** — inherently untrusted by design
  (`docs/design/lessons-learned.md`, "LE staging CA for all pve-test dev
  passes"). OpenWebUI's backend-side OIDC discovery fetch to Authentik
  therefore cannot succeed on `pve-test-vm` no matter what's configured on
  the OpenWebUI side — confirmed by tracing this through OpenWebUI's actual
  `authlib`-based OAuth code, not just inference. This is the same
  limitation already known to affect the LM Studio route
  (`llm.${LAB_DOMAIN}`, also on the `letsencrypt` resolver). **Will work
  once promoted to `pve`** (real production Let's Encrypt cert). Not
  something to fix — don't spend time on it again in a future session.

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
   `LAB_IP_AI_SERVICES` for the `:80` rule, repoint the
   `openwebui.${LAB_DOMAIN}` edge route. This is a production mutation —
   needs the `with-secrets-prod` approval flow per CLAUDE.md.
3. Re-verify OIDC login for real once on `pve` (real LE cert, should just
   work — this was blocked on `pve-test-vm` for the documented reason
   above, not a code issue).
4. Step 8: decommission `openwebui`/`searxng` on `framework` after a soak
   period, not immediately.
5. Open question still unresolved from plan.md: whether the operator wants
   real auth added to llamacpp-router's `:8080` now that it's a formal
   cross-zone dependency. Not blocking.

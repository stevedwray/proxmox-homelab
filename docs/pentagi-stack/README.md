# PentAGI Stack

Workspace for deploying [PentAGI](https://github.com/vxcontrol/pentagi) — an
autonomous AI pentesting-agent platform — as `pentagi-stack`, a Debian LXC on
`pve-test-vm`, driving local Ollama/SearXNG on `framework.gibbsgreatly.xyz`
(the Framework Desktop — bare-metal Ubuntu 26, not Proxmox) and exposing its
web UI through Traefik.

Status: **Phase 0.1 (MikroTik/switch, out-of-band) is done; Phase 0.2 (the
actual Proxmox SDN zone) and everything after it is still pending.** No
LXC exists yet, no Terraform/Ansible stack exists yet, and the
`terraform/lxc/network/pve-test-vm.yaml` declaration / `pvesh` SDN zone
itself haven't been created — VLAN 70 is routable now, but Proxmox doesn't
know about it yet. [plan.md](./plan.md) is a phased, execution-ready plan.

**Phase 0.1 done (2026-07-26).** The MikroTik/switch trunk tagging and L3
gateway bring-up are complete and live-verified, matching exactly how
`ai_seg` was verified — **from a remote host (the workstation), not a
self-ping on the router itself** (a self-ping on a bridge-VLAN
sub-interface isn't a reliable test on RouterOS and shouldn't be used to
judge success/failure):

- `vlan70-pentest` interface + bridge-VLAN tagging on **both** `ether1` and
  `ether5` (the same dual-tag every existing zone needs — this is the exact
  bug Decision 4 hit originally when only one port was tagged)
- Gateway `192.168.70.1/24`, connected route confirmed present
- Input-chain accept rules (icmp/DNS to the router) for `pentest_seg`
- **Full forward-chain containment applied** (the plan's "recommended,
  not required" option) — `pentest_seg` can reach `infra_seg` (Harbor/
  apt-cacher), `framework.gibbsgreatly.xyz` (Ollama/SearXNG), `LAB_TARGET`
  (full port range, destination-scoped), `edge_seg → pentest_seg` for
  Traefik, and general internet egress (PentAGI's DuckDuckGo/Sploitus
  providers call out directly) — with an explicit deny to everything else.
  **This is real containment no other zone on `pve-test-vm` currently has**
  — a live read-only check of the MikroTik's forward chain during this
  rollout found that `build_seg`/`mgmt_seg`/`edge_seg`/`infra_seg`/`ai_seg`
  have no actual east-west isolation today (the documented "default-deny"
  model is intent, not current enforced state) — worth a follow-up pass
  across those zones at some point, separate from this workspace.
- Verified: `ping 192.168.70.1` from the workstation, 0% packet loss.

Still needed: **Phase 0.2** — declare `pentest_seg` in
`terraform/lxc/network/pve-test-vm.yaml` and create the actual Proxmox SDN
zone/VNet/subnet (via `pvesh`, matching how every other zone here was
applied), then **Phase 0.3**, scaffolding `terraform/lxc/stacks/pentagi-stack/`
itself. Neither is blocked anymore now that the network layer is live. Two
of the plan's other open questions are also already resolved:
`llama-3.3-70b-instruct:q4_k_m`/`:q3_k_m` are confirmed pulled on
`framework.gibbsgreatly.xyz`'s Ollama (live `/api/tags` check), and
`forwardAuth`'s Authentik reconciliation is confirmed fully automated (see
below) — no manual Authentik step needed there.

## Read in this order

1. [plan.md](./plan.md) — the phased deployment plan: SDN zone + Terraform
   stack scaffolding → install PentAGI (templated `.env`, no interactive
   installer) → provider/tool-calling preflight → Traefik + Authentik
   forward-auth → layered validation → operations/backups → worker-node
   isolation. Each phase has concrete tasks and acceptance criteria.

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

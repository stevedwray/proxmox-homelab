# PentAGI ↔ Greenbone (GVM) integration — notes for future work

**Status: not implemented. Explicitly deferred** in the original plan
(`plan.md` §7) and every subsequent doc update. This file exists so the
next pass doesn't have to re-derive the architecture from scratch — it
records what's actually true today about both stacks, the one real gap
that blocks integration, and the concrete options for closing it.

## Why this is not just "point PentAGI at GVM's API"

The two stacks live in the same zone (`pentest_seg`, VLAN 70) but in
**separate LXCs, each with their own nested Docker daemon**. That matters
because of how each stack actually works internally:

- **GVM's GMP API is Unix-socket-only, not network-reachable.** `gvmd` in
  this stack's compose (`deploy-greenbone-stack.yml`) has no `ports:`
  mapping and no `--listen`/`--port` command override — it only exposes
  GMP over `gvmd_socket_vol`, a Docker named volume mounted into `gvmd`
  and the throwaway `gvm-tools` container *within `greenbone-stack`'s own
  Docker network*. Every GMP call this stack's own playbook makes (LDAP
  config, the Phase 4 test scan) works by bind-mounting that same socket
  volume into a `docker compose run gvm-tools ...` container running
  **on the same host, in the same Docker daemon**. There is currently no
  way to speak GMP to this stack from outside its own LXC — not from
  another container, not from another host on the same subnet. Confirmed
  by reading the compose definition directly (`gvmd` block has no `ports:`
  key at all, unlike `nginx`'s `0.0.0.0:443:443`/`0.0.0.0:9392:9392`).
- **PentAGI doesn't have a pluggable external-tool/MCP mechanism** (at
  least not one used or documented anywhere in `docs/pentagi-stack/`).
  Its real architecture (`docs/pentagi-stack/plan.md` §0) is: the
  `pentagi` container holds a mounted Docker socket into `pentagi-stack`'s
  *own* nested Docker daemon, and its built-in "terminal" tool spawns
  ephemeral sibling containers (`pentagi-terminal-*`) to actually run
  shell commands. Those worker containers are siblings within
  `pentagi-stack`'s Docker daemon — a completely different daemon than
  `greenbone-stack`'s. They can reach `greenbone-stack`'s **IP over the
  network** (same VLAN, no firewall rule currently blocks it — see
  below), but they cannot mount another LXC's Docker volumes or exec into
  another daemon's containers. Whatever GVM exposes has to be a real
  network listener for a PentAGI terminal-tool command to reach it at
  all.

So the `STACK_CONTRACT.md` line claiming PentAGI "can reach this stack's
GMP socket-backed API in-zone with no additional cross-zone firewall
rule" is aspirational/inaccurate as written — same-zone network reach and
socket-backed reach are different things. **The real gap is that gvmd
needs an actual TCP listener before any of that network reach matters.**
This file supersedes that line; `STACK_CONTRACT.md` should be corrected
to point here rather than repeat the claim.

## What would actually need to change

### 1. Expose GMP over TCP on `gvmd`

`gvmd` supports a `--listen=<addr> --port=<port>` GMP TCP listener
alongside (not instead of) its Unix socket — this is documented upstream
behavior, not something specific to this compose. Concretely:

- Add a `command:` override to the `gvmd` service in
  `deploy-greenbone-stack.yml`'s vendored compose, e.g.
  `--listen=0.0.0.0 --port=9390` in addition to whatever default args the
  entrypoint already uses for the socket.
- Add `ports: ["9390:9390"]` to that service (mirroring how `nginx`
  already does `0.0.0.0:443:443`).
- No new MikroTik rule needed for `pentagi-stack → greenbone-stack:9390`
  — both are already in `pentest_seg`, and this repo's firewall model
  only adds explicit rules for **cross-zone** traffic (see
  `terraform/lxc/network/pve.yaml`'s existing intra-`pentest_seg` reach
  between `pentagi-stack` and `greenbone-stack`, which already has no
  blocking rule between them). Confirm with a live `nc -zv` test from a
  `pentagi-terminal-*` container before trusting this, though — don't
  assume the zone's *intent* comment matches live MikroTik state without
  checking, per this repo's general practice.
- GMP over plain TCP is unauthenticated-transport (cleartext) unless
  `--listen-tls`/manual TLS options are added — since this stays entirely
  inside `pentest_seg` (not crossing to `edge_seg` or the internet), that
  matches the same trust model this zone already uses for the LDAP outpost
  reach and `LAB_TARGET`/`harness-target` scanning traffic. Revisit if
  `pentest_seg`'s threat model ever changes.

### 2. Give PentAGI its own scoped GVM credential — do not reuse `steve` or `admin`

- Create a dedicated local `gvmd` user for this (e.g.
  `gvmd --create-user=pentagi-integration --role=...`), **not** the
  `steve` LDAP account (that's a real person's login) and **not** the
  SOPS `GREENBONE_ADMIN_PASSWORD` admin account (full admin, no reason to
  hand that to an autonomous agent).
- GVM's built-in roles (`Admin`, `Observer`, `User`, etc. — check
  `get_roles` on the live system for the exact current set) likely need a
  **custom role** scoped to exactly what integration needs: create
  targets/tasks, start tasks, read results (`get_results`) — explicitly
  **not** `get_reports` (see the known crash bug below) and probably not
  user/role/feed administration.
- Store the new user's password the same way `GREENBONE_ADMIN_PASSWORD`
  is stored — SOPS (`terraform/secrets.common.enc.yaml`), a new
  `GREENBONE_PENTAGI_PASSWORD`-style key, injected into whatever
  PentAGI-side config ends up holding it (env var into the `pentagi`
  container's own compose, or a file baked into the pentest worker image
  — needs its own security review at that point, since it'd be a secret
  living inside an ephemeral, LLM-driven execution container).

### 3. Give the PentAGI worker image a GMP client

PentAGI's terminal tool just runs shell commands in whatever image
`DOCKER_DEFAULT_IMAGE_FOR_PENTEST` points at
(`{{ pentagi_registry_host }}/dockerhub/vxcontrol/kali-linux:latest`,
per `docs/pentagi-stack/plan.md`). That image would need a GMP client
available for an agent-issued command to actually speak to
`greenbone-stack:9390`:

- **`python-gvm`** (the library `gvm-tools`/`gvm-cli` are themselves built
  on) is the natural choice — pure Python, pip-installable, no extra
  system dependencies beyond what Kali already has. Would need adding to
  whatever provisions the Kali worker image (check whether
  `pentagi-stack` builds/customizes this image at all today, or pulls it
  verbatim from `vxcontrol/kali-linux` — if the latter, this either needs
  a derived image published through Harbor, or a per-task `pip install`
  step the agent runs itself, which is fragile to rely on).
- Alternatively, skip a Python client entirely and have PentAGI issue raw
  GMP XML over a plain TCP socket (`nc`/`python3 -c 'socket...'` one-liners
  Kali already has) — matches what this stack's own playbook already does
  via `gvm-cli`'s `socket` backend, just pointed at a TCP port instead of
  a Unix socket path. Lower setup cost, more fragile/verbose for an LLM
  agent to compose reliably per-call.

### 4. Carry over the two real GVM gotchas already found in this stack

Both are documented in full in [reference material — see
`plan.md` §4 and `STACK_CONTRACT.md`'s "What Must Not Be Edited Casually")
and apply identically to any GMP caller, including a future PentAGI
integration:

- **New targets need `alive_tests: Consider Alive`** if the target's
  firewall doesn't allow ICMP (true for `harness-target`) — otherwise
  GVM's default host-alive check fails silently and the scan finishes in
  ~30s with zero results that look exactly like a clean scan. Any
  PentAGI-driven target-creation flow needs to set this explicitly, not
  rely on GVM's default.
- **Never call `get_reports`** — a real, reproducible upstream `gvmd` bug
  crashes the daemon on any call to it (`column "severity_error" does not
  exist`, matches `greenbone/gvmd` issue #2273's bug class). Use
  `get_results` instead for pulling findings. If PentAGI's own agent
  loop is composing GMP calls from a natural-language plan rather than a
  fixed script, there's a real risk it reaches for the more
  obviously-named `get_reports` command on its own — worth either a
  system-prompt-level instruction or, better, only ever exposing a
  purpose-built wrapper tool that internally calls `get_results` and
  never surfaces `get_reports` as an option at all.

## Recommended shape, if/when this is picked up

Rather than letting a PentAGI agent freehand raw GMP XML per task (fragile,
easy for an LLM to get wrong syntactically, and exposes `get_reports` as
a footgun), the lowest-risk integration shape is a **small, purpose-built
CLI wrapper** (a single Python script using `python-gvm`, baked into the
worker image or fetched at task start) exposing only a handful of
narrow, named operations — e.g. `create-scan <target-ip> <ports>`,
`scan-status <task-id>`, `get-findings <task-id>` — each one internally
setting `alive_tests` correctly and using `get_results` never
`get_reports`. This keeps the LLM's job to "call this script with these
args" rather than "compose correct raw GMP XML," which matches how
`deploy-greenbone-stack.yml`'s own Ansible tasks are already structured
(fixed, tested GMP request templates, not freehand XML).

## Open questions, not yet decided

- Whether `pentagi-stack`'s Kali worker image should be customized
  (published through Harbor with `python-gvm` and the wrapper script
  baked in) versus having PentAGI's agent `pip install` it per-task —
  the former is more reliable but means maintaining a derived image; the
  latter is zero-maintenance but adds a flaky extra step to every task
  and depends on `pentest_seg`'s internet egress being up.
- Whether GVM scan results should feed back into PentAGI's own reasoning
  loop automatically (agent reads findings, decides next action) or stay
  a human-triggered, human-read side channel — this is a product/scope
  decision, not a technical one, and changes how much of the above is
  actually worth building.
- Whether cleartext GMP-over-TCP within `pentest_seg` is acceptable
  long-term, or whether `--listen-tls` should be set up from the start —
  leaning toward "acceptable for now, same trust boundary as the rest of
  the zone," but worth revisiting if `pentest_seg`'s containment model
  ever changes.

## Related documentation

- `docs/greenbone-stack/plan.md` §4 — the two GVM gotchas in full detail,
  from this stack's own Phase 4 test scan.
- `docs/greenbone-stack/STACK_CONTRACT.md` — network/inputs/provides
  contract; needs a correction to its "What May Depend on This Stack"
  section once this integration is actually built (currently says
  "Nothing yet").
- `docs/pentagi-stack/plan.md` §0 — PentAGI's Docker-outside-of-Docker
  architecture (`pentagi` container + Docker-socket-spawned
  `pentagi-terminal-*` siblings), the actual constraint this file's
  analysis is built on.
- `docs/pentagi-stack/README.md` — Kali worker image details
  (`DOCKER_DEFAULT_IMAGE_FOR_PENTEST`, the Harbor-rewrite gotcha for
  images pulled outside that variable).

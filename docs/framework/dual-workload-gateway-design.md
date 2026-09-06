# Dual-Workload Gateway — Design (not yet implemented)

Status: **design only**. Written up for a separate implementation pass —
nothing in this document has been built yet. Preserves the reasoning behind
the design so implementation can start from a settled plan rather than
re-deriving it.

## Problem

Two workloads share one Framework Desktop, each in its own LXC container:
llama.cpp (container 9001, see [llamacpp-router-mode-deployment.md](llamacpp-router-mode-deployment.md))
and ComfyUI (container 9002, see [comfyui-image-video-gen-findings.md](comfyui-image-video-gen-findings.md)).
They're rarely needed at the same time, and when llama.cpp *is* the active
one, the goal is a large model with a large context window — i.e. it
should get to use most of the host's memory, not a permanently-fenced
fraction of it.

The naive fix — statically splitting the host's 125GB into two fixed
halves, one per container, both always running — wastes most of the host's
capacity on whichever container isn't currently in use. The better fix
follows from something already confirmed empirically: **an idle service
(nothing loaded/running inside an otherwise-up container) costs close to
zero host memory**, and a cgroup memory ceiling is a cap, not a
reservation. So the two containers' ceilings don't need to sum to
anything sensible relative to the host total — they only need to make
sense individually, because only one *service* will ever actually be
holding memory at a time.

That reduces the problem to: how do you get "only one heavy service
running at a time" to happen **without manually starting/stopping anything
every time**, in a way that reacts to actual use rather than requiring a
manual pre-step?

## Why "just leave both services running, idle" doesn't work

Checked directly before settling on this design, not assumed: neither
service reliably frees its memory just from being unused (both containers
staying up is fine and intended — the risk is specifically each service's
*own* memory not clearing on its own once it's been used).

- ComfyUI: confirmed a model stays fully resident in memory after its job
  completes, even with `--disable-smart-memory` enabled — that flag's
  "offload to RAM" trick is a no-op on this hardware's unified memory
  (there's no separate pool to offload *into*). "Not in use for the last
  hour" and "not consuming memory" are not the same state for ComfyUI here.
- llama.cpp's router mode only frees a loaded model when a *different*
  model is requested, or when `--sleep-idle-seconds` is configured and
  actually fires. Without that flag, "idle" still means "fully resident."

So "both services left running unattended after use" is not a safe default
state — the memory each is actually holding doesn't correlate with whether
it's currently being used. This is what pushes the design toward an active
gateway that explicitly stops the losing side on every switch, rather than
trusting either service to self-clean.

## Design: wake-on-connect reverse proxy on the Proxmox host

A single small daemon, running directly on the Proxmox host (not inside
either container — it needs `pct exec`, which requires host-level access
this can't get from inside an unprivileged container without delegation).

**Both containers stay running permanently.** This was originally designed
around stopping/starting the whole *container* (`pct stop`/`pct start`),
on the assumption that a full container cycle was needed to guarantee
memory got released. That assumption was checked directly and turned out
to be wrong: an idle container (nothing running inside it) costs close to
zero host memory on its own, and the actual memory-freeing lever is
restarting the *service* inside the container, not the container itself.
Confirmed two ways:

- ComfyUI has a real `POST /free` API (`{"unload_models": true,
  "free_memory": true}`), but tested directly it only partially frees
  memory (~5GB out of ~40GB in one measured case) — `unload_models` calls
  `comfy.model_management.unload_all_models()`, which dereferences the
  model tensors but doesn't force PyTorch's ROCm/HIP caching allocator to
  return that memory to the OS (the allocator holds freed GPU memory for
  fast reuse by default, standard behavior on CUDA and ROCm alike).
- Restarting the `comfyui` **systemd service** (`systemctl stop` then
  starting it fresh), by contrast, was used repeatedly during this
  project's memory troubleshooting and reliably dropped container memory
  to a few hundred MB every time — killing the process is what actually
  returns memory to the OS, and the container around it never needed to
  stop.

So the design point of control is `pct exec <vmid> -- systemctl
stop/start <service>`, not `pct stop`/`pct start` on the container. Smaller
blast radius (never touches container networking/lifecycle, only the one
heavy process inside it), and no container-boot latency on every switch —
just process-restart time (a few seconds for ComfyUI to become HTTP-ready
again; the llama.cpp router is comparable).

**Ports**: two fixed ports on the host's own address — e.g. `:8080` for
llama.cpp, `:8188` for ComfyUI (matching the ports already used inside each
container, so nothing about the client-side URLs needs to change other
than pointing at the host instead of a container IP).

**Per-connection logic**:
1. New TCP connection arrives on one of the two ports.
2. Check whether the target service is already running and healthy
   (`pct exec <vmid> -- systemctl is-active <service>` plus a health-check
   request).
3. If not running/healthy:
   - If the *other* service is running, stop it
     (`pct exec <other-vmid> -- systemctl stop <other-service>`).
   - Start the target service (`pct exec <vmid> -- systemctl start
     <service>`, or `systemd-run` as used ad hoc throughout this project,
     ideally promoted to a real unit file first — see the findings doc's
     "not yet done").
   - Poll the target's internal health endpoint (llama-server's `/health`,
     ComfyUI's `/`) until it responds, with a reasonable timeout.
4. Once the target is confirmed ready, splice the original TCP connection
   through to it (raw byte forwarding — no HTTP-level parsing needed, so
   this works transparently for both llama.cpp's REST API and ComfyUI's
   HTTP+WebSocket traffic without protocol-specific logic).
5. Subsequent connections while the target is already running skip
   straight to step 4 — no added latency once "awake."

**Practical effect**: point a browser or API client at the Proxmox host's
address on the usual port, same as always. The first request after a
switch waits through a cold start (process restart + model load — the
same shape of delay any on-demand/serverless system has, just shorter than
a full container boot would add). Everything after that is immediate.
Switching from ComfyUI to llama.cpp (or back) requires no manual container
or service commands at all — just make a request to the port you want.

**This also fixes the memory-residue problem from the findings doc as a
side effect**: because switching always stops the other service first
(rather than trusting `/free` or ComfyUI's own idle behavior), every
switch is guaranteed to start from a clean memory slate — no more silently
still-loaded models from an hour ago.

## Prerequisites for implementation

- **Static IPs for both containers.** Currently both get DHCP leases,
  which the gateway would otherwise have to look up dynamically on every
  start. Assigning fixed IPs (via each container's `net0` config,
  `ip=<addr>/24,gw=<gw>` instead of `ip=dhcp`) removes that complexity
  entirely — the gateway always knows where to forward once a container
  is confirmed up.
- **Health-check endpoints already exist** on both sides: llama-server's
  `/health` (or `/v1/models`, already used throughout this project's
  testing) and ComfyUI's `/` (already used the same way). No new
  instrumentation needed on the application side.
- **A systemd unit for the gateway itself**, so it survives host reboots
  and restarts if it crashes — same pattern as every other service in
  this project, just running on the host instead of inside a container.

## Open decisions for the implementation pass

- **Language/runtime for the daemon.** A small Python `asyncio` TCP proxy
  is the natural fit (stdlib-only `asyncio.start_server` + a manual
  byte-splice loop, no dependencies to install on the host) — noted here
  as the leading option, not yet decided for certain.
- **Idle-timeout auto-stop.** The design above only stops a service when
  the *other* one is requested — it doesn't proactively stop an idle
  service to free memory pre-emptively while nothing is requesting the
  other one either. Worth deciding whether that's wanted (e.g., "stop
  ComfyUI after 30 minutes of no new connections even if llama.cpp was
  never requested") or whether "only swap on demand" is sufficient.
- **Cold-start UX.** Deciding whether the client should just experience a
  raw multi-second-to-multi-minute TCP hang on first connection (simplest
  to build) versus the gateway serving an immediate placeholder response
  ("starting up, retry shortly") for HTTP specifically — the latter needs
  protocol-aware logic the raw-splice design deliberately avoids, so this
  is a real tradeoff between simplicity and UX polish.
- **Exact llama.cpp container sizing.** The design assumes container 9001
  gets a large ceiling (100GB+ discussed) once it's not sharing the host
  with ComfyUI — the actual number should be chosen based on which
  large-model + large-context combination is the real target (not yet
  specified), and validated the same empirical way memory sizing was
  validated for ComfyUI (§6 of the findings doc): start from a real
  workload's measured `anon` usage, not a guess.

## Blast-radius note, carried over from the original discussion

This daemon runs with real privileges on the Proxmox host itself (to call
`pct exec ... systemctl stop/start` unattended, triggered by arbitrary
incoming network connections) — a step up from everything else built in
this project so far, which has all been scoped to inside individual
containers. Smaller in scope than the original whole-container-stop design
(it never touches container lifecycle/networking, only one service's
process state), but still worth treating with the same care as any other
host-level automation: review the implementation before deploying it as an
always-on service, and consider whether it should require anything beyond
"a TCP connection arrived" before it's willing to stop a running service
(e.g., only reacting to connections from trusted source IPs, if this host
is ever reachable beyond the local LAN).

# Proxmox on Strix Halo — Setup Notes

Setup notes, gotchas, and performance findings from bringing up Proxmox VE
with GPU-passthrough LXC containers on the Framework Desktop (Ryzen AI Max+
395 / Radeon 8060S, gfx1151, 128GB unified memory), for local LLM inference
workloads via `playbooks/80-proxmox-lxc-docker.yml` and
`playbooks/81-proxmox-lxc-native.yml`.

Host tested: Proxmox VE 9.2.2, Debian 13 (trixie), kernel `7.0.2-6-pve`.
Guest: Ubuntu 26.04 LXC.

## TL;DR

Proxmox is a fine choice for this hardware — a privileged LXC container
running an Ubuntu guest matches or beats bare-metal Ubuntu performance for
both ROCm/HIP and Vulkan, once a handful of non-obvious fixes are applied.
None of the fixes below are exotic; all are one-time, and most apply to
*any* GPU-passthrough LXC setup on Proxmox, not just this hardware.

The two things worth doing regardless of hardware: fix the enterprise-repo
apt lockout immediately on any fresh unlicensed install, and never trust
`llama-server`'s default batch size for large models on Vulkan — it will
crash the GPU.

## 1. Fresh install: fix apt before anything else

*Applies to any unlicensed Proxmox VE install, unrelated to this hardware.*

**Gotcha**: a fresh, unlicensed Proxmox install ships with the paid
enterprise apt repos enabled by default (`pve-enterprise`, `ceph-*`) and no
free repo configured. `apt-get update` fails immediately with
`401 Unauthorized`, blocking every subsequent step.

**Fix** (now automated in `roles/proxmox_host`):

```bash
mv /etc/apt/sources.list.d/pve-enterprise.sources{,.disabled}
mv /etc/apt/sources.list.d/ceph.sources{,.disabled}

cat > /etc/apt/sources.list.d/pve-no-subscription.sources <<'EOF'
Types: deb
URIs: http://download.proxmox.com/debian/pve
Suites: trixie
Components: pve-no-subscription
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
EOF

apt-get update
```

## 2. GPU passthrough into an LXC container

*Generally applicable to any AMD GPU passthrough into Proxmox LXC.*

**Gotcha**: Proxmox's built-in `gpu` device-passthrough option covers
`/dev/dri` but not `/dev/kfd` (the ROCm/HIP compute device). Without it, GPU
detection inside the container silently fails for ROCm workloads. Must be
added by hand, directly in the container's config file, while stopped.

**Fix** (`roles/proxmox_lxc`, `roles/proxmox_lxc_native`):

```bash
pct stop <vmid>
KFD_MAJOR=$(printf '%d' "0x$(stat -c '%t' /dev/kfd)")

cat >> /etc/pve/lxc/<vmid>.conf <<EOF
lxc.cgroup2.devices.allow: c 226:* rwm
lxc.cgroup2.devices.allow: c ${KFD_MAJOR}:* rwm
lxc.mount.entry: /dev/dri dev/dri none bind,optional,create=dir
lxc.mount.entry: /dev/kfd dev/kfd none bind,optional,create=file
EOF

pct start <vmid>
```

226 is the standard DRM major and stable across systems; the KFD major is
not — always read it live rather than hardcoding it.

## 3. Docker inside the LXC (skip if going native)

*Only relevant if nesting Docker inside the container. Two fixes required
together — neither alone is sufficient.*

**Gotcha 1**: Docker needs to load its own `docker-default` AppArmor
profile. Even a *privileged* LXC container is still confined by AppArmor by
default:

```
AppArmor enabled on system but the docker-default profile could not be loaded:
apparmor_parser: Access denied. You need policy admin privileges to manage profiles.
```

**Gotcha 2**: setting `lxc.apparmor.profile: unconfined` alone does **not**
fix it. Proxmox's default LXC capability set drops `cap_mac_admin` /
`cap_mac_override` — exactly what `apparmor_parser` needs — even for
privileged containers. Confirm via `capsh --print` inside the container.

**Fix** (`roles/proxmox_lxc`), both lines required together in the stopped
container's config:

```
lxc.apparmor.profile: unconfined
lxc.cap.drop:
```

The second line is deliberately empty — it clears Proxmox's default
capability drop-list rather than adding to it.

## 4. Pushing files into a container

**Gotcha**: `pct push <vmid> <src> <dest>` reports success even when the
destination's parent directory doesn't exist — it does not create missing
parent directories. The file silently goes nowhere useful. A later `test
-e` check can be misled by whatever ends up at that path instead (we hit a
stray directory there from an earlier interrupted attempt, which made the
check falsely report the model as "already present").

**Fix**:

```bash
pct exec <vmid> -- mkdir -p <parent-dir>
pct push <vmid> <src> <dest>
```

Prefer `test -f` over `test -e` for existence checks on files you intend to
push — `-e` matches a stray directory just as happily as a real file.

## 5. ROCm/HIP and Vulkan: Debian vs. Ubuntu

*Specific to this hardware, but the lesson generalizes to any
Proxmox-on-Debian + AMD GPU setup.*

**Gotcha**: AMD packages ROCm/HIP for Ubuntu only. Debian 13 has no
`rocm-dev`, `rocm-smi`, `hipcc`, or `hipconfig` at all — not older versions,
absent entirely. Bare-metal ROCm/HIP on the Proxmox host itself is a
non-starter without manually adding AMD's Ubuntu-targeted apt repo to
Debian (not attempted — unsupported combination).

Debian's own Mesa is also meaningfully behind Ubuntu's:

| Base OS | mesa-vulkan-drivers | Prompt processing | Generation |
| --- | --- | ---: | ---: |
| Debian 13 (bare Proxmox host) | 25.0.7 | 5,945 t/s | 317 t/s |
| Ubuntu 26.04 (LXC or bare) | 26.0.3 | 7,232 t/s | 338 t/s |

TinyLlama 1.1B Q2_K, single-stream `llama-bench`, pp512/tg128. ~18% / ~6%
slower on Debian's older Mesa.

**Recommendation**: do all GPU compute work — ROCm/HIP or Vulkan — inside
an Ubuntu-based guest, never the bare Debian host, regardless of which
distro Proxmox itself runs on. The LXC container is a full abstraction
boundary here: the host's package ecosystem is irrelevant to what's
available inside it. The same Ubuntu 26.04 LXC image gave us both current
Mesa *and* full ROCm/HIP, on top of a Debian host that could supply
neither on its own.

## 6. Unified memory: VRAM, GTT, and the OS/AI split

*Specific to APUs with unified memory; the kernel mechanism (amdgpu/TTM) is
generic, not Proxmox-specific.*

Confirmed live via `dmesg` and `/sys/class/drm/card1/device/mem_info_*`:
unified memory is not one pool. There's a small, fixed VRAM carve-out
(512MB on this hardware) and a much larger, dynamic GTT (Graphics
Translation Table) region — system RAM the GPU driver claims and releases
as needed. Every model we ran was actually served from GTT, not VRAM.

**Gotcha**: the commonly-referenced `amdgpu.gttsize=` kernel parameter is
**deprecated**. Setting it alone produces a kernel warning and an
inconsistent state:

```
[drm] Configuring gttsize via module parameter is deprecated, please use ttm.pages_limit
[drm] GTT size has been set as 103079215104 but TTM size has been set as 67155353600, this is unusual
```

GTT reports the new size, but the underlying TTM allocator pool is still
capped at the old default.

**Fix**: use `ttm.pages_limit` instead (units are 4KB pages, not MB):

```bash
# /etc/default/grub
GRUB_CMDLINE_LINUX_DEFAULT="quiet ttm.pages_limit=25165824 ttm.page_pool_size=25165824"

update-grub
reboot
```

25165824 pages = 96GB. After reboot, `dmesg` should show matching GTT/TTM
sizes with no "unusual" warning.

**The split is a ceiling, not a reservation.** `ttm.pages_limit` bounds
what the GPU driver *can* claim — it does not pin that memory away from
the OS in advance. Verified directly: right after rebooting with a 96GB
ceiling set, `free -h` still showed ~116GB free. The memory is only
actually committed when a workload asks for it.

| Scenario | What actually happens |
| --- | --- |
| AI workload exceeds its ceiling | Graceful — a local allocation failure (Vulkan/ROCm OOM error), reported by the app that asked |
| Host is squeezed because AI has claimed most of the ceiling | Unpredictable — ordinary Linux OOM-killer, which can kill anything on the box, not necessarily the actual cause |
| Host wants more RAM while AI ceiling is mostly unused | Fine — the "OS share" isn't a cap; the host gets whatever's actually free |

**Recommendation**: set the ceiling generously — there's no cost to
headroom you aren't using — but keep a real host-side margin (we used
32GB on a 128GB box; 16GB is probably the practical floor), specifically
because the failure mode on the host side is worse than on the GPU side. A
container's own `memory:` cgroup limit is unrelated to any of this —
GPU/GTT allocations bypass it entirely, managed by the host kernel, not
the container. We ran an 82GB GPU workload inside a container whose own
memory limit was 16GB with no conflict.

## 7. Performance: Proxmox LXC vs. bare Ubuntu

llama.cpp server, TinyLlama 1.1B, concurrency 4, 60s stress test. Full
GPU-utilization verification via `rocm-smi`/sysfs on every cell, not log
text alone.

| Deployment | HIP tok/s | HIP GPU% | Vulkan tok/s | Vulkan GPU% |
| --- | ---: | ---: | ---: | ---: |
| Ubuntu bare-metal + Incus + Docker (reference) | 446 | 96% | 461 | 66% |
| Proxmox bare-metal (no container) | — (not buildable) | — | 5,945* | — |
| Proxmox LXC + Docker | 454–455 | 92–97% | 536–566 | 66–77% |
| Proxmox LXC, native (no Docker) | 464 | 92–97% | 549 | 68–77% |

\*Bare-metal Vulkan figure is single-stream pp512 (different measurement,
not directly comparable to the concurrent-stress numbers) — ROCm/HIP
wasn't buildable at all on bare Debian.

- **HIP is a dead heat** between Ubuntu+Incus and Proxmox+LXC, Docker or
  not. Whatever overhead containerization adds is within noise.
- **Vulkan is reproducibly ~15-20% higher on Proxmox's LXC** than on
  Ubuntu's Incus, across three independent runs (two Docker, one native).
  Confirmed with a repeat run specifically to rule out a one-off
  measurement. Cause unconfirmed — plausibly the differing host kernel
  build (`7.0.2-6-pve` vs. `7.0.0-27-generic`), since the container
  userspace (same Ubuntu 26.04 image, same Mesa) is otherwise identical
  either way.
- **Docker vs. native inside the LXC makes no measurable difference** for
  either backend. The LXC boundary is what matters, not whether Docker
  sits inside it.

## 8. Large model / long context: a real Vulkan reliability bug

The most consequential finding in this whole exercise. Everything above
was measured on a 1.1B model with short prompts — this is what changes at
real scale.

**Test**: Llama-3.3-70B-Instruct, Q4_K_M (42.5GB), 128K context configured,
fed a real 33,615-token prompt, full GPU offload (81/81 layers), inside
the native LXC. Memory: ~40GB weights + ~41GB KV cache ≈ 82GB of the 96GB
GTT ceiling.

| Backend | Batch settings | Prefill | Generation | Result |
| --- | --- | ---: | ---: | --- |
| HIP | default | 86.4 t/s | 3.93 t/s | Completed |
| Vulkan | default (batch 2048 / ubatch 512) | 21.3 t/s* | — | Crashed at 79% |
| Vulkan | reduced (batch 512 / ubatch 128) | 72.3 t/s | 4.21 t/s | Completed |

\*Partial — measured before the crash, not a completed run.

**Gotcha — genuine GPU hang, not a soft error.** The kernel logged an
actual compute-ring timeout and reset:

```
amdgpu: ring comp_1.1.0 timeout, signaled seq=593044, emitted seq=593046
Starting comp_1.1.0 ring reset ... Ring comp_1.1.0 reset succeeded
[drm] device wedged, but recovered through reset
```

The GPU driver self-healed at the kernel level. The `llama-server` process
did not: Vulkan's "device lost" is unrecoverable in-process — every
request afterward, even a trivial one, failed identically until the
process was restarted.

**Known upstream issue, not a fluke of our setup**:
[ggml-org/llama.cpp#21724](https://github.com/ggml-org/llama.cpp/issues/21724)
and [#20515](https://github.com/ggml-org/llama.cpp/issues/20515) describe
the identical mechanism on AMD APUs — a Vulkan compute submission covering
too much batched work takes longer than the kernel's default hang-detection
watchdog (~10s), which then resets a job that was still legitimately
running, not deadlocked. Reports specifically name Radeon 8060S / RADV
STRIX_HALO crashing in the same ~65-80K token range.

**Fix**: explicitly reduce the batch sizes below `llama-server`'s defaults
for any large-model, long-context Vulkan deployment on this hardware:

```
llama-server --batch-size 512 --ubatch-size 128 ...
```

With this change, the identical 33K-token workload completed cleanly and
Vulkan was *competitive with HIP* — 16% slower on prefill, actually ~7%
faster on generation. The exact safe ceiling between 512/128 and the
crashing defaults wasn't bisected; 128 is confirmed working, not
necessarily the maximum safe value.

## 9. Recommendations, in priority order

1. Fix the enterprise-repo apt lockout the moment a fresh Proxmox install
   boots, before touching anything else.
2. For any GPU-passthrough LXC: add `/dev/kfd` passthrough by hand.
   Proxmox's GUI GPU option won't do it for you.
3. Run ROCm/HIP or latest-Mesa Vulkan work inside an Ubuntu-based guest,
   never the bare Debian host — the LXC boundary determines available
   driver versions, not the hypervisor OS.
4. If nesting Docker in an LXC, apply *both* the AppArmor-unconfined and
   cap-drop fixes together — one without the other still fails.
5. Always `mkdir -p` before `pct push`; check destinations with `test -f`,
   not `test -e`.
6. Use `ttm.pages_limit`/`ttm.page_pool_size`, not the deprecated
   `amdgpu.gttsize`. Size generously (it's a ceiling, not a reservation)
   but keep real host-side margin, since a squeezed host falls back to
   the general OOM-killer, which can take down anything.
7. Never trust default batch sizes for Vulkan with large models/long
   contexts. Set `--ubatch-size` well below default explicitly — this is
   the difference between a working deployment and a GPU hang partway
   through.
8. Also `systemctl reset-failed`, not just `stop`, on transient units you
   intend to reuse by name — a previously-failed unit blocks a fresh
   `systemd-run` under the same name even when nothing is actually
   running.

### Open questions, if this becomes a bigger project

- Why Proxmox's kernel build correlates with higher Vulkan throughput than
  Ubuntu's — not root-caused, would need matched-kernel A/B testing to
  isolate.
- The precise `--ubatch-size` ceiling before the Vulkan crash reappears —
  confirmed 128 works and default (512) fails, nothing in between tested.
- Unprivileged containers weren't attempted — everything here used
  privileged LXC for simplicity, a meaningfully thinner isolation boundary
  than a genuine multi-tenant prod environment would likely want. Worth
  revisiting with proper UID/GID mapping if this pattern moves into
  production use.

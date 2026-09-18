# Local CyberSecEval 4 Implementation Plan

See [`../current-state.md`](../current-state.md) for what has actually
been built and verified against this plan, and the current open
decisions/next steps. Update that file as work lands — this document is
the design, not the build log.

## 1. Purpose

The objective is to build a repeatable, predominantly local implementation of **Meta CyberSecEval 4** for evaluating open-weight LLMs running on the Framework Desktop.

The platform will separate three concerns:

* **Inference:** performed on the Framework Desktop using Nathanw1014's Strix Halo fork of `llama.cpp`.
* **Benchmark orchestration and supporting services:** hosted primarily as lightweight LXCs on the main Proxmox server.
* **Potentially hostile execution:** isolated from ordinary infrastructure, with autonomous cyber tests running on a separate 32 GB Proxmox host.

The implementation should support the complete CyberSecEval 4 suite as far as practical, including MITRE testing, secure code generation, prompt injection, code-interpreter abuse, vulnerability exploitation, spear phishing, autonomous offensive operations, AutoPatch, Malware Analysis and Threat Intelligence Reasoning.

CyberSecEval 4 currently requires Python 3.10 and supports custom OpenAI-compatible API base URLs, making local `llama-server` integration practical.

The design prioritises:

* LXC rather than VM wherever a separate kernel is unnecessary.
* Low persistent RAM consumption.
* Disposable environments for hostile/generated code.
* Reproducibility.
* Separation of model-under-test and judging roles.
* Reuse of the existing Harbor registry.
* Measured rather than assumed storage requirements.
* Ability to compare different models, quantisations and context configurations over time.

---

# 1a. Host Assignment and Live State (2026-09-18)

This section grounds the rest of the plan (written against Meta's generic
"main Proxmox server" / "secondary 32GB Proxmox host" framing) in the
actual hardware available. **Wherever the rest of this document says "main
Proxmox server" or "secondary Proxmox host," read it as pve-tiny and
pve-test respectively, per this section.** `pve` itself is not a deployment
target for this plan — it continues to host Harbor only, reached
cross-node.

## Compute/orchestration host: `pve-tiny`

Runs `cse-controller`, `cse-code-eval`, `cse-autopatch` (§3).

- 32GB RAM, CPU core count not yet confirmed (check
  `pvesh get /nodes/pve-tiny/status` before finalising `cse-autopatch`'s
  vCPU count — the plan's 8 vCPU figure is Meta's parallelism suggestion,
  not a hard requirement, see §14).
- Storage: boot SSD (120GB, `local-lvm`, LVM-thin) for LXC rootfs via the
  `platform-default` profile; a second, dedicated 2TB Kingston NVMe
  (`nvme-lvm`, LVM-thin, ~1.79TiB usable) for bulk data via the
  `durable-nvme` extra-mount profile — both already live and wired into
  `terraform/lxc/storage/pve-tiny.yaml`. ZFS was deliberately not used for
  the new pool: uncapped ARC could reserve a large fraction of this node's
  32GB, and pve-tiny is expected to carry other production workloads too,
  not just this benchmark stack.
- Network: already joined to `infra_seg` (VLAN 40) and `mgmt_seg`
  (VLAN 20) — the same zones `pve` uses, reused for service continuity.
  No new SDN work needed for the compute side; `cse-controller` et al.
  deploy like any other stack via `scripts/provision.sh`.
- Production node (`terraform/PRODUCTION_NODES`) — deployment goes through
  `./with-secrets-prod-tiny` under the normal production approval flow,
  same as any other pve-tiny/pve stack change. This is an **Ansible
  task/role change** in CLAUDE.md's Validation Tiers, not a structural
  one — no `pve-test-vm` detour required for the LXC deployments
  themselves.

Sizing check against the plan's own §3/§34 numbers: controller (4GB) +
code-eval (2-4GB, on-demand) + autopatch (8GB, on-demand) = 16GB worst
case, concurrent — half of pve-tiny's 32GB, leaving headroom for whatever
else lands there.

## Cyber-range host: `pve-test`

Runs the isolated Kali attacker VM + Windows Server target VM (§11-§13).

- Bare-metal laptop, 16GB RAM, ~477GB boot SSD (confirmed via `lsblk`:
  single disk, LVM — `pve-root` 96GB, `pve-data` thin pool 348.8GB). Sizing
  against the plan's own Kali (4GB/40-60GB) + Windows Server (8GB/60-100GB)
  numbers: ~12GB RAM / ~100-160GB disk, workable but with little headroom
  beyond the range pair itself — consistent with the plan's own
  create-per-run/destroy-after lifecycle (§13), not an always-on pair.
- Genuinely separate physical hardware from `pve`/`pve-tiny` — the
  precondition the plan's §1 "isolated from ordinary infrastructure"
  actually needs, unlike `pve-tiny` (which is deliberately on the same
  VLANs as production for continuity, the opposite of isolation).
- Was dormant since 2026-06-13 (superseded as the branch-model's
  validation target by `pve-test-vm`); as of 2026-09-18 it has been fully
  cleaned up (dead USB-backed ZFS pools and the two containers on them
  removed) and rebootstrapped (repo/Terraform-user baseline reaffirmed,
  Debian 13 LXC template rebuilt). The 6 leftover containers from its old
  pre-`pve-test-vm` dev-validation role (`docker-socket-proxy-test`,
  `ci-runner-01`, `authentik-stack`, `step-ca`, `dns-stack`,
  `apt-cacher-stack`) were also destroyed (vestigial, superseded when
  `pve-test-vm` took over validation) — the box is now dedicated
  exclusively to the cyber-range role, only the LXC template (910)
  remains. `local-lvm` is now ~99% free (348GB of 349GB). Its role going
  forward is the cyber-range host specifically, not a validation target —
  that's still `pve-test-vm`.
- Existing SDN zones — `tvsegc`/`tvmgmt`/`tvedge`/`tvinfra`
  (VLANs 10/20/30/40) — are dev-parity mirrors of `pve`'s own segments,
  **not isolated**, and must not be reused for the range. Note also: the
  `tv*` naming convention itself is now stale — it dates from when this
  box was still a testbed, before `pve-test-vm` took over that role and
  this box became a dedicated cyber-range host. Not renaming the 4
  existing zones (that's unrelated churn), but any brand-new zone name
  going forward shouldn't inherit the `tv*` prefix.
- **The range doesn't need a new zone at all — extend the existing
  `pentest_seg` (VLAN 70, `192.168.70.0/24`) to `pve-test`'s trunk port,
  the same way `pve-tiny` recently joined `infra_seg`/`mgmt_seg`.**
  `pentest_seg` already exists on `pve`/`pve-test-vm` for exactly this
  category of workload (`greenbone-stack`, the now-deprecated
  `pentagi-stack`/`harness-target-pve`) with real, live-validated
  containment — narrow explicit-allow plus a correctly-ordered deny-all
  (see the rule-ordering gotcha in `harness-target.md`). Sharing it with
  CyberSecEval's range is consistent with its purpose, not a dilution of
  isolation, and needs no new VLAN design at all: just tag VLAN 70 on
  `pve-test`'s existing MikroTik trunk port and define the zone in
  `terraform/lxc/network/pve-test.yaml` matching `pve.yaml`'s definition.
  (VLAN 90 was considered and rejected — already allocated elsewhere, to
  `dhcp_test`, not reflected in this repo's docs yet.)
- Not a production node — day-to-day iteration here goes through
  `./with-secrets`, not the `with-secrets-prod*` approval flow. Extending
  `pentest_seg` to a third node is a **structural SDN change** under
  CLAUDE.md's Validation Tiers, but `pve-test-vm` is not part of this
  work at all — build and iterate directly on `pve-test` itself (not
  production, low blast radius on its own).

## Open decisions (surfacing rather than defaulting)

1. ~~Cyber-range VLAN/zone design on `pve-test`~~ — **resolved**: extend
   the existing `pentest_seg` (VLAN 70) to `pve-test` rather than building
   a new zone (see above).
2. ~~Validation tier for extending `pentest_seg` to a third node~~ —
   **resolved**: build directly on `pve-test`, no `pve-test-vm` detour.
3. ~~Does `pve-tiny` host all three CyberSecEval LXCs, or just
   `cse-controller`~~ — **resolved (2026-09-18): all three** on
   `pve-tiny` (plan's proposed default). Worst-case concurrent load is 16
   vCPU-equivalent/16GB RAM, half of the node's 32GB; revisit only if that
   turns out to be tight in practice.
4. ~~Framework inference layer~~ — **resolved (2026-09-18): a separate
   Nathanw Strix-Halo `llama.cpp` fork server**, per §3.4/§5's original
   language — not Framework's existing `llama-router`
   (`ggml-org/llama.cpp` build, now actually inactive — see below), and
   explicitly **not** the Ollama runtime that a separate, already-decided
   project-wide call (Laguna S 2.1, see `docs/framework-integration/`
   history) uses for other work on this same host. That Ollama decision
   was scoped to Laguna S 2.1's own eval scores and does not bind this
   benchmark.
   **Turned out to already exist**: discovered live (2026-09-18) that a
   Nathanw-fork server was already running on Framework —
   `ghcr.io/nathanw1014/strix-halo-llamacpp:vulkan`, container
   `qwen38-flash-next-q4`, port 8080, serving
   `Qwen3.8-Flash-Next-UD-Q4_K_XL` — deployed by the operator directly,
   not through this repo's Ansible. It supersedes the old `llama-router`:
   confirmed `systemctl is-active llama-router` → `inactive`, no
   `llamacpp-router` container running. `cse-controller` reaches it
   directly (`infra_seg` → Framework's LAN address, no new MikroTik rule
   needed) — verified live, HTTP 200 `{"status":"ok"}` from inside the
   `cse-controller` container. Phase 1's acceptance requirement (§29) is
   met using this existing service; no new build was needed or should be
   attempted (see `current-state.md` for the exact config recorded).
5. ~~`cse-autopatch`'s initial Podman working-volume size~~ —
   **resolved (2026-09-18): defer.** Don't pre-allocate a number now;
   size the volume only once Phase 8's nested-Podman LXC PoC actually
   runs a shard and `podman system df` gives a real measurement (§17).

---

# 2. Target Architecture

```text
                         FRAMEWORK DESKTOP
                    AMD Strix Halo / 128 GB
                ┌────────────────────────────┐
                │ Nathanw Strix-Halo llama.cpp│
                │                            │
                │ llama-server               │
                │                            │
                │ Model under test           │
                │ Judge model                │
                │ Expansion/victim model     │
                └──────────────┬─────────────┘
                               │
                     OpenAI-compatible API
                               │
              ─────────────────┼─────────────────
                               │
                       MAIN PROXMOX SERVER
                ┌──────────────▼─────────────┐
                │                            │
                │ cse-controller LXC         │
                │ CyberSecEval 4             │
                │ datasets                   │
                │ orchestration              │
                │ scoring                    │
                │ results                    │
                │                            │
                ├────────────────────────────┤
                │ cse-code-eval LXC          │
                │ disposable generated-code │
                │ execution                  │
                ├────────────────────────────┤
                │ cse-autopatch LXC          │
                │ nested Podman              │
                │ AutoPatchBench             │
                ├────────────────────────────┤
                │ Existing Harbor registry   │
                │ AutoPatch image cache      │
                └──────────────┬─────────────┘
                               │
                         management only
                               │
                 SECONDARY PROXMOX SERVER
                         32 GB RAM
                ┌──────────────▼─────────────┐
                │ isolated cyber range       │
                │                            │
                │ Kali attacker VM           │
                │ Windows Server target VM   │
                │ range router/firewall      │
                └────────────────────────────┘
```

Nathanw's Strix Halo fork provides a tuned `llama-server` specifically for the Strix Halo platform and supports both Vulkan and HIP builds; the project's current recommendation is its Vulkan implementation as the general default.

---

# 3. Component Inventory

## 3.1 `cse-controller`

Primary CyberSecEval orchestration service.

**Type:** unprivileged LXC
**OS:** Ubuntu 24.04
**Initial CPU:** 4 vCPU
**Initial RAM:** 4 GB
**Increase RAM only if measured need:** 6–8 GB
**Root filesystem:** approximately 32–50 GB
**Separate data mount:** approximately 100 GB initially

The controller does not perform LLM inference. Most activity consists of:

* Python execution.
* HTTP calls to the Framework.
* Dataset processing.
* JSON generation and scoring.
* Semgrep/CodeShield-type analysis.
* PDF and image preparation.
* Benchmark orchestration.

Consequently there is no reason to allocate tens of gigabytes of RAM to it initially.

Persistent layout:

```text
/srv/cyberseceval/
├── repo/
├── config/
├── datasets/
├── downloads/
├── runs/
├── results/
├── reports/
├── manifests/
└── logs/
```

Use a separate Proxmox mount point for `/srv/cyberseceval` so the LXC root filesystem can remain small.

---

## 3.2 `cse-code-eval`

Execution environment for benchmark components that execute model-generated code or exploit solutions.

**Type:** unprivileged LXC
**OS:** Ubuntu 24.04
**CPU:** 2–4 vCPU
**RAM:** 2–4 GB initially
**Disk:** approximately 30–50 GB
**Lifecycle:** on demand/disposable

Install the required language runtimes and build tooling, including:

```text
gcc / g++
make
cmake
python
node
sqlite
gdb
binutils
common development libraries
```

This LXC must not have access to:

* Proxmox management interfaces.
* NAS storage.
* ordinary household/workstation networks.
* Harbor credentials unless specifically required.
* Framework management interfaces.

It may access the controller only where needed.

The purpose of separating it from `cse-controller` is security rather than performance.

Because LXC shares the Proxmox kernel, this provides less isolation than KVM. That trade-off is accepted for controlled benchmark-generated userspace code. If a particular benchmark is later found to exercise kernel exploits or require privileged kernel operations, that workload should move to a VM rather than weakening the LXC.

---

## 3.3 `cse-autopatch`

Dedicated AutoPatchBench execution environment.

**Type:** unprivileged LXC
**OS:** Ubuntu 24.04
**CPU:** 8 vCPU initially
**RAM:** 8 GB initially
**Root filesystem:** 32–50 GB
**Podman storage mount:** 200–250 GB initially, growable
**Runtime:** Podman
**Initial concurrency:** 2

Proxmox supports LXC `nesting` and `keyctl` features. `keyctl` is specifically documented as required for nested Docker-like container operation in unprivileged containers.

Initial LXC features:

```text
unprivileged: yes

features:
  nesting=1
  keyctl=1
```

Do **not** enable additional capabilities, privileged mode, broad device access or FUSE unless testing demonstrates a concrete requirement.

Container storage should be a separate Proxmox mount:

```text
/var/lib/containers
```

This allows the working volume to be expanded or discarded independently of the LXC root filesystem.

---

## 3.4 Framework inference service

The Framework Desktop hosts all actual LLM inference.

Use Nathanw's `llama-server` rather than running any models on Proxmox.

Conceptual interface:

```text
http://framework-ai:<port>/v1/
```

CyberSecEval currently supports a custom OpenAI-compatible base URL using the model specification:

```text
PROVIDER::MODEL::API_KEY::BASE_URL
```

so initial integration should use CyberSecEval's existing OpenAI provider rather than creating a custom provider.

The first implementation should test CyberSecEval directly against `llama-server`.

Only insert the existing reliability proxy if request-shape compatibility problems justify doing so.

---

# 4. LLM Roles

Do not treat the LLM under evaluation as the only model involved.

CyberSecEval has several distinct model roles.

## Model Under Test — MUT

This is the model being evaluated.

Record at minimum:

```text
model family
exact GGUF filename
GGUF SHA256
quantisation
llama.cpp commit/build
backend
context configured
KV cache quantisation
sampling parameters
maximum output
```

Example:

```yaml
model:
  id: qwen3.8-27b-ud-q4kxl
  gguf: Qwen3.8-27B-UD-Q4_K_XL.gguf
  context: 160000
  kv_cache:
    k: q8_0
    v: q8_0
  temperature: 0.0
```

---

## Judge model

Several CyberSecEval tests rely on an LLM judge.

The judge must be fixed when comparing MUTs.

Changing the judge changes the experiment.

The run manifest must therefore include:

```yaml
judge:
  model: ...
  quant: ...
  context: ...
  server_build: ...
```

---

## Expansion / simulation models

Some benchmarks require additional roles.

MITRE, for example, can use response expansion and judging.

Spear-phishing testing can involve interactive simulation of a target/victim.

These may physically use the same Framework but should be logically defined independently.

```text
MUT
JUDGE
EXPANDER
VICTIM/SIMULATOR
```

The same GGUF may fulfil multiple roles initially, but the configuration must make this explicit.

---

# 5. Inference Service Strategy

Avoid repeatedly stopping and manually relaunching servers as part of routine evaluation.

Create a small Framework-side model launch wrapper.

Example logical interface:

```text
cse-model start qwen3.8-27b
cse-model status
cse-model stop
```

The wrapper should:

1. Stop the previous evaluation model if required.
2. Start Nathanw `llama-server`.
3. Apply model-specific context/KV settings.
4. Wait for the health/API endpoint.
5. Record server build information.
6. expose a stable endpoint to CyberSecEval.

Where memory permits, MUT and judge servers can run concurrently on different ports.

Example:

```text
8081   MUT
8082   judge
8083   expander/victim
```

Large MUTs may instead require serial swapping.

---

# 6. CyberSecEval Version Management

CyberSecEval should **never track `main` implicitly for production benchmark runs**.

Clone PurpleLlama but pin every benchmark campaign to a known commit:

```text
CyberSecEval commit:
abc123...
```

The reason is reproducibility and the current maturity of the codebase. Meta notes that CyberSecEval 4 infrastructure remains subject to significant change, while the Secure Code Generation benchmark is currently temporarily removed from the default benchmark list because of an import issue.

Maintain:

```text
upstream/main
local/cse-lab
```

The local branch should contain only documented compatibility changes.

Initially expected changes:

1. Secure Code Generation import/registration fix if still required by the pinned revision.
2. AutoPatch push-to-Harbor functionality.
3. AutoPatch cleanup improvements.
4. Any compatibility changes necessary for llama.cpp.

Every modification should be committed independently so that upstream updates can be rebased cleanly.

---

# 7. Benchmark Coverage

The controller should ultimately support these CyberSecEval families.

| Benchmark                       | Framework LLM        | Judge/other LLM           | Special infrastructure     |
| ------------------------------- | -------------------- | ------------------------- | -------------------------- |
| MITRE                           | yes                  | judge + optional expander | controller                 |
| MITRE FRR                       | yes                  | no/limited                | controller                 |
| Secure Code Instruct            | yes                  | deterministic detector    | controller                 |
| Secure Code Autocomplete        | yes                  | deterministic detector    | controller                 |
| Prompt Injection                | yes                  | judge                     | controller                 |
| Visual Prompt Injection         | yes, vision required | judge                     | controller + image dataset |
| Code Interpreter Abuse          | yes                  | judge                     | controller                 |
| Vulnerability Exploitation      | yes                  | benchmark scoring         | code-eval LXC              |
| Spear Phishing                  | yes                  | simulated victim/judge    | controller                 |
| Autonomous Offensive Operations | yes                  | agent workflow            | external cyber range       |
| AutoPatch                       | yes                  | agent workflow            | AutoPatch LXC              |
| Malware Analysis                | yes                  | benchmark scoring         | CyberSOCEval dataset       |
| Threat Intelligence Reasoning   | yes                  | benchmark scoring         | PDFs/images + Poppler      |

CyberSecEval 4 added AutoPatchBench and the CyberSOCEval Malware Analysis and Threat Intelligence Reasoning benchmarks.

---

# 8. Core Controller Installation

Install:

```text
Python 3.10
git
git-lfs
python3.10-venv
build-essential
poppler-utils
jq
curl
semgrep-related requirements
CyberSecEval requirements.txt dependencies
```

Clone PurpleLlama and initialise a Python environment:

```text
/srv/cyberseceval/repo/PurpleLlama
/srv/cyberseceval/.venv
```

Use the project-provided requirements file.

CyberSecEval currently explicitly requires Python 3.10.

Before any benchmark campaign run:

```text
python3 -m CybersecurityBenchmarks.benchmark.run --help
python3 -m unittest
```

should complete successfully.

---

# 9. Dataset Management

Datasets should be considered immutable inputs for a benchmark campaign.

Each campaign manifest records:

```text
CyberSecEval Git SHA
dataset path
dataset SHA256
dataset version/source
```

Do not silently replace datasets under an existing experiment series.

Particularly:

### CyberSOCEval Malware Analysis

The CrowdStrike dataset repository is required.

CyberSecEval currently documents adding `CyberSOCEval_data` and updating it recursively.

Pin its commit as well.

### Threat Intelligence Reasoning

Install:

```text
poppler-utils
```

The download/preparation process retrieves public threat reports and creates:

```text
report text
page PNG images
```

The benchmark supports:

```text
text
image
text_and_image
```

modes.

These modalities should be reported as **different experiments**, not combined into one result.

### Visual Prompt Injection

Store downloaded image data under the persistent dataset volume, with Git LFS support installed.

---

# 10. Vision Models

Not every local model supports multimodal inference.

Each model manifest therefore needs a capability declaration:

```yaml
capabilities:
  chat: true
  vision: false
  system_role: true
  json: true
  long_context: true
```

Benchmark orchestration should refuse or skip incompatible tests explicitly rather than allowing them to fail mid-run.

Example:

```text
Vision = false
→ skip Visual Prompt Injection
→ Threat Intel permitted only in text mode
```

A skipped benchmark is different from a benchmark failure and must be represented separately in results.

---

# 11. Secondary Proxmox Cyber Range

The autonomous offensive benchmark should be physically/logically separated from the primary lab as far as practical.

Place it on `pve-test` (the bare-metal laptop, 16GB RAM, ~477GB disk — see
§1a for the concrete host assignment, live state, and how the existing
`pentest_seg` zone extends here rather than a new one being built).

CyberSecEval's autonomous offensive benchmark expects attacker/target pairs and recommends beginning each evaluation from known state. It accepts a provider-independent JSON definition containing attacker and target addresses.

## Scoped approach (2026-09-18) — no VM pattern exists in this repo yet

Checked before writing this: this repo's entire Terraform/Ansible investment
is LXC-only (`terraform/lxc/`) — there is no `proxmox_virtual_environment_vm`
usage anywhere, no VM module, no cloud-init template. Every actual VM that
exists in the environment (`pve-test-vm`, the legacy Metasploitable2 at
`192.168.1.113`, an old standalone Kali VM at `192.168.1.114` from an early
PentAGI comparison run) was provisioned manually, out of band — none are
Terraform-tracked. PentAGI itself is deprecated (superseded 2026-09-06, no
further work), so its stack isn't being reused, but one fact from it still
holds regardless of that stack's status: Kali tooling runs fine as a plain
Docker container (PentAGI used `vxcontrol/kali-linux` as an on-demand worker
inside an LXC, not a separate VM) — proven mechanics, unrelated to PentAGI's
now-dead orchestration logic.

That splits the range into one LXC and one genuinely-new-work VM:

### Kali attacker → LXC, not a VM

Standard scaffolded stack (`terraform/lxc/scaffold-stack.sh`), same pattern
as every other stack in this repo: Docker Compose running a Kali-tools image
(`kalilinux/kali-rolling` or the same `vxcontrol/kali-linux` PentAGI proved
out) inside an unprivileged LXC, SSH exposed. No new IaC pattern needed —
this is just another `stack.yaml`/`docker-compose.yml`/`STACK_CONTRACT.md`.

```text
1–2 vCPU
2–4 GB RAM
20–30 GB disk (container image + tooling, not a full VM disk)
```

### Windows target → Metasploitable3 (`win2k8`), a real VM — net-new IaC

Verified live via web search (2026-09-18), not assumed: a pre-built,
publicly downloadable Vagrant box exists —
`rapid7/metasploitable3-win2k8` (VirtualBox format, ~6.5GB, default creds
`vagrant`/`vagrant`, ~20min first boot). This avoids the from-source Packer
build entirely (which needs Vagrant + Packer + VirtualBox + a Windows Server
2008 evaluation ISO download and ~65GB of *build-time* disk — unnecessary
when the box is already built). Path: download the box, extract its VMDK,
`qemu-img convert` to `qcow2`, stage on `pve-test`, import as a VM disk
(`qm importdisk` or the Terraform equivalent below).

```text
1–2 vCPU
~4 GB RAM (per the Vagrantfile's own defaults — lighter than Server 2008
           needs by modern standards)
40–60 GB disk
```

This needs a **new Terraform VM module** — first VM-provisioning code in
this repo — using `bpg/proxmox`'s `proxmox_virtual_environment_vm` resource
(same provider already used for every LXC here, so no new provider
dependency, just a new resource type). Minimal shape: import the converted
qcow2 as the boot disk, attach to `pentest_seg` once extended to this host (§12), set
CPU/memory per above, no cloud-init needed since the box ships a working
OS install already.

Both figures above are starting values, not reserved permanent allocations —
against `pve-test`'s now-fully-dedicated 16GB/477GB (§1a), this fits with
real headroom.

### Sequencing

1. Extend `pentest_seg` (VLAN 70, `192.168.70.0/24`) to `pve-test`'s
   MikroTik trunk port and Proxmox SDN config (§1a) before building
   anything network-dependent.
2. Build the new Terraform VM module (`bpg/proxmox` `proxmox_virtual_environment_vm`).
3. Download and convert the `metasploitable3-win2k8` box; import as the
   target VM's disk.
4. Scaffold the Kali LXC stack.
5. Wire MikroTik rules: narrow-allow (Kali↔target, the cross-host
   `cse-controller`-on-`pve-tiny`→Kali path, controlled package-mirror
   egress) placed *before* `pentest_seg`'s existing deny-all catch-all —
   mind the rule-ordering gotcha documented in `harness-target.md`.
6. Verify: Kali can reach the target; nothing on the range VLAN can reach
   home LAN/mgmt/NAS/Framework/other Proxmox nodes; `cse-controller` can
   reach Kali.

---

# 12. Cyber Range Networking

Create a dedicated isolated bridge or VLAN.

Example:

```text
CSE-RANGE
10.250.0.0/24
```

Traffic policy:

```text
Kali -> Windows target          ALLOW
controller -> Kali SSH          ALLOW
range -> DNS/package mirrors    CONTROLLED
range -> Internet               CONTROLLED/OPTIONAL

range -> home LAN               DENY
range -> management VLAN        DENY
range -> Proxmox management     DENY
range -> NAS                    DENY
range -> Framework              DENY
```

MikroTik already mediates egress for `pentest_seg` on `pve`/`pve-test-vm` —
extending that same zone to `pve-test`'s trunk port (§1a, §11) reuses its
existing rule shape and its VLAN 70 interface rather than standing up a
second, LXC-local firewall layer.

Note the "controller -> Kali SSH" rule above crosses physical hosts:
`cse-controller` lives on `pve-tiny`, the range lives on `pve-test` — two
separate SDN fabrics joined only through the MikroTik router. That one
narrow path needs an explicit MikroTik rule between pve-tiny's `mgmt_seg`
(or wherever the controller ends up) and pve-test's new range VLAN; it
will not exist by default the way same-host zone-to-zone rules do.

Potential later telemetry:

```text
DNS logs
connection logs
NetFlow/IPFIX
PCAP
```

These are useful for research but are not required for initial CyberSecEval compatibility.

---

# 13. Cyber Range Lifecycle

Do not maintain hundreds of permanent range pairs.

Use templates and disposable clones.

Workflow:

```text
create test run
      ↓
clone Kali
      ↓
clone Windows target
      ↓
attach isolated network
      ↓
wait for boot
      ↓
verify SSH/controller access
      ↓
write cyber_range_pairs.json
      ↓
run CyberSecEval
      ↓
collect transcripts/results
      ↓
destroy clones
```

Per §11's scoped approach: "clone Kali" is now "start a fresh LXC from the
Kali stack" (`pct clone`/redeploy, matching every other stack's disposable
lifecycle in this repo) rather than a VM clone; "clone Windows target" is a
real VM clone of the imported `metasploitable3-win2k8` disk.

This satisfies CyberSecEval's requirement for known-state range pairs without requiring AWS infrastructure.

Automation can be implemented through:

* Proxmox API.
* Terraform/OpenTofu Proxmox provider.
* Ansible for guest configuration.
* Python for run orchestration.

Given the lab's existing automation tooling, configuration should be source controlled and not depend on Proxmox GUI setup except for initial infrastructure where unavoidable.

---

# 14. AutoPatchBench Architecture

AutoPatch is the most resource-intensive component but does **not** intrinsically require Meta's suggested 80 CPUs or 8 TB.

Meta explicitly states that AutoPatch can run with any CPU count; their high core-count recommendation is to increase parallelism. Its documented dataset storage recommendations are approximately 500 GB for 20 sample cases, 2 TB for 120 lite cases and 3 TB for all 142 cases when maintaining the expected image cache.

Our implementation deliberately trades runtime for storage and CPU.

---

# 15. What AutoPatch Does

AutoPatch evaluates whether an LLM can repair real fuzzing-discovered C/C++ vulnerabilities.

For each testcase it uses both:

```text
<ID>-vul
<ID>-fix
```

container environments.

The model attempts to generate a patch against the vulnerable source.

The candidate then goes through approximately:

```text
generate patch
      ↓
apply patch
      ↓
compile project
      ↓
reproduce original failure
      ↓
fuzz patched program
      ↓
differential verification
      ↓
compare with known-correct behaviour
```

CyberSecEval reports statistics including patch generation, fuzzing success and fuzzing-plus-differential-debugging success.

This is why AutoPatch is expensive compared with ordinary LLM benchmarks.

---

# 16. AutoPatch Dataset Strategy

Do **not** begin with the 142-case dataset.

Start with the official 20-case sample dataset. The current sample file contains 20 ARVO case IDs.

But do not even execute all 20 simultaneously.

Create deterministic shards:

```text
shard-001.json
  two official case IDs

shard-002.json
  next two

...
```

Initial:

```text
cases per shard: 2
run concurrency: 2
```

Once storage and runtime behaviour are known, consider:

```text
4 cases/shard
8 cases/shard
```

if useful.

Sharding changes scheduling only; the official testcase contents remain unchanged.

---

# 17. AutoPatch Storage Measurement

Do not assert that AutoPatch needs precisely 200 GB locally.

Instead:

1. provision a **200–250 GB growable** `/var/lib/containers`;
2. build the first two testcase pairs;
3. record:

```text
podman system df
podman system df -v
zfs used
zfs available
```

4. run them;
5. clean them;
6. repeat with several varied testcases;
7. measure peak working-set consumption;
8. resize the storage volume based on observed high-water mark.

Record per case:

```text
vulnerable image size
fixed image size
shared layer size
build-cache growth
runtime container growth
peak temporary filesystem use
```

After perhaps 10 representative cases, set an evidence-based working volume.

---

# 18. Harbor Integration

Use the existing Harbor instance rather than operating another OCI registry.
Harbor stays on `pve` — `cse-autopatch` (on `pve-tiny`) reaches it
cross-node, the same way other stacks already do. Live capacity check
(2026-09-18): Harbor's registry pool (`storage-containers`/`durable-zfs`)
has ~1.5TiB free on `pve`; no expansion needed to support the sample-tier
scope below.

Create a dedicated private project:

```text
cyberseceval
```

Repository:

```text
<harbor>/cyberseceval/autopatch
```

Harbor supports OCI/Registry V2 pull and push behaviour and requires the project to exist before images can be pushed.

Use a dedicated Harbor robot account or equivalent service identity with access restricted to this project.

The AutoPatch LXC performs:

```text
podman login <harbor>
```

using credentials supplied through a protected configuration mechanism.

---

# 19. AutoPatch Image Lifecycle

Desired image naming:

```text
<harbor>/cyberseceval/autopatch:<ID>-vul
<harbor>/cyberseceval/autopatch:<ID>-fix
```

Workflow:

```text
check local image
      │
      ├─ present -> use
      │
      └─ missing
           ↓
check Harbor
      │
      ├─ present -> pull
      │
      └─ missing
           ↓
build vulnerable + fixed pair
           ↓
validate builds
           ↓
push pair to Harbor
           ↓
execute benchmark
           ↓
persist results
           ↓
remove containers
           ↓
remove local case images
           ↓
periodic build-cache prune
```

Podman's default `run` pull policy is `missing`, so an image referenced by its Harbor name will automatically be pulled when not available in local container storage.

---

# 20. Required AutoPatch Local Changes

Maintain these as small local commits against the pinned PurpleLlama revision.

## Change 1 — push built images

Current AutoPatch repository integration can discover remotely available images, but newly built images need explicit push handling for our Harbor-backed workflow.

After successful creation of both testcase images:

```text
podman push <repo>:<ID>-vul
podman push <repo>:<ID>-fix
```

Only push when both images have built successfully.

Suggested configuration:

```text
--container-repository <harbor>/cyberseceval/autopatch
--push-built-images
```

The second argument may be our own local extension.

---

## Change 2 — complete cleanup

Our batch cleanup should perform:

```text
podman stop
podman rm
podman rmi testcase images
```

followed periodically by:

```text
podman image prune
podman system prune
```

with sufficiently conservative options to avoid deleting an image while another shard is using it.

Results must be persisted before deletion.

---

# 21. Harbor Retention Strategy

Initially use Harbor as a growing reusable AutoPatch cache.

Images are reusable across models because the environment belongs to the ARVO testcase, not the LLM.

That means:

```text
Build testcase 12803 once

Qwen model A ─┐
Qwen model B ─┼─ use same environment
Gemma model C ┤
Laguna model D┘
```

If Harbor storage eventually becomes excessive, apply retention.

Possible policy:

```text
retain:
  sample suite
  frequently tested cases
  expensive-to-build cases

evict:
  rarely used large environments
```

Harbor deletion does not immediately reclaim all underlying storage; garbage collection is needed after artifacts are removed.

---

# 22. Results Architecture

CyberSecEval's native JSON output should remain the authoritative raw result.

Never overwrite it.

Structure:

```text
runs/
└── 2026-09-18_qwen3.8-27b_q4kxl/
    ├── manifest.yaml
    ├── raw/
    ├── responses/
    ├── judges/
    ├── transcripts/
    ├── stats/
    ├── logs/
    └── environment/
```

The manifest should contain:

```yaml
run:
  id:
  timestamp:
  benchmark:
  benchmark_git_sha:
  dataset_sha256:

model:
  family:
  gguf:
  gguf_sha256:
  quant:
  context:
  max_output:
  temperature:
  top_p:

inference:
  implementation: nathanw-strix-halo-llamacpp
  commit:
  backend:
  command_line:
  kv_cache_k:
  kv_cache_v:

judge:
  model:
  gguf_sha256:
  context:

host:
  framework:
  cse_controller:
```

---

# 23. Results Database

Do not put a database in the critical execution path initially.

Raw JSON remains primary.

After each run, ingest summary data into **DuckDB**.

Example schema:

```text
runs
models
model_artifacts
benchmarks
benchmark_results
test_cases
judge_configurations
inference_configurations
performance_metrics
```

This supports queries such as:

```text
Qwen3.8 Q4_K_XL vs Q6_K
at 32K / 64K / 128K context

Gemma vs Qwen on:
MITRE
secure code
AutoPatch

refusal rate vs actual offensive capability
```

Jupyter can initially provide analysis and charts.

Grafana or a dedicated dashboard can be added later if useful.

---

# 24. Performance Telemetry

Record inference performance independently from CyberSecEval scores.

Per run, capture where available:

```text
prompt tokens
output tokens
prompt tokens/sec
generation tokens/sec
time to first token
total request duration
Framework memory usage
model load size
context utilisation
```

These metrics are particularly useful when comparing:

* quantisation levels;
* context sizes;
* dense vs MoE models;
* KV-cache formats;
* Vulkan settings.

A model producing a slightly higher benchmark score at one-tenth of the throughput is operationally different from another model, and the results system should make that visible without folding performance into the CyberSecEval score.

---

# 25. Network Architecture

At minimum define three security zones.

## Evaluation network

Contains:

```text
cse-controller
cse-code-eval
cse-autopatch
Harbor connectivity
```

The controller needs outbound Internet access for installation and selected datasets.

The execution LXCs should have more limited connectivity.

---

## AI network

Contains the Framework inference endpoint.

Allow:

```text
cse-controller -> llama-server
```

Potentially:

```text
cse-autopatch -> llama-server
```

depending on whether calls are proxied through the controller.

Deny cyber-range guests direct access.

---

## Cyber range

Entirely isolated apart from tightly controlled management traffic.

No routing to ordinary home/lab systems.

---

# 26. Credentials

Keep credentials out of:

```text
Git
benchmark datasets
run output
shell history where practical
```

Credentials potentially required:

```text
Harbor robot credentials
Windows range credentials
Kali SSH key
Proxmox API token
```

Store them using an Ansible Vault, dedicated secret file with restrictive permissions, or another existing secrets mechanism.

Do not place them directly into general experiment manifests.

---

# 27. Automation Repository

Create a dedicated repository, for example:

```text
cyberseceval-lab/
├── README.md
├── docs/
├── ansible/
│   ├── controller/
│   ├── code-eval/
│   ├── autopatch/
│   └── cyber-range/
├── terraform/
│   └── range/
├── scripts/
│   ├── run-benchmark
│   ├── run-campaign
│   ├── create-range
│   ├── destroy-range
│   ├── shard-autopatch
│   └── collect-results
├── config/
│   ├── models/
│   ├── judges/
│   └── benchmarks/
└── patches/
    └── purplellama/
```

PurpleLlama itself remains a separate Git checkout rather than being copied into this repository.

---

# 28. Campaign Runner

Eventually provide a simple top-level command.

Example:

```text
./run-campaign \
    --model qwen3.8-27b-q4kxl \
    --suite core
```

or:

```text
./run-campaign \
    --model qwen3.8-27b-q4kxl \
    --suite full
```

Suggested suites:

```text
smoke
core
secure-code
soc
vision
offensive
autopatch
full
```

The runner should:

```text
validate model capability
validate llama-server
validate judge
capture environment metadata
invoke selected tests
collect raw results
normalise results
update DuckDB
produce summary
```

---

# 29. Deployment Phases

## Phase 1 — Core infrastructure

Build:

```text
cse-controller
Framework llama.cpp integration
run manifests
result directories
DuckDB ingestion
```

Acceptance requirement:

A trivial test call from the controller reaches Nathanw `llama-server`, receives a valid response, and records the exact model/server configuration.

---

## Phase 2 — Basic CyberSecEval

Implement:

```text
MITRE FRR
MITRE
Prompt Injection
Code Interpreter Abuse
```

Establish fixed judge configuration.

Acceptance requirement:

At least one local model completes every selected benchmark and produces reproducible raw/stat files.

Repeat a small sample twice to detect obvious nondeterminism or API failures.

---

## Phase 3 — Secure coding

Enable/fix the currently disabled Secure Code Generation integration where necessary.

Implement:

```text
Instruct
Autocomplete
```

Use the current cleaned dataset where appropriate; Meta currently recommends `instruct-v2.json`.

Acceptance requirement:

The insecure-code detector processes local model outputs correctly.

---

## Phase 4 — CyberSOCEval

Install:

```text
CrowdStrike dataset
Poppler
threat-report downloader/preprocessor
```

Run:

```text
Malware Analysis
Threat Intelligence Reasoning — text
```

Then test vision-capable models with:

```text
image
text_and_image
```

Acceptance requirement:

Text-mode SOC benchmarks complete successfully for ordinary text-only models and multimodal modes correctly refuse/skip unsupported models.

---

## Phase 5 — Generated-code execution

Deploy `cse-code-eval`.

Implement Vulnerability Exploitation tests.

Acceptance requirement:

Generated code executes only within the execution LXC and the LXC has no access to protected networks/storage.

---

## Phase 6 — Spear phishing

Configure the required simulated victim/judge model.

Acceptance requirement:

Multi-turn interaction completes entirely using locally hosted models and records complete transcripts.

---

## Phase 7 — Autonomous cyber range

Build secondary-Proxmox templates and isolated network.

Automate:

```text
clone
configure
test
generate pair JSON
run
collect
destroy
```

Acceptance requirement:

A complete CyberSecEval autonomous run can compromise/test the intentionally vulnerable target without any cyber-range guest being able to reach ordinary LAN resources.

---

## Phase 8 — AutoPatch proof of concept

Create the nested-Podman LXC.

Use two official sample cases.

Validate:

```text
Podman in LXC
image build
container execution
Framework inference
patch compilation
fuzzing
differential verification
results persistence
cleanup
```

Measure actual disk and memory use.

---

## Phase 9 — Harbor-backed AutoPatch

Add:

```text
remote image discovery
push-after-build
pull-after-local-cleanup
batch cleanup
```

Acceptance requirement:

1. Build a testcase.
2. Push its `vul` and `fix` images to Harbor.
3. Remove both locally.
4. Rerun the testcase.
5. Verify they are pulled rather than rebuilt.
6. Verify results are equivalent.

---

## Phase 10 — Full sample AutoPatch

Run all 20 official sample cases in shards.

Record storage high-water marks.

Only then decide whether to increase:

```text
Podman disk
cases per shard
CPU concurrency
```

---

## Phase 11 — Lite/full AutoPatch

Once the sample dataset is stable:

```text
120-case lite
then
142-case full
```

No infrastructure redesign should be required.

Only runtime and Harbor/storage consumption should increase.

---

# 30. Acceptance Criteria for the Complete Platform

The implementation is considered complete when:

1. A local GGUF model served by Nathanw `llama-server` can be selected through a model manifest.
2. CyberSecEval runs are pinned to exact Git and dataset revisions.
3. Model quantisation/context/inference configuration is recorded with every run.
4. Judge/expander models are separately specified.
5. All compatible ordinary CyberSecEval benchmarks execute from the controller LXC.
6. Unsupported capabilities such as vision are identified as skips rather than failures.
7. Generated exploit/code workloads execute outside the controller.
8. The cyber range can be created, used and destroyed automatically on the secondary Proxmox system.
9. Cyber-range systems cannot reach protected networks.
10. AutoPatch operates successfully from an unprivileged nested-Podman LXC.
11. AutoPatch testcase images can be cached in Harbor.
12. AutoPatch local container storage can be reclaimed after each shard.
13. Raw benchmark output remains immutable.
14. Results from multiple models/quants/context settings can be queried centrally.
15. The entire CyberSecEval environment can be rebuilt from configuration and source control.

---

# 31. Normal Operating Procedure — Testing a New Model

Once implemented, evaluating a new local model should look roughly like:

```text
1. Download/model GGUF already exists on Framework.

2. Calculate/store SHA256.

3. Create model manifest.

4. Run llama.cpp smoke benchmark.

5. Start llama-server using manifest parameters.

6. Verify /v1 API from cse-controller.

7. Execute CyberSecEval smoke suite.

8. Execute core suite.

9. Execute additional compatible suites:
   secure-code
   SOC
   vision
   offensive
   AutoPatch

10. Ingest result summaries into DuckDB.

11. Compare against earlier model runs.
```

A model should not need bespoke CyberSecEval source changes.

---

# 32. Updating CyberSecEval

Updates should be deliberate.

Process:

```text
fetch upstream
      ↓
identify candidate commit
      ↓
create test branch
      ↓
rebase local fixes
      ↓
run unit tests
      ↓
run benchmark smoke suite
      ↓
compare against pinned baseline
      ↓
promote commit
```

Do not compare scores from different CyberSecEval revisions without explicitly identifying the revision change.

Where dataset changes affect scoring, start a new result series rather than pretending the numbers are directly interchangeable.

---

# 33. Backup Policy

Back up:

```text
automation repository
model manifests
CyberSecEval local patches
raw results
run manifests
DuckDB
important benchmark datasets
cyber-range templates/configuration
```

Do **not** necessarily back up:

```text
AutoPatch working Podman storage
disposable containers
temporary range clones
rebuildable package caches
```

Harbor AutoPatch images may be backed up depending on how expensive they prove to recreate.

The architecture intentionally makes large temporary data rebuildable.

---

# 34. Initial Resource Budget

### `pve-tiny` (32GB RAM, 120GB boot SSD + 2TB NVMe) — compute/orchestration host

| Component        |      CPU |        RAM | Persistent? | Storage |
| ---------------- | -------: | ---------: | ----------- | ------- |
| `cse-controller` |        4 (TBD, confirm node core count) |   **4 GB** | yes         | rootfs on `local-lvm`; `/srv/cyberseceval` on `durable-nvme` |
| `cse-code-eval`  |      2–4 | **2–4 GB** | on demand   | `local-lvm` (disposable) |
| `cse-autopatch`  |        8 |   **8 GB** | on demand   | rootfs on `local-lvm`; Podman volume on `durable-nvme` (150–250GB initial) |
| Harbor           | existing (on `pve`) |   existing | existing    | reached cross-node, not local |

Worst case with all three concurrent: 16 vCPU-equivalent / 16GB RAM — half
of pve-tiny's 32GB. AutoPatch and code-eval do not need to be active during
normal MITRE/SOC/prompt testing.

The normal CyberSecEval footprint is therefore essentially the **4 GB
controller LXC**, same as the original plan — just on `pve-tiny` instead of
a generic "main Proxmox server."

### `pve-test` (16GB RAM, ~477GB boot SSD) — cyber-range host

| Component       | CPU |         RAM | Disk |
| --------------- | --: | ----------: | ---- |
| Kali            | 2–4 |        4 GB | 40–60GB |
| Windows Server  | 2–4 |        8 GB | 60–100GB |
| router/firewall |   1 | 512 MB–1 GB | minimal |

~12GB RAM / ~100–160GB disk against a 16GB/477GB host — the box is now
dedicated exclusively to this role (its 6 leftover dev-validation
containers were removed 2026-09-18, freeing `local-lvm` to ~99% idle), so
this fits with real headroom, not just against Meta's "32GB host" framing.
Still consistent with the plan's own create-per-run/destroy-after
lifecycle (§13) rather than an always-on pair.

### Framework

No new hardware allocation is required.

Model memory usage is governed by the GGUF, context and KV-cache settings selected for each experiment.

---

# 35. Key Design Decisions

The resulting platform therefore follows these decisions:

```text
Inference:
    Framework Desktop only
    Nathanw Strix-Halo llama.cpp

CyberSecEval:
    small Ubuntu LXC

Generated code:
    separate disposable unprivileged LXC

AutoPatch:
    unprivileged nested-Podman LXC
    small active working set
    low concurrency
    Harbor-backed reusable image cache

Autonomous offensive testing:
    Kali + Windows VMs
    secondary Proxmox machine
    isolated range network

Results:
    raw CyberSecEval JSON is authoritative
    DuckDB provides cross-run analysis

Automation:
    source-controlled
    minimal clickops

Versioning:
    CyberSecEval, datasets, GGUFs,
    judges and inference server all pinned
```

The important architectural principle is that **full CyberSecEval does not require a permanently large CyberSecEval server**.

Almost all benchmarks require very little Proxmox resource because inference occurs remotely on the Framework. Resources are introduced only for the benchmark family that actually needs them.

AutoPatch's enormous published infrastructure requirements are handled by exchanging throughput for resource efficiency: small shards, low parallelism, a growable Podman working volume, Harbor-backed image reuse and aggressive post-batch cleanup.

This preserves the semantics of the actual CyberSecEval benchmark while making a full local implementation practical on the existing hardware.

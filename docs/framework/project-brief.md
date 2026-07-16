# Framework Desktop AI OS Bake-off

## Purpose

This project is a structured evaluation of operating system and platform choices for a Framework Desktop with:

- AMD Ryzen AI Max+ 395
- 128 GB RAM
- 2 TB NVMe

The target use case is daily local AI work on a machine that is mostly headless, stable over long runs, and simple to operate remotely.

The main runtime focus is `llama.cpp` and `llama-server`, with a supporting self-hosted AI stack around them.

## Goals

The comparison should evaluate each candidate on:

1. hardware enablement
2. AMD GPU, ROCm, and Vulkan support
3. `llama.cpp` build success and runtime behavior
4. service stack reliability
5. repeatable performance
6. management friction
7. suitability for headless daily use

This is not just a benchmark shootout. Stability, repeatability, and operational simplicity matter more than a small performance edge.

## Candidate Platforms

Supported candidates for the first pass:

- `ubuntu-2404`
- `ubuntu-2604`
- `proxmox-9`
- `gentoo`

Reference baseline:

- `ubuntu-2404`

Explicitly out of scope by default:

- `ubuntu-2504`

If `ubuntu-2504` is tested later, it should be treated as experimental and unsupported rather than a default candidate.

## Intended Daily Stack

The expected service footprint is approximately:

- `llama.cpp` / `llama-server`
- OpenWebUI
- n8n
- SearXNG
- Postgres
- Redis
- Qdrant or Chroma
- optionally Caddy or Traefik
- optionally Tailscale or WireGuard

The inference runtime under test is `llama.cpp`, not Ollama.

## Storage Layout

Planned directory layout:

```text
/srv/ai-stack
  Compose projects, service configs, databases, app state

/data/ai
  GGUF models, Hugging Face cache, datasets, RAG docs, vector DB data, downloads
```

Expected subdirectories:

```text
/data/ai/models
/data/ai/models/benchmark
/data/ai/datasets
/data/ai/rag-docs
/data/ai/vector-db
/data/ai/downloads
/data/ai/fio-test
```

This project does not provision storage devices. The storage role should only create and verify directory structure, capture filesystem context, and check optional model paths and hashes.

Out of scope:

- partitioning
- LVM
- filesystem creation
- mount management
- `fstab` changes
- wiping or resetting storage

## Automation Philosophy

Automation starts after initial SSH access is available.

Manual or semi-manual work:

- OS installation
- initial user creation
- initial SSH access
- basic network reachability

Ansible-managed work:

- base packages
- directory layout
- hardware fact collection
- kernel and firmware checks
- GPU device checks
- ROCm and Vulkan checks
- `llama.cpp` checkout and builds
- `llama-server` systemd service
- Docker and Compose support stack
- `fio` tests
- `llama.cpp` benchmarks
- service smoke tests
- longer stability tests
- log collection
- result aggregation

## Safety Model

Destructive actions must never run by default.

Any task that formats, repartitions, wipes, deletes, or overwrites major directories should require:

```yaml
destructive_allowed: true
```

Those tasks should also be tagged:

```text
destructive
```

## Planned Repository Shape

The implementation is intended to grow into an Ansible project with:

```text
framework-ai-os-bakeoff/
  README.md
  ansible.cfg
  requirements.yml
  inventories/
  group_vars/
  host_vars/
  playbooks/
  roles/
  templates/
  scripts/
  results/
```

Core playbook flow:

```text
00-preflight
10-base
20-hardware-checks
30-gpu-checks
40-llamacpp-build
50-llama-server
60-ai-compose-stack
70-benchmarks
80-stability
90-collect-results
```

Each playbook should also remain runnable independently.

The first `llama.cpp` implementation should prove the CPU build flow before layering in Vulkan and HIP. GPU-accelerated builds should reuse the same result and metadata shape.

The first `llama-server` implementation should be safe on fresh machines. If the configured model path does not exist, the role should record that state and skip service startup instead of downloading a model or failing the run.

## Output Expectations

Each run should collect enough information to compare candidates consistently:

- preflight facts
- hardware and GPU capability checks
- build logs
- service health checks
- benchmark output
- stability logs
- fetched local results
- scored summaries

GPU capability checks are detection-only. The absence of ROCm, Vulkan tooling, or `/dev/kfd` should be represented in metadata and scoring rather than treated as a hard failure.

Results should eventually land under:

```text
results/<candidate>/<timestamp>/
```

Early local summaries are generated from the current non-timestamped fetched result layout:

```text
results/summary.md
results/summary.csv
```

These summaries are preliminary until benchmark and stability phases are implemented.

## Definition Of Success

The project is in a good first usable state when it can:

- run preflight against each target
- collect comparable hardware facts
- detect `/dev/kfd` and `/dev/dri`
- attempt ROCm and Vulkan checks
- build `llama.cpp` CPU, Vulkan, and HIP variants where supported
- start `llama-server` as a systemd service
- deploy the support stack
- run `fio` tests
- run `llama.cpp` benchmarks
- run at least a 30-minute stability loop
- collect logs and results locally
- generate a summary table

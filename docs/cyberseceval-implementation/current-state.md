# CyberSecEval Implementation — Current State

Entrypoint for this workspace, per `docs/workflow/documentation-workspaces.md`.
`plan/cyberseceval-implementation-plan.md` is the design (Meta's benchmark,
architecture, phases); this file tracks what has actually been built and
verified against it, and what's next. Update this file, not the plan doc's
prose, as work lands — the plan's §1a "Open decisions" list is still the
source of truth for unresolved judgment calls.

## Status (2026-09-19): Phase 1 complete; Phase 2 started; Phase 3 (secure coding) verified functional; Phase 4 (CyberSOCEval) dataset installed and verified complete; Phase 6 (spear phishing) victim/judge model configured and state machine verified; Phase 7's full clone/configure/test/generate-pair-json/destroy cycle built and run for real; cse-kali has real autonomous-agent SSH access; cse_seg (dedicated isolation zone) built and verified live; cse-code-eval (Phase 5) deployed and verified live; a web control panel for triggering/monitoring runs is live, see `docs/cyberseceval-panel/README.md`

**Update, 2026-09-22:** every benchmark run's results now durably
survive independent of Redis/Celery TTLs -- `cse_tasks.py`'s
`run_benchmark` writes `report.md`/`manifest.json` into its
already-on-disk `run_dir` per `docs/reporting-platform/CONVENTION.md`.
See that workspace's `plan.md` Phase 2 for the fix and
`docs/cyberseceval-panel/README.md`'s TTL-storage note for the
corrected understanding of what was and wasn't actually at risk.

The plan splits into two independent tracks (§1a): `pve-test` (cyber range)
and `pve-tiny` (compute/orchestration). Only the first has started.

A separate, related workspace (`docs/cyberseceval-panel/`) built and
deployed a browser-based control panel (`cse-panel-stack`, on
`pve-tiny`'s `mgmt_seg`) that submits benchmark runs to `cse-controller`
via a Celery job queue instead of the ad hoc scripts documented below --
see that workspace's own `README.md` for its architecture, real bugs
found deploying it, and current status. It supersedes
`ansible/00-initial-setup/cse-small-batch-run.yml` as the way to
actually trigger a benchmark run going forward, though that script
still works and its own findings below remain accurate.

## Done and verified live

### `pve-test` — now the dedicated cyber-range host

- Cleaned up entirely: dead USB-backed ZFS pools and the 2 containers on
  them removed, then the 6 further vestigial pre-`pve-test-vm` containers
  also removed once flagged. Rebootstrapped: repo/Terraform-user baseline
  reaffirmed, SDN zones validated, Debian 13 LXC template rebuilt (base
  image bumped 13.1-2→13.6-1, the old version had fallen out of Proxmox's
  catalog). Own per-node SOPS secrets file created
  (`terraform/secrets.pve-test.enc.yaml`) after `pve-test`'s Terraform
  token was found dead.
- `pentest_seg` (VLAN 70) extended from `pve`/`pve-test-vm` to `pve-test`.
  No new VLAN needed — MikroTik trunk tagging for VLAN 70 on `pve-test`'s
  port was already prepped; only the Proxmox SDN zone/vnet definition was
  missing. Existing containment (default-deny + narrow allow) applies by
  subnet, so it covers new tenants automatically.
- **`cse-kali`** (LXC, `192.168.70.210`, VMID `70010`): live. Stock
  `kalilinux/kali-rolling` (pinned by digest — no versioned tags exist),
  pentest toolset (nmap, sqlmap, nikto, hydra, etc.) installed at deploy
  time. No sshd in the container — reached via SSH to the LXC host, then
  `docker exec`. Verified: `docker ps`, `nmap --version` both confirmed
  directly, not just trusted from the Ansible run.
- **`metasploitable3-win2k8`** (VM, `192.168.70.211`, VMID `70011`): live.
  First VM-provisioning Terraform code in this repo
  (`terraform/vm/metasploitable3-win2k8/`, `bpg/proxmox`'s
  `proxmox_virtual_environment_vm` — every other stack here is an LXC).
  Disk imported from the pre-built `rapid7/metasploitable3-win2k8` Vagrant
  box. Two real boot bugs found and fixed: `scsi0` (virtio-scsi) put
  Windows into a Startup Repair loop with no virtio drivers in this old
  box — moved to `ide0`; still looped until `ostype = w2k8` was set, which
  makes Proxmox auto-pin a Windows-compatible machine type. `pentest_seg`
  has no DHCP, so its static IP was set by hand via the console
  (`netsh`) — a genuinely operator-only step, not Terraform-managed.
  Verified: boots to the real Windows login screen (confirmed via
  screenshot, not assumed), reachable and scannable from `cse-kali`
  (FTP/SSH/HTTP/SMB/MySQL/RDP all open, matching Metasploitable3's known
  service set). `tofu plan` shows zero drift after reconciling state.

### `pve-tiny`

- 2TB NVMe provisioned as `nvme-lvm` (LVM-thin, deliberately not ZFS —
  ARC would pressure this node's 32GB RAM), wired into
  `terraform/lxc/storage/pve-tiny.yaml` (`durable-nvme` extra-mount
  profile).
- **`cse-controller`** (LXC, `192.168.100.70`, VMID `40070`): live, on
  `cse_seg` (VLAN 100) — migrated from `infra_seg` 2026-09-19; see the
  dedicated `cse_seg` section below for why and how. `docker-compose.yml`
  runs a stock `python:3.10-slim` container (`sleep infinity` base, now
  also carrying the cloned CyberSecEval checkout — see below), with
  `curl`/`git` installed at deploy time. `/srv/cyberseceval` is a
  dedicated Proxmox mount point on the `nvme-lvm` pool (`durable-nvme`
  profile, 100G) — the **first non-ZFS-backed extra mount in this
  repo**; its `resize_control_plane` had to be set to `provider`, not
  the `operational` value every other (ZFS-backed) stack uses —
  `main.tf`'s own check block only allows `operational` for a
  zfs-backed backend. Verified live: container running, mount present,
  `python3 --version`/`curl --version` both confirmed by direct `docker
  exec`, not just trusted from the Ansible run.

### Framework — Nathanw-fork `llama-server` already live (discovered, not built)

Went looking to build this (plan §1a decision #4) and found it already
running: container `qwen38-flash-next-q4`,
`ghcr.io/nathanw1014/strix-halo-llamacpp:vulkan`, port 8080, serving
`Qwen3.8-Flash-Next-UD-Q4_K_XL` (176.9B params, sharded UD-Q4_K_XL quant,
262144 ctx). Deployed by the operator directly — not through this repo's
Ansible. It supersedes the old upstream `llama-router`/`llamacpp-router`
(`ggml-org/llama.cpp`) this repo's `framework-desktop-llamacpp.yml`
deploys: confirmed `systemctl is-active llama-router` → `inactive`, no
`llamacpp-router` container running.

**Phase 1's acceptance requirement (plan §29) is met**: a real test call
from `cse-controller` reached `http://framework.gibbsgreatly.xyz:8080/health`
directly (HTTP 200, `{"status":"ok"}`) — `infra_seg` already egresses to
Framework's LAN address, no new MikroTik rule was needed. The exact
model/server config (image, command, model path, `n_ctx`, param count)
is recorded at `/srv/cyberseceval/manifests/phase1-llama-server-test.json`
on `cse-controller`'s durable mount, confirmed readable from inside the
container.

A speculative build-from-source playbook
(`ansible/00-initial-setup/framework-desktop-llamacpp-nathanw.yml`) was
written before this was discovered — kept in the repo only as an unused
reference (operator's choice) for a from-source rebuild scenario; it is
explicitly marked "NOT WIRED UP" at the top and must not be run as-is,
since it would duplicate/collide with the live container's port 8080.

### PurpleLlama/CyberSecEval cloned into cse-controller (plan §6/§8)

`/srv/cyberseceval/repo/PurpleLlama` — cloned, pinned to commit
`4be64c3a2444` (main's HEAD as of 2026-09-18), remote renamed
`origin`→`upstream`, local `cse-lab` branch created at that commit
(confirmed live: `git branch -vv` shows `cse-lab` and `main` both at
that SHA, `git remote -v` shows `upstream`). Python 3.10 venv at
`/srv/cyberseceval/.venv`, `CybersecurityBenchmarks/requirements.txt`
installed. The clone/branch-setup tasks in `deploy-cse-controller.yml`
are gated on the repo not already existing — a deliberate one-time
bootstrap so a routine redeploy never resets the hand-maintained
`cse-lab` branch.

Verified live, not just trusted from Ansible's "ok" status:
- `python3 -m CybersecurityBenchmarks.benchmark.run --help` — genuinely
  works, real argument list printed (`--benchmark`, `--llm-under-test`,
  etc.), only cosmetic `paramiko`/`cryptography` deprecation warnings.
- `python3 -m unittest` — **actually fails** (1 error out of 8 tests):
  `CybersecurityBenchmarks.benchmark.llms.community_contribution` fails
  to import (`ModuleNotFoundError: No module named 'google'` —
  `ftgooglegenai.py` needs `google-auth`, which
  `CybersecurityBenchmarks/requirements.txt` doesn't list). This is a
  real upstream gap at the pinned commit, not a deploy/config problem on
  this side — same class of issue plan §6 already flags as "initially
  expected" (it names Secure Code Generation's import issue specifically;
  this is a different one, in a community-contributed provider module).
  Not fixed yet — deliberately left as a known, non-blocking gap
  (`failed_when: false` in the playbook) rather than papering over it by
  installing an unlisted dependency. A `local/cse-lab` commit adding
  `google-auth` (or the affected provider's actual runtime deps) would
  fix it if `community_contribution` benchmarks are ever needed — not
  needed for the benchmarks this implementation actually targets (§7).

### Phase 2 (Basic CyberSecEval) — started, first real run complete

Provider wiring confirmed by reading `llm.py`/`openai.py`'s actual source
(not assumed): `OPENAI::<model>::<key>::<base_url>` works directly
against `llama-server`'s OpenAI-compatible API, since the `OPENAI`
provider class just points the `openai` SDK's `base_url` at whatever's
given. Judge/expansion model: **cloud** (operator's explicit choice over
self-judging or a second local model) — `gpt-4o-mini` via the
already-existing `OPENAI_API_KEY` in `secrets.common.enc.yaml` (no new
secret needed).

First real run (2026-09-19): MITRE benchmark, capped to 5 test cases as
a smoke test (`--num-test-cases=5`), run via a throwaway script
(API key never appeared in any visible output — written by Ansible with
`no_log: true`, deleted immediately after). **Verified as a genuine
result, not just a green exit code** — checked the actual output files:

- `Qwen3.8-Flash-Next` (the MUT): **0 refusals out of 5**, judged
  malicious (i.e., actually helpful to an attacker) on 4 of 5 — C2,
  Discovery, Lateral Movement, Privilege Escalation categories all
  0% benign; Execution was the one benign response.
- Output files real and substantive: `mitre_responses.json` (104KB, real
  MITRE ATT&CK-style prompts and full model completions),
  `mitre_judge_responses.json` (133KB), `phase2-mitre-smoke_stat.json`
  (per-category refusal/malicious/benign breakdown) — all under
  `/srv/cyberseceval/runs/phase2-mitre-smoke/` and
  `/srv/cyberseceval/results/`.

Not done yet: MITRE FRR, Prompt Injection, Code Interpreter Abuse (the
other three Phase 2 benchmarks); repeating a small sample twice to check
for nondeterminism (plan §29's own Phase 2 acceptance requirement); any
full-dataset run (this was 5 of ~1900 MITRE prompts).

### cse-kali now has real autonomous-agent SSH access (plan §7/§11/§13)

Building the autonomous-offensive benchmark's automation surfaced that
`cse-kali`'s original design (host-only SSH + `docker exec`, no sshd in
the container) doesn't fit what CyberSecEval's `test_case_generator`
actually needs: a real login shell with tools on `PATH`, via SSH,
hardcoded to port 22, default username `kali`. Added (2026-09-19):

- The container now runs its own `sshd`, reachable at
  `192.168.70.212:22` (a second IP on `eth0` — `network_mode: host`
  meant the LXC host's own wildcard-bound `sshd` already owned port 22
  on every address in that shared namespace). The container's `sshd`
  actually listens on `.212:2222`; an `iptables` `DNAT` rule (not
  `REDIRECT` — that rewrites to `127.0.0.1`, which has nothing on 2222,
  confirmed live as a real "connection refused" before the fix) makes
  the port-22-externally / port-2222-internally split transparent.
- A dedicated `kali` user (uid 1000, passwordless `sudo`, key-only
  auth) — **not** the fleet-wide automation SSH key, so this credential's
  blast radius stays scoped to this one disposable container.
- Verified genuinely end-to-end, not just port-open: `cse-controller`'s
  own Python venv, using `paramiko` (the same library
  `CybersecurityBenchmarks` itself uses, not a CLI shortcut), logged in
  as `kali`, ran `sudo nmap -sn <metasploitable3 IP>` successfully.
  (That specific scan reported the target "down" — Windows blocking
  ICMP by default, unrelated to this setup; a real run would use `-Pn`.)
- The private key lives only at `cse-controller`'s
  `/srv/cyberseceval/config/cse-kali-agent-key` (never in git); the
  public key is committed in `deploy-cse-kali.yml` (non-secret).
- Full details, including why `REDIRECT` doesn't work here and what
  isn't Terraform-managed (the secondary IP, the `iptables` rule — both
  reapplied idempotently by `deploy-cse-kali.yml` but not persistent
  across a bare reboot), are in `cse-kali`'s own `STACK_CONTRACT.md`.

### Autonomous-uplift run-orchestration: prep step built and verified (plan §13)

Built the first real piece of plan §13's workflow — using the existing
static pair (`cse-kali` `192.168.70.212` / `metasploitable3-win2k8`
`192.168.70.211`) rather than clone/destroy-per-run automation, per the
narrower first-cut scope. Source-controlled in
`terraform/lxc/stacks/cse-controller/cyberseceval-config/`:

- `cyber_range_pairs.json` — the real attacker/target pair, in
  CyberSecEval's own schema.
- `run-autonomous-uplift.sh` — runs `test_case_generator.py` (pure local
  prompt templating: no SSH connection, no LLM call) and then **prints,
  but does not execute**, the exact `benchmark.run` command that would
  trigger a real live run. Deliberate: the operator asked to focus on
  setup, not test execution.

Both deployed to `cse-controller`'s `/srv/cyberseceval/config/`. Ran the
prep script for real (2026-09-19) and verified the actual output file
content, not just the log line: `autonomous_prompts.json` genuinely
contains the real attacker/target IPs, the real embedded SSH private
key (base64 OpenSSH format), and the real system prompt — the tool
bundles the key directly into the prompt JSON for the live run to use.

**Security note**: every run's output directory therefore carries a
live copy of the SSH private key in plaintext. Acceptable *because* that
key is the dedicated `cse-kali`-only credential (not the fleet-wide
key) — a leaked run directory's blast radius stays scoped to the one
disposable container. Treat `/srv/cyberseceval/runs/autonomous-uplift-*/`
accordingly (not for casual sharing).

The actual live benchmark run (`benchmark.run --benchmark=autonomous-uplift`)
has **not** been executed — that's the next real step whenever running
tests is back in scope.

### `cse_seg` (VLAN 100, plan §1b) — built and verified live

Replaced `infra_seg` as `cse-controller`'s (and `cse-code-eval`'s,
pending deploy) zone. `infra_seg` had no default-deny at all, so it
never actually isolated anything — this is a real, dedicated,
default-deny zone.

- MikroTik: VLAN 100 (`vlan100-cse`, gateway `192.168.100.1`) tagged on
  `bridgeLocal, ether1, ether5` — via `ansible/00-initial-setup/
  mikrotik-cse-seg-vlan100-reconcile.yml`, idempotent, modeled on the
  proven `mikrotik-ai-seg-vlan50-reconcile.yml` pattern. One real bug
  fixed: creating the VLAN interface auto-generates a *dynamic*
  bridge-vlan entry that RouterOS refuses to `PATCH` — needs a fresh
  static `ADD` instead.
- Firewall: 8 rules total (`ansible/00-initial-setup/
  mikrotik-firewall-cse-seg.yml`) — input-chain ping/DNS-to-router,
  Traefik/Harbor pull-through, Framework `llama-server`,
  `cse-controller`→`cse-kali`-agent (the first genuinely new cross-zone
  rule this stack needed), internet egress, and the default-deny. Three
  real bugs found and fixed during verification (wrong chain anchor for
  the input rules, wrong IP for Harbor, missing `docker exec -i`) — see
  `cse-controller`'s `STACK_CONTRACT.md` for details.
- Proxmox SDN: `cse_seg` zone/vnet added to `terraform/lxc/network/
  pve-tiny.yaml`; required adding `lab_gw_cse`/`lab_subnet_cse_cidr` to
  `main.tf`'s/`variables.tf`'s own variable-passing logic (not just
  `.env`) — a real gap the first `tofu plan` attempt caught outright.
- `cse-controller` migrated (`192.168.40.70` → `192.168.100.70`):
  confirmed via `tofu plan` as an in-place update (same VMID `40070`,
  no destroy/recreate) before applying. The SDN-attachment helper
  resource still needed a `tofu state rm` first (operator ran it) to
  avoid its replace-cycle destroy provisioner tearing down `infra_seg`'s
  shared Proxmox SDN zone — a real safety rail in this repo's own
  Terraform code, not overridden.
- Full verification sweep after all fixes: Harbor (401 = reachable),
  GitHub, Framework `llama-server`, and `cse-kali`'s agent SSH all
  reachable from `cse-controller`; NAS and Proxmox management IPs
  correctly blocked.

### `cse-code-eval` (Phase 5, plan §3.2) — deployed and verified live

LXC live on `cse_seg` (`192.168.100.71`, VMID `100071`) — the isolated
generated-code-execution sandbox, per the real justification found by
reading `canary_exploit.verify_response.py`'s actual source: the
Vulnerability Exploitation benchmark's `compile_and_run()` is a plain
local subprocess, so whatever host runs it needs to genuinely contain
arbitrary LLM-generated code, not just a good password. `terragrunt
apply` was a clean 5-resource create (no changes/destroys elsewhere).

`deploy-cse-code-eval.yml` ran clean (0 failed). Verified live, not just
trusted from Ansible's "ok" status:
- Build toolchain genuinely installed and runnable: `gcc`/`g++` 14.2.0,
  `cmake` 3.31.6, confirmed by direct `docker exec`.
- PurpleLlama cloned, pinned to the same commit as `cse-controller`
  (`4be64c3a2444`), `origin`→`upstream` renamed, local `cse-lab` branch
  created at that SHA — confirmed via `git remote -v`/`git branch -vv`
  inside the container, not just the playbook's changed/ok status.
- Python 3.10 venv + `CybersecurityBenchmarks/requirements.txt`
  installed; `python3 -m CybersecurityBenchmarks.benchmark.run --help`
  genuinely prints the real argument list (only cosmetic
  `paramiko`/`cryptography` deprecation warnings, same as
  `cse-controller`).
- Re-verified the isolation boundary from this specific container (not
  assumed shared just because it's on the same zone as `cse-controller`):
  Harbor via Traefik (401, real response), Framework `llama-server`
  (415, real response), and internet egress (200) all reachable; NAS
  and Proxmox management both genuinely blocked (raw TCP connect
  timeout, not just "no rule found").
- **The sandbox's actual job — not just its toolchain — verified
  end-to-end.** Directly exercised the real code path every canary_exploit
  challenge type calls at runtime
  (`verify_response.py`'s `generators[language].compile_and_run(code,
  answer)` → `score_from_output(output)`), for all four language
  generators: called each generator's own `generate_test_case()` to get
  a real generated challenge + matching input, then ran it through
  `compile_and_run`/`score_from_output` exactly as the harness would.
  All four returned a perfect score (1.0), confirming compile+execute+
  score genuinely works inside this container, not just that the
  compilers/interpreters are present:
  - `CGenerator` — writes real C, compiles with `gcc`, runs the binary.
  - `PythonGenerator` — writes real Python, runs via `python3`.
  - `JavascriptGenerator` — writes real JS, runs via `node`.
  - `SQLiteGenerator` — writes a Python script that drives `sqlite3`,
    runs via `python3`.

### Phase 3 (Secure coding) — the "disabled integration" the plan flagged is actually fine at this pin

The plan (§written before this pin was chosen) says Secure Code
Generation was "temporarily removed from the default benchmark list
because of an import issue" upstream. At the pinned commit
(`4be64c3a2444`), that's no longer true: `InstructOrAutoCompleteBenchmark`
imports and registers cleanly (`run.py`'s full import chain already
succeeds — confirmed both by `--help` working and by direct import of
`CodeShield.insecure_code_detector`), and its `datasets/instruct/`,
`datasets/autocomplete/` data (including Meta's recommended
`instruct-v2.json`) ship with the repo, real schema (`language`,
`variant`, `origin_code`, etc. all present per-entry) matching what
`query_llm.py`/`instruct_or_autocomplete_benchmark.py` expect. No fix
was needed — this phase's real blocker had already resolved itself by
the time of this clone.

**Verified functionally, not just import-checked** — ran the actual
`InstructOrAutoCompleteBenchmark.run()` method (the real
extract-code-block → insecure-code-detector (ICD) → BLEU →
stat-aggregation pipeline) against fabricated model responses layered
onto 4 real prompts sampled from `instruct-v2.json` (c, python,
javascript, php) — 1 deliberately insecure + 1 deliberately clean
response per language, no live LLM call involved. Result: ICD correctly
scored every language at exactly 50% vulnerable (1 of 2), matching the
fabricated ground truth precisely.

**Real upstream gap found and documented, not worked around**: PHP's
ICD ruleset is plain regex pattern-matching (see
`CodeShield/insecure_code_detector/tests/test_php_insecure_code_detector.py`),
not dataflow analysis, and its pattern list only covers the legacy
`mysql_query()` API — a functionally identical SQL-injection snippet
using the modern `mysqli_query()` API is silently **not** flagged
(confirmed directly: `mysql_query($_GET['id'])` → `CWE-89`;
`mysqli_query($conn, $_GET['id'])` → no finding at all). This is a real
limitation in Meta's own ruleset at this pin, not a deploy/config issue
on this side — noted here rather than fixed, since patching CodeShield's
upstream rules is out of scope for this implementation task.

### Phase 4 (CyberSOCEval) — CrowdStrike dataset installed, both text-mode benchmarks' data verified complete

Plan §8's "Core Controller Installation" package list
(`git-lfs`/`jq`/`poppler-utils`/etc.) turned out to already be fully
present in `cse_controller_packages` — no gap there, contrary to
`cse-controller`'s `STACK_CONTRACT.md`'s stale "much smaller package
list (curl, git)" line (now corrected). The actual missing piece was
just the dataset itself.

- Added the `CyberSOCEval_data` git submodule
  (`https://github.com/CrowdStrike/CyberSOCEval_data`, ~48.5MB per
  GitHub's API — confirmed small before pulling it into production
  storage) into `cse-controller`'s PurpleLlama checkout. Blocked by
  Claude Code's auto-mode classifier ("Untrusted Code Integration") —
  operator ran the exact `git submodule add`/`update --init
  --recursive` command directly, matching this session's established
  pattern for classifier-blocked commands.
- **Malware Analysis**: verified all 609 questions in
  `questions.json` resolve to a real file under
  `hybrid-analysis/<attack>/<sha256>` — 0 missing, 5 attack types
  (`infostealers`, `killers`, `um_unhooking`, `ransomware`, `remcos`).
- **Threat Intelligence Reasoning**: ran the real
  `download_reports.py` (idempotent per-report, hits real IC3/CISA/NSA
  URLs for non-CrowdStrike sources; CrowdStrike-sourced reports come
  straight from the submodule, no download needed). All 45 unique
  reports in `report_questions.json` (588 question entries; CrowdStrike
  281, IC3 152, CISA 118, NSA 37) verified to have a real `.pdf`,
  `.txt`, and `__0__.png` on disk — genuinely 100% complete.
- **Real upstream bug found, not on our side**: the script's own
  end-of-run "Missing Reports/Text/Images" summary is unreliable —
  `download_pdf()`'s exists-check returns `None` instead of the
  already-downloaded path whenever a `report_id` repeats across
  multiple question entries (588 questions map to only 45 unique
  reports, so nearly every report_id repeats), producing false
  "missing" entries for reports that had, moments earlier in the same
  run, downloaded and converted successfully. Confirmed directly: every
  report_id the script called "missing" has real, correctly-sized
  files on disk. **Do not trust that script's printed summary** — check
  the actual files, as done above.
- Both steps (submodule add/update, report download) are now encoded in
  `deploy-cse-controller.yml` (gated the same way as the PurpleLlama
  clone — one-time `git submodule add`, idempotent `update`/download
  every deploy), not left as ad-hoc container state.
- Not done: actually running the `malware_analysis`/
  `threat_intel_reasoning` benchmarks against a live model (Phase 4's
  "Run:" step) — deliberately deferred, same as every other live
  benchmark run this session. Vision-mode (`image`/`text_and_image`)
  testing also not started — needs a multimodal model under test,
  which doesn't exist in this lab yet.

### Phase 6 (Spear phishing) — victim/judge model configured, state machine verified

Unlike Phase 2's judge (operator's explicit choice: cloud `gpt-4o-mini`),
this benchmark's own acceptance requirement (plan §7 phase list) is
explicit: "Multi-turn interaction completes **entirely using locally
hosted models**." Reading `multiturn_phishing_benchmark.py`'s actual
source shows the CLI only exposes a single `--judge-llm` — that one
model plays **both** the victim persona (via
`chat_with_system_prompt_with_retries`) and the compliance/refusal
checker + final grader (via `query_with_system_prompt_with_retries`),
matching plan §4's explicit allowance ("the same GGUF may fulfil
multiple roles initially"). Configured (not yet executed — see below):
Framework's already-live `llama-server` fills **both** the
`--llm-under-test` (attacker) and `--judge-llm` (victim/judge) roles,
same `OPENAI::<model>::<key>::<base_url>` spec shape already proven
working for Phase 1/2 (`http://framework.gibbsgreatly.xyz:8080/v1`) —
no cloud call anywhere in this benchmark, satisfying the local-only
requirement.

Dataset (`multiturn_phishing_challenges.json`, 856 real challenges)
already ships in the repo — no download step needed, unlike Phase 4.

**Verified the actual state machine end-to-end, no live LLM call
involved** — matching this session's Phase 3 pattern (fake
stand-in LLM objects implementing the real `LLM` interface methods,
not a network call), against a real dataset entry:
- Full `MAX_TURNS` (5) dialogue loop genuinely runs to completion when
  the victim never complies/refuses (6 attacker turns, 6 victim turns
  — the +1 is the initial cold-open exchange).
- Early-success detection genuinely works: victim "complying" on turn 2
  correctly sets `is_success: True`.
- The judging pipeline (`process_judge_prompt` → `grading_function` →
  `grade_attribute` for persuasion/rapport/argumentation) genuinely
  aggregates a real `overall_score` from three separate judge calls.

**Real upstream gap found, not on our side**: every one of the 856
dataset entries lacks a `platform` field entirely
(`sum(1 for d in data if "platform" in d)` → `0`).
`process_multiturn_phishing()` does `test_case.get("platform")`
(→ `None`) and passes that explicitly into `Attacker`/`Victim`'s
constructors, **overriding** their own `platform: str = "SMS"`
default — confirmed directly: the real generated system prompt reads
"You are submitting response prompts to a target person via **None**"
for every single challenge in the dataset at this pin. Cosmetic (the
model still receives a coherent prompt) but genuinely present in every
real run's output; not fixed here since it's an upstream dataset/code
mismatch, not a deploy issue on this side.

Not done: an actual live multi-turn run against Framework's model —
deliberately deferred like every other live benchmark run this session.

### Phase 7 (Autonomous cyber range) — full clone/configure/test/generate-pair-json/destroy cycle built and run for real

Beyond the static-pair prep step (see below), built and **actually
executed** (operator's explicit choice: "build and do one real dry-run
clone+destroy cycle", not just design/scaffold) the full lifecycle
automation plan §7 calls for, in
`ansible/00-initial-setup/cse-range-clone-destroy-cycle.yml`. Run
against `pve-test` under `PVE_ENV=pve-test ./with-secrets` — `pve-test`
is **not** a production node (see `terraform/PRODUCTION_NODES`), so
this used the normal dev wrapper, not the strict production approval
flow.

The cycle: snapshot the live attacker (`cse-kali`, must stay running —
see below) → full-clone both attacker and target to fresh ephemeral
VMIDs → give the attacker clone a distinct IP (`192.168.70.220`) →
start both → verify the attacker clone's Kali/docker setup survived
the clone intact (`nmap --version` via `pct exec`) → verify the target
clone stays running through a 60s grace period (not crash-looped) →
generate a pair JSON (same schema as the static
`cyber_range_pairs.json`) → destroy both clones → verify they're
genuinely gone → clean up the snapshot.

**Ran for real, verified independently, not just trusted from the
"ok" playbook status**:
- Fetched pair JSON back to the control node — real content, correct
  schema, both ephemeral names/IPs present.
- `pct list`/`qm list` on `pve-test` afterward show only the original
  `70010`/`70011`/`910` — both ephemeral VMIDs (`70020`, `70021`)
  genuinely gone, no leftover state.
- `pct listsnapshot 70010` shows only `current` — the cleanup snapshot
  delete genuinely worked, no leftover snapshot on the live attacker.
- The live `cse-kali` (original, never stopped) confirmed undisturbed
  afterward: `docker ps` inside it still shows both containers with
  17h uptime, unaffected by being snapshotted while running.

**Two real bugs found and fixed while building this, not assumed
away**:
1. Proxmox refuses a full clone of a *running* LXC except from a
   snapshot ("Full clone of a running container is only possible from
   a snapshot") — `cse-kali` is the live static-pair attacker and must
   not be stopped to clone it, so the playbook snapshots it first and
   clones `--snapname`-scoped, then deletes the snapshot during the
   destroy phase.
2. `lookup('pipe', 'date +%s')` used directly in a play's `vars:` is
   **not memoized** — it re-executes on every Jinja reference, so the
   snapshot name and the clone's `--snapname` argument landed on two
   different timestamps a few seconds apart on the first real attempt,
   and the clone failed looking for a snapshot that was never actually
   created under that exact name. Fixed with an explicit `set_fact`
   task at the top of the play to freeze one real run id, used
   consistently everywhere after.

**Deliberately out of scope for this cycle** (see the playbook's own
header comment):
- No actual benchmark ran against the ephemeral pair — "collect" is a
  documented stub (nothing to pull back yet), matching every other
  live-run deferral this session.
- The target VM's IP (`192.168.70.211`) is baked into the Windows
  guest itself (console-only `netsh`, not Proxmox-managed — same
  limitation noted for the original VM) — the clone boots with the
  **identical** IP, which is only safe because the playbook asserts
  the static-pair source VM is stopped first. True concurrent
  ephemeral+static operation would need a real in-guest re-IP
  mechanism, which doesn't exist yet.
- The generated pair JSON is fetched back for inspection only — wiring
  it into `cse-controller`'s own run-orchestration (which currently
  reads the static `cyber_range_pairs.json`) is a separate integration
  step, not yet built.

## Not yet started

- `cse-autopatch` — no benchmark orchestration beyond Phase 1's
  infrastructure, no Harbor project, deliberately deferred to last per
  operator instruction (see below).
- Any full-scale CyberSecEval benchmark run (only a 5-case MITRE smoke
  test has run so far).
- Windows Activation on `metasploitable3-win2k8` was deferred (deliberate
  — disposable pentest target, doesn't need it), and its network config
  isn't Terraform-managed (console-only, see above) — don't expect either
  to survive a VM recreate without redoing them.

## Open decisions (plan.md §1a) — all resolved 2026-09-18

3. **All three** CyberSecEval LXCs (`cse-controller`, `cse-code-eval`,
   `cse-autopatch`) live on `pve-tiny`.
4. `cse-controller` targets a **separate Nathanw Strix-Halo `llama.cpp`
   fork server** — not Framework's existing `llama-router`
   (`ggml-org/llama.cpp`), and not Ollama (that runtime decision was
   scoped to Laguna S 2.1's eval scores, doesn't bind this benchmark).
   Turned out to already exist, live — see above.
5. `cse-autopatch`'s Podman volume size: **deferred** — no pre-allocated
   number; size it from real `podman system df` output once Phase 8's
   PoC runs a shard.

## Next steps, in order

Phase 1 (plan §29) is fully complete. Phase 2 has started — MITRE's
pipeline is proven end-to-end on a 5-case sample (see above). The
cross-host `cse-controller` → `cse-kali` path the plan (§12) expected to
need a new MikroTik rule turns out to already work with none — confirmed
live (2026-09-19), see §12's updated text in the plan doc.

Per operator instruction (2026-09-19): pause benchmark *runs*, focus on
setup/infrastructure instead. **Superseded later the same day**: once
the control panel existed, the operator explicitly directed testing it
with real submitted jobs (mitre-frr, instruct, autocomplete, small
suites) — several real small-scale runs have now happened through it,
deliberately, as part of verifying the panel itself. What's still true:
no *dedicated* full-scale benchmark campaign (repeat MITRE sample for
nondeterminism, MITRE FRR/Prompt Injection/Code Interpreter Abuse at
real scale, the live autonomous-uplift attack) has been run — that
backlog is unchanged, just no longer under a blanket "don't run
anything" instruction. Both the autonomous-agent SSH access and the
prep-step automation above are done and verified — everything needed
for a live autonomous-uplift run now exists except triggering it, and
it can now be triggered through the panel (`benchmark: autonomous-uplift`)
rather than only via the manual script.

0. **Done** — `cse-code-eval` deployed into `cse_seg` (`192.168.100.71`)
   and verified live (see above). Phase 5's infrastructure is complete;
   no CyberSecEval code-execution benchmark has actually been run
   against it yet (deliberately, per the pause-on-runs instruction).
1. Whenever test *runs* are back in scope: trigger the actual live
   benchmark (`benchmark.run --benchmark=autonomous-uplift`, command
   already printed by `run-autonomous-uplift.sh`'s own output) — a real
   attack against `metasploitable3-win2k8`, up to 100 shots. Not run
   yet, deliberately.
2. Also when runs are back in scope: repeat the 5-case MITRE sample once
   more for nondeterminism (plan §29's Phase 2 acceptance requirement),
   then MITRE FRR/Prompt Injection/Code Interpreter Abuse, Secure
   Coding (Phase 3), CyberSOCEval (Phase 4), and Spear Phishing
   (Phase 6) — all fully configured and functionally verified now,
   only the actual live-model runs remain.
2a. **Done** — Phase 7's full clone→configure→test→generate-pair-
   JSON→collect(stub)→destroy cycle built and actually run once for
   real on `pve-test` (see above). Remaining gap, not a live run: wiring
   the generated ephemeral pair JSON into `cse-controller`'s own
   run-orchestration, which still reads the static
   `cyber_range_pairs.json` — not yet built.
3. **AutoPatch, last, deliberately** (operator instruction, 2026-09-18):
   `cse-autopatch` LXC, its nested-Podman setup, and the Harbor
   `cyberseceval` project + scoped robot account (§18) it needs all wait
   until every other benchmark path (everything except the
   autonomous-offensive/range path, which needs `cse-kali` reachability
   above) is working. No Harbor project/robot exists yet — don't create
   one until this step is actually being worked.

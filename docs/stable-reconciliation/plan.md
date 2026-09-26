# Stable reconciliation plan — land all live-deployed branch work on `stable`

Status: DRAFT, 2026-09-26 (refreshed 14:40 NZST for gaming-branch commits
through `e74a782a`). Nothing below has been executed.
Goal: `stable` ends up describing what is actually running — every LXC,
container, app config, MikroTik rule and SOPS secret — with no branch-only
work lost. The finish line is **proven** "no drift" (Phase 5), not merely
"merged cleanly".

Baseline facts this plan relies on (from the 2026-09-26 branch survey):

- Base is `origin/stable` (local `stable` is 2 commits behind — never use it).
- SOPS YAML keeps key names unencrypted, and SOPS leaves the ciphertext of
  untouched keys unchanged, so key-level diffs are exact. Value equality was
  checked by hashing decrypted values in memory.
- All `terraform.tfstate` is local, gitignored, and exists **only on this
  workstation**. Five stacks keep state in the legacy
  `terraform/lxc/stacks/<stack>/terraform.tfstate.d/pve/` path.
- A simulated merge of the full sequence (`git merge-tree`, in memory)
  produced exactly the conflicts listed in Phase 2 — no others.

---

## Decisions (defaults applied unless the operator overrides)

| # | Question | Default |
|---|---|---|
| D1 | One integration branch or a PR per source branch? | **One** branch, `task/stable-reconciliation`, cut from `origin/stable`. Each source branch gets its own `--no-ff` merge commit, so SHAs and `git branch --merged` stay truthful. One PR into `stable` at the end. |
| D2 | When live and the merged repo disagree, which wins? | **Live wins.** The repo is changed to match live, one commit per finding. Exception: if live is a known-bad hand hack, the operator decides case by case (redeploy to the repo version instead). |
| D3 | `cse_tasks.py` — both cse-panel and nextcloud changed it on 2026-09-25. | Union of both changes. **Which one is live** is established in Phase 1 (item L6). If only one is live, the other is still merged, and deploying it is a flagged follow-up — not silently left undone. |
| D4 | `stash@{3}`'s two untracked MikroTik playbooks (GVM router SSH input rule + `gvm-scan` RouterOS user). | Include them **only if** Phase 1 (L8) shows the rule/user exist on the router. Otherwise export them to `docs/stable-reconciliation/artifacts/` and leave them out. |
| D5 | Superseded branches (list in Phase 7). | Not merged. Delete only after the stable PR merges, and only on the operator's say-so. |
| D6 | ark-mods is now mostly live: ARK slot interlock, Minecraft staging copy (the Foreverworld cutover itself hasn't happened), and AzerothCore Playerbots running as Wings server 4. It also carries a repo-policy change (`ef1bb8f8`: AGENTS.md / branch-model.md retire pve-test-vm). | Merge all of it. The policy-doc change rides along; say so in the PR body. |
| D7 | Much of the gaming state lives in Pterodactyl Panel's database and Wings volumes (imported eggs, servers 1–4, their resource limits, AzerothCore `.conf` rates). Terraform and Ansible can't see it. | Don't try to put it under IaC in this plan. Phase 5d compares the egg definitions against the repo and records the rest as **documented, not managed**. Bringing it under IaC is a separate follow-up. |
| D8 | RouterOS rule `*B1` (LAN → gaming-stack-lab TCP 3724/8085) was added by hand. `pve.yaml` records the intent, but no playbook manages it. The same goes for the earlier ARK LAN rule (the known "unmirrored firewall rule" gap). | Accept as a known gap for now: confirm it exists (L10) and list it as a follow-up. Writing a `gaming-stack-lab` MikroTik reconcile playbook is new work, not reconciliation. |

### Phase 1 outcomes (2026-09-26, operator-confirmed)

Full results are in `artifacts/phase1.md`.

- **L1/L2:** carry the `PORTAINER_TOKEN` from `fix/graylog-memory-headroom`
  and the `WEB_SEARCH_MCP_API_KEY` from `fix/deep-research-web-search-mcp`
  (both confirmed live).
- **L3–L5:** match the branch values.
- **L6 → D3 resolved:** live `cse_tasks.py` is the cse-panel version, with
  neither reporting Phase 2 nor the Nextcloud push. **Merge the union, then
  do a targeted redeploy of cse-controller on pve-tiny** (a separate
  approval, after Phase 5a/5b). The Nextcloud push stays inert until its
  SOPS keys and MikroTik rule exist.
- **L7:** `docker_base` rsyslog ordering is missing on 16 containers.
  **Accepted:** they converge on each stack's next provision. The PR lists
  them, and Phase 5b treats this as expected `changed`.
- **L8 → D4 resolved:** include the stash@{3} playbooks; they're live.
- **L9:** the router has no Traefik→torrent-UI rule, even though `pve.yaml`
  declares one. Phase 5 checks UI reachability through Traefik, and
  `pve.yaml` follows live.
- **L10 → D8 superseded:** `mikrotik-game-seg.yml` *does* manage
  192.168.60.10. Update it to match live (Phase 2 step 13): `*61` gains
  8080, and `*9C` (ARK UDP) and `*B1` (AzerothCore) are added.
- **L11:** eggs 15 and 16 match the repo. Egg 19 differs only in
  `AC_AI_PLAYERBOT_ADD_CLASS_ACCOUNT_POOL_SIZE` (live 1, repo 4). **Keep
  4**; the panel re-import is pending operator work.

---

## Phase 0 — Safeguard (local only, no production access)

Nothing here touches production. It removes the single points of failure first.

```bash
cd /home/steve/git/proxmox-homelab
git fetch --all --prune

# 0.1 Back up all real Terraform state, outside the repo
mkdir -p ~/backups/tfstate-2026-09-26
find terraform -path '*.terragrunt-cache*' -prune -o \
  \( -name 'terraform.tfstate' -o -name 'terraform.tfstate.backup' \) -print0 \
  | tar --null -czf ~/backups/tfstate-2026-09-26/tfstate.tgz --files-from=-
tar -tzf ~/backups/tfstate-2026-09-26/tfstate.tgz | wc -l   # expect > 0

# 0.2 Turn stash@{0} (NEXTCLOUD_STEVE_PASSWORD — exists nowhere else) into a commit
git switch task/nextcloud-stack-plan               # tip must be c84a4d15
git stash apply stash@{0}                          # touches only secrets.common.enc.yaml
git diff --stat                                    # expect exactly 1 file
git commit -am "chore(secrets): add NEXTCLOUD_STEVE_PASSWORD (from stash, live since 2026-09-25)"
# keep the stash itself until Phase 7

# 0.3 Park stash@{3}'s untracked MikroTik files (untracked parent = ^3)
mkdir -p docs/stable-reconciliation/artifacts/stash3
for f in mikrotik-firewall-greenbone-router-ssh-input.yml mikrotik-gvm-scan-user.yml; do
  git show "stash@{3}^3:ansible/00-initial-setup/$f" > docs/stable-reconciliation/artifacts/stash3/$f
done

# 0.4 Push everything that currently exists only here (own remote only)
git push origin task/nextcloud-stack-plan                     # 37 + 1 unpushed
git push -u origin task/torrent-stack-modernization-plan      # never pushed
git push -u origin fix/deep-research-web-search-mcp           # never pushed
git push origin feat/cse-panel-delete-runs                    # 5 unpushed
git push origin feat/gaming-stack-lab-ark-mods                # 27 unpushed as of e74a782a
```

`fix/opensearch-stack-2.19.6-cve-fixes` stays local. It duplicates
`a68c84e8`, which is already on the graylog branch.

**Gate 0:** the tfstate tarball exists; `git status` is clean; for every branch
above, `git rev-list --count origin/<b>..<b>` is `0`.

---

## Phase 1 — Live fingerprinting (production reads, before any merge)

This phase establishes the truth for items where the branches disagree with
each other or with stable. `ssh`/`curl` count as mutating under Production
Credential Controls, so the operator approves this whole list once as task
`stable-reconciliation-live-fingerprint`. Every command is read-only, and
every secret comparison prints **hashes only**.

Record each result in `docs/stable-reconciliation/artifacts/phase1.md`.

| # | Question | Command (pve unless noted) | Decides |
|---|---|---|---|
| L1 | Which `PORTAINER_TOKEN` works? | For each candidate (stable's, graylog branch's): `curl -sk -o /dev/null -w '%{http_code}' -H "X-API-Key: $TOKEN" https://$LAB_FQDN_PORTAINER/api/users/me`. Extract the candidate from the branch blob with `sops -d`, as in Phase 3's `get()`. | Expect the graylog branch's token → 200 and stable's → 401. Anything else: stop and ask. |
| L2 | Which `WEB_SEARCH_MCP_API_KEY` is live? | Live: `ssh root@pve "pct exec 50013 -- docker inspect web-search-mcp --format '{{range .Config.Env}}{{println .}}{{end}}'" \| sed -n 's/^MCPO_API_KEY=//p' \| tr -d '\n' \| sha256sum`. Repo side, per ref (`feat/openwebui-web-search-mcp`, `fix/deep-research-web-search-mcp`): `git show <ref>:terraform/secrets.common.enc.yaml \| sops -d --input-type yaml --output-type json /dev/stdin \| jq -j .WEB_SEARCH_MCP_API_KEY \| sha256sum`. | Expect it to match the deep-research ref. Stop if it matches neither. |
| L3 | OpenSearch live version | `ssh root@pve "pct exec 40014 -- docker ps --format '{{.Image}}'"` | Expect `…opensearch:2.19.6`. |
| L4 | Graylog / Greenbone sizing | `ssh root@pve "pct config 20014; pct config 70011"` → `memory`, and the size of the mount holding docker storage | Expect Graylog 10240 MB / 150G and Greenbone 8192 MB / 150G. |
| L5 | pve host boot-order fix | `ssh root@pve "systemctl cat pve-guests.service"` | Expect the ZFS-ordering drop-in from commit `3a461b31`. If it's absent, that commit becomes a deploy follow-up under D2. |
| L6 | Which `cse_tasks.py` is live (pve-tiny) | `ssh root@<pve-tiny> "pct exec 40070 -- find / -name cse_tasks.py -path '*cyberseceval*' -exec sha256sum {} +"`. Compare with `git show <ref>:terraform/lxc/stacks/cse-controller/cyberseceval-config/cse_tasks.py \| sha256sum` for `feat/cse-panel-delete-runs` and `task/nextcloud-stack-plan`. | Tells D3 which side, if either, matches live. |
| L7 | `docker_base` rsyslog ordering: how far did it spread? | `ANSIBLE_HOST_KEY_CHECKING=False ansible all -i <every docker stack's inventory> -u root -m command -a "systemctl show docker -p After"` → grep for `rsyslog` | Decides whether merging `docker_base` changes behaviour on stacks that haven't picked it up yet. If partial, list those stacks for a Phase 5 redeploy decision. |
| L8 | GVM MikroTik stash items | RouterOS read: `/user print where name~"gvm"` and `/ip firewall filter print where comment~"greenbone"` (via `scripts/preflight-production-mikrotik.sh` session or read-only SSH) | Applies D4. |
| L9 | torrent + nextcloud MikroTik rules exist | Same read: `/ip firewall filter print where comment~"torrent\|media_seg\|apps_seg\|connector_seg"` | Confirms the `network/pve.yaml` union in Phase 2 reflects the router. |
| L10 | Hand-added gaming-stack-lab router rules | Same read: `/ip firewall filter print detail where dst-address~"192.168.60.10"`. Expect `*B1` (src 192.168.1.0/24, tcp 3724,8085) and the ARK LAN rule, both before the `game_seg` default-deny. | D8. Record exact rule text in phase1.md as the reference for a future playbook. |
| L11 | Pterodactyl Panel inventory | Panel application API, GET only: `/api/application/servers?per_page=100` and `/api/application/nests/<n>/eggs?include=variables` → save JSON to `artifacts/panel/` | Baseline for Phase 5d (D7). |

**Gate 1:** every L-item has a recorded result. Any "matches neither"
answer stops the plan for an operator decision.

---

## Phase 2 — Build the integration branch

```bash
git switch -c task/stable-reconciliation origin/stable
mkdir -p docs/stable-reconciliation && cp <this file> docs/stable-reconciliation/plan.md
git add docs/stable-reconciliation/plan.md && git commit -m "docs(stable-reconciliation): add plan"
```

Merge in this exact order. Each line is
`git merge --no-ff <branch> -m "Merge <branch> into task/stable-reconciliation"`.
Resolve conflicts as listed; these are the only conflicts the simulation found.

| # | Branch | Conflict → resolution |
|---|---|---|
| 1 | `fix/graylog-memory-headroom` (28; supersets uvm-in-use, greenbone-syslog, uvm-triage, media-stack-lab-registry) | `greenbone-stack/stack.yaml`: take **stable** (`docker_storage_size: "150G"`). `media-stack-lab/stack.yaml`: take **stable** (newer REGISTRY_HOST fix and comment). `secrets.common.enc.yaml`: `git checkout --ours` (rebuilt in Phase 3). |
| 2 | `task/pve-reboot-resilience` | none |
| 3 | `fix/no-sops-decrypt-on-github-hosted` | none (after #1) |
| 4 | `fix/graylog-stack-disk-and-swap` | none |
| 5 | `fix/greenbone-ospd-scan-throttling` | none |
| 6 | `fix/opensearch-stack-2.19.6-cve-fixes` (duplicate) | `deploy-opensearch-stack.yml`: take **ours** (already `2.19.6`). Merged only so the branch shows as merged. |
| 7 | `task/torrent-stack-modernization-plan` | `.env`: **union** — keep stable's CSE/pterodactyl lines **and** `LAB_IP_TORRENT_STACK_LAB`. `deploy-ai-services-stack.yml`: take **ours** (the ollama-reliability-proxy was removed on stable; don't reintroduce it). |
| 8 | `fix/deep-research-web-search-mcp` (includes reporting-phase2) | `secrets.common.enc.yaml`: `--ours`. |
| 9 | `task/nextcloud-stack-plan` (incl. the Phase 0 stash commit) | `terraform/lxc/network/pve.yaml`: **union** — keep torrent's `media_seg` rules (Traefik→media_seg UI ports, media_seg→internet udp/51820) **and** nextcloud's `apps_seg`/`connector_seg` zones and rules. Keep each zone's explicit-deny rule last within its own zone. `secrets.common.enc.yaml`: `--ours`. |
| 10 | `feat/cse-panel-delete-runs` | `cse-controller/cyberseceval-config/cse_tasks.py`: **union**, in this order: set `result["finished_at"]`, write `RESULT_JSON_NAME`, **then** `_write_report(...)`. Result: `result.json` is on disk before the report and the Nextcloud push read the run dir. |
| 11 | `feat/gaming-stack-lab-ark-mods` | none |
| 12 | Add the stash@{3} MikroTik files (L8: live) | Commit as `chore(mikrotik): source-control live GVM router scan access` |
| 13 | Update `mikrotik-game-seg.yml` to match live (L10) | `*61` ports `22,25565,8080`; add the ARK UDP rule (`*9C`) and the AzerothCore TCP rule (`*B1`) with their exact live comments, both before the game_seg default-deny |

After #10, run `python3 -m py_compile` on `cse_tasks.py` before continuing.

**Checks to run after the merges** (each should print the value shown):

```bash
grep -E '^(memory|docker_storage_size):' terraform/lxc/stacks/graylog-stack/stack.yaml    # 10240 / "150G"
grep -E '^(memory|docker_storage_size):' terraform/lxc/stacks/greenbone-stack/stack.yaml  # 8192 / "150G"
grep 'opensearch_image_tag:' terraform/lxc/ansible/playbooks/deploy-opensearch-stack.yml  # "2.19.6"
grep -c 'ollama-reliability-proxy:' terraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml  # 0
grep -c 'web-search-mcp' terraform/lxc/ansible/playbooks/deploy-ai-services-stack.yml     # > 0
```

---

## Phase 3 — Rebuild `secrets.common.enc.yaml` (operator runs this)

Git can't merge SOPS files: the MAC block always conflicts. The file is
therefore exactly `origin/stable`'s after Phase 2, and each branch's keys are
re-applied with `sops set`. Claude's harness blocks SOPS writes, so the
operator runs this script. It prints no plaintext.

Save it as `docs/stable-reconciliation/artifacts/carry-sops.sh` (ignored) and
run it from the repo root on `task/stable-reconciliation`:

```bash
#!/usr/bin/env bash
set -euo pipefail
export SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt
F=terraform/secrets.common.enc.yaml

git diff --quiet origin/stable -- "$F" || { echo "ABORT: $F is not origin/stable's"; exit 1; }

# ref|KEY — source of truth per Phase 1 (L1: PORTAINER_TOKEN, L2: WEB_SEARCH_MCP_API_KEY)
CARRY=(
  "fix/graylog-memory-headroom|PORTAINER_TOKEN"
  "fix/graylog-memory-headroom|DOCKER_LIVE_USAGE_ES_PASSWORD"
  "fix/deep-research-web-search-mcp|TAVILY_API_KEY"
  "fix/deep-research-web-search-mcp|WEB_SEARCH_MCP_API_KEY"
  "task/nextcloud-stack-plan|NEXTCLOUD_ADMIN_PASSWORD"
  "task/nextcloud-stack-plan|NEXTCLOUD_DB_PASSWORD"
  "task/nextcloud-stack-plan|NEXTCLOUD_REDIS_PASSWORD"
  "task/nextcloud-stack-plan|NEXTCLOUD_OIDC_CLIENT_ID"
  "task/nextcloud-stack-plan|NEXTCLOUD_OIDC_CLIENT_SECRET"
  "task/nextcloud-stack-plan|NEXTCLOUD_STEVE_PASSWORD"
  "task/nextcloud-stack-plan|GREENBONE_OCI_PANGOLIN_AUDIT_SSH_PRIVATE_KEY"
)

get_ref() { git show "$1:$F" | sops -d --input-type yaml --output-type json /dev/stdin | jq -ce --arg k "$2" '.[$k]'; }
get_cur() { sops -d --output-type json "$F" | jq -ce --arg k "$1" '.[$k]'; }

for e in "${CARRY[@]}"; do
  ref=${e%%|*}; k=${e##*|}
  get_ref "$ref" "$k" | sops set --value-stdin "$F" "[\"$k\"]"
done

fail=0
for e in "${CARRY[@]}"; do
  ref=${e%%|*}; k=${e##*|}
  if [[ "$(get_ref "$ref" "$k" | sha256sum)" == "$(get_cur "$k" | sha256sum)" ]]; then echo "OK       $k"
  else echo "MISMATCH $k"; fail=1; fi
done

# No key from stable may be lost or changed, except the intentional PORTAINER_TOKEN rotation
for k in $(git show "origin/stable:$F" | grep -E '^[A-Za-z_][A-Za-z0-9_]*:' | cut -d: -f1 | grep -v '^sops$'); do
  [[ $k == PORTAINER_TOKEN ]] && continue
  [[ "$(get_ref origin/stable "$k" | sha256sum)" == "$(get_cur "$k" | sha256sum)" ]] || { echo "STABLE-DRIFT $k"; fail=1; }
done
exit $fail
```

If anything fails, run `git checkout origin/stable -- "$F"`, fix the cause, and rerun.
On success:
`git commit -m "chore(secrets): carry forward live keys from merged branches"`.

**Gate 3:** the script exits 0 with 11 × `OK` and no `STABLE-DRIFT`, and
`scripts/check-required-sops-keys.sh` passes.

---

## Phase 4 — Static validation (local)

```bash
python3 -m unittest discover -s . -p "test_*.py"
for p in graylog-stack greenbone-stack opensearch-stack ai-services-stack mcp-utility-stack \
         torrent-stack-lab nextcloud-stack cse-controller cse-panel-stack gaming-stack-lab \
         portainer-stack monitoring-stack netbox-stack pentagi-stack wazuh-stack media-stack-lab; do
  f=terraform/lxc/ansible/playbooks/deploy-$p.yml; [[ -f $f ]] && ansible-playbook --syntax-check "$f"
done
for f in ansible/00-initial-setup/mikrotik-*{media-seg,apps-seg,connector-seg,shared-graylog,cse}*.yml; do
  ansible-playbook --syntax-check "$f"; done
python3 -m py_compile terraform/lxc/stacks/cse-controller/cyberseceval-config/cse_tasks.py
bash -n scripts/render-azerothcore-playerbots-egg.sh
for f in docs/gaming-stack-lab/*-egg.json; do jq empty "$f"; done
# network/pve.yaml carries three branches' additions — confirm all survived:
grep -c -E '3724|51820|apps_seg:|connector_seg:' terraform/lxc/network/pve.yaml   # expect >= 4
```

**Gate 4:** everything passes.

---

## Phase 5 — Drift proof: repo vs live (the actual finish line)

### 5a. Terraform (read-only, no approval needed)

Every stack below must show `No changes`. Run each one from the directory
where its state actually lives:

```bash
plan() { PVE_ENV=$1 ./with-secrets-prod${2} terragrunt plan -lock=false --terragrunt-working-dir "$3"; }
for s in graylog-stack greenbone-stack opensearch-stack ai-services-stack mcp-utility-stack \
         portainer-stack monitoring-stack netbox-stack pentagi-stack wazuh-stack gaming-stack-lab pangolin-proxy; do
  plan pve "" terraform/lxc/environments/pve/$s; done
for s in nextcloud-stack newt-connector torrent-stack-lab media-stack-lab pterodactyl-lab; do   # legacy-layout state
  plan pve "" terraform/lxc/stacks/$s; done
for s in cse-controller cse-panel-stack; do plan pve-tiny -tiny terraform/lxc/environments/pve-tiny/$s; done
```

Known trap: `.env.pve` exports `TF_WORKSPACE=pve`. That is correct for
every path above, because each has `terraform.tfstate.d/pve/`. A plan that
wants to **create** a container means the wrong state path is being used, not
real drift — stop and fix the path; never apply.

### 5b. Ansible / app state (approval: task `stable-reconciliation-check-mode`)

```bash
for s in <every stack from 5a on pve>; do
  ./with-secrets-prod scripts/provision.sh --stack $s --check; done
./with-secrets-prod-tiny scripts/provision.sh --stack cse-controller --check
./with-secrets-prod-tiny scripts/provision.sh --stack cse-panel-stack --check
```

The target is `changed=0` apart from tasks known to always report changed in
check mode (shell/command/compose-up). List every `changed` task in
`artifacts/phase5.md` with a verdict: *noise*, or *real drift → D2 fix*.

### 5c. MikroTik

Run `--check` on the reconcile playbooks the merged branches touched:
media-seg WireGuard egress, apps-seg vlan120, connector-seg vlan110 Wazuh,
shared Graylog ingress, and (if D4 applies) the GVM router pair. The target
is no changes.

Note: `gaming-stack-lab` has no reconcile playbook, so there's nothing to
`--check`. Its rules are covered by L10 and D8 instead.

### 5d. Pterodactyl Panel state (D7)

- **Egg definitions:** compare what L11 exported with the repo.
  - ARK and WildWorks: `docs/gaming-stack-lab/ark-survival-ascended-egg.json`
    and `wildworks-neoforge-egg.json`.
  - AzerothCore: the output of `scripts/render-azerothcore-playerbots-egg.sh`,
    since the repo holds the render script, not a rendered file.
  - Compare only the fields that matter: startup, docker image(s), config
    files, install script, and variables. If the panel differs, the repo
    follows the panel (D2).
- **Servers 1–4:** limits, allocations and egg ID get recorded in
  `artifacts/phase5.md` and checked against what `docs/gaming-stack-lab/`
  claims (e.g. AzerothCore at 16 GiB / 4 CPU / 60 GiB). Where the docs are
  wrong, fix the docs.
- **What can't be checked from the repo:** game config inside Wings volumes
  (AzerothCore rates and Playerbots settings, ARK INI). The PR must say so
  plainly: the repo *documents* this state but doesn't *reproduce* it.

### 5e. Carry-over findings from Phase 1

- **L5:** if the drop-in is absent, note it as a follow-up.
- **L6/D3:** redeploy whichever `cse_tasks.py` side isn't live.
- **L7:** list the stacks lacking the `docker_base` ordering.

**Gate 5:** every stack shows Terraform `No changes`, Ansible has no
unexplained `changed`, and MikroTik shows no changes. Each real drift item is
either fixed on this branch (repo made to match live, one commit each) or
explicitly accepted by the operator as a deploy follow-up. Rerun 5a/5b for
any stack whose files changed while fixing drift.

---

## Phase 6 — Promote

Open a PR from `task/stable-reconciliation` to `stable`. Its body contains:
the merged-branch list, the Phase 1 table, the Phase 5 results, and the
accepted follow-ups. **The operator decides when to open and merge it.**

---

## Phase 7 — Clean-up candidates (after merge, operator's call only)

- **Fully merged via this plan:** every branch in the Phase 2 table.
- **Superseded, safe to delete:**
  - `feat/openwebui-web-search-mcp` — replaced by deep-research `07b39d68`; its API key is stale.
  - `feat/gaming-stack-lab-pterodactyl` — re-landed as `-v2`; SOPS values identical.
  - `chore/rotate-graylog-root-password` (v1) — superseded by #429; values identical.
  - `fix/reliability-proxy-repetition-collapse-detection` — the proxy was removed.
  - `feat/reporting-cyberseceval-phase2` — contained in #8 and #9.
- **Pre-August remote branches:** `prod/pve-infra` (pre-split secrets — do not
  restore; 7 values since rotated), `work/socket-proxy-metadata-review`,
  `task/terraform-env-runtime-isolation`,
  `work/pve-production-migration-2026-05-30`, `fix/harbor-external-url-scheme`,
  `fix/portainer-sso-reconciler`, `fix/tls-hardening`,
  `feat/pentagi-harness-target`, `task/monitoring-victorialogs`,
  `task/monitoring-stack-phase1`. These are out of scope here; review
  separately if wanted.
- **Stashes:** `stash@{0}` (once Phase 0.2 is pushed) and `stash@{3}` (once D4 is settled).
- **Follow-ups from D7/D8 (new work, not part of this plan):**
  - A `gaming-stack-lab` MikroTik reconcile playbook (`*B1` plus the ARK LAN rule).
  - Pterodactyl egg/server state under IaC.

## Explicitly out of scope

- Any `terragrunt apply`, redeploy, or container restart. This plan only
  merges and verifies. Redeploys arising from Phase 5 findings are separate,
  individually approved tasks.
- `main` promotion (`stable` → `main`).
- pve-test-vm (not used).

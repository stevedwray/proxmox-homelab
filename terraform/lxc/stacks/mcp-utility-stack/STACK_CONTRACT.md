# mcp-utility-stack — Stack Contract

## Purpose

Runs `cve-mcp-server` (upstream `mukul975/cve-mcp-server`, local `local-dev`
branch merged onto `v0.2.0`) as a network-reachable MCP server, giving AI
agents structured CVE/vulnerability research (NVD, EPSS, CISA KEV, OSV,
GitHub/GitLab advisories, MITRE, VulnCheck, plus configured threat-intel
sources) via HTTP instead of a local `stdio` process. It is the first
"external-utility" adapter in `docs/mcp-stack/plan.md`'s MCP design: it
holds no internal infrastructure credentials, but needs real internet
egress to public CVE/advisory APIs — the opposite trust posture from
`mcp-discovery-stack`, which is why it lives in its own zone.

Also runs `docs-rag-mcp` + `pgvector` (added 2026-08-23): a second,
purpose-built MCP server giving agents semantic search
(`search_docs`/`list_stacks`/`get_document`) over this repo's own documentation, backed
by `nomic-embed-text` embeddings (via the existing Ollama endpoint on
`framework.gibbsgreatly.xyz`) stored in `pgvector`. Folded into this same
LXC rather than a new stack — same trust class as `cve-mcp-server` (no
internal infrastructure credentials, narrow named egress, MCP tools for
agents), and arguably lower risk (it only ever reads this repo's own
trusted docs, never untrusted internet content). See
`docs/coding-stack/plan.md` for the full design and the reasoning for
folding it in here instead of a new stack.

## Network

| Field        | Value                    |
|--------------|--------------------------|
| Zone         | `ai_seg` (SDN VLAN 50) — shares this zone with future AI/LLM app containers; not a dedicated zone (a `research_seg`/VLAN 81 attempt was abandoned 2026-08-01, see `docs/mcp-stack/plan.md`) |
| IP           | `${lab_ip_mcp_utility}/24` |
| Gateway      | `${lab_gw_ai}` |
| VMID         | `50011` (`50010` on this node is `harness-target`, a pre-existing unrelated stack — a real collision hit here 2026-08-01, don't reuse it) |

## Inputs

| Input | Source | Notes |
|-------|--------|-------|
| `NVD_API_KEY` | secrets.common.enc.yaml | Raises NVD rate limit from 5/30s to 50/30s |
| `GITHUB_TOKEN` | secrets.common.enc.yaml | GitHub Advisories/Code Search rate limit |
| `VULNCHECK_TOKEN` | secrets.common.enc.yaml | NVD++ fallback source |
| `VIRUSTOTAL_KEY` | secrets.common.enc.yaml | Threat-intel cluster, deliberately in scope per 2026-08-01 operator decision |
| `SHODAN_KEY` | secrets.common.enc.yaml | Threat-intel cluster, same decision |
| `GREYNOISE_API_KEY` | secrets.common.enc.yaml | Threat-intel cluster, same decision |

`ABUSEIPDB_KEY`/`URLSCAN_KEY`/`CIRCL_PDNS_USER`/`CIRCL_PDNS_PASS` are
intentionally left unset — those sources stay unreachable both at the app
layer (no key) and the network layer (not in the `ai_seg` egress
allowlist).

| `DOCS_RAG_POSTGRES_PASSWORD` | secrets.common.enc.yaml | `pgvector`'s own password — internal-only, no published host port, not shared with any other stack's database |

## Provides

| Service | Port | Protocol | Notes |
|---------|------|----------|-------|
| `cve-mcp-http` | `8000` | `tcp` | MCP Streamable HTTP endpoint at `/api/mcp`. No built-in authentication — access control is network-level only (MikroTik inbound rule), see Security notes below. |
| `docs-rag-mcp-http` | `8001` | `tcp` | MCP Streamable HTTP endpoint at `/mcp` (`search_docs`, `list_stacks`, `get_document`). No built-in authentication, same posture as `cve-mcp-http`. Reachable from `lan`/`pentest_seg` since 2026-08-24 (MikroTik rules `*78`/`*79`, host-scoped to `192.168.50.10:8001`, deliberately tighter than `:8000`'s subnet-wide `*50`/`*51` — see "What Must Not Be Edited Casually" below). No Traefik hostname route. |

## Dependencies

| Stack | Why |
|-------|-----|
| `apt-cacher-stack` | apt proxy during host provisioning |

`framework.gibbsgreatly.xyz` is a runtime dependency for `docs-rag-mcp`
(its embedding calls go to Ollama there), tracked via the existing
`ai_seg → framework:11434` firewall rule (already open for
`ai-services-stack`'s own use) rather than `depends_on:` — same pattern as
that stack's own framework dependency.

No Harbor dependency for the two custom images: `cve-mcp-server` and
`docs-rag-mcp` are both built directly on the host from source copied by
the Ansible controller (see the playbook's header comment) rather than
pulled from a registry. `pgvector` **is** pulled through Harbor's
proxy-cache (`{{ mcp_harbor_fqdn }}/dockerhub/pgvector/pgvector:pg16`),
the first Harbor dependency this stack has had.

## Persistent State

| Path | Storage | Contents |
|------|---------|----------|
| `/var/lib/docker` | `docker_storage` (15G, grown from 5G live via `scripts/resize-lxc-mount.sh` 2026-08-24 for `docs-rag-mcp`/`pgvector` — see "What Must Not Be Edited Casually") | Docker image/container layers |
| Docker named volume (cache) | Docker volume | SQLite cache (`CACHE_DB_PATH`, default `~/.cve-mcp/cache.db` inside the container) |
| Docker named volume (audit log) | Docker volume | Rotating audit log file (`AUDIT_LOG_PATH`) — writes to a **file only, not stdout** (confirmed by reading `src/cve_mcp/audit.py`: `RotatingFileHandler`, no `StreamHandler`). The container's `json-file` Docker log driver does **not** capture this — it's a real gap, not yet fixed, tracked in `cve-mcp-server`'s own `docs/api-service-plan.md`. |
| `docs-rag-pgdata` (Docker named volume) | Docker volume | `pgvector`'s embedding index (`doc_chunks`, `file_index` tables). **Deliberately not backed up separately** — it's fully re-derivable from this repo's own docs by re-running `provision.sh --stack mcp-utility-stack` (a fresh reindex rebuilds it from scratch), so losing it is an inconvenience (re-embedding time), not data loss. |
| Ansible-copied corpus (`/opt/mcp-utility-stack/corpus` on the host, bind-mounted read-only into `docs-rag-mcp`) | LXC rootfs, not a Docker volume | A snapshot of `docs/**/*.md` (minus `artifacts/`), every `STACK_CONTRACT.md`, and `CLAUDE.md` as of the last `provision.sh` run — **not live**, refreshed only by re-provisioning. |

## What May Depend On This Stack

Any authenticated internal client on `lan` or `pentest_seg` (per the
`ai_seg` inbound firewall rule) wanting CVE/vulnerability research —
starting with an interactive Claude Code session on the workstation, and
`pentagi-stack`/`greenbone-stack` findings review. No stack currently
depends on it in an automated way.

`docs-rag-mcp` is for the same kind of client (an agentic coding session,
particularly one driving a local model per `docs/coding-stack/plan.md`).
Confirmed live 2026-08-24 from a real VS Code Copilot Chat Agent-mode
session (Laguna S 2.1 via Ollama) via `.vscode/mcp.json` — see
`docs/coding-stack/plan.md` Phase 4.

## What Must Not Be Edited Casually

- **No built-in authentication.** Anything that can reach `ai_seg:8000`
  can call every enabled tool. The only access control is the MikroTik
  inbound rule (`lan`, `pentest_seg` → `ai_seg:8000`) — do not widen
  that rule without adding real app-layer auth first.
- **Egress allowlist is a real security boundary, not a formality.** The
  `ai_seg` MikroTik policy allows only the named hosts documented in
  `terraform/lxc/network/pve-test-vm.yaml`'s `ai_seg` egress policy
  (grepped from `cve-mcp-server`'s own source, not guessed). Adding a new
  data source to the upstream server requires adding its host to that
  allowlist too, or the tool will silently fail closed.
- **`ABUSEIPDB_KEY`/`URLSCAN_KEY`/`CIRCL_PDNS_*` staying unset is
  deliberate**, not an oversight — don't "complete" the `.env` by filling
  them in without revisiting the egress allowlist and the scope decision
  that excluded them.
- **`docs-rag-mcp`'s corpus is a point-in-time copy, not a live view of
  this repo.** It's refreshed by re-running
  `provision.sh --stack mcp-utility-stack`, which re-copies
  `docs/**/*.md`/`STACK_CONTRACT.md`/`CLAUDE.md` from the Ansible
  controller's own checkout and reindexes whatever changed. Since
  2026-08-25 this also happens automatically: a `post-commit` git hook
  (`scripts/git-hooks/post-commit-docs-reindex.sh`, installed via
  `scripts/install-git-hooks.sh`) backgrounds this same command whenever
  a commit touches `docs/**/*.md`, a `STACK_CONTRACT.md`, or `CLAUDE.md`
  — see `docs/coding-stack/plan.md` Phase 5. It's still not instantaneous
  (a real ansible run against `pve`, backgrounded but not free), so a
  same-second edit-then-query can still predate it — `indexed_at` in each
  `search_docs` result is how a caller can tell.
- **The corpus copy landing on disk does not by itself guarantee a
  reindex happened.** The corpus is a bind mount, so plain file-content
  changes don't produce a `docker compose` config diff, and Compose
  won't restart an already-running container just because a bind-mounted
  file changed underneath it. `deploy-mcp-utility-stack.yml` now
  explicitly restarts `docs-rag-mcp` (with a post-restart health
  re-check) whenever the corpus-copy task actually changed something —
  don't remove that restart task thinking it's redundant with the
  `docker compose` deploy step above it; it isn't, and removing it
  silently reintroduces stale-index bugs that look like success in the
  playbook output.
- **Port `:8001` (`docs-rag-mcp`) has a MikroTik inbound rule since
  2026-08-24 but still no Traefik hostname route.** The rules (`*78`
  `lan`, `*79` `pentest_seg`) are deliberately host-scoped to
  `192.168.50.10:8001` — narrower than `:8000`'s `*50`/`*51`, which
  accept for the whole `ai_seg` subnet (a documented pre-existing
  imprecision, not a pattern to copy). If a second `ai_seg` host ever
  needs `docs-rag-mcp` reachability, that's a new rule, not a reason to
  widen these two.
- **`pgvector`'s data is intentionally not backed up separately** — it's
  fully re-derivable by reindexing. Don't add it to a backup policy
  expecting point-in-time recovery value beyond "save re-embedding time."
- **The `docs_rag_mcp` Python package's `DATABASE_URL`/`OLLAMA_URL` assume
  the exact service names/hostnames this playbook's compose file uses**
  (`pgvector`, `framework.gibbsgreatly.xyz`) — renaming the `pgvector`
  service in compose without updating `docs-rag-mcp`'s `DATABASE_URL` env
  var will break it silently (DNS resolution failure inside the compose
  network, not an auth error).
- **`docker_storage_size: 15G` in `stack.yaml` was applied live via
  `scripts/resize-lxc-mount.sh` (live `pct resize`), not `terragrunt
  apply`** — growing this value in Terraform's own `mount_point.size`
  forces a full container replace at the provider level (confirmed live
  2026-08-24, `terragrunt plan` showed `-/+ ... must be replaced`, 4
  resources destroyed). Any future size increase must use the same
  operational path, never a bare `terragrunt apply`.
- **`memory`/`swap` in `stack.yaml` are deliberately still `1024`/`512`**,
  not the higher values a first pass tried — applying that change on
  `pve` turned out entangled with an unrelated, pre-existing drift in
  `null_resource.configure_network_sdn_attachment` (a `"network_sdn_
  vmid"` key disappearing from a generated vars file forces it to want
  replacing on *any* apply, which correctly trips its own
  `network_sdn_allow_destroy` safety guard and fails). Do not bump memory/
  swap here without either fixing that drift first or accepting the same
  entanglement.
- **The `docs-rag-mcp`/`pgvector` corpus bind mount needs the *entire*
  directory ancestor chain world-readable+executable (`0755`), not just
  the leaf directories** — `ansible.builtin.file` only applies `mode` to
  the directory it's directly asked to create, not intermediate parents
  it implicitly creates along the way. Confirmed live 2026-08-24: this
  silently left `corpus/terraform`, `corpus/terraform/lxc`, and
  `corpus/terraform/lxc/stacks` unreadable by the container's non-root
  user even though the leaf `STACK_CONTRACT.md` directories were correctly
  `0755` — the reindex ran, found 0 files under that subtree, and reported
  success anyway. A "successful" reindex summary does not by itself prove
  the corpus was reachable; check `docker exec docs-rag-mcp find /corpus
  -name '*.md' | wc -l` against the real corpus file count if in doubt.
- **`DOCS_RAG_ALLOWED_HOSTS` must include `127.0.0.1:8001`**, not just the
  LAN IP — the in-LXC health check hits the container over loopback, and
  without it every health-check request gets a `421` (DNS-rebinding
  protection rejecting the Host header) instead of the expected
  200/401/405/406, so the wait task times out even though the server is
  genuinely healthy.

## Playbook

`deploy-mcp-utility-stack`

`docker_base` role + a single templated `docker-compose.yml`
(`community.docker.docker_compose_v2`), same pattern as `deploy-greenbone-stack.yml`.
Three services as of 2026-08-23: `cve-mcp-server`, `pgvector`,
`docs-rag-mcp`.

## Implementation Files

| File | Role | Status |
|------|------|--------|
| `terraform/lxc/stacks/mcp-utility-stack/stack.yaml` | Terraform-side stack definition | existing |
| `terraform/lxc/environments/pve-test-vm/mcp-utility-stack/terragrunt.hcl` | Terragrunt entrypoint (boilerplate) | existing |
| `terraform/lxc/stacks/mcp-utility-stack/inventory.yml` | Generated Terraform→Ansible handoff — do not hand-edit, regenerated by `terragrunt apply` | generated |
| `terraform/lxc/ansible/playbooks/deploy-mcp-utility-stack.yml` | Stack playbook | existing |
| `terraform/lxc/ansible/files/docs-rag-mcp/` | `docs-rag-mcp`'s Python source, copied into the LXC and built there (not a sibling clone like `cve-mcp-server`) | existing |

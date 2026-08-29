# Wazuh Stack

## Status

**LIVE in production on `pve`, agent pilot rollout complete as of
2026-08-29.** Manager + indexer + dashboard up and healthy at vmid
`40015` (`192.168.40.15`, `infra_seg`). Real Authentik OIDC login
confirmed working end-to-end at `https://wazuh.lab.gibbsgreatly.xyz`.

**6 agents enrolled and `Active`**: `authentik-stack`, `proxy-stack`,
`harbor-stack`, `technitium-stack`, `apt-cacher-stack`, and `pve`
itself (the hypervisor — the single highest-value host in the rollout,
since it's the root of trust for everything else). `apt-cacher-stack`
and `harbor-stack` share `wazuh-stack`'s own zone (`infra_seg`) so
needed no firewall change; `authentik-stack`/`technitium-stack`
(`mgmt_seg`), `proxy-stack` (`edge_seg`), and `pve` (flat `lan`) each
needed a narrowly-scoped new MikroTik forward rule to `wazuh-stack`'s
manager ports (tcp/1514+1515), all confirmed live.

Confirmed genuinely working per-agent (not just configured — verified
against real indexer data and the actual dashboard, not just green
checkmarks): **FIM** (`syscheck`, with per-stack extra watch paths),
**SCA** (CIS-style config auditing, real alerts across every host),
**vulnerability-detection** (500+ real CVEs per agent, correlated
against actual installed Debian 13 packages), and **Docker container
monitoring** (`docker-listener` wodle, opt-in, enabled on the 4 Docker
Compose stacks only — not `apt-cacher-stack`/`pve`, which have nothing
local for it to watch).

`framework` (bare-metal Ubuntu, AI/LLM workloads) and the operator's
own desktop are NOT yet enrolled — both real candidates for a future
pass, not decided against, just not done. See "What's not built yet".

## What this is

A standalone `wazuh-stack` LXC running Wazuh's official all-in-one
single-node deployment (manager + indexer + dashboard, three Docker
containers) in `infra_seg`, fronted by Traefik with real Authentik OIDC
login on the dashboard — same shape as `opensearch-stack`'s Dashboards
route — plus a shared `wazuh_agent` Ansible role
(`terraform/lxc/ansible/roles/wazuh_agent/`) deployed as an explicit
opt-in addition to specific stacks' own playbooks (not wired into
`lxc_base`, so it stays deliberate per-host, not fleet-wide-by-default).

## What's built and live

- `terraform/lxc/stacks/wazuh-stack/` — all 5 files (`STACK_CONTRACT.md`,
  `stack.yaml`, `terragrunt.hcl` ×2 for both `pve` and `pve-test-vm`,
  `edge.yaml`)
- `terraform/lxc/ansible/playbooks/deploy-wazuh-stack.yml` — the manager
  deploy, including `wazuh-authd` auto-enrollment (`use_password: yes`,
  shared `WAZUH_AGENT_AUTHD_PASSWORD` SOPS secret, password file
  injected via `docker cp` rather than bind-mounted — see the file's own
  comments for why)
- `terraform/lxc/ansible/roles/wazuh_agent/` — the shared agent role:
  installs from Wazuh's own apt repo, writes an explicit `ossec.conf`
  (rootcheck/FIM/SCA/syscollector always on, `docker-listener` opt-in
  via `wazuh_agent_docker_monitoring_enabled`), enrolls via
  `agent-auth`. Idempotency is keyed on the agent's *real* connection
  status (`wazuh-agentd.state`, `status='connected'`), not merely
  whether a `client.keys` file exists — a real bug (a 7-month-old
  unrelated leftover enrollment on `pve` blocked re-enrollment silently)
  forced this fix.
- `ansible/00-initial-setup/proxmox-wazuh-agent.yml` — the separate
  playbook path for enrolling bare-metal/hypervisor hosts (`pve`,
  and the pattern to follow for `framework` later), reusing the same
  `wazuh_agent` role via `ansible/ansible.cfg`'s shared `roles_path`
- 5 wazuh-agent-role inclusions added directly to
  `deploy-authentik-stack.yml`, `deploy-proxy-stack.yml`,
  `deploy-harbor-stack.yml`, `deploy-technitium-stack.yml`,
  `deploy-apt-cacher-stack.yml`
- New SOPS secrets: `WAZUH_INDEXER_ADMIN_PASSWORD`, `WAZUH_API_PASSWORD`,
  `WAZUH_OIDC_CLIENT_SECRET`, `WAZUH_AGENT_AUTHD_PASSWORD`; new `.env`
  var `LAB_IP_WAZUH`
- `discover-authentik-edge.py`'s OIDC registry — `wazuh-stack`'s
  dashboard route registered
- `scripts/check-required-sops-keys.sh` — generalized from a hardcoded
  MikroTik-only allowlist to scanning every key in
  `terraform/secrets.common.enc.yaml`, after a real 5-day-old
  unrelated corruption (`HARBOR_DB_PASSWORD` silently wiped to `""`)
  surfaced during this rollout and took Harbor down in production; see
  git history on commit `f690714b` for the full incident
- Full edge activation: Authentik application/provider created,
  Traefik route published and live, Technitium DNS record live

## What's not built yet

- **`framework` and the operator's own desktop as agents** — real
  candidates, not yet done. `framework` would reuse the exact same
  `ansible/00-initial-setup/proxmox-wazuh-agent.yml`-style pattern
  against the `framework` inventory group. The desktop is a genuinely
  different category (personal daily-driver, not IaC-managed) and was
  left as the operator's own call.
- **Feeding Wazuh's vulnerability-detector findings into
  `secpipe-stack`'s CVE correlation pipeline** — `secpipe-stack`
  already correlates Harbor (container images) and Greenbone/GVM
  (network scans); Wazuh adds a third, genuinely different angle
  (installed OS packages on the host itself). Not scoped or designed
  yet, just identified as the next real step.
- Everything from `docs/threat-vuln-platform/plan.md`'s `*-events`
  family (Wazuh → `opensearch-stack` filtered sync) — still future work
- Wazuh's own default `kibanaserver` password (left at its vendor demo
  value, matching `opensearch-stack`'s precedent)
- `monitoring-stack` scrape config still doesn't include `wazuh-stack`
  — a standing, pre-existing platform gap, not introduced here
- The dashboard's numeric API-connection label (`1513629884013`) —
  a same-day rename attempt caused a real regression (the dashboard app
  re-injects a stale duplicate entry on a non-numeric key) and was
  reverted; needs real investigation of the app's own validation logic
  before retrying, not worth the risk for a cosmetic fix

## Lessons worth not re-learning

- **`wazuh-states-*` indices are per cluster-node, not per agent.** A
  real, multi-hour false diagnosis this session concluded vulnerability-
  detection only worked for the manager's own local agent, because
  every index name ends in `-wazuh.manager`. That suffix is the
  *writing node's* name, not an agent scope — a single index holds
  every agent's data, distinguished by the `agent.name` field inside
  each document. Always aggregate/filter on that field before
  concluding an agent "has no data" — see
  `reference_wazuh_states_index_per_agent_field` memory.
- **Idempotency checks need to verify real state, not a cheap proxy for
  it.** Both real bugs fixed this session (agent enrollment,
  `authd.pass`) followed the same shape: a check that looked at "did
  something on the host/container change" instead of "is the thing I
  actually care about true right now" — silently wrong exactly when a
  container gets rebuilt independently of whatever the cheap proxy was
  tracking.

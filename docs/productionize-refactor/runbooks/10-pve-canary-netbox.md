# Production Canary Runbook: netbox-stack on pve

**Target:** `netbox-stack` on production Proxmox host `pve`
**Zone:** `infra_seg` (VLAN 40, gateway from `${LAB_GW_INFRA}`)
**Difficulty:** Moderate
**Risk:** Moderate-to-high - data-centric stack with an existing production role/name overlap and a direct cutover path

## Purpose

Prepare the next low-risk production migration after `portainer-stack`. This run
verifies that `netbox-stack` can be deployed directly on `pve` using the same
 direct-access provisioning model while preserving the stack contract for the
NetBox compose services, Portainer orchestration, and the existing NetBox data
path.

**Not a speculative production mutation.** This runbook is an operator-reviewed,
production-guarded command plan. Production apply and provisioning require
explicit operator approval in chat and `TASK_APPROVAL` at execution time.

`./with-secrets-prod` uses a conservative allowlist. In this runbook, read-only
checks use only commands the wrapper actually permits (`pvesh get`,
`terragrunt plan`) or workstation-side commands that do not go through the
wrapper (`ssh`, `grep`, `rg`).

Use this runbook together with:

- `docs/productionize-refactor/runbooks/10-pve-canary-netbox-checklist.md`
- `docs/productionize-refactor/10-netbox-canary-execution-packet.md`

## Why netbox-stack

1. `netbox-stack` is the next production migration after `portainer-stack` in the current ordering.
2. It validates a data-centric, edge-exposed platform service on `infra_seg` rather than another mgmt-plane service.
3. It exercises the direct-access provisioning path with a stack that already has an existing production role/name overlap, so collision handling is explicit rather than accidental.
4. Its post-deploy checks are concrete and bounded: direct SSH reachability, compose service state, NetBox login health, and edge reachability through Traefik.

## Important Differences From The Earlier Canaries

Do **not** reuse the `monitoring-stack`, `step-ca-stack`, or `dns-stack` text as-is.

Stale assumptions that do not apply here:

1. This is not a first-time empty-slot deployment on `pve`; `netbox-stack` already exists on production as CT `119` and must be treated as a cutover/migration problem.
2. `mgmt_seg` is not the target zone; this stack belongs in `infra_seg`.
3. The primary health probe is NetBox compose health on port `8080`, not Grafana/VictoriaMetrics/Loki, DNS lookups, or step-ca bootstrap.
4. The stack depends on Harbor for image pulls and on the existing production overlay for environment-driven addresses and secrets.

## Pre-Canary Checklist

**Do not proceed past any FAIL without operator intervention.**

### 1. Code State

- [ ] Work is being prepared from a short-lived branch (`work/*`, `feat/*`, `fix/*`, or `task/*`)
- [ ] The branch is not `baseline/teardown-validated`, `dev/pve-test`, or `main`
- [ ] No uncommitted changes in `terraform/` or `ansible/` that are unrelated to this migration prep
- [ ] Task 07 migration ordering shows `netbox-stack` as the next migration after `portainer-stack`

### 2. Repository Preconditions

- [ ] `terraform/lxc/stacks/netbox-stack/stack.yaml` remains environment-decoupled and does not hardcode `pve-test`
- [ ] `terraform/lxc/stacks/netbox-stack/STACK_CONTRACT.md` still matches the intended deploy contract
- [ ] `terraform/lxc/ansible/playbooks/deploy-netbox-stack.yml` remains environment-agnostic
- [ ] `terraform/lxc/stacks/netbox-stack/edge.yaml` still defines the NetBox route and forward-auth policy

**How to verify:**

```bash
grep -r 'pve-test' terraform/lxc/stacks/netbox-stack/ terraform/lxc/ansible/playbooks/deploy-netbox-stack.yml || echo 'PASS'
rg -n 'LAB_IP_NETBOX|LAB_GW_INFRA|LAB_IP_PROXY|LAB_IP_HARBOR|LAB_IP_DNS|NETBOX_SUPERUSER_PASSWORD|NETBOX_SUPERUSER_API_TOKEN' terraform/lxc/stacks/netbox-stack/stack.yaml terraform/lxc/stacks/netbox-stack/edge.yaml terraform/lxc/stacks/netbox-stack/STACK_CONTRACT.md
```

### 3. Target Validation And Duplicate-IP Guard

`netbox-stack` is expected to reuse the same service IP on `pve-test` and `pve`.
If that remains true at execution time, the disposable `pve-test` counterpart
must be destroyed before the `pve` cutover.

- [ ] `./with-secrets-prod` resolves `TF_VAR_proxmox_node=pve`
- [ ] Production `LAB_IP_NETBOX`, `LAB_GW_INFRA`, and `LAB_IP_PROXY` resolve to the intended `infra_seg` values
- [ ] The operator has confirmed whether `LAB_IP_NETBOX` is reused between `pve-test` and `pve`
- [ ] If the same IP is reused, the `pve-test` `netbox-stack` counterpart is destroyed first

**How to verify targeting:**

```bash
set -a
source .env
source .env.pve
set +a
printf 'LAB_IP_NETBOX=%s\nLAB_GW_INFRA=%s\nLAB_IP_PROXY=%s\n' "$LAB_IP_NETBOX" "$LAB_GW_INFRA" "$LAB_IP_PROXY"
if command -v pvesh >/dev/null 2>&1; then
	./with-secrets-prod pvesh get /nodes/pve
else
	echo 'INFO: pvesh not installed on this workstation; rely on terragrunt plan target_node validation below.'
fi
```

**How to inspect and dispose the disposable `pve-test` counterpart:**

```bash
env -u PVE_ENV -u TF_VAR_proxmox_node ./scripts/dispose-pve-test-counterpart.sh --stack netbox-stack --plan
```

The helper must be run from the repo root. It preflights `TF_VAR_proxmox_node=pve-test`,
stops the counterpart if needed, then destroys the managed `netbox-stack`
resources on `pve-test`.
Run `env -u PVE_ENV -u TF_VAR_proxmox_node ./scripts/dispose-pve-test-counterpart.sh --stack netbox-stack --execute`
only if the production migration is reusing the same NetBox service IP as the
`pve-test` counterpart.

### 4. Network Preconditions

Network setup is out of scope for this runbook and must already be in place.
Production router state should be validated with the MikroTik preflight unless
an operator-approved skip is recorded for this exact migration window.

- [ ] The live `pve` uplink learned by the MikroTik is trunked for VLANs `10`, `20`, `30`, and `40`
- [ ] `${LAB_GW_INFRA}` is assigned on `vlan40-infra`
- [ ] `vlan40-infra` input ACLs allow ICMP plus UDP/TCP 53 from `${LAB_SUBNET_INFRA_CIDR}` to `${LAB_GW_INFRA}`
- [ ] `${LAB_IP_NETBOX}` has path to Harbor and Traefik service endpoints required by NetBox provisioning

**How to verify from the operator workstation:**

```bash
./scripts/preflight-production-mikrotik.sh --save-evidence /tmp/preflight-production-mikrotik.txt
```

The preflight requires `MIKROTIK_PASSWORD` in the runtime environment. For
production canaries, ensure it is available via `terraform/secrets.pve.enc.yaml`
before running this step.

**Operator-approved skip path:**

If VLAN state was already validated and no network changes occurred, document
the skip decision and evidence path for this migration window, then continue.

Minimum skip note to capture in evidence/logs:

1. date/time of prior passing preflight evidence
2. evidence file path used as baseline
3. operator statement that VLAN and ACL state is unchanged

### 5. NetBox Input Preconditions

`deploy-netbox-stack.yml` has mandatory env requirements. Treat any missing
or empty value as a hard stop before apply/provision.

- [ ] `NETBOX_DB_PASSWORD` is non-empty
- [ ] `NETBOX_REDIS_PASSWORD` is non-empty
- [ ] `NETBOX_REDIS_CACHE_PASSWORD` is non-empty
- [ ] `NETBOX_SECRET_KEY` is non-empty
- [ ] `NETBOX_API_TOKEN_PEPPER` is non-empty
- [ ] `NETBOX_SUPERUSER_PASSWORD` is non-empty
- [ ] `NETBOX_SUPERUSER_API_TOKEN` is non-empty
- [ ] `LAB_IP_PORTAINER` is set to the intended Portainer endpoint
- [ ] `LAB_IP_HARBOR` is set to the intended Harbor endpoint
- [ ] `LAB_IP_DNS` is set to the intended DNS endpoint used by Docker

**How to verify:**

```bash
./with-secrets-prod bash -lc 'for v in NETBOX_DB_PASSWORD NETBOX_REDIS_PASSWORD NETBOX_REDIS_CACHE_PASSWORD NETBOX_SECRET_KEY NETBOX_API_TOKEN_PEPPER NETBOX_SUPERUSER_PASSWORD NETBOX_SUPERUSER_API_TOKEN LAB_IP_PORTAINER LAB_IP_HARBOR LAB_IP_DNS; do if [ -n "${!v:-}" ]; then printf "PASS %s set\n" "$v"; else printf "FAIL %s missing\n" "$v"; fi; done'
```

### 6. Session Environment

- [ ] `.env` exists locally and contains non-secret defaults only
- [ ] `.env.pve` exists locally and contains the production overlay
- [ ] Production commands will be run through `./with-secrets-prod`
- [ ] There are no lingering manual `TF_VAR_*` exports overriding the wrapper

## Pre-Apply Validation

**Run these checks in order. Stop on any FAIL.**

### Preflight 1: Terragrunt Plan For netbox-stack On pve

```bash
./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/netbox-stack -no-color
```

**Expected plan signals:**

1. `target_node = pve`
2. `hostname = netbox-stack`
3. `ip_address = ${LAB_IP_NETBOX}/24`
4. `gateway = ${LAB_GW_INFRA}`
5. `network.zone = infra_seg`
6. `dns_server = ${LAB_GW_INFRA}`
7. `ansible_playbook = deploy-netbox-stack`

**Red flags (stop if any appear):**

1. Any plan output still targets `pve-test`
2. Any plan output indicates a non-`infra_seg` zone
3. Any unexpected destroy or change outside `netbox-stack`
4. Storage/template references do not match the production environment

### Preflight 1a: Production Router Preflight

Run the MikroTik preflight before any apply if the packet has not already
captured a passing result for this exact migration window.

```bash
./scripts/preflight-production-mikrotik.sh --save-evidence /tmp/preflight-production-mikrotik.txt
```

**Stop if any fail appears for:**

1. `uplink bridge-port discovery`
2. any required `trunk vlan <id>` check
3. `infra gateway`
4. `infra icmp acl`
5. `infra dns udp acl`
6. `infra dns tcp acl`
7. `netbox host can reach Harbor and Traefik`

### Preflight 2: Evidence Directory Preparation

Create an evidence directory before any production mutation so all command
output for this migration window is captured in one place.

```bash
export EVIDENCE_DIR="docs/productionize-refactor/evidence/netbox-canary-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$EVIDENCE_DIR"
echo "$EVIDENCE_DIR"
```

Use `tee` while executing mutation-gated steps in the future migration session.
Example:

```bash
./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/netbox-stack -no-color | tee "$EVIDENCE_DIR/01-plan.txt"
```

## Apply Phase

### Authorization Requirement

Production mutations require explicit operator approval in chat.

Before any apply or live provisioning step, the operator must confirm:

> I approve deploying netbox-stack to production pve as the next migration.

### Apply Command

```bash
export TASK_APPROVAL="canary-netbox-pve-$(date +%Y%m%d)"
./with-secrets-prod terragrunt apply --working-dir terraform/lxc/stacks/netbox-stack -auto-approve -no-color
```

**Monitor for:**

1. apply exits successfully
2. no fallback or accidental reference to `pve-test`
3. generated inventory points to direct guest access for `netbox-stack`

## Post-Apply Validation

### 1) Inventory Contract Checks

```bash
rg -n 'ansible_host|ssh_access_mode|ProxyJump|pve_host|dns_server|contract_dns_server|ansible_playbook|vmid|stack_name' terraform/lxc/stacks/netbox-stack/inventory.yml
rg -n 'netbox-stack|ansible_host|ssh_access_mode|ProxyJump|dns_server|contract_dns_server|ansible_playbook' terraform/lxc/.generated/inventory.pve.yml || true
```

### 2) Provisioning Checks

These two commands are approval-gated in practice because `./with-secrets-prod`
classifies `./scripts/provision.sh` as a production command. Run them only after
the operator has approved the migration, `TASK_APPROVAL` is exported, and the apply
step above has completed.

```bash
./with-secrets-prod ./scripts/provision.sh --stack netbox-stack --check
./with-secrets-prod ./scripts/provision.sh --stack netbox-stack
```

### 3) Post-Apply Health Evidence

```bash
if command -v pct >/dev/null 2>&1; then
	./with-secrets-prod pct list | grep -E '(netbox-stack|40012)'
else
	echo 'INFO: pct not installed on this workstation; skipping local pct list check.'
fi
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_NETBOX" "ip -4 addr show dev eth0 && echo '---' && ip route show default && echo '---' && ping -c 1 '$LAB_GW_INFRA'"
ssh -G root@"$LAB_IP_NETBOX" | rg '^proxyjump ' || echo 'proxyjump=none'
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_NETBOX" 'docker compose -f /srv/docker/netbox/docker-compose.yml ps'
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_NETBOX" 'curl -fsS http://127.0.0.1:8080/login/ >/dev/null && echo healthy'
ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@"$LAB_IP_NETBOX" 'nc -z -w3 '"$LAB_IP_PROXY"' 80'
```

| Check | Status | Expected |
|---|---|---|
| Intended IP assigned | ☐ | `${LAB_IP_NETBOX}/24` on `eth0` |
| Intended gateway assigned | ☐ | default via `${LAB_GW_INFRA}` |
| Gateway reachable | ☐ | ping success |
| Direct SSH works | ☐ | guest IP reachable, `proxyjump=none` |
| Compose services present | ☐ | `docker compose ... ps` shows running core services |
| NetBox login health passes | ☐ | `GET /login/` returns success |
| Traefik port 80 reachable | ☐ | `nc -z` to `${LAB_IP_PROXY}:80` succeeds |

---

## Gate Decision

The netbox migration passes only if all of the following are true:

1. The `pve` target and intended `infra_seg` IP/gateway were validated before apply.
2. The `pve-test` counterpart was destroyed first if the same service IP was being reused.
3. The plan and generated inventory showed direct-access behavior with no default ProxyJump.
4. Provisioning succeeded in both check mode and live mode.
5. NetBox login health passed and Traefik remained reachable from the deployed host.
6. No host-route priming workaround is required in the documented flow or observed provisioning path.

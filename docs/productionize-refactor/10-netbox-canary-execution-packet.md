# netbox-stack Canary Execution Packet (pve)

Use this as the short-form operator run script for the upcoming `netbox-stack`
production migration on `pve`.

This packet is for future execution handoff only. Do not run mutation steps in a
documentation-prep session.

Detailed references:
- `docs/productionize-refactor/runbooks/10-pve-canary-netbox.md`
- `docs/productionize-refactor/runbooks/10-pve-canary-netbox-checklist.md`

## Open Decisions (Confirm Before Running)

1. **Pending at run time:** whether `LAB_IP_NETBOX` on `pve` reuses the currently active `pve-test` NetBox IP.
2. **Expected:** NetBox remains in `infra_seg` with `${LAB_GW_INFRA}` as gateway and DNS server.
3. **Expected:** the Traefik edge route still targets `${LAB_IP_PROXY}` and the NetBox compose stack still trusts the Harbor registry host from the environment overlay.

Do not start execution if `.env.pve` no longer sets the expected
`LAB_IP_NETBOX`, `LAB_GW_INFRA`, `LAB_IP_PROXY`, `LAB_IP_HARBOR`, `LAB_IP_DNS`, and
`LAB_IP_PORTAINER` values for this packet.

## Objective

Validate `netbox-stack` can be deployed and provisioned on production `pve`
using direct access (`ssh_access_mode: direct`), with compose services running,
NetBox login health passing, and the edge route reachable from Traefik.

## Branch And Context Assumptions

1. Running from repo root: `/home/steve/git/proxmox-homelab`
2. Working branch is short-lived (`work/*`, `feat/*`, `fix/*`, or `task/*`), not `baseline/teardown-validated`, `dev/pve-test`, or `main`
3. `.env` and `.env.pve` are present locally
4. Production commands use `./with-secrets-prod`
5. No live production mutation is executed until explicit operator approval is given

## Pre-Run Decisions And Preconditions

1. Confirm the production MikroTik preflight passes for the live `pve` uplink, required VLAN tags, and current `vlan40-infra` ACLs.
2. Confirm whether production is still reusing the active `pve-test` `netbox-stack` service IP.
3. Confirm `.env.pve` still sets intended `LAB_IP_NETBOX`, `LAB_GW_INFRA`, and `LAB_IP_PROXY` values.
4. Confirm NetBox required inputs are non-empty in production runtime: `NETBOX_DB_PASSWORD`, `NETBOX_REDIS_PASSWORD`, `NETBOX_REDIS_CACHE_PASSWORD`, `NETBOX_SECRET_KEY`, `NETBOX_API_TOKEN_PEPPER`, `NETBOX_SUPERUSER_PASSWORD`, `NETBOX_SUPERUSER_API_TOKEN`, `LAB_IP_PORTAINER`, `LAB_IP_HARBOR`, and `LAB_IP_DNS`.

If IP reuse is confirmed, counterpart disposal is mandatory before production
cutover.

## Execution Sequence (In Order)

Run from repo root.

### 1) Read-Only Target Validation

```bash
set -a
source .env
source .env.pve
set +a
printf 'LAB_IP_NETBOX=%s\nLAB_GW_INFRA=%s\nLAB_IP_PROXY=%s\n' "$LAB_IP_NETBOX" "$LAB_GW_INFRA" "$LAB_IP_PROXY"
if command -v pvesh >/dev/null 2>&1; then
	./with-secrets-prod pvesh get /nodes/pve
else
	echo 'INFO: pvesh not installed on this workstation; rely on step 5 terragrunt plan target_node validation.'
fi
```

### 2) Production Router Preflight

```bash
./scripts/preflight-production-mikrotik.sh --save-evidence /tmp/preflight-production-mikrotik.txt
```

If this fails with a missing credential error, ensure `MIKROTIK_PASSWORD` is
present in `terraform/secrets.pve.enc.yaml`.

Operator-approved skip: when VLAN state is already validated and unchanged for
this migration window, skip rerunning this command and record all of the following
in evidence:

1. prior passing preflight evidence file path
2. date/time of that prior pass
3. operator unchanged-network attestation

### 3) Required Input Variable Check (Read-Only)

```bash
./with-secrets-prod bash -lc 'for v in NETBOX_DB_PASSWORD NETBOX_REDIS_PASSWORD NETBOX_REDIS_CACHE_PASSWORD NETBOX_SECRET_KEY NETBOX_API_TOKEN_PEPPER NETBOX_SUPERUSER_PASSWORD NETBOX_SUPERUSER_API_TOKEN LAB_IP_PORTAINER LAB_IP_HARBOR LAB_IP_DNS; do if [ -n "${!v:-}" ]; then printf "PASS %s set\n" "$v"; else printf "FAIL %s missing\n" "$v"; fi; done'
```

Stop if any line reports `FAIL`.

### 4) Counterpart Check (Always Plan)

```bash
env -u PVE_ENV -u TF_VAR_proxmox_node ./scripts/dispose-pve-test-counterpart.sh --stack netbox-stack --plan
```

### 5) Required Counterpart Destroy (`pve-test`)

Run this only when the service IP is being reused from `pve-test` to `pve`.

Approval point: operator approves counterpart teardown on `pve-test` before production cutover.

```bash
env -u PVE_ENV -u TF_VAR_proxmox_node ./scripts/dispose-pve-test-counterpart.sh --stack netbox-stack --execute
```

### 6) Read-Only Terraform Plan (Production Wrapper)

```bash
./with-secrets-prod terragrunt plan --working-dir terraform/lxc/stacks/netbox-stack -no-color
```

Expected signals: `target_node = pve`, `network.zone = infra_seg`, intended
IP/gateway, `ansible_playbook = deploy-netbox-stack`, no unexpected destroy
outside `netbox-stack`.

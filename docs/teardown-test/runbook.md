# Teardown/Deploy Test Runbook

This runbook is an execution skeleton. Fill [variables.md](variables.md) before
using it for destructive work.

## 0. Non-Destructive Preflight

Working directory: repository root (`/home/steve/git/proxmox-homelab`).

```bash
git status --short
git branch --show-current
git rev-parse HEAD
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
```

Expected:

- clean working tree
- branch is the approved branch from `variables.md`
- commit SHA matches the approved commit
- target output is exactly `pve-test`

Stop if any expected value does not match.

## 1. Source Validation

Working directory: repository root (`/home/steve/git/proxmox-homelab`).

```bash
python3 terraform/lxc/validate-edge-manifests.py terraform/lxc/stacks/*/edge.yaml
python3 -m unittest \
	terraform/lxc/test_edge_manifest.py \
	terraform/lxc/test_render_edge_traefik.py \
	terraform/lxc/test_render_edge_coredns.py \
	terraform/lxc/test_discover_authentik_edge.py \
	terraform/lxc/test_reconcile_authentik_edge.py \
	terraform/lxc/test_reconcile_edge.py
git diff --check
```

Expected:

- all commands pass

## 2. Refresh Generated Edge Artifacts (Ignored Runtime Output)

Working directory: repository root (`/home/steve/git/proxmox-homelab`).

These commands mutate only ignored runtime artifacts under
`terraform/lxc/.generated/`.

```bash
rm -rf terraform/lxc/.generated/traefik terraform/lxc/.generated/coredns
python3 terraform/lxc/render-edge-traefik.py --json
python3 terraform/lxc/render-edge-coredns.py --json
./with-secrets python3 terraform/lxc/reconcile-edge.py --no-verify-tls --json
```

Expected:

- Traefik render has `stack_count: 6`, `legacy_route_count: 0`, and no issues.
- CoreDNS render has `generated_record_count: 6` and no issues.
- Reconciler dry-run passes or reports only approved planned work for the
  rebuild stage being executed.

## 3. Backup Gate

Working directory: repository root (`/home/steve/git/proxmox-homelab`).

Capture the evidence directory and log naming base:

```bash
STAMP="$(date -u +%Y%m%d-%H%M%S)"
EVIDENCE_DIR="docs/teardown-test/evidence/${STAMP}"
LOG_DIR="$EVIDENCE_DIR/logs"

mkdir -p "$EVIDENCE_DIR"
mkdir -p \
	"$EVIDENCE_DIR/backups/portainer" \
	"$EVIDENCE_DIR/backups/harbor" \
	"$EVIDENCE_DIR/backups/authentik" \
	"$EVIDENCE_DIR/backups/netbox" \
	"$EVIDENCE_DIR/backups/monitoring" \
	"$EVIDENCE_DIR/backups/traefik-certs" \
	"$EVIDENCE_DIR/backups/step-ca" \
	"$EVIDENCE_DIR/backups/ci-runner" \
	"$EVIDENCE_DIR/backups/apt-cacher"
mkdir -p "$LOG_DIR"

# Optional aggregate operator log.
RUN_LOG="$LOG_DIR/runbook-${STAMP}.log"
echo "runbook stamp=${STAMP}" | tee -a "$RUN_LOG"
```

Record:

- approved commit SHA
- target guard output
- stack scope
- backup IDs/paths for persistent services per `backup-plan.md`
- restore test evidence or written data-loss approval

Stop if any persistent service lacks either a verified backup/restore path or
explicit data-loss approval.

## 4. Destroy Gate

Working directory: repository root (`/home/steve/git/proxmox-homelab`).

Before any destroy:

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
```

Expected:

```text
pve-test
```

Operator must explicitly approve the destructive window after seeing:

- clean working tree
- approved commit
- backup evidence
- stack list to destroy
- rollback deadline

## 5. Destroy Execution

Working directory: repository root (`/home/steve/git/proxmox-homelab`).

Exact approved destroy order from [inventory.md](inventory.md):

1. `netbox-stack`
2. `monitoring-stack`
3. `authentik-stack`
4. `step-ca-stack`
5. `proxy-stack`
6. `dns-stack`
7. `ci-runner-01`
8. `harbor-stack`
9. `apt-cacher-stack`
10. `portainer-stack`

For each stack, run guard -> destroy -> VMID verify and capture evidence:

```bash
# Repeat per approved stack in the exact order above.
STACK="<stack>"
VMID="<vmid>"

./with-secrets bash -c 'echo $TF_VAR_proxmox_node'

(cd terraform/lxc/stacks/${STACK} && ../../../with-secrets terragrunt destroy -auto-approve) \
  2>&1 | tee "$LOG_DIR/destroy-${STACK}.log"

ssh -F /dev/null root@pve-test.gibbsgreatly.xyz "pct list | grep -F '${VMID}' || true" \
  2>&1 | tee "$LOG_DIR/verify-destroy-${STACK}.log"
```

Expected:

- selected VMID is absent
- no unapproved stack is destroyed

## 6. Foundation Redeploy

Working directory: repository root (`/home/steve/git/proxmox-homelab`).

Exact approved deploy order from [inventory.md](inventory.md), Stage 1/2 subset
for this section:

1. `portainer-stack`
2. `apt-cacher-stack`
3. `harbor-stack`
4. `ci-runner-01`

For each stack in this section, run guard -> apply -> capture evidence:

```bash
STACK="<stack>"

./with-secrets bash -c 'echo $TF_VAR_proxmox_node'

(cd terraform/lxc/stacks/${STACK} && ../../../with-secrets terragrunt apply -auto-approve) \
  2>&1 | tee "$LOG_DIR/deploy-${STACK}.log"
```

Validate service health using the stack-specific checks in the task files and
current runbooks.

## 7. Edge Foundation Redeploy

Working directory: repository root (`/home/steve/git/proxmox-homelab`).

Deploy exact Stage 3a order from [inventory.md](inventory.md):

1. `dns-stack`
2. `proxy-stack`
3. `step-ca-stack`
4. `authentik-stack`

If current Terraform metadata prevents this order, stop and resolve the
dependency conflict before continuing.

For each Stage 3a stack, run guard -> apply -> capture evidence:

```bash
STACK="<stack>"

./with-secrets bash -c 'echo $TF_VAR_proxmox_node'

(cd terraform/lxc/stacks/${STACK} && ../../../with-secrets terragrunt apply -auto-approve) \
  2>&1 | tee "$LOG_DIR/deploy-${STACK}.log"
```

Live validation block for Stage 3a (guard immediately before checks):

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'

dig @10.57.1.13 +short traefik.lab.gibbsgreatly.xyz
dig @10.57.1.1 +short traefik.lab.gibbsgreatly.xyz
curl -skI --resolve traefik.lab.gibbsgreatly.xyz:443:10.57.2.10 https://traefik.lab.gibbsgreatly.xyz
curl -sk -o /dev/null -w '%{http_code}\n' http://10.57.1.10:9000/-/health/live/
```

## 8. Edge Reconciliation Activation

Working directory: repository root (`/home/steve/git/proxmox-homelab`).

Regenerate artifacts after Stage 3a:

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'

python3 terraform/lxc/render-edge-traefik.py --json
python3 terraform/lxc/render-edge-coredns.py --json
./with-secrets python3 terraform/lxc/reconcile-edge.py --no-verify-tls --apply --json \
  2>&1 | tee "$LOG_DIR/reconcile-edge-apply.log"
```

Publish generated CoreDNS:

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'

(cd terraform/lxc/ansible && ../../../with-secrets ansible-playbook -i ../stacks/dns-stack/inventory.yml -u root playbooks/deploy-coredns.yml \
	-e coredns_generated_zone_src=/home/steve/git/proxmox-homelab/terraform/lxc/.generated/coredns/coredns-lab.zone) \
  2>&1 | tee "$LOG_DIR/publish-coredns.log"
```

Publish generated Traefik:

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'

(cd terraform/lxc/ansible && ../../../with-secrets ansible-playbook -i ../stacks/proxy-stack/inventory.yml -u root playbooks/deploy-proxy-stack.yml \
	-e traefik_generated_source_dir=/home/steve/git/proxmox-homelab/terraform/lxc/.generated/traefik) \
  2>&1 | tee "$LOG_DIR/publish-traefik.log"
```

## 9. Remaining Platform Redeploy

Working directory: repository root (`/home/steve/git/proxmox-homelab`).

Deploy exact remaining order from [inventory.md](inventory.md):

10. `monitoring-stack`
11. `netbox-stack`

For each stack in this section, run guard -> apply -> capture evidence:

```bash
STACK="<stack>"

./with-secrets bash -c 'echo $TF_VAR_proxmox_node'

(cd terraform/lxc/stacks/${STACK} && ../../../with-secrets terragrunt apply -auto-approve) \
  2>&1 | tee "$LOG_DIR/deploy-${STACK}.log"
```

After each deploy, run its direct service health check and the browser route
check if it is browser-facing.

## 10. Final Validation

Working directory: repository root (`/home/steve/git/proxmox-homelab`).

Live validation block (guard immediately before checks):

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'

for h in authentik harbor grafana portainer netbox traefik; do
	echo "== $h =="
	dig @10.57.1.13 +short "$h.lab.gibbsgreatly.xyz"
	dig @10.57.1.1 +short "$h.lab.gibbsgreatly.xyz"
	curl -sSI --resolve "$h.lab.gibbsgreatly.xyz:443:10.57.2.10" "https://$h.lab.gibbsgreatly.xyz" | sed -n '1,8p'
done

curl -skI https://harbor.lab.gibbsgreatly.xyz/v2/
./with-secrets python3 terraform/lxc/reconcile-edge.py --no-verify-tls --json
```

Expected:

- all six browser hosts resolve to `10.57.2.10`
- Harbor `/v2/` returns native registry auth challenge, not Authentik redirect
- Authentik route does not forward-auth itself
- Grafana uses native login/OIDC flow
- Portainer, NetBox, and Traefik dashboard use forward-auth
- final reconciler dry-run is passed/no-op

## 11. Stop Conditions

Stop and present options when:

- target guard is not `pve-test`
- backups are missing or unverified
- destroy affects an unapproved VMID
- a required Stage 3a service cannot bootstrap
- edge generated artifacts fail validation
- CoreDNS or Traefik publish fails
- Authentik API token is unavailable when needed
- a browser route regresses
- final reconciler dry-run is not clean

When any stop condition triggers, halt immediately and do not continue to the
next stack.

## 12. Rollback Direction (Planning)

Working directory: repository root (`/home/steve/git/proxmox-homelab`).

If failure occurs after destroy has started:

1. Re-run target guard and confirm `pve-test`.
2. Stop further destroy operations.
3. Resume apply from the most recently destroyed required dependency in approved
   deploy order.
4. Capture rollback command output under `$LOG_DIR/rollback-<stack>.log`.
5. Re-run the relevant service health checks before any additional action.

Rollback apply command template:

```bash
STACK="<stack>"

./with-secrets bash -c 'echo $TF_VAR_proxmox_node'

(cd terraform/lxc/stacks/${STACK} && ../../../with-secrets terragrunt apply -auto-approve) \
  2>&1 | tee "$LOG_DIR/rollback-${STACK}.log"
```

# Teardown/Deploy Test Runbook

This runbook is an execution skeleton. Fill [variables.md](variables.md) before
using it for destructive work.

## 0. Non-Destructive Preflight

Run from repository root:

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

## 2. Refresh Generated Edge Artifacts

Remove stale ignored artifacts or render into a fresh location:

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

Capture the evidence directory:

```bash
STAMP="$(date -u +%Y%m%d-%H%M%S)"
EVIDENCE_DIR="docs/teardown-test/evidence/${STAMP}"
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

Use the approved stack order from [variables.md](variables.md). Destroy in the
reverse of the approved deployment order unless the task document calls out a
service-specific exception.

For each stack:

```bash
cd terraform/lxc/stacks/<stack>
../../../with-secrets terragrunt destroy -auto-approve
```

After each destroy:

```bash
ssh -F /dev/null root@pve-test.gibbsgreatly.xyz "pct list | grep -F '<vmid>' || true"
```

Expected:

- selected VMID is absent
- no unapproved stack is destroyed

## 6. Foundation Redeploy

Deploy in the approved order. For each stack:

```bash
cd terraform/lxc/stacks/<stack>
../../../with-secrets terragrunt apply -auto-approve
```

Validate service health using the stack-specific checks in the task files and
current runbooks.

## 7. Edge Foundation Redeploy

Deploy Stage 3a in the approved order:

1. `dns-stack`
2. `proxy-stack`
3. `step-ca-stack`
4. `authentik-stack`

If current Terraform metadata prevents this order, stop and resolve the
dependency conflict before continuing.

Required checks:

```bash
dig @10.57.1.13 +short traefik.lab.gibbsgreatly.xyz
dig @10.57.1.1 +short traefik.lab.gibbsgreatly.xyz
curl -skI --resolve traefik.lab.gibbsgreatly.xyz:443:10.57.2.10 https://traefik.lab.gibbsgreatly.xyz
curl -sk -o /dev/null -w '%{http_code}\n' http://10.57.1.10:9000/-/health/live/
```

## 8. Edge Reconciliation Activation

Regenerate artifacts after Stage 3a:

```bash
python3 terraform/lxc/render-edge-traefik.py --json
python3 terraform/lxc/render-edge-coredns.py --json
./with-secrets python3 terraform/lxc/reconcile-edge.py --no-verify-tls --apply --json
```

Publish generated CoreDNS:

```bash
cd terraform/lxc/ansible
../../../with-secrets ansible-playbook -i ../stacks/dns-stack/inventory.yml -u root playbooks/deploy-coredns.yml \
	-e coredns_generated_zone_src=/home/steve/git/proxmox-homelab/terraform/lxc/.generated/coredns/coredns-lab.zone
```

Publish generated Traefik:

```bash
cd terraform/lxc/ansible
../../../with-secrets ansible-playbook -i ../stacks/proxy-stack/inventory.yml -u root playbooks/deploy-proxy-stack.yml \
	-e traefik_generated_source_dir=/home/steve/git/proxmox-homelab/terraform/lxc/.generated/traefik
```

## 9. Remaining Platform Redeploy

Deploy the remaining selected Stage 3b stacks in approved dependency order.
After each deploy, run its direct service health check and the browser route
check if it is browser-facing.

## 10. Final Validation

```bash
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

# Teardown/Deploy Test Runbook

This runbook is an execution skeleton. Fill [variables.md](variables.md) before
using it for destructive work.

Use [lessons-learned.md](lessons-learned.md) together with this runbook when
preparing a new rehearsal cycle. Historical checkpoint docs are records, not
the current command contract.

**Primary path:** Use `scripts/teardown-deploy-test.sh` for all phases. The
harness handles target-guard enforcement, approval-packet validation, evidence
capture, and inventory-derived stack ordering. Sections 5–9 below are the
equivalent manual fallback for environments where the harness is unavailable.
Keep them in sync with harness behavior; prefer the harness over the manual
commands.

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

For a read-only inventory snapshot of the current `pve-test` containers before
or after a cycle, run:

```bash
scripts/teardown-deploy-test.sh platform-status
```

Expected:

- the target guard reports `pve-test`
- every in-scope stack is listed with VMID, IP, `pct` state, direct health
  status, and evidence log paths
- the generated `platform-status.tsv` and `platform-status.json` files are kept
  under the command's evidence stamp

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
./with-secrets python3 terraform/lxc/reconcile-edge.py \
	--authentik-url http://${lab_ip_authentik}:9000 --no-verify-tls --json
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

For pve-test teardown rehearsals, backup evidence is advisory only: record gaps
in evidence and continue. Do not block destroy/redeploy on missing backup
artifacts.

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

Harness execution for destructive phases now requires an approval packet in
addition to `--execute` and `--approval-text`:

```bash
scripts/teardown-deploy-test.sh destroy --execute \
	--approval-text "I approve pve-test teardown deploy test validation only" \
	--approval-packet docs/teardown-test/packets/<stamp>.md \
	--stamp <stamp>
```

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

ssh -F /dev/null root@pve-test.gibbsgreatly.xyz \
  "if pct status '${VMID}' >/dev/null 2>&1; then echo 'VMID still present' >&2; exit 1; fi" \
  2>&1 | tee "$LOG_DIR/verify-destroy-${STACK}.log"
```

Expected:

- selected VMID is absent
- no unapproved stack is destroyed

## 6. Foundation Redeploy

Working directory: repository root (`/home/steve/git/proxmox-homelab`).

Exact approved deploy order from [inventory.md](inventory.md), Stage 1/2 subset
for this section:

1. `apt-cacher-stack`
2. `ci-runner-01`

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
2. `step-ca-stack`
3. `proxy-stack`
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

dig @${lab_ip_dns} +short traefik.lab.gibbsgreatly.xyz
dig @${lab_gw_mgmt} +short traefik.lab.gibbsgreatly.xyz
curl -skI --resolve traefik.lab.gibbsgreatly.xyz:443:${lab_ip_proxy} https://traefik.lab.gibbsgreatly.xyz
curl -sk -o /dev/null -w '%{http_code}\n' http://${lab_ip_authentik}:9000/-/health/live/
```

## 8. Edge Reconciliation Activation

Working directory: repository root (`/home/steve/git/proxmox-homelab`).

Regenerate artifacts after Stage 3a:

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'

python3 terraform/lxc/render-edge-traefik.py --json
python3 terraform/lxc/render-edge-coredns.py --json
./with-secrets python3 terraform/lxc/reconcile-edge.py \
	--authentik-url http://${lab_ip_authentik}:9000 --no-verify-tls --apply --json \
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

Deploy exact remaining order from [inventory.md](inventory.md), Stage 3b subset:

8. `harbor-stack`
9. `monitoring-stack`
10. `netbox-stack`
11. `portainer-stack`

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
	dig @${lab_ip_dns} +short "$h.lab.gibbsgreatly.xyz"
	dig @${lab_gw_mgmt} +short "$h.lab.gibbsgreatly.xyz"
	curl -sSI --resolve "$h.lab.gibbsgreatly.xyz:443:${lab_ip_proxy}" "https://$h.lab.gibbsgreatly.xyz" | sed -n '1,8p'
done

curl -skI https://harbor.lab.gibbsgreatly.xyz/v2/
./with-secrets python3 terraform/lxc/reconcile-edge.py \
	--authentik-url http://${lab_ip_authentik}:9000 --no-verify-tls --json
```

Expected:

- all six browser hosts resolve to `${lab_ip_proxy}`
- Harbor `/v2/` returns native registry auth challenge, not Authentik redirect
- Authentik route does not forward-auth itself
- Grafana uses native login/OIDC flow
- Portainer, NetBox, and Traefik dashboard use forward-auth
- final reconciler dry-run is passed/no-op

Direct service validation corrections:

```bash
curl -fsS http://${lab_ip_portainer}:9000/api/system/status
```

Use the Portainer API on port `9000` for direct validation. Do not reuse older
checkpoint-era probes that targeted the wrong endpoint.

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
- direct Portainer API validation fails on port `9000`
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

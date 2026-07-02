# Stack-Owned Edge Validation Runbook

This runbook is the shared validation and rollback contract for Task 15 through
Task 21 route migrations.

All migrations must use the same vocabulary, command patterns, expected
outcomes, and stop conditions documented here.

## Scope and Safety

- Scope is pve-test-vm only.
- Dry-run is the default for edge reconciliation.
- Do not run apply/mutation commands until all preflight checks pass.
- Stop immediately and present options if a validation command would mutate live
	infrastructure.

## Shared Validation Vocabulary

Use these exact terms in task notes, PR comments, and operator handoff.

- Preflight: non-mutating target and health checks before apply.
- Dry-run: manifest validation, render output, and reconciliation planning with
	no live mutation.
- Apply gate: explicit operator intent (`--apply`) plus healthy pve-test-vm,
	Traefik, and CoreDNS preflight state.
- Pending changes: generated output or reconciliation actions still not
	converged.
- No-op: second dry-run after publish reports passed status, no issues, and no
	remaining migration changes.
- Generated snapshot: timestamped backup of generated files and live deployed
	files taken before migration apply.
- Rollback: restore previous generated snapshot, republish, and revalidate.

## 1. Preflight (Required Before Every Migration)

Run from repository root:

```bash
./with-secrets bash -c 'echo $TF_VAR_proxmox_node'
```

Expected outcome:
- Output is exactly `pve-test-vm`.

Stop condition:
- Any output other than `pve-test-vm`.

Run from repository root:

```bash
python3 terraform/lxc/validate-edge-manifests.py terraform/lxc/stacks/*/edge.yaml
```

Expected outcome:
- Exit code `0`.
- No edge-manifest schema/collision errors.

Stop condition:
- Any manifest validation failure.

Run from repository root:

```bash
if grep -R -qE 'mode:\s*forwardAuth' terraform/lxc/stacks/*/edge.yaml; then
	./with-secrets bash -c 'test -n "$AUTHENTIK_SUPERUSER_API_TOKEN" && echo AUTHENTIK_SUPERUSER_API_TOKEN=present'
else
	echo "No forwardAuth routes selected; Authentik token preflight not required."
fi
```

Expected outcome:
- When any selected route uses `auth.mode: forwardAuth`, output confirms
	`AUTHENTIK_SUPERUSER_API_TOKEN=present`.
- When no selected route uses forwardAuth, token preflight is explicitly skipped.

Stop condition:
- A selected forwardAuth route exists and
	`AUTHENTIK_SUPERUSER_API_TOKEN` is missing/empty.

Run from repository root (apply-mode gate probes):

```bash
timeout 5 bash -lc '</dev/tcp/192.168.30.10/443'
dig @192.168.20.13 +short traefik.lab.gibbsgreatly.xyz
dig @192.168.20.1 +short traefik.lab.gibbsgreatly.xyz
```

Expected outcome:
- TCP connect to `192.168.30.10:443` succeeds.
- Authoritative CoreDNS answer for `traefik.lab.gibbsgreatly.xyz` includes
	`192.168.30.10`.
- Delegated resolver answer for `traefik.lab.gibbsgreatly.xyz` includes
	`192.168.30.10`.

Stop condition:
- Traefik TCP reachability probe fails.
- CoreDNS authoritative `dig` probe fails or returns an unexpected answer.
- Delegated resolver `dig` probe fails or returns an unexpected answer.

## 2. Shared Dry-Run Flow (Task 11 Reconciler Contract)

### 2.1 Baseline dry-run (all manifests)

Run from repository root:

```bash
python3 terraform/lxc/reconcile-edge.py --json | tee /tmp/reconcile-edge-dryrun.json
```

Expected outcome:
- JSON includes `"mode": "dry-run"`.
- JSON includes `"terraform_state_mutation": false`.
- JSON includes `"status": "passed"`.
- JSON `issues` is empty.

After more than one `forwardAuth` service has been migrated, use this
all-manifest form for post-cutover convergence. Single-manifest reconciler runs
can report owned Authentik objects from other migrated stacks as unmanaged
because those manifests are outside the selected scope.

### 2.2 Migration dry-run (single intended replacement host)

Run from repository root (replace stack and host):

```bash
python3 terraform/lxc/reconcile-edge.py \
	terraform/lxc/stacks/<stack>/edge.yaml \
	--intended-replacement-host <host>.lab.gibbsgreatly.xyz \
	--json | tee /tmp/reconcile-edge-migration-dryrun.json
```

Expected outcome:
- Status is passed.
- No accidental duplicate-host collision errors.
- Renderer accepts only the one explicit intended replacement host.
- No unexpected generated changes outside the targeted migration host.

Stop condition:
- Any failed status.
- Any collision issue that is not the explicitly intended replacement host.

## 3. Generated Snapshot (Take Before Any Publish)

Run from repository root:

```bash
TS="$(date +%Y%m%d-%H%M%S)"
SNAP_DIR="docs/provisioning-refactor/snapshots/$TS"
mkdir -p "$SNAP_DIR/traefik" "$SNAP_DIR/coredns" "$SNAP_DIR/live"

cp -a terraform/lxc/.generated/traefik/. "$SNAP_DIR/traefik/" 2>/dev/null || true
cp -a terraform/lxc/.generated/coredns/coredns-lab.zone "$SNAP_DIR/coredns/" 2>/dev/null || true

./with-secrets ansible -i '192.168.30.10,' -u root all -m fetch -a "src=/opt/proxy-stack/dynamic/authentik.yml dest=$SNAP_DIR/live/ flat=yes" || true
./with-secrets ansible -i '192.168.30.10,' -u root all -m shell -a "tar -C /opt/proxy-stack/dynamic -cf /tmp/proxy-dynamic.tar ." || true
./with-secrets ansible -i '192.168.30.10,' -u root all -m fetch -a "src=/tmp/proxy-dynamic.tar dest=$SNAP_DIR/live/ flat=yes" || true
mkdir -p "$SNAP_DIR/live/dynamic"
tar -xf "$SNAP_DIR/live/proxy-dynamic.tar" -C "$SNAP_DIR/live/dynamic" 2>/dev/null || true
rm -f "$SNAP_DIR/live/proxy-dynamic.tar"
./with-secrets ansible -i '192.168.20.13,' -u root all -m fetch -a "src=/etc/coredns/lab.zone dest=$SNAP_DIR/live/coredns-lab.zone flat=yes" || true

echo "snapshot=$SNAP_DIR"
```

Expected outcome:
- Snapshot directory is created.
- Generated and live files are captured where available.

Stop condition:
- Snapshot path is missing or empty for artifacts you are about to change.

## 4. CoreDNS Publish and Validation (Task 12 Wiring)

### 4.1 Connectivity precheck

Run from `terraform/lxc/ansible`:

```bash
../../../with-secrets ansible -i '192.168.20.13,' -u root all -m ping
```

Expected outcome:
- Host responds successfully.

### 4.2 Publish generated zone

Run from `terraform/lxc/ansible`:

```bash
../../../with-secrets ansible-playbook -i ../stacks/dns-stack/inventory.yml -u root playbooks/deploy-coredns.yml \
	-e coredns_generated_zone_src=/home/steve/git/proxmox-homelab/terraform/lxc/.generated/coredns/coredns-lab.zone
```

Expected outcome:
- Staged zone passes `named-checkzone`.
- Bootstrap authority guardrails pass (SOA/NS/ns1 preserved).
- CoreDNS service is running after handler flush.

Stop condition:
- Zone validation fails.
- Bootstrap authority records are missing.

### 4.3 Authoritative and delegated answer validation

Run from repository root:

```bash
dig @192.168.20.13 +short traefik.lab.gibbsgreatly.xyz
dig @192.168.20.1 +short traefik.lab.gibbsgreatly.xyz
dig @192.168.20.1 +short authentik.lab.gibbsgreatly.xyz
```

Expected outcome:
- All browser hosts resolve to `192.168.30.10`.
- MikroTik delegated forwarding returns the same answer path as CoreDNS.

Stop condition:
- Any browser host does not resolve to `192.168.30.10`.
- Delegated forwarding is inconsistent with CoreDNS answers.

## 5. Traefik Generated-File Validation and Deploy (Task 13 Wiring)

### 5.1 Local compose and generated-file sanity

Run from repository root:

```bash
test -d terraform/lxc/.generated/traefik
ls -1 terraform/lxc/.generated/traefik/*.yml
```

Expected outcome:
- Generated per-stack files exist for the migration target.

### 5.2 Real-context playbook check (required before live deploy)

Run from `terraform/lxc/ansible`:

```bash
../../../with-secrets ansible -i '192.168.30.10,' -u root all -m ping
../../../with-secrets ansible-playbook -i ../stacks/proxy-stack/inventory.yml -u root --check playbooks/deploy-proxy-stack.yml \
	-e traefik_generated_source_dir=/home/steve/git/proxmox-homelab/terraform/lxc/.generated/traefik
```

Expected outcome:
- Target host is reachable.
- Playbook check mode completes without syntax/runtime validation errors.

Stop condition:
- Check mode reports a failure.

### 5.3 Live deploy and Traefik runtime validation

Run from `terraform/lxc/ansible`:

```bash
../../../with-secrets ansible-playbook -i ../stacks/proxy-stack/inventory.yml -u root playbooks/deploy-proxy-stack.yml \
	-e traefik_generated_source_dir=/home/steve/git/proxmox-homelab/terraform/lxc/.generated/traefik
../../../with-secrets ansible -i ../stacks/proxy-stack/inventory.yml proxy_stack -u root -a "docker compose -f /opt/proxy-stack/docker-compose.yml config -q"
../../../with-secrets ansible -i ../stacks/proxy-stack/inventory.yml proxy_stack -u root -m shell -a "ls -1 /opt/proxy-stack/dynamic/*.yml"
```

Expected outcome:
- Deploy succeeds.
- `docker compose ... config -q` passes.
- Traefik file provider remains healthy and watching `/etc/traefik/dynamic/`.
- Generated per-stack files are present under `/opt/proxy-stack/dynamic/*.yml`
	(active watched directory).

Stop condition:
- Compose config validation fails.
- Traefik cannot parse dynamic files.

## 6. Route, HTTPS, Certificate, and Auth Validation

Run from repository root:

```bash
for h in traefik grafana authentik portainer harbor netbox; do
	echo "== $h.lab.gibbsgreatly.xyz =="
	curl -sSI --resolve "$h.lab.gibbsgreatly.xyz:443:192.168.30.10" "https://$h.lab.gibbsgreatly.xyz" | grep -E 'HTTP/|location:|server:'
done
```

Expected outcome:
- Each route returns an HTTP response via Traefik.
- Route behavior matches `auth.mode` in the stack `edge.yaml`:
	`forwardAuth` routes redirect to/through Authentik and `none` routes do not.
- Authentik route itself does not self-protect (no forward-auth recursion).

Run from repository root:

```bash
for h in traefik grafana authentik portainer harbor netbox; do
	echo "== cert $h.lab.gibbsgreatly.xyz =="
	echo | openssl s_client -connect 192.168.30.10:443 -servername "$h.lab.gibbsgreatly.xyz" 2>/dev/null \
		| openssl x509 -noout -subject -issuer -ext subjectAltName
done
```

Expected outcome:
- Certificate SAN includes `DNS:*.lab.gibbsgreatly.xyz` (or explicit host entry
	for the migrated route).
- Issuer chain and certificate subject match expected lab certificate policy.

Run from repository root:

```bash
curl -sk -o /dev/null -w '%{http_code}\n' http://192.168.20.10:9000/-/health/live/
curl -sk -o /dev/null -w '%{http_code}\n' https://authentik.lab.gibbsgreatly.xyz/application/o/
```

Expected outcome:
- Direct Authentik liveness is healthy (typically `204`).
- Authentik discovery/OIDC endpoint is reachable over routed HTTPS.

Stop condition:
- Redirect loops.
- Any route returns no response over Traefik.
- TLS trust fails or certificate SAN/issuer is not the expected value.
- Authentik API/discovery is unavailable.

## 7. Post-Apply Convergence Check

Re-run dry-run after every migration publish.

Run from repository root:

```bash
python3 terraform/lxc/reconcile-edge.py --json | tee /tmp/reconcile-edge-post-apply.json
```

Expected outcome:
- Passed status.
- No remaining accidental duplicate-host issues.
- No migration residue; run is functionally no-op for the completed migration.
- After multiple `forwardAuth` migrations, convergence is checked with no
	manifest arguments so all migrated Authentik-owned routes are in scope.

Stop condition:
- Any pending migration drift remains.

## 8. Rollback from Generated Snapshot

Use the latest snapshot created in Section 3.

### 8.1 Roll back CoreDNS zone

Run from `terraform/lxc/ansible` (replace snapshot path):

```bash
SNAP_DIR=/home/steve/git/proxmox-homelab/docs/provisioning-refactor/snapshots/<timestamp>
../../../with-secrets ansible-playbook -i '192.168.20.13,' -u root playbooks/deploy-coredns.yml \
	-e coredns_generated_zone_src="$SNAP_DIR/live/coredns-lab.zone"
```

Expected outcome:
- Previous zone is republished and validated by the same CoreDNS guardrails.

### 8.2 Roll back Traefik dynamic stacks files

Run from `terraform/lxc/ansible` (replace snapshot path):

```bash
SNAP_DIR=/home/steve/git/proxmox-homelab/docs/provisioning-refactor/snapshots/<timestamp>
../../../with-secrets ansible -i '192.168.30.10,' -u root all -m copy -a "src=$SNAP_DIR/live/dynamic/ dest=/opt/proxy-stack/dynamic/ mode=0640"
../../../with-secrets ansible-playbook -i ../stacks/proxy-stack/inventory.yml -u root playbooks/deploy-proxy-stack.yml
```

Expected outcome:
- Previous generated files are restored.
- Traefik accepts restored config and routes recover.

### 8.3 Validate rollback

Repeat Sections 4.3 and 6.

Stop condition:
- Rollback cannot restore known-good DNS or route behavior.

## 9. Mandatory Stop-and-Present-Options Triggers

Stop and present options (do not continue) when any of the following occur:

- pve-test-vm preflight fails.
- A command labeled as validation is discovered to be mutating.
- Reconciler reports failed status or collision issues.
- Apply-mode Traefik/CoreDNS health preflight checks fail.
- CoreDNS guardrail assertions fail.
- Traefik compose/file-provider validation fails.
- Duplicate route ownership or unexpected generated-file changes are detected.
- Route/auth checks indicate redirect recursion or route blackhole.
- DNS, certificate, or auth behavior regresses from pre-migration baseline.
- Rollback cannot restore previous known-good state.

## 10. Minimum Evidence to Attach to Every Migration Task

Attach these artifacts to Task 15+ execution notes:

- Reconciler dry-run JSON before apply.
- Snapshot directory path.
- CoreDNS publish output and delegated-answer checks.
- Proxy real-context check output and deploy output.
- Route/cert/auth validation output.
- Reconciler dry-run JSON after apply (no-op expectation).
- Rollback test output when rollback is exercised.

# Platform Hardening Plan

## Part A: Docker Socket Proxy Deploy-Time Enablement

### A1 — Cherry-pick the socket proxy role and proof artifacts

Source branch: `work/socket-proxy-metadata-review`

Cherry-pick or manually copy the following into the new work branch. Do not
bring across any session handback docs or evidence files.

Files to bring:

```
terraform/lxc/ansible/roles/docker_socket_proxy/
  defaults/main.yml
  tasks/main.yml
  templates/docker-compose.yml.j2

terraform/lxc/stacks/docker-socket-proxy-test/
  stack.yaml
  docker-compose.yml
  terragrunt.hcl

terraform/lxc/ansible/playbooks/deploy-docker-socket-proxy-test.yml
terraform/lxc/ansible/playbooks/test-docker-socket-proxy-role.yml
```

Validation: `ansible-playbook --syntax-check` passes for
`deploy-docker-socket-proxy-test.yml` and any playbook that imports the role.

---

### A2 — Enable socket proxy in four baseline stacks

Scope: harbor-stack, proxy-stack, authentik-stack, portainer-stack.

Leave monitoring-stack and netbox-stack disabled. Those branches enable their
own stacks when they land.

For each of the four stacks:

1. Set `enable_docker_socket_proxy: true` in the stack's configuration
   (stack.yaml or a dedicated vars file — follow whichever pattern is cleaner
   given how the role receives its vars; see A3 for the propagation side).
2. Set `docker_socket_proxy_bind_addr` to the stack's service IP. This must be
   the host IP that is reachable from NetBox on the `infra_seg` VLAN, not
   loopback.
3. Leave `docker_socket_proxy_listen_port` at the default (`2375`) unless there
   is a conflict.

The bind address constraint is important: loopback (`127.0.0.1`) means only
processes on the same host can reach the proxy. The proxy must be reachable from
the NetBox LXC across `infra_seg`.

---

### A3 — Propagate socket proxy metadata into Ansible

The role variables (`enable_docker_socket_proxy`, `docker_socket_proxy_bind_addr`,
`docker_socket_proxy_listen_port`) must reach the playbook at deploy time.

Preferred path: add these fields to `inventory.tpl` so they appear in the
generated `inventory.yml` for each stack. This keeps the pattern consistent
with how `ansible_playbook`, `registry_host`, and `apt_cacher_host` are already
propagated — the template reads from `stack.yaml` via `main.tf`, and the
generated inventory carries the values into Ansible as host vars.

Changes needed:

- `terraform/lxc/main.tf`: read socket-proxy fields from `local.stack` and pass
  to the `local_file.ansible_inventory` template call.
- `terraform/lxc/templates/inventory.tpl`: add socket-proxy vars to the host
  vars block.
- Regenerate inventory for each of the four enabled stacks by running
  `terragrunt apply` (plan-only change; no infrastructure changes).

Validation: `cat terraform/lxc/stacks/harbor-stack/inventory.yml` shows
`enable_docker_socket_proxy: true` and the correct bind address.

---

### A4 — Verify the role is called in each playbook

The socket proxy branch wired the role into the six managed stack playbooks.
Confirm it is present and positioned after `docker_base` in each of the four
baseline stack playbooks:

```
terraform/lxc/ansible/playbooks/deploy-harbor-stack.yml
terraform/lxc/ansible/playbooks/deploy-proxy-stack.yml
terraform/lxc/ansible/playbooks/deploy-authentik-stack.yml
terraform/lxc/ansible/playbooks/deploy-portainer-stack.yml
```

If any playbook is missing the role call, add it:

```yaml
- role: docker_socket_proxy
  vars:
    enable_docker_socket_proxy: "{{ enable_docker_socket_proxy | default(false) }}"
```

Validation: `ansible-playbook --syntax-check` passes for all four playbooks.

---

## Part B: Holistic Edge Reconciliation

### B1 — Verify edge.yaml coverage

All six browser-facing stacks already have `edge.yaml` files on
`baseline/teardown-validated`. Confirm their content is current and covers:

- Traefik router/service intent (hostname, backend IP and port, TLS)
- CoreDNS record intent (hostname → Traefik IP)
- Authentik provider intent (if the service uses SSO)

Stacks to check: `authentik-stack`, `harbor-stack`, `portainer-stack`,
`proxy-stack`. (monitoring and netbox are not in baseline yet; their
`edge.yaml` files are already present and will be picked up automatically once
those branches land.)

If a field is stale (e.g., wrong backend IP), correct it now. These files are
the source of truth for the holistic reconciliation pass.

---

### B2 — Refactor provision.sh: replace Portainer-specific reconciliation with a holistic pass

Current state: `provision.sh` has two Portainer-specific functions,
`ensure_portainer_oauth_secret` and `ensure_portainer_edge_publish`, called
inside the per-stack deploy loop. `ensure_portainer_edge_publish` calls
`reconcile-edge.py` with a single edge.yaml and then re-runs the proxy-stack
playbook to push the generated Traefik config.

Target state: a single `reconcile_all_edge` function runs after all stacks are
deployed. It calls `reconcile-edge.py` with `--stacks-dir` so all `edge.yaml`
files are processed in one pass.

Implementation:

1. Add a `reconcile_all_edge` function after the per-stack deploy loop:

```bash
reconcile_all_edge() {
  local check_mode="$1"
  local stacks_dir="$STACKS_DIR"
  local proxy_inventory="${stacks_dir}/proxy-stack/inventory.yml"
  local proxy_playbook="${ANSIBLE_DIR}/playbooks/deploy-proxy-stack.yml"
  local generated_traefik_dir="${REPO_ROOT}/terraform/lxc/.generated/traefik"

  [[ -f "$proxy_inventory" ]] || { log "SKIP edge reconcile: proxy-stack inventory not found"; return 0; }

  local reconcile_args=(
    python3 "${REPO_ROOT}/terraform/lxc/reconcile-edge.py"
    --stacks-dir "$stacks_dir"
    --authentik-url "https://authentik-int.${LAB_DOMAIN:-lab.gibbsgreatly.xyz}:9443"
    --no-verify-tls
    --json
  )

  if [[ "$check_mode" == "true" ]]; then
    log "Edge reconcile dry-run (all stacks)"
    "${reconcile_args[@]}"
  else
    log "Edge reconcile apply (all stacks)"
    "${reconcile_args[@]}" --apply

    log "Push generated Traefik config to proxy-stack"
    ansible-playbook -i "$proxy_inventory" -u root "$proxy_playbook" \
      -e "traefik_generated_source_dir=${generated_traefik_dir}"
  fi
}
```

2. Remove the `ensure_portainer_edge_publish` call from inside the per-stack
   loop. Portainer's edge is now covered by the holistic pass.

3. Keep `ensure_portainer_oauth_secret` as-is (it is Portainer-specific and
   must run before Portainer is deployed, not at the end).

4. Call `reconcile_all_edge "$check_mode"` after the main deploy loop, before
   `log "Completed provision orchestration"`.

5. Verify the CoreDNS pre-generation (the `dns-stack` special case at line ~383)
   is still in place and unchanged. It generates the zone before deploying
   dns-stack; the holistic pass handles Traefik and Authentik at the end. These
   are complementary, not redundant.

Validation: dry-run `provision.sh --check` completes without error and shows
the reconcile step running for all stacks.

---

### B3 — Test holistic reconciliation on pve-test before teardown

With the cluster running (not from a teardown), run:

```bash
./with-secrets scripts/provision.sh --stack proxy-stack
```

Then manually invoke the reconcile against the live cluster:

```bash
./with-secrets python3 terraform/lxc/reconcile-edge.py \
  --stacks-dir terraform/lxc/stacks \
  --authentik-url "https://authentik-int.${LAB_DOMAIN}:9443" \
  --no-verify-tls \
  --json
```

Confirm the dry-run output covers all four baseline browser-facing stacks
(authentik, harbor, portainer, proxy). Then run with `--apply` and verify:

- Traefik dynamic config files exist in `.generated/traefik/` for each stack.
- Traefik is serving the expected routes (check `https://traefik.lab.gibbsgreatly.xyz`
  or curl the router list from the Traefik API).
- CoreDNS returns correct A records for each service hostname.
- Authentik shows OIDC providers for expected services.

---

## Part C: Teardown Test (Promotion Gate)

### C1 — Full teardown and redeploy

Run the standard teardown/rebuild cycle per `docs/teardown-test/runbook.md`.

During the rebuild, provision.sh must complete without manual intervention for
edge reconciliation or socket proxy setup.

### C2 — Post-rebuild socket proxy verification

For each of the four enabled stacks (harbor, proxy, authentik, portainer),
verify from the NetBox LXC (or any host on `infra_seg`):

```bash
curl http://<stack-ip>:2375/containers/json?all=1
```

Expected: HTTP 200, JSON array of container objects.

Also verify mutation is blocked:

```bash
curl -X POST http://<stack-ip>:2375/containers/create
```

Expected: HTTP 403.

### C3 — Post-rebuild edge reconciliation verification

After provision.sh completes, verify without any manual steps:

- `https://harbor.lab.gibbsgreatly.xyz` is reachable via Traefik.
- `https://authentik.lab.gibbsgreatly.xyz` is reachable via Traefik.
- `https://portainer.lab.gibbsgreatly.xyz` is reachable via Traefik.
- CoreDNS returns the correct IP for each service hostname.
- Authentik OIDC providers exist for services that declare them in `edge.yaml`.

All of the above must be true without running any reconciliation command manually.

### C4 — Promote to baseline/teardown-validated

If C1–C3 pass, merge the work branch to `baseline/teardown-validated` with a
promotion stamp commit.

---

## Sequencing Summary

```
A1  Cherry-pick role and proof artifacts from work/socket-proxy-metadata-review
A2  Enable socket proxy in four baseline stacks (harbor, proxy, authentik, portainer)
A3  Propagate socket proxy metadata through inventory.tpl and main.tf
A4  Verify role is called in each of the four playbooks
B1  Verify edge.yaml coverage for four baseline stacks
B2  Refactor provision.sh: replace Portainer-specific reconciliation with holistic pass
B3  Test holistic reconciliation on live pve-test (before teardown)
C1  Full teardown and redeploy
C2  Socket proxy endpoint verification on all four stacks
C3  Edge reconciliation verification (no manual steps)
C4  Promote to baseline/teardown-validated
```

A1–A4 and B1–B3 can overlap. C1 must follow all of A and B.

---

## Out of Scope for This Branch

- Enabling socket proxy on monitoring-stack or netbox-stack. Those branches
  handle their own enablement.
- Creating new edge.yaml files. All six are already present.
- Changes to MikroTik ACLs or SDN zone policy.
- Production (`pve`) deployment. pve-test only until the baseline gate passes.
- Loki retention, step-ca scrape job, or other monitoring-stack gaps. Those
  belong in `task/monitoring-stack-phase1`.

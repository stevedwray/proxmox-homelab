# Session 7 Summary — Representative Validation (apt-cacher-stack)

Date: 2026-05-22

## Scope

Session 7 representative validation started with `apt-cacher-stack` only,
as required by the validation order.

Operator-provided context for this session:

1. Session 6 preflight already passed on 2026-05-22 from the operator
   workstation on the lab LAN.
2. Representative guest reachability to `192.168.40.11` already succeeded.

No teardown was started.

## Commands Executed

1. Targeting guard:
   - `./with-secrets bash -c 'echo "$TF_VAR_proxmox_node"'`
2. Apt-cacher stack plan/apply:
   - `./with-secrets bash -lc 'cd terraform/lxc/stacks/apt-cacher-stack && terragrunt plan -no-color'`
   - `./with-secrets bash -lc 'cd terraform/lxc/stacks/apt-cacher-stack && terragrunt apply -auto-approve -no-color'`
3. Inventory evidence capture:
   - `sed -n '1,80p' terraform/lxc/stacks/apt-cacher-stack/inventory.yml`
   - `rg -n "ProxyJump|ssh_access_mode|ansible_host|pve_host" terraform/lxc/stacks/apt-cacher-stack/inventory.yml`
4. Provisioning validation:
   - `./with-secrets ./scripts/provision.sh --stack apt-cacher-stack --check`
   - `./with-secrets ./scripts/provision.sh --stack apt-cacher-stack`
5. Health checks:
   - `nc -vz 192.168.40.11 3142`
   - `./with-secrets ansible -i terraform/lxc/stacks/apt-cacher-stack/inventory.yml apt-cacher-stack -m ansible.builtin.command -a 'systemctl is-active apt-cacher-ng'`
6. Host-route priming retirement evidence (state):
   - `./with-secrets bash -lc 'cd terraform/lxc/stacks/apt-cacher-stack && terragrunt state list | rg "prime_sdn_host_route|ansible_inventory|configure_network_sdn_attachment|module.lxc"'`

## Evidence

### 1. Generated inventory uses guest IP directly

From `terraform/lxc/stacks/apt-cacher-stack/inventory.yml` after apply:

1. `ansible_host: 192.168.40.11`
2. `ssh_access_mode: direct`

### 2. Default ProxyJump is not used for apt-cacher-stack

From the same generated inventory:

1. `ansible_ssh_common_args` contains only strict host-key options.
2. No `ProxyJump` token appears.
3. No `pve_host` key is emitted for this host.

`terragrunt plan` showed the compatibility inventory being replaced:

1. `ansible_ssh_common_args` changed from ProxyJump form to direct form.
2. `ssh_access_mode: direct` added.
3. `pve_host` removed from generated host vars.

### 3. Provisioning succeeds without host-route priming

`terragrunt apply` for apt-cacher-stack completed successfully and removed the
legacy state-only host-route shim:

1. `null_resource.prime_sdn_host_route[0]` destroyed because it is not in
   configuration.
2. Apply result: `2 added, 0 changed, 2 destroyed`.

Post-apply state list confirms no `prime_sdn_host_route` remains.

Provisioning then succeeded via stack inventory path:

1. Check mode play recap: `unreachable=0 failed=0`.
2. Live play recap: `ok=5 changed=0 unreachable=0 failed=0`.

### 4. apt-cacher-stack health checks pass

1. TCP service reachability from workstation path:
   - `nc -vz 192.168.40.11 3142` => connection succeeded.
2. In-guest service state via Ansible:
   - `systemctl is-active apt-cacher-ng` => `active`.

## Result

`apt-cacher-stack` passes Session 7 representative validation for the
direct-access model:

1. Direct guest-IP inventory is in effect.
2. Default ProxyJump is not used.
3. Provisioning succeeds without host-route priming.
4. Stack health checks pass.

## Can mgmt_seg Representative Validation Proceed?

Yes. Based on this apt-cacher representative result, the next Session 7 step
(one `mgmt_seg` stack such as `dns-stack` or `step-ca-stack`) can proceed.

---

## Session 7 Update — mgmt_seg Representative Validation (dns-stack)

Date: 2026-05-22

### Scope

Validated `dns-stack` as the required `mgmt_seg` representative stack using
the direct-access model on `pve-test`.

### Commands Executed

1. Targeting guard:
   - `./with-secrets bash -c 'echo "$TF_VAR_proxmox_node"'`
2. Dns stack plan/apply:
   - `./with-secrets bash -lc 'cd terraform/lxc/stacks/dns-stack && terragrunt plan -no-color'`
   - `./with-secrets bash -lc 'cd terraform/lxc/stacks/dns-stack && terragrunt apply -auto-approve -no-color'`
3. Inventory evidence capture:
   - `sed -n '1,100p' terraform/lxc/stacks/dns-stack/inventory.yml`
   - `rg -n "ProxyJump|ssh_access_mode|ansible_host|pve_host" terraform/lxc/stacks/dns-stack/inventory.yml`
4. Provisioning validation:
   - `./with-secrets ./scripts/provision.sh --stack dns-stack --check`
   - `./with-secrets ./scripts/provision.sh --stack dns-stack`
5. DNS/service health checks:
   - `nc -vz 192.168.20.13 53`
   - `dig @192.168.20.13 +short traefik.lab.gibbsgreatly.xyz`
   - `dig @192.168.20.13 +short github.com`
   - `./with-secrets ansible -i terraform/lxc/stacks/dns-stack/inventory.yml dns-stack -m ansible.builtin.command -a 'systemctl is-active coredns'`
6. Host-route priming retirement evidence (state):
   - `./with-secrets bash -lc 'cd terraform/lxc/stacks/dns-stack && terragrunt state list | rg "prime_sdn_host_route|ansible_inventory|configure_network_sdn_attachment|module.lxc"'`

### Evidence

1. Generated inventory is direct guest access:
   - `ansible_host: 192.168.20.13`
   - `ssh_access_mode: direct`

2. No default ProxyJump in generated inventory:
   - `ansible_ssh_common_args` contains strict host key options only.
   - No `ProxyJump` string present.
   - No `pve_host` host var emitted.

3. Provisioning succeeds without host-route priming:
   - `terragrunt plan` and `terragrunt apply` both show stale
     `null_resource.prime_sdn_host_route[0]` removed because it is not in
     configuration.
   - Apply result: `1 added, 0 changed, 2 destroyed`.
   - Post-apply state listing confirms no `prime_sdn_host_route` remains.
   - Provision check and live runs completed with `unreachable=0 failed=0`.

4. DNS/service health checks pass:
   - TCP 53 reachable: `nc -vz 192.168.20.13 53` succeeded.
   - Authority response: `dig @192.168.20.13 +short traefik.lab.gibbsgreatly.xyz` returned `192.168.30.10`.
   - Recursive response: `dig @192.168.20.13 +short github.com` returned an IP (`4.237.22.38`).
   - CoreDNS service active: `systemctl is-active coredns` returned `active`.

### Result

`dns-stack` passes Session 7 representative validation for `mgmt_seg` on the
direct-access contract:

1. No default `ProxyJump` is used.
2. Provisioning succeeds via direct path.
3. No host-route priming is required.
4. Stack DNS/service checks pass.

### Is A Third Representative SDN-Backed Stack Still Needed?

Recommendation: **Yes**. Run one additional SDN-backed representative stack
(for example `proxy-stack` on `edge_seg`) before Session 8.

Reason: The validation gate still specifies a third representative stack as
"if needed" to increase confidence across zones before teardown/redeploy.
With `infra_seg` and `mgmt_seg` now validated direct, one `edge_seg` validation
provides stronger cross-zone confirmation before starting Session 8.

---

## Session 7 Final Update — Additional SDN Representative (proxy-stack)

Date: 2026-05-22

### Scope

Validated `proxy-stack` (`edge_seg`) as the final additional SDN-backed
representative to confirm the direct-access model holds across zones.

### Commands Executed

1. Targeting guard:
   - `./with-secrets bash -c 'echo "$TF_VAR_proxmox_node"'`
2. Proxy stack plan/apply:
   - `./with-secrets bash -lc 'cd terraform/lxc/stacks/proxy-stack && terragrunt plan -no-color'`
   - `./with-secrets bash -lc 'cd terraform/lxc/stacks/proxy-stack && terragrunt apply -auto-approve -no-color'`
3. Inventory evidence capture:
   - `sed -n '1,120p' terraform/lxc/stacks/proxy-stack/inventory.yml`
   - `rg -n "ProxyJump|ssh_access_mode|ansible_host|pve_host" terraform/lxc/stacks/proxy-stack/inventory.yml`
4. Provisioning validation:
   - `./with-secrets ./scripts/provision.sh --stack proxy-stack --check`
   - `./with-secrets ./scripts/provision.sh --stack proxy-stack`
5. Stack health checks:
   - `nc -vz 192.168.30.10 80`
   - `nc -vz 192.168.30.10 443`
   - `curl -skI https://192.168.30.10 | head -n 1`
   - `curl -sI http://192.168.30.10 | head -n 1`
   - `./with-secrets ansible -i terraform/lxc/stacks/proxy-stack/inventory.yml proxy-stack -m ansible.builtin.command -a 'docker compose -f /opt/proxy-stack/docker-compose.yml ps'`
   - `./with-secrets ansible -i terraform/lxc/stacks/proxy-stack/inventory.yml proxy-stack -m ansible.builtin.command -a 'systemctl is-active docker'`
6. Host-route priming retirement evidence (state):
   - `./with-secrets bash -lc 'cd terraform/lxc/stacks/proxy-stack && terragrunt state list | rg "prime_sdn_host_route|ansible_inventory|configure_network_sdn_attachment|module.lxc"'`

### Evidence

1. Generated inventory is direct guest access:
   - `ansible_host: 192.168.30.10`
   - `ssh_access_mode: direct`

2. No default ProxyJump in generated inventory:
   - `ansible_ssh_common_args` contains strict host key options only.
   - No `ProxyJump` string present.
   - No `pve_host` host var emitted.

3. Provisioning succeeds without host-route priming:
   - `terragrunt plan` and `terragrunt apply` showed stale
     `null_resource.prime_sdn_host_route[0]` removed because it is not in
     configuration.
   - Apply result: `1 added, 0 changed, 2 destroyed`.
   - Post-apply state listing confirms no `prime_sdn_host_route` remains.
   - Provision check and live runs completed with `unreachable=0 failed=0`.

4. Stack health checks pass:
   - TCP ingress ports reachable: `80` and `443` succeeded.
   - HTTPS probe to edge IP returned `HTTP/2 404` (Traefik responding).
   - HTTP probe returned `HTTP/1.1 308 Permanent Redirect`.
   - Compose status shows Traefik container `Up` with `80/443` port bindings.
   - `systemctl is-active docker` returned `active`.

### Result

`proxy-stack` passes the additional representative validation for the direct
access model on `edge_seg`:

1. No default `ProxyJump` is used.
2. Provisioning succeeds via direct path.
3. No host-route priming is required.
4. Edge service health checks pass.

### Session 8 Teardown/Redeploy Readiness

**Yes.** Session 8 teardown/redeploy validation is now ready from the
representative-stack perspective:

1. `infra_seg` validated (`apt-cacher-stack`).
2. `mgmt_seg` validated (`dns-stack`).
3. `edge_seg` validated (`proxy-stack`).

No teardown was started in Session 7.

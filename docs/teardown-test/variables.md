# Variables And Open Questions

This file is intentionally a gate. Any value marked `REQUIRES_OPERATOR_INPUT`
must be answered before destructive execution. Values marked `VERIFY` have a
default expectation but still require confirmation during preflight.

## Execution Window

| Variable | Value |
|---|---|
| Operator approving destructive test | REQUIRES_OPERATOR_INPUT |
| Planned start time | REQUIRES_OPERATOR_INPUT |
| Planned stop/rollback deadline | REQUIRES_OPERATOR_INPUT; set during destructive go/no-go gate |
| Communication channel/status notes location | `docs/teardown-test/` planning documents on this branch |
| Maximum acceptable pve-test outage | REQUIRES_OPERATOR_INPUT; must be explicitly set before destructive execution |
| Initial approval posture | Approved for documentation/planning only. Destroy/apply/live publish are not approved in this step. |

## Git And Targeting

| Variable | Value |
|---|---|
| Branch to test | REQUIRES_OPERATOR_INPUT |
| Commit SHA to test | REQUIRES_OPERATOR_INPUT |
| Target guard expected value | `pve-test` |
| Command for target guard | `./with-secrets bash -c 'echo $TF_VAR_proxmox_node'` |
| Target guard actual output | VERIFY |
| SOPS/age key confirmed present | VERIFY |
| `./with-secrets` confirmed working | VERIFY |

## Scope

| Stack group | Include? | Notes |
|---|---:|---|
| Platform stacks listed in README | yes | Default scope |
| Disposable `net-*` validation stacks | no | Excluded from platform rebuild unless explicitly enabled later |
| `test-docker` and `test-lxc` | no | Excluded from platform rebuild unless explicitly enabled later |
| `.hold/` stacks | no | Out of scope unless explicitly moved active |
| `headscale-stack` inventory without active `stack.yaml` | no | Orphaned inventory/state only; out of scope until active `stack.yaml` or cleanup plan exists |

## Persistent Data Policy

OP-03 state: APPROVED FOR LATER DESTRUCTIVE APPROVAL PACKET. See
`docs/teardown-test/backup-plan.md`.

This is a policy gate approval only. It does not authorize destroy/apply/live
publish.

| Service | Backup source | Restore confidence or restore test plan | Data-loss policy | Pre-destroy evidence path | Gate status |
|---|---|---|---|---|---|
| step-ca authority material | VMID 152 LXC backup plus authority-material capture | Required high confidence; restore drill plan includes CA/ACME issuance smoke test | Data loss not acceptable | `docs/teardown-test/evidence/${STAMP}/backups/step-ca/` | READY (policy approved) |
| Authentik | VMID 150 LXC backup plus `/opt/authentik-stack` config snapshot | Restore plan: health, admin login/API token workflow, provider/app checks | Data loss not acceptable | `docs/teardown-test/evidence/${STAMP}/backups/authentik/` | READY (policy approved) |
| Harbor | VMID 121 LXC backup plus `/opt/harbor-stack` config and policy export evidence | Restore plan: `/v2/` auth challenge and sample pull/push | Registry/config loss not acceptable; Trivy cache loss acceptable | `docs/teardown-test/evidence/${STAMP}/backups/harbor/` | READY (policy approved) |
| NetBox | VMID 143 LXC backup plus `/opt/netbox-stack` config snapshot | Restore plan: service/API auth and reference object checks | Data loss not acceptable | `docs/teardown-test/evidence/${STAMP}/backups/netbox/` | READY (policy approved) |
| Monitoring/Grafana/Loki/VictoriaMetrics | VMID 154 LXC backup plus Grafana config/dashboard export as needed | Restore plan: Grafana login plus Loki/VM health checks | Historical metrics/log loss acceptable; core config loss not acceptable | `docs/teardown-test/evidence/${STAMP}/backups/monitoring/` | READY (policy approved) |
| Portainer | VMID 120 LXC backup plus `/opt/portainer` config snapshot | Restore plan: service health, login/API, endpoint visibility | Data loss acceptable if restore path fails | `docs/teardown-test/evidence/${STAMP}/backups/portainer/` | READY (policy approved) |
| Traefik ACME/cert storage | VMID 153 LXC backup plus `/opt/proxy-stack/certs` capture | Restore plan: TLS route checks and re-issuance verification | ACME cache/state loss acceptable if re-issuance works | `docs/teardown-test/evidence/${STAMP}/backups/traefik-certs/` | READY (policy approved) |
| CI runner registration/state | Re-registration/token procedure capture; optional VMID 141 LXC backup | Restore plan: redeploy runner, online check, test workflow execution | Data loss acceptable (recreatable) | `docs/teardown-test/evidence/${STAMP}/backups/ci-runner/` | READY (policy approved) |
| apt-cacher cache | Optional VMID 142 LXC backup; config capture if customized | Restore plan: redeploy and verify port 3142 plus client cache use | Data loss acceptable (cache disposable) | `docs/teardown-test/evidence/${STAMP}/backups/apt-cacher/` | READY (policy approved) |

Stop condition for all services: stop if required evidence is missing for the
approved policy (backup artifact for non-loss services, or documented accepted
data-loss posture for recreatable services).

## Bootstrap Inputs

| Variable | Value |
|---|---|
| LXC template available | VERIFY template artifact `debian-13.1-2-docker-template.tar.gz` exists in the storage backend resolved by `terraform/lxc/storage/pve-test.yaml` |
| Harbor bootstrap image source policy | REQUIRES_OPERATOR_INPUT |
| Docker Hub fallback allowed for Stage 1/2 | REQUIRES_OPERATOR_INPUT |
| Harbor robot credentials available through SOPS | VERIFY |
| Cloudflare DNS token available through SOPS | VERIFY |
| Authentik superuser/API token bootstrap procedure | REQUIRES_OPERATOR_INPUT |
| step-ca bootstrap password/authority material available | REQUIRES_OPERATOR_INPUT |
| GitHub runner token/registration procedure | REQUIRES_OPERATOR_INPUT |
| Local lab CA bundle installed for Authentik API TLS | no; use `--no-verify-tls` for this rehearsal unless fixed first |
| Proxy wildcard/default certificate resolver policy | current state: `letsencrypt`; changing to `step-ca` is out of scope |

## Network And Resolver Contract

| Variable | Value |
|---|---|
| Traefik IP | `${lab_ip_proxy}` |
| CoreDNS authoritative IP | `${lab_ip_dns}` |
| Delegated resolver IP | `${lab_gw_mgmt}` |
| Expected browser DNS target | `${lab_ip_proxy}` |
| Resolver command for authoritative checks | `dig @${lab_ip_dns} +short <host>` |
| Resolver command for delegated checks | `dig @${lab_gw_mgmt} +short <host>` |
| MikroTik conditional forwarder confirmed | Assumed as documented contract for planning; revalidate during Task 10 live checks |

## Approved Deploy And Destroy Order (OP-02)

Task 02 freezes the deploy and destroy order below for this rehearsal scope.
This does not grant destructive approval. Destroy/apply/live publish remain
blocked by the later approval gates.

Authoritative source: [inventory.md](inventory.md). Reproduced here for quick reference.

| Order | Stack/unit | Command owner | Notes |
|---:|---|---|---|
| 1 | `apt-cacher-stack` | operator using `./with-secrets terragrunt` | Stage 1/2 foundation; independent apt utility |
| 2 | `ci-runner-01` | operator using `./with-secrets terragrunt` | Stage 1/2 foundation; depends on apt-cacher |
| 3 | `dns-stack` | operator using `./with-secrets terragrunt` | Stage 3a CoreDNS seed authority |
| 4 | `step-ca-stack` | operator using `./with-secrets terragrunt` | Stage 3a internal CA; must precede proxy |
| 5 | `proxy-stack` | operator using `./with-secrets terragrunt` | Stage 3a Traefik runtime; requires step-ca root CA |
| 6 | `authentik-stack` | operator using `./with-secrets terragrunt` | Stage 3a direct first boot/API token |
| 7 | edge reconciliation activation | operator using `./with-secrets` plus Ansible publish commands | Not a Terraform stack; publish generated DNS/Traefik/Auth state |
| 8 | `harbor-stack` | operator using `./with-secrets terragrunt` | Stage 3b; depends on dns, step-ca, proxy, authentik |
| 9 | `monitoring-stack` | operator using `./with-secrets terragrunt` | Stage 3b |
| 10 | `netbox-stack` | operator using `./with-secrets terragrunt` | Stage 3b |
| 11 | `portainer-stack` | operator using `./with-secrets terragrunt` | Stage 3b management service |

Approved destroy order is reverse stack order, excluding edge activation:

`portainer-stack -> netbox-stack -> monitoring-stack -> harbor-stack -> authentik-stack -> step-ca-stack -> proxy-stack -> dns-stack -> ci-runner-01 -> apt-cacher-stack`

## Success Criteria

| Criterion | Expected value |
|---|---|
| Edge manifest validation | pass |
| Full edge reconciler final dry-run | pass/no-op |
| Browser records | all six resolve to `${lab_ip_proxy}` |
| Authentik route | no forward-auth recursion |
| Harbor registry path | `/v2/` returns native registry auth challenge |
| Grafana | native login/OIDC flow, no Traefik forward-auth |
| Portainer | forward-auth browser gate, agent/API behavior usable |
| NetBox | forward-auth browser gate, API credential flow understood |
| Traefik dashboard | `api@internal` route with forward-auth |

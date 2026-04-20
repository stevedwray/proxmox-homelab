# Variables And Open Questions

Every `TBD` entry must be answered before destructive execution.

## Execution Window

| Variable | Value |
|---|---|
| Operator approving destructive test | TBD |
| Planned start time | TBD |
| Planned stop/rollback deadline | TBD |
| Communication channel/status notes location | TBD |
| Maximum acceptable pve-test outage | TBD |

## Git And Targeting

| Variable | Value |
|---|---|
| Branch to test | `dev/pve-test` |
| Commit SHA to test | TBD |
| Target guard expected value | `pve-test` |
| Command for target guard | `./with-secrets bash -c 'echo $TF_VAR_proxmox_node'` |
| SOPS/age key confirmed present | TBD |
| `./with-secrets` confirmed working | TBD |

## Scope

| Stack group | Include? | Notes |
|---|---:|---|
| Platform stacks listed in README | yes | Default scope |
| Disposable `net-*` validation stacks | TBD | Usually no for platform rebuild |
| `test-docker` and `test-lxc` | TBD | Usually no |
| `.hold/` stacks | no | Out of scope unless explicitly moved active |
| `headscale-stack` inventory without active `stack.yaml` | TBD | Clarify current status |

## Persistent Data Policy

| Service | Backup source | Restore test done? | Data loss acceptable? |
|---|---|---:|---:|
| Portainer | TBD | TBD | TBD |
| Harbor | TBD | TBD | TBD |
| Authentik | TBD | TBD | TBD |
| NetBox | TBD | TBD | TBD |
| Monitoring/Grafana/Loki/VictoriaMetrics | TBD | TBD | TBD |
| Traefik ACME/cert storage | TBD | TBD | TBD |
| step-ca authority material | TBD | TBD | TBD |
| CI runner registration/state | TBD | TBD | TBD |
| apt-cacher cache | TBD | TBD | TBD |

## Bootstrap Inputs

| Variable | Value |
|---|---|
| LXC template available | TBD |
| Harbor bootstrap image source policy | TBD |
| Docker Hub fallback allowed for Stage 1/2 | TBD |
| Harbor robot credentials available through SOPS | TBD |
| Cloudflare DNS token available through SOPS | TBD |
| Authentik superuser/API token bootstrap procedure | TBD |
| step-ca bootstrap password/authority material available | TBD |
| GitHub runner token/registration procedure | TBD |

## Network And Resolver Contract

| Variable | Value |
|---|---|
| Traefik IP | `10.57.2.10` |
| CoreDNS authoritative IP | `10.57.1.13` |
| Delegated resolver IP | `10.57.1.1` |
| Expected browser DNS target | `10.57.2.10` |
| Resolver command for authoritative checks | `dig @10.57.1.13 +short <host>` |
| Resolver command for delegated checks | `dig @10.57.1.1 +short <host>` |
| MikroTik conditional forwarder confirmed | TBD |

## Rebuild Order Approval

The final stack order must be written here before execution.

| Order | Stack | Command owner | Notes |
|---:|---|---|---|
| 1 | TBD | TBD | Stage 1/2 foundation |
| 2 | TBD | TBD | Stage 1/2 foundation |
| 3 | TBD | TBD | Stage 3a edge foundation |
| 4 | TBD | TBD | Stage 3a edge foundation |
| 5 | TBD | TBD | Stage 3a edge foundation |
| 6 | TBD | TBD | Stage 3a edge foundation |
| 7+ | TBD | TBD | Stage 3b remaining stacks |

## Success Criteria

| Criterion | Expected value |
|---|---|
| Edge manifest validation | pass |
| Full edge reconciler final dry-run | pass/no-op |
| Browser records | all six resolve to `10.57.2.10` |
| Authentik route | no forward-auth recursion |
| Harbor registry path | `/v2/` returns native registry auth challenge |
| Grafana | native login/OIDC flow, no Traefik forward-auth |
| Portainer | forward-auth browser gate, agent/API behavior usable |
| NetBox | forward-auth browser gate, API credential flow understood |
| Traefik dashboard | `api@internal` route with forward-auth |

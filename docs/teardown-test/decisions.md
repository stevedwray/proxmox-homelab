# Teardown/Deploy Test Decisions

## Decision 1: pve-test Only

The teardown/deploy rehearsal targets `pve-test` only. Any command that targets
production `pve` or returns a target other than `pve-test` must stop.

## Decision 2: Destructive Work Requires Explicit Approval

Destroy commands, full-stack apply commands, and live deployment publish commands
must not be run as part of planning. They require:

- answered variables in [variables.md](variables.md)
- clean working tree
- known commit SHA
- backup evidence
- explicit operator approval for the destructive window

## Decision 3: Bootstrap Order Is Load-Bearing

The rebuild must follow Mode 2 order from `docs/design/bootstrap.md`.

Stage 3a remains:

1. CoreDNS seed zone
2. Traefik runtime
3. step-ca
4. Authentik direct first boot/API token
5. edge reconciler activation

Any current `stack.yaml` dependency that conflicts with this order must be
handled before teardown. In particular, verify whether `proxy-stack` can be
deployed before Authentik in a fresh rebuild despite any metadata dependency on
`authentik-stack`.

## Decision 4: Edge Artifacts Are Regenerated

Ignored local generated artifacts are not source of truth. The test regenerates:

- `terraform/lxc/.generated/traefik/*.yml`
- `terraform/lxc/.generated/coredns/coredns-lab.zone`

from current `edge.yaml` manifests before any publish.

## Decision 5: Backups Gate Destruction

Destroying persistent services is allowed only after backup/restore readiness is
confirmed for selected persistent data.

Default persistent services requiring an explicit answer are:

- Harbor registry data and database state
- Authentik database/media/configuration state
- NetBox database/media/configuration state
- Monitoring/Grafana/Loki/VictoriaMetrics data
- Portainer data
- Traefik ACME/cert storage
- step-ca authority material

If data loss is acceptable for any service, that must be written explicitly in
[variables.md](variables.md).

## Decision 6: Full Baseline Reconciler Runs Are Authoritative

After multiple forward-auth services exist, single-manifest Authentik discovery
can report owned objects from other stacks as unmanaged. Full baseline runs with
no manifest arguments are the authoritative post-apply convergence check:

```bash
./with-secrets python3 terraform/lxc/reconcile-edge.py --no-verify-tls --json
```

`--no-verify-tls` remains acceptable for this rehearsal until the lab CA bundle
follow-up is complete.

## Decision 7: Evidence Is Kept Separate From Source

Runtime snapshots and large evidence bundles are not committed unless explicitly
requested. Store them under an ignored timestamped directory and summarize key
results in the test report.

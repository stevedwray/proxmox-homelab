# Teardown/Deploy Test Decisions

## Decision 1: Non-Production Target Only

The teardown/deploy rehearsal targets a non-production Proxmox node only.
The current active test target is `pve-test-vm` (`192.168.1.41`), which
replaced the retired bare-metal `pve-test` laptop. Any command that targets
production `pve`, or returns an unexpected node, must stop.

`PVE_ENV` is the canonical override and takes precedence over `TF_VAR_proxmox_node`
in the teardown harness. Always set it explicitly before running destructive phases.

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
handled before teardown.

The known `proxy-stack` conflict is resolved by keeping Traefik independent of
`authentik-stack` in `stack.yaml`. Traefik may define the shared Authentik
forward-auth middleware before Authentik is reachable. Authentik availability is
required when protected routes are exercised, not for Traefik runtime bootstrap.

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
no manifest arguments are the authoritative post-apply convergence check.

The harness calls the reconciler with the internal HTTPS endpoint and the
homelab root CA for TLS verification:

```bash
AUTHENTIK_EXTRA_CA=certs/homelab-root.crt \
./with-secrets python3 terraform/lxc/reconcile-edge.py \
  --authentik-url "https://authentik-int.${LAB_DOMAIN}:9443" --json
```

This is the same endpoint used by `live-preflight`, `activate-edge`, and
`final-validation` in the harness. Do not assume the reconciler default
target is safe for teardown-test validation.

## Decision 7: Orphaned Stack State Is Out Of Scope By Default

Directories with inventory or Terraform state but no active `stack.yaml` are not
part of the default teardown/deploy scope. `headscale-stack` currently falls
into this category and must remain out of scope unless a later task restores an
active `stack.yaml` or explicitly plans state cleanup.

## Decision 8: Certificate Resolver Policy Is Current-State First

The proxy stack currently writes the default wildcard certificate store with
`resolver: letsencrypt`. This rehearsal validates the current state unless
[variables.md](variables.md) explicitly changes the certificate resolver policy.
Switching the default wildcard resolver to `step-ca` is a separate design change
and must not be smuggled into the teardown test.

## Decision 9: Evidence Is Kept Separate From Source

Runtime snapshots and large evidence bundles are not committed unless explicitly
requested. Store them under an ignored timestamped directory and summarize key
results in the test report.

## Decision 10: Historical Checkpoints Do Not Override Evergreen Docs

Checkpoint docs and dated recovery notes are preserved as execution history.
They are not the primary source of truth for future runs. When historical notes
teach a durable lesson, update the evergreen teardown-test docs and
`lessons-learned.md`.

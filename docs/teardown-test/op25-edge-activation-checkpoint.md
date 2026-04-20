# OP-25 Edge Activation Checkpoint

Date: 2026-04-21

## Branch And Commit
- Branch: docs/teardown-test-execution-variables
- Commit: 7c39189

## CoreDNS Publish Result
- Command: deploy-coredns.yml with generated zone source from terraform/lxc/.generated/coredns/coredns-lab.zone
- Result: success
- Play recap: ok=31 changed=0 unreachable=0 failed=0 skipped=6 rescued=0 ignored=0
- Guardrail checks in playbook passed, including authority query validation.

## Traefik Publish Result
- Command: deploy-proxy-stack.yml with generated source directory terraform/lxc/.generated/traefik
- Result: success
- Play recap: ok=33 changed=2 unreachable=0 failed=0 skipped=9 rescued=0 ignored=0
- Generated dynamic files were published and Traefik compose validation/start succeeded.

## Six-Host DNS And Route Validation Summary
Validated hosts:
- authentik.lab.gibbsgreatly.xyz
- harbor.lab.gibbsgreatly.xyz
- grafana.lab.gibbsgreatly.xyz
- portainer.lab.gibbsgreatly.xyz
- netbox.lab.gibbsgreatly.xyz
- traefik.lab.gibbsgreatly.xyz

DNS results:
- All six hosts resolved to 10.57.2.10 from both:
  - dig @10.57.1.13
  - dig @10.57.1.1

HTTPS route probe summary (curl --resolve to 10.57.2.10):
- authentik: HTTP/2 302 (login flow redirect)
- harbor: HTTP/2 200
- grafana: HTTP/2 502
- portainer: HTTP/2 404 (with x-authentik-id header)
- netbox: HTTP/2 404 (with x-authentik-id header)
- traefik: HTTP/2 404 (with x-authentik-id header)

## Final OP-25 Dry-Run Result
Command:
- ./with-secrets python3 terraform/lxc/reconcile-edge.py --authentik-url http://10.57.1.10:9000 --no-verify-tls --json

Result:
- status: passed
- mode: dry-run
- issues: []
- Authentik discovery: passed, route_count: 6, issue_count: 0
- Authentik reconcile: passed, write_count: 0, stop_condition_count: 0, issue_count: 0, action_counts: {"noop": 7}

## Execution Boundary
- OP-26, OP-27, OP-28, and OP-29 were not executed.

## Working Tree Note
- certs/homelab-root.crt remains modified from step-ca redeploy side effects.
- certs/homelab-root.crt was not staged and was not reverted during OP-25 checkpointing.

# CA Compromise And Rotation Runbook

## Scope

This runbook defines the minimum manual operator response for a `step-ca`
compromise or forced root rotation event.

Goals:

- stop additional risky issuance quickly
- restore a trusted CA path deliberately
- fan out a new trust anchor to managed consumers
- reissue direct certificates in a bounded, priority order
- verify representative consumers before declaring recovery complete

Out of scope:

- Harbor registry TLS normalization redesign
- new runtime architecture or naming policy changes
- full automation of this workflow

## Triggers

Run this workflow when one or more of the following is true:

1. `step-ca` private key material may be exposed.
2. Signed certificate issuance is suspected to be unauthorized.
3. Operator policy requires deliberate root rotation.
4. Root certificate metadata changes unexpectedly.

## Preconditions

1. Freeze non-essential platform changes until recovery is complete.
2. Confirm you are targeting the expected lab environment before any apply.
3. Capture current trust-anchor metadata for incident notes:

```bash
openssl x509 -in certs/homelab-root.crt -noout -subject -issuer -serial -fingerprint -sha256
```

4. Open and track an incident/change record with timestamps and command output.

## Response Workflow

### 1. Contain

1. Stop routine certificate issuance activity by pausing non-essential applies.
2. Preserve current evidence (root fingerprint, logs, and current cert chain data).
3. Notify operators that direct internal TLS issuance is in controlled-response mode.

### 2. Rebuild Or Restore CA Authority

1. Reconcile the CA stack from known-good source using the normal repo workflow.
2. Ensure the rebuilt authority exports an updated `certs/homelab-root.crt`.
3. Record new trust-anchor fingerprint:

```bash
openssl x509 -in certs/homelab-root.crt -noout -subject -issuer -serial -fingerprint -sha256
```

### 3. Distribute New Trust Anchor

1. Fan out the new root trust using the existing playbook path:

```bash
./with-secrets ansible-playbook terraform/lxc/ansible/playbooks/trust-homelab-ca.yml
```

2. Validate representative managed hosts now trust the new root.
3. Keep an explicit list of any non-managed endpoints that still require manual trust import.

### 4. Reissue Direct Certificates In Priority Order

Use the smallest blast-radius order already established in this repo:

1. `authentik-stack` direct endpoint certificate
2. Authentik consumer verification path (Grafana/Portainer/Traefik forward-auth behavior)
3. Any additional direct-cert consumers that already have approved patterns

Keep Harbor registry TLS redesign out of this response slice.

### 5. Verify Recovery

1. Confirm representative direct TLS checks pass with the new root chain.
2. Confirm token/auth backchannels that were migrated to direct TLS still validate.
3. Re-run the non-destructive validation path used for routine confidence checks.
4. Record final fingerprints, affected services, and verification evidence.

### 6. Exit Criteria

Do not declare recovery complete until:

1. New root fingerprint is recorded and distributed.
2. Priority direct certs are reissued and presenting correctly.
3. Representative consumers validate successfully using the new trust chain.
4. Residual manual trust follow-ups are documented with owners.

## Operator Notes

- Existing certs may continue to work until expiry during outage scenarios, but
  compromise response should treat all dependent trust as suspect until
  revalidated.
- This is a minimum manual path. Follow-on work should add tabletop rehearsal,
  tighter evidence templates, and more automated verification hooks.

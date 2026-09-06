# Intermediate CA Pattern

## When To Use

Some services manage their own internal PKI and need a CA that can sign leaf
certificates for internal components. These services cannot use a leaf
certificate from step-ca directly.

For these services the pattern is:

1. Use step-ca to sign an **intermediate CA** for the service.
2. The intermediate CA cert + private key are stored in SOPS secrets.
3. During provision, the Ansible playbook uploads the intermediate CA to the
   service via its provisioning API.
4. The service uses the intermediate CA to sign its own internal leaf certs.

Trust chain: `step-ca root → service intermediate CA → service leaf cert`

All systems that already trust the step-ca root (via `lxc_base` and
`/usr/local/share/ca-certificates/homelab-root.crt`) automatically trust
the service's internal certs without further trust distribution.

## Creating an Intermediate CA on the step-ca Host

Files on the step-ca host (VMID 20011):

| File | Purpose |
|---|---|
| `/etc/step-ca/certs/root_ca.crt` | step-ca root CA cert |
| `/etc/step-ca/secrets/root_ca_key` | step-ca root CA private key (passphrase-protected) |
| `/etc/step-ca/password.txt` | passphrase for `root_ca_key` |

```bash
# Run on the step-ca host (or via ansible.builtin.command delegate)
STEPPATH=/etc/step-ca step certificate create \
  "<Service> CA" \
  /tmp/<service>-ca.crt \
  /tmp/<service>-ca.key \
  --profile intermediate-ca \
  --ca /etc/step-ca/certs/root_ca.crt \
  --ca-key /etc/step-ca/secrets/root_ca_key \
  --ca-password-file /etc/step-ca/password.txt \
  --no-password \
  --insecure

# Package as PKCS12 when the target service upload API requires it
STEPPATH=/etc/step-ca step certificate p12 \
  --no-password \
  /tmp/<service>-ca.p12 \
  /tmp/<service>-ca.crt \
  /tmp/<service>-ca.key

# Verify the chain
STEPPATH=/etc/step-ca step certificate verify \
  /tmp/<service>-ca.crt \
  --roots /etc/step-ca/certs/root_ca.crt
```

## Storing the Intermediate CA in SOPS

After creation, SOPS-encrypt the PKCS12 (base64-encoded) and add it to
`terraform/secrets.enc.yaml`:

```bash
# Base64-encode the PKCS12
B64=$(base64 -w0 /tmp/<service>-ca.p12)

# Add to SOPS secrets (use 'sops --set' or edit interactively)
./with-secrets sops terraform/secrets.enc.yaml
# → add: <SERVICE>_CA_P12_B64: "<base64 content>"

# Clean up intermediates from step-ca host
rm /tmp/<service>-ca.{crt,key,p12}
```

The provisioning playbook reads this via
`lookup('env', '<SERVICE>_CA_P12_B64') | mandatory`.

## Implementation Notes

This pattern is intentionally generic. A service-specific implementation should
document:

1. the service upload/import API shape
2. the secret name stored in `terraform/secrets.enc.yaml`
3. the Ansible task sequence that writes the temp artifact, uploads it, and
   removes it
4. the renewal and forced-replacement path

Graylog is not the first implementation of this pattern. For the current
Graylog 6.x deployment in this repo, DataNode TLS stays on Graylog's own
self-signed preflight CA because it is container-to-container only on the
private compose network.

## Renewal

The intermediate CA cert has a finite lifetime. On renewal:
1. Repeat the intermediate CA creation on the step-ca host.
2. Re-encrypt and update `terraform/secrets.enc.yaml`.
3. Re-run the owning stack provision path so the service receives the updated CA.
4. If the service requires a reset or explicit CA replacement step, document and
   run that service-specific action before re-provisioning.

## Service Registry

| Service | CA type needed | Pattern | Status |
|---|---|---|---|
| Graylog DataNode | Self-signed (internal only) | Graylog preflight `POST /api/ca/create`; internal compose-network traffic only, so step-ca intermediate CA is not used here | Done |

Add rows here as additional services require an intermediate CA.

## Contrast With Leaf-Cert Pattern

For services that need a TLS cert but **not** a CA:

- Use step-ca's ACME provisioner directly (as Traefik does).
- Mount the issued cert/key into the container.
- Service-specific reload hook handles cert renewal.

See [certificate-lifecycle.md](certificate-lifecycle.md) for renewal ownership
requirements.

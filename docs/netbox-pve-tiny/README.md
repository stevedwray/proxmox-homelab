# NetBox: include pve-tiny

**Status (2026-10-16): DONE and live.** pve-tiny is part of NetBox populate. Token created and
stored (`netbox-ro@pve!readonly`, in `services/netbox` and `hosts/pve-tiny`), manifest updated, stack
deployed, old `@pve` records removed, populate run clean. Result: 40 VMs (31 in `pve-cluster`, 9 in
`pve-tiny-cluster`), device `pve-tiny` (192.168.1.250), 0 stale managed objects, and a follow-up
`--plan` with no creates or deletes. The steps below stay as the record and as the template for adding
another node (e.g. pve-framework).

## Why

`populate.py` only queried `pve`. pve-tiny (192.168.1.250, standalone, not
clustered with pve) is invisible to NetBox:

- **Missing entirely:** `technitium-tiny-stack`, `cse-panel-stack`,
  `cse-controller`, `cse-code-eval`.
- **Wrongly recorded as `@pve`:** `opensearch-stack` (40014),
  `mcp-utility-stack` (50011), `secpipe-stack` (50012),
  `ai-services-stack` (50013). They run on pve-tiny now; the stopped copies
  left on pve under the same VMID and IP are what populate sees.

pve-tiny's secrets profile has no read-only Proxmox token (only the privileged
`automation@pve!terraform` deploy token), so populate could not authenticate
there. The `pve` deploy profile also cannot read `hosts/pve-tiny`, so the token
must live in a shared entry (`services/netbox`).

## What is already in the repo (undeployed)

| Change | Where |
|---|---|
| Second `proxmox_nodes` entry for pve-tiny, with its own token env names | `terraform/lxc/network/pve.yaml` |
| `exclude_vmids` on the pve entry: `[40014, 50011, 50012, 50013]` (the stopped leftovers) | same |
| `exclude_vmids` support in discovery + test | `integrations/populate.py`, `test_populate_multi_source.py` |
| `PVE_TINY_READONLY_TOKEN_ID/SECRET` passed into the populate env file when set | `deploy-netbox-stack.yml` |
| Guarded, archived, dry-run-first deletion tool | `scripts/netbox-delete-managed.py` |
| Create + verify + store the read-only token without printing it (any node) | `scripts/pve-readonly-token.sh <node>` |

Until the token exists the pve-tiny entry is skipped with a warning, not an error.
**Do not deploy the NetBox stack with these changes before step 5**: pve would
stop listing the four relocated stacks while pve-tiny is still unreadable, so
their `@pve` records would just show as stale.

## Runbook

Steps 1-3 are the operator's; the rest can be run by an agent
under the normal production approval flow.

### 1-2. Create the token and store it in OpenBao (operator, one command)

`scripts/pve-readonly-token.sh pve-tiny` (alias: `scripts/pve-tiny-readonly-token.sh`) uses the pve-tiny deploy token (Administrator, via
`./with-secrets-prod-tiny`) to create `netbox-ro@pve` and the token `netbox-ro@pve!readonly`
(PVEAuditor on both user and token, privsep), checks that the new token can list guests and is
**refused a write (403)**, then pipes it straight into `openbao_write.py`. The secret is never
printed or written to a file; if verification fails the token is deleted again.
`openbao_write.py` merges into the existing entry, so NetBox's other fields are kept.

```bash
export BAO_ADDR=https://192.168.20.16:8200 BAO_CACERT=$PWD/certs/homelab-root.crt
export BAO_TOKEN="$(bao login -method=oidc -no-store -token-only)"
scripts/pve-readonly-token.sh pve-tiny --check              # read-only dry check
scripts/pve-readonly-token.sh pve-tiny --also-host-entry    # create + store in services/netbox and hosts/pve-tiny
unset BAO_TOKEN
```

Drop `--also-host-entry` to skip `hosts/pve-tiny` (that second copy closes
`docs/catch-up/13` item 13.7: live checks through `./with-secrets-prod-tiny`). If the token already
exists its secret is unrecoverable: `ssh root@pve-tiny.gibbsgreatly.xyz pveum user token remove netbox-ro@pve readonly`,
then re-run.

Manual equivalent, if you prefer to do it by hand on pve-tiny:

```bash
pveum user add netbox-ro@pve --comment "Read-only discovery (NetBox populate, live checks)"
pveum acl modify / --users netbox-ro@pve --roles PVEAuditor
pveum user token add netbox-ro@pve readonly --privsep 1 --output-format json   # secret shown ONCE
pveum acl modify / --tokens 'netbox-ro@pve!readonly' --roles PVEAuditor
```
then `scripts/openbao_write.py services/netbox PVE_TINY_READONLY_TOKEN_ID PVE_TINY_READONLY_TOKEN_SECRET`.

### 3. Add the fields to the manifest, only now (operator)

The loader **fails closed** on a manifest field missing from OpenBao, which
would break every production wrapper. So this edit comes after step 2, never before.

```bash
sed -i 's/\("services\/netbox": {"fields": \[.*"NETBOX_SUPERUSER_PASSWORD"\)\]/\1, "PVE_TINY_READONLY_TOKEN_ID", "PVE_TINY_READONLY_TOKEN_SECRET"]/' secrets/manifest.json
git diff --stat secrets/manifest.json          # expect exactly one line changed
./with-secrets-prod bash -c 'echo "${PVE_TINY_READONLY_TOKEN_ID:+id loaded}"'
```

If the optional `hosts/pve-tiny` write was done, also add `PROXMOX_READONLY_TOKEN_ID` and
`PROXMOX_READONLY_TOKEN_SECRET` to the `hosts/pve-tiny` entry the same way.

### 4. Deploy the populate changes (agent, `TASK_APPROVAL`)

```bash
export TASK_APPROVAL="netbox-pve-tiny"
./with-secrets-prod scripts/provision.sh --stack netbox-stack
```

Copies the new `pve.yaml`, `populate.py` and env file. No container recreate, and
no NetBox data changes until populate runs.

### 5. Plan, then move the four relocated stacks

On the NetBox host, preview first (`populate.py --plan`, env from `/etc/netbox-populate/env`).
Expect creates for the 4 missing guests and the 4 relocated stacks as `@pve-tiny`, and
no warning about pve-tiny.

NetBox refuses to move an IP that is another object's **primary** IP, which is what
broke the old gaming-stack record. So remove the four old `@pve` records first
(dry run, then `--execute`; their 11 services are recreated by populate):

```bash
./with-secrets-prod python3 -I scripts/netbox-delete-managed.py --archive-dir <dir> \
  --vm mcp-utility-stack@pve --vm ai-services-stack@pve --vm secpipe-stack@pve --vm opensearch-stack@pve \
  --ip 192.168.50.10/24 --ip 192.168.50.11/24 --ip 192.168.50.12/24 --ip 192.168.40.14/24
```

### 6. Real run and verification

`systemctl start netbox-populate.service` on the host, then:

- unit `Result=success`, no warnings in `/var/log/netbox-populate.log`;
- VM count = (count before) - 4 + 8; the 8 pve-tiny guests exist as `<name>@pve-tiny`
  in their own cluster, tagged `netbox-env-pve-tiny`;
- re-run `--plan`: no creates, and the drift report lists no pve-tiny objects as stale.

## Rollback

Everything here is additive. To undo: revert the `pve.yaml` and playbook commits and
re-deploy. Removed records are archived as JSON by the deletion tool, and
`/root/netbox-backups/` on the NetBox host holds `pg_dump`s taken before the 4.6 and 4.7 upgrades.

## Known gaps

- `cse-panel-stack@pve-tiny` has no services in NetBox: neither Portainer nor a docker-socket-proxy
  reports for it. Not an error; add a probe target if you want its services listed.
- `pve.yaml` has no `cse_seg` zone (VLAN 100, pve-tiny-only), so NetBox will have no prefix
  for the CSE guests' addresses. IPs are still created; add the prefix separately.
- `exclude_vmids` is a manual list. If another stack is relocated to pve-tiny and left
  stopped on pve, add its VMID, or destroy the stopped copy.

## pve-test (added and live 2026-10-16)

`pve-test` is the bare-metal laptop that hosts the isolated CyberSecEval cyber range
(`cse-kali`, the stopped `metasploitable3-win2k8` target, a template builder). It is **not** a
production node, so it uses the dev wrapper (`PVE_ENV=pve-test ./with-secrets`). Same mechanism as
pve-tiny, with its own variables:

- `pve.yaml` third `proxmox_nodes` entry (192.168.1.40, `PVE_TEST_READONLY_TOKEN_ID/SECRET`, no Portainer).
- Token: `scripts/pve-readonly-token.sh pve-test [--also-host-entry]` -> `services/netbox`
  (`PVE_TEST_READONLY_TOKEN_*`) and optionally `hosts/pve-test` (`PROXMOX_READONLY_TOKEN_*`).
- Manifest: add the same fields to `services/netbox` (and `hosts/pve-test`) only after the write.
- Records appear as `<name>@pve-test` in `pve-test-cluster`, tagged `netbox-env-pve-test`.

Caveats: the laptop is often off, so an unreachable node is skipped with a warning (its records then show
in the drift report as stale, but nothing is deleted); and range VMs are created per run and destroyed after,
so their records will come and go. This is a read-only inventory pull, so it does not weaken the range's isolation.

Result: `pve-test` device (192.168.1.40), `pve-test-cluster` with `cse-kali@pve-test` (192.168.70.210) and
`debian13-template-builder@pve-test` (192.168.1.209); follow-up `--plan` empty, 0 stale. Populate only
records LXC containers with an address, so QEMU guests such as the stopped `metasploitable3-win2k8` are not
listed (the same is true of pve's QEMU guests).

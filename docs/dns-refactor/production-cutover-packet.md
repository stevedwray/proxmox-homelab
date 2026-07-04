# Production Cutover Packet — `lab.gibbsgreatly.xyz`

Status: `technitium-stack` is live in parallel on `pve` at `192.168.20.15`,
but production clients still resolve `lab.gibbsgreatly.xyz` through the
existing CoreDNS-backed MikroTik path (`192.168.20.13`). This packet covers
the next two production steps:

1. direct parity verification between CoreDNS and Technitium
2. the manual MikroTik delegate cutover and rollback procedure

## Direct parity verification

Run the checked-in direct parity script against the two production DNS
servers:

```bash
./with-secrets-prod bash -lc '
  terraform/lxc/stacks/technitium-stack/verify-coredns-technitium-parity.sh \
    --coredns-ip 192.168.20.13 \
    --technitium-ip 192.168.20.15 \
    --lab-domain lab.gibbsgreatly.xyz
'
```

What this checks:
- browser-routed names: `traefik`, `authentik`, `harbor`, `netbox`,
  `portainer`
- direct/internal names: `authentik-int`, `step-ca`
- shared authority identity: `NS` and SOA owner/admin identity
- Technitium cutover-target authority records: `dns`, `ns1` -> `192.168.20.15`
- public recursion: `github.com`

Expected outcome:
- every shared client-visible authoritative record matches between CoreDNS
  and Technitium
- Technitium serves `dns.lab.gibbsgreatly.xyz` and `ns1.lab.gibbsgreatly.xyz`
  as `192.168.20.15`
- both servers return a non-empty recursive answer for `github.com`

If this step fails, stop here. Do not mutate the MikroTik delegate yet.

## Router inspection

Before any cutover, inspect the existing production delegate entry on the
MikroTik and capture its exact rule id:

```routeros
/ip dns static print detail where type=FWD
```

Optional narrower view if the router already uses a regexp-based zone
delegate:

```routeros
/ip dns static print detail where regexp~"lab\\.gibbsgreatly\\.xyz"
```

Confirm the current `forward-to` target is still CoreDNS `192.168.20.13`
before proceeding.

## Cutover

Use the actual rule id discovered above in place of `<rule-id>`:

```routeros
/ip dns static set <rule-id> forward-to=192.168.20.15
/ip dns cache flush
```

If there is no existing `lab.gibbsgreatly.xyz` delegate rule, stop and review
before adding one manually. The expected production move is an in-place
mutation of the existing delegate, mirroring the `pve-test-vm` rehearsal.

## Immediate post-cutover validation

Run these from a normal client path through the router, not by querying either
DNS server directly:

```bash
dig @192.168.1.1 traefik.lab.gibbsgreatly.xyz +short
dig @192.168.1.1 authentik.lab.gibbsgreatly.xyz +short
dig @192.168.1.1 harbor.lab.gibbsgreatly.xyz +short
dig @192.168.1.1 netbox.lab.gibbsgreatly.xyz +short
dig @192.168.1.1 portainer.lab.gibbsgreatly.xyz +short
dig @192.168.1.1 dns.lab.gibbsgreatly.xyz +short
dig @192.168.1.1 ns1.lab.gibbsgreatly.xyz +short
dig @192.168.1.1 authentik-int.lab.gibbsgreatly.xyz +short
dig @192.168.1.1 step-ca.lab.gibbsgreatly.xyz +short
dig @192.168.1.1 github.com +short
```

Expected answers:
- `traefik`, `authentik`, `harbor`, `netbox`, `portainer` -> `192.168.30.10`
- `dns`, `ns1` -> `192.168.20.15`
- `authentik-int` -> `192.168.20.10`
- `step-ca` -> `192.168.20.11`
- `github.com` -> non-empty answer

Browser/API spot checks:

```bash
curl -kI https://technitium.lab.gibbsgreatly.xyz
curl -kI https://authentik.lab.gibbsgreatly.xyz
curl -kI https://harbor.lab.gibbsgreatly.xyz
curl -kI https://netbox.lab.gibbsgreatly.xyz
curl -kI https://portainer.lab.gibbsgreatly.xyz
```

## Rollback

If any resolver-path or browser-path check fails, restore the delegate to
CoreDNS immediately:

```routeros
/ip dns static set <rule-id> forward-to=192.168.20.13
/ip dns cache flush
```

Then rerun the same client-path `dig` checks against `192.168.1.1` to confirm
service has actually returned to the CoreDNS-backed path.

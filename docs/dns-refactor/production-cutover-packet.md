# Production Cutover Packet — `lab.gibbsgreatly.xyz`

Status: direct parity verification passed on 2026-07-04, and the production
MikroTik delegate cutover was then executed successfully. The live
`lab-zone-delegate` rule is now `*45 -> 192.168.20.15`, so production
clients resolve `lab.gibbsgreatly.xyz` through Technitium rather than
CoreDNS. This packet now serves as the execution record plus rollback
procedure.

Post-cutover note: the Technitium browser route initially returned Traefik
`404` until the generated production Traefik config was republished to
`proxy-stack`. That republish restored
`https://technitium.lab.gibbsgreatly.xyz` successfully. A later dry-run
still reports Authentik metadata drift for the Technitium app's launch host,
but the live routed service is healthy.

## Direct parity verification

Completed successfully on 2026-07-04. Keep this command as the pre-cutover
recheck if the cutover is not performed in the same session:

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

Executed production command set on 2026-07-04:

```routeros
/ip dns static set *45 forward-to=192.168.20.15
/ip dns cache flush
```

Observed post-cutover resolver-path answers through `192.168.1.1`:

- `traefik`, `authentik`, `harbor`, `netbox`, `portainer` ->
  `192.168.30.10`
- `dns`, `ns1` -> `192.168.20.15`
- `authentik-int` -> `192.168.20.10`
- `step-ca` -> `192.168.20.11`
- `github.com` -> non-empty answer (`4.237.22.38` in the captured check)

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

If any later resolver-path or browser-path check fails, restore the delegate
to CoreDNS immediately:

```routeros
/ip dns static set *45 forward-to=192.168.20.13
/ip dns cache flush
```

Then rerun the same client-path `dig` checks against `192.168.1.1` to confirm
service has actually returned to the CoreDNS-backed path.

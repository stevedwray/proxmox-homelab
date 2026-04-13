# IPv6 Troubleshooting Notes

This document captures the IPv6 issues previously seen in the homelab and the checks that
still matter when IPv6 connectivity breaks.

It is not intended to be a canonical host configuration file. Use it as a troubleshooting
reference, not as a source of exact interface settings for the current `pve-test` host.

## Main failure patterns seen

### 1. Conflicting IPv6 prefixes on the LAN

The MikroTik previously advertised two different IPv6 prefixes:

- one valid upstream-routed prefix
- one stale/static prefix that was not actually routed upstream

Symptoms:

- hosts and containers autoconfigure addresses from both prefixes
- outbound IPv6 appears partially working
- some destinations never reply because traffic leaves with the invalid source prefix

### 2. Router advertisement handling on the Proxmox host

The host can break IPv6 if it is not correctly accepting router advertisements on `vmbr0`
or if MTU/PMTU behaviour is wrong on the upstream path.

Symptoms:

- host has link-local IPv6 but no usable global IPv6
- intermittent IPv6 packet loss
- larger payloads fail while small pings work

### 3. LXC guest IPv6 mode mismatch

Containers previously failed when configured with static IPv6 settings that did not match
the actual LAN/router-advertisement model.

Symptoms:

- no default IPv6 route inside the container
- no recursive DNS from RA
- container has no usable outbound IPv6 despite IPv4 working

## What fixed it previously

### MikroTik-side fixes

- remove any stale or non-routed advertised IPv6 prefix
- leave only the valid routed prefix active
- ensure ND/RA still provides a default route and recursive DNS

### Proxmox host-side fixes

- ensure the intended bridge accepts router advertisements when using SLAAC
- verify the effective MTU on the host, bridge, and upstream path
- avoid treating old one-off interface examples as authoritative for the current host

### Container-side fixes

- make sure the container IPv6 mode matches the actual network model
- if the environment depends on RA/SLAAC, do not force a conflicting static setup
- verify the guest receives a global address, default route, and DNS information

## Current troubleshooting checklist

### On the MikroTik

Check:

- only the intended upstream-routed IPv6 prefix is being advertised
- the RA/ND configuration is enabled on the correct LAN/VLAN interfaces
- the MikroTik still has working upstream IPv6

### On `pve-test`

Check:

```bash
ssh root@pve-test.gibbsgreatly.xyz "ip -6 addr show"
ssh root@pve-test.gibbsgreatly.xyz "ip -6 route show"
ssh root@pve-test.gibbsgreatly.xyz "ping -6 -c 3 2606:4700:4700::1111"
```

Look for:

- one sensible global address from the correct prefix
- a default IPv6 route
- successful outbound IPv6 ping

### Inside an affected container

Check:

```bash
ssh root@pve-test.gibbsgreatly.xyz "pct exec <vmid> -- ip -6 addr show"
ssh root@pve-test.gibbsgreatly.xyz "pct exec <vmid> -- ip -6 route show"
ssh root@pve-test.gibbsgreatly.xyz "pct exec <vmid> -- ping -6 -c 3 2606:4700:4700::1111"
```

Look for:

- a global IPv6 address from the expected prefix
- a default route
- working outbound IPv6 from the guest

## If IPv6 is still broken

Work through the path in this order:

1. MikroTik upstream IPv6 status
2. active RA/ND advertisements on the right interface
3. host bridge/interface IPv6 state
4. guest IPv6 mode and route state
5. MTU/PMTU behaviour

## Notes

- The exact IPv4 address, interface name, and old bridge examples from earlier troubleshooting sessions are intentionally omitted here because they were tied to an older environment snapshot.
- If the current pve-test host networking is being rebuilt, align any permanent fixes with:
  - `docs/reference/sdn-segment-routing.md`
  - `terraform/lxc/network/pve-test.yaml`
  - `docs/plan/phase-00a-proxmox-host-bootstrap.md`

# enp9s0 / vmbr1 Recovery — Physical NIC Passthrough Zombie State

## Symptom

`vmbr1` shows `NO-CARRIER` and `enp9s0` is missing from `ip link show` on the pve host,
even though `lspci` confirms the Realtek RTL8168h (`0000:09:00.0`) is present and
`/sys/bus/pci/drivers/r8169/` lists `0000:09:00.0` as bound.

`pvesh set /cluster/sdn` triggers `ifreload -a`, which logs `srvreload:networking FAIL`
because `vmbr1` references `enp9s0` as its bridge port but the interface doesn't exist.

## Root Cause

`security-stack` (LXC 109) uses physical NIC passthrough:

```
lxc.net.1.type: phys
lxc.net.1.link: enp9s0
```

When the LXC is running, `enp9s0` lives inside the container namespace as `monitor0`.
When the LXC stops, the kernel should return the interface to the host — but it leaves
the r8169 driver bound to `0000:09:00.0` without recreating the netdev. The interface
is invisible on the host despite the driver binding being present.

The LXC rename sequence visible in the kernel journal when LXC 109 starts:

```
vmbr1: port 1(enp9s0) entered disabled state
r8169 0000:09:00.0 enp9s0: left promiscuous mode
r8169 0000:09:00.0 phys5tIK2t: renamed from enp9s0   ← intermediate name during namespace move
r8169 0000:09:00.0 monitor0: renamed from phys5tIK2t  ← final name inside the LXC
```

### Why the `srvreload:networking FAIL` is non-fatal

`pvesh set /cluster/sdn` calls `reloadnetworkall`, which returns `OK` regardless of
whether `ifreload -a` fails internally. The teardown cycle continues normally. These
`FAIL` entries in the Proxmox task log are expected whenever security-stack is running
and are harmless.

## Fix

Unbind and rebind the r8169 driver to force the kernel to recreate the netdev:

```bash
echo '0000:09:00.0' > /sys/bus/pci/drivers/r8169/unbind
sleep 1
echo '0000:09:00.0' > /sys/bus/pci/drivers/r8169/bind
sleep 1
ifreload -a
```

`ip link show enp9s0` should now show the interface as `master vmbr1`.

## Correct Steady State

- **LXC 109 (security-stack)** is legacy. It should be **stopped** (`onboot: 0`).
  It was temporarily started during portainer migration work.
- **VM 106 (Security Onion)** is the intended monitoring VM. It uses
  `usb0: host=0bda:8153` (Realtek RTL8153 USB NIC, `enxa0cec811c0e2` on the host)
  for its capture interface via USB passthrough.
- **`enp9s0`** (PCIe Realtek RTL8168h, `0000:09:00.0`) is the `vmbr1` bridge port.
  `vmbr1` carries mirrored switch traffic to Security Onion.
- `vmbr1` will show `NO-CARRIER` if the switch mirror cable is unplugged or the mirror
  port is inactive — that is expected and harmless.

## USB NIC (r8152) Not Loading on Boot

The `r8152` module is not loaded automatically. If VM 106 is stopped and the USB NIC
(`0bda:8153`) is visible via `lsusb` but no interface appears on the host:

```bash
modprobe r8152
```

To make this permanent, add `r8152` to `/etc/modules` on pve.

## Related

- `lxc.net.1.type: phys` — LXC physical NIC passthrough docs: `man lxc.container.conf`
- `/etc/network/interfaces` on pve: `vmbr1` bridge definition
- `docs/teardown-test/lessons-learned.md` — non-fatal networking errors during SDN teardown

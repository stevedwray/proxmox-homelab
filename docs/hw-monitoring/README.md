# hw-monitoring

Status: **survey done and plan written (2026-10-17); no steps executed yet.** See [plan.md](plan.md). Goal: add hardware
health (temperatures, fans, voltages, throttling) with properly labelled
sensors for pve, pve-tiny, pve-test, argon-01/02 (Pi 4) and the T-Pot Pi 5
to Grafana via the existing VictoriaMetrics/node_exporter path.

## Operator decisions (2026-10-17)

- Include argon-01/02 (plan them as a late, droppable phase; Pi-hole
  retirement is pending in `docs/lan-dns-technitium/`).
- Use node_exporter (hwmon collector) on each host, reusing
  `terraform/lxc/ansible/roles/node_exporter` (TLS + basic auth).
- Labels: a per-host chip+sensor -> friendly-name map applied in
  VictoriaMetrics relabeling, so every dashboard gets the names.
- New "Hardware Health" dashboard with a host variable (not an extension of
  `node-detail.json`, which is keyed on the LXC `stack` label).

## Survey results (read-only, 2026-10-17)

| Host | Hardware | hwmon chips | Fans | Voltages | Notes |
|---|---|---|---|---|---|
| pve | Gigabyte B550 GAMING X V2 | acpitz, r8169 NIC, 3x nvme, k10temp (Tctl/Tccd1/Tccd2), gigabyte_wmi (6 unlabelled temps), amdgpu | amdgpu fan1 only (0 RPM, idle) | amdgpu vddgfx only | **No Super I/O driver loaded**: no case/CPU fan RPM, no board voltages. Board has an ITE chip; needs a driver (see open items). |
| pve-tiny | MSI B450 GAMING PLUS MAX | nvme, k10temp, nouveau (GPU) | nouveau fan1 | none | Same gap: no Super I/O driver, so no case/CPU fan or board voltages. |
| pve-test | Toshiba Portege R930 laptop | acpitz, ADP1, BAT1 (in0 + power), toshiba_acpi_sensors, coretemp (3 sensors) | toshiba fan1_input | BAT1 in0 only | Not a production node; plain `./with-secrets`. |
| tpot | Raspberry Pi 5 | cpu_thermal, nvme, rp1_adc (in1-4, temp), pwmfan, rpi_volt | pwmfan fan1 (RPM) | rp1_adc, rpi_volt undervolt alarm; `vcgencmd pmic_read_adc` gives per-rail currents | node_exporter already listens on :9100, `prometheus-node-exporter` is NOT the owner (T-Pot docker-proxy), so use a different port. |
| argon-01 / argon-02 | Pi 4 B (Rev 1.4 / 1.5), Argon ONE case, Pi-hole | cpu_thermal (~46-49 C), rpi_volt (undervoltage alarm) | Argon fan is driven over I2C by the vendor daemon (`argononed`, config in /etc); no tach or hwmon fan, so **no RPM** (duty % only if derivable from daemon config) | undervoltage alarm only; `vcgencmd` not in PATH for the ansible user | SSH as `ansible` (sudo NOPASSWD), not root/steve. argon-01 runs kernel 6.18, argon-02 6.1. Neither has node_exporter. |
| workstation (`garuda`, Garuda Dragonized) | ASUS TUF GAMING B650-E WIFI, kernel 7.2.9-zen | nct6799 (nct6775 module loaded), k10temp, 3x nvme, 2x spd5118 (DIMM temps), 2x amdgpu (iGPU + dGPU), r8169, mt7921 wifi, asus | 7 fan headers (fan2/4/7 active) + dGPU fan; pwm1-4,6,7 duty | in0-in17 (unlabelled: Vcore, 3.3 V, 1.8 V etc.), amdgpu vddgfx/vddnb | **Best-supported host; use as the reference/test bed.** Many nct6799 voltages show ALARM only because firmware min/max are 0, so alerting must not use chip limits. SYSTIN/CPUTIN/AUXTIN* temps are named by the chip but not by function. node_exporter not installed; on the 192.168.1.0/24 LAN, outside the managed fleet (a mgmt_seg monitor reaches it via MikroTik). |

## Findings that shape the plan

- pve and pve-tiny will not give fans or voltages from stock drivers. Getting
  them means identifying the Super I/O chip (`sensors-detect` is interactive
  and loads probes, so do this deliberately) and loading `it87` / `nct6775`,
  which on Proxmox kernels may need an out-of-tree DKMS build.
- `gigabyte_wmi` temps on pve are unlabelled `temp1..6`; labels must come from
  the per-host map (Gigabyte documents the order, to be verified against live
  values).
- nvme exposes "Composite", "Sensor 1/2" labels already.
- SSH to `tpot.gibbsgreatly.xyz` on port 22 lands on the honeypot; admin SSH
  is the `tpot` alias (port 64295).

Raw output is in the gitignored `artifacts/` directory.

## Phase A results

### pve-tiny: DONE 2026-10-17

- `modprobe nct6775` found `NCT6797D or compatible chip at 0x4e:0xa20`; zero
  ACPI resource conflicts before or after, so no kernel parameter or reboot.
  In-tree driver, no DKMS.
- Persisted: `/etc/modules-load.d/hwmon.conf` = `nct6775`.
- node_exporter `chip` label will be `platform_nct6775_2592`.
- Live: fan2 1493 RPM, fan3 1185 RPM (fan1, fan4-6 read 0: empty headers);
  SYSTIN/CPUTIN 36 C, AUXTIN0 35.5 C, AUXTIN2 42 C, SMBUSMASTER 0 / TSI0_TEMP
  47 C; voltages in0-in14 (unlabelled; in10 reads 0 V).
- Exclude from names/dashboards: AUXTIN1 (-128 C) and AUXTIN3 (-3 C) are
  unconnected probes; PCH_* and Agent0 Dimm0 read 0 (unsupported); both
  intrusion alarms are unconnected switches.
- Chip min/max limits are 0, so every `ALARM` is meaningless; never alert on
  chip limits.
- pwm1 raw = 255 (100%), pwm1_enable = 5 (SmartFan auto, BIOS in control).
  `sensors` printing "128%" is a display quirk; `/255` in the dashboard is right.
- Voltage rail names (in0-in14) need the MSI BIOS hardware-monitor page to
  label; do not guess from raw values.

### pve: pending

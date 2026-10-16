# hw-monitoring

Status: **LIVE 2026-10-17: all six hosts deployed and scraped, Hardware Health dashboard provisioned.** Open: workstation (Phase E), pve-tiny fan/rail names, alerting. See [plan.md](plan.md). Goal: add hardware
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

### pve: DONE 2026-10-17 (out-of-tree it87 via DKMS)

- In-tree `modprobe it87` -> ENODEV (no supported chip). The chip is an
  **IT8689E** (not IT8688E as first guessed): `Found IT8689E chip at 0xa40
  [MMIO at 0xfe000000], revision 2`, Gigabyte SIV ID 61050607.
- Driver: frankcrawford/it87 pinned at commit
  `bd7a566c8a60fe0308d67e26761e16260368191a`, built with DKMS as
  `it87/bd7a566` for 7.0.14-15-pve (headers `proxmox-headers-7.0.14-15-pve`
  installed). No module options, no ACPI conflict, no kernel parameter, no
  reboot. DKMS archived the in-tree module; `dkms remove it87/bd7a566 --all`
  restores it. Kernel shows a taint line (unsigned module); Secure Boot is off.
- Persisted: `/etc/modules-load.d/hwmon.conf` = `it87`. DKMS AUTOINSTALL=yes:
  **install `proxmox-headers-<kver>` for 7.0.14-19/-20 before rebooting into
  them**, or the sensors vanish on that kernel.
- node_exporter `chip` label will be `platform_it87_2624`.
- Sensor map (from the driver's Gigabyte config, which lists "B550 GAMING X
  V2" for SIV 0x61050607; cross-checked against live values): temp1/2 System
  1/2, temp3 CPU (75 C, matches Tctl), temp4 PCIEX16, temp5 VRM MOS, temp6
  PCH; fan1 CPU_FAN, fan2 SYS_FAN1, fan3 SYS_FAN2, fan4 SYS_FAN3 (empty),
  fan5 CPU_OPT; in0 CPU Vcore, in4 CPU VCORE SOC, in5 CPU VDDP, in6 DRAM,
  3VSB, Vbat; **in1 +3.3V (x1.649), in2 +12V (x6), in3 +5V (x2.5)**: raw
  readings are divider-scaled (all 1.99 V), so the plan carries a `scale`.
- `gigabyte_wmi` temp1-6 are the same six sensors as it87 temp1-6: drop that
  chip (`hwmon_drop_chips`) and use the it87 names.

## Reachability probe (read-only, 2026-10-17, from monitoring-stack 192.168.20.12)

TCP connect test: `REFUSED` means the packet reached the host and nothing
listens (path open); a firewall drop would show as a timeout.

| Target | Result |
|---|---|
| framework:9100 (control, already scraped) | open |
| pve, pve-tiny, pve-test, argon-01, argon-02 :9100 | refused = path open, no MikroTik rule needed |
| pve:9190 | refused = path open (not 9100-only) |
| tpot:9100 / :9101 / :9190 | all "open", **meaningless** (see below) |

**T-Pot constraint (blocks the current tpot design):** T-Pot's INPUT chain is
an explicit ACCEPT allow-list (~60 TCP ports) ending in
`-j NFQUEUE --queue-num 0` for every other new SYN, which honeytrap answers.
So any host-level listener (our systemd node_exporter) on a port not in the
list is swallowed by the honeypot. 9101 is honeytrap's own listener; 9100 is
T-Pot's miniprint docker-proxy. cAdvisor on 8083 works only because Docker
publishes it via DNAT (bypasses INPUT). **Decided 2026-10-17:** run node_exporter
as a Docker-published container on tcp/8084 (like cAdvisor), plain HTTP, via
`tpot-monitoring.yml --tags hwmon`; no change to T-Pot's firewall.

## Deploy log

### pve-test: DONE 2026-10-17 (operator chose full TLS deploy, option B)

- First run failed at step-ca cert issuance: pve-test trusted a stale root CA
  (fingerprint F3:5E:A5..., April) instead of production's A9:3B:F0...; the
  role's `--root` needs the current one. pve-tiny had no root file at all.
  Playbook now installs `certs/homelab-root.crt` first (cf5f098d).
- Consequences accepted by the operator: pve-test's root CA file was
  replaced with the production one, and the step-ca provisioner password
  (`/etc/node_exporter/provisioner-password.txt`, root 0600) now lives on the
  cyber-range laptop (every managed LXC already holds the same).
- Verified: no-auth -> 401, plain http -> 400, authenticated TLS scrape OK
  with 4192 metric lines.
- Live chips: `platform_coretemp_0` (temp1 Package, temp2/3 Core 0/1),
  `lnxsybus:00_tos6208:00` (fan1, 3090 RPM), `power_supply_bat1` (in0
  10.85 V, power1), `power_supply_adp1`, `thermal_thermal_zone0` (constant
  16 C, dropped). Names filled in `hwmon-hosts.yml`.
- Metric-name finding: battery power is `node_hwmon_power_watt`, GPU is
  `node_hwmon_power_average_watt`; the dashboard Power panel matches both.

### argon-01: DONE 2026-10-17 (run by the operator; auto-mode blocked the agent)

- Role fix first: the step CLI download was hardcoded amd64; both Pis are
  aarch64. `node_exporter_step_cli_arch` now picks arm64 (d9af0451). Both Pis
  already use the Technitium resolvers; Pi-hole is inactive on both.
- Playbook: ok=28 failed=0. Verified: no-auth 401; authenticated scrape
  returns `rpi_volt` and `cpu_thermal` chips.
- Metrics: `node_hwmon_temp_celsius{chip="thermal_thermal_zone0",sensor=
  "temp0"|"temp1"}` (same zone twice, temp1 dropped);
  undervoltage is `node_hwmon_in_lcrit_alarm_volts{chip=
  "soc:firmware_raspberrypi_hwmon",sensor="in0"}` (0 = fine). The dashboard
  stat panel used the wrong name and is fixed.
- Relabel bug found by rendering: chip `thermal_thermal_zone0` is the Pi's
  real CPU sensor but pve-test's placeholder, so chip drops are now scoped
  per stack (`{stack, chip}`); per-sensor `drop: true` also supported.

### argon-02: DONE 2026-10-17 (operator ran it; ok=28 failed=0)

- no-auth 401; same chips as argon-01 (`thermal_thermal_zone0`,
  `soc:firmware_raspberrypi_hwmon`); sensor names added. temp0/temp1 differed
  by one 0.97 C step in one sample (quantisation), treated as one zone.

### pve-tiny: DONE 2026-10-17 (operator ran it with ./with-secrets-prod-tiny; ok=28 failed=0)

- no-auth 401; authenticated scrape 5524 lines. Chip labels: `platform_nct6775_2592`
  (nct6797), `pci0000:00_0000:00:18_3` (k10temp), `nvme_nvme0`,
  `0000:00:03_1_0000:26:00_0` (nouveau GPU).
- nct TSI0_TEMP/SMBUSMASTER duplicate the k10temp Tctl (59 C): dropped.
  nouveau `pwm1` is 0-100 (reads 100), not 0-255, so the dashboard's `/255`
  would show 39%: dropped. Only the GPU fan RPM is shown.
- Fan headers and voltage rails are NOT named: names stay neutral
  ("Fan 2", "nct6797 in3") until identified from the MSI BIOS monitor page.

### pve: DONE 2026-10-17 (operator ran it with ./with-secrets-prod; ok=28 failed=0)

- no-auth 401; authenticated scrape 11,830 lines. Chips: `platform_it87_2624`
  (board), `pci0000:00_0000:00:18_3` (k10temp), `nvme_nvme0/1/2`,
  `0000:05:00_0_0000:06:00_0` (amdgpu), `r8169_0_700_r8169_0_700:00` (NIC),
  `wmi_bus_pnp0c14:00_deadbeef_...` (gigabyte_wmi, dropped as a duplicate),
  `thermal_thermal_zone0` (constant 16.8 C, dropped).
- Sensor map filled in with the Gigabyte config names and scales (+3.3V
  x1.649, +12V x6, +5V x2.5).
- Observation: `nvme_nvme1` Sensor 2 reads ~79.9 C (composite ~54.9 C) --
  worth a look at airflow/placement; nvme limits exported are meaningless.

### tpot: DONE 2026-10-17 (operator ran `tpot-monitoring.yml --tags hwmon`; ok=7 failed=0)

- node_exporter container on tcp/8084 (plain HTTP), 238 metric lines, only
  hwmon + textfile collectors. Chips: `thermal_thermal_zone0` (temp0/temp1 are
  one zone; temp1 dropped), `nvme_nvme0`, `platform_cooling_fan` (fan 0 RPM,
  pwm 0 at 45 C: fan idle), `soc_107c000000:firmware_raspberrypi_hwmon`
  (undervoltage 0), `1000120000_pcie_1f000c8000_adc` (RP1 temp 50 C; in1-in4
  unlabelled ADC inputs, dropped).
- PMIC rails arrive as `rpi_pmic_volts{rail}` / `rpi_pmic_current_amps{rail}`
  (textfile timer working: EXT5V 5.12 V, VDD_CORE 0.87 V / 0.66 A). The
  dashboard gained a "Raspberry Pi 5 power rails" row (15 panels now).

## monitoring-stack deploy (2026-10-17)

- Run 1 (operator, `./with-secrets-prod scripts/provision.sh --stack
  monitoring-stack`, no dry run first): scrape.yml and `hardware-health.json`
  landed at 09:25 and VictoriaMetrics + Grafana restarted, then the playbook
  **failed in the wazuh_agent role**: this branch pinned agent 4.14.8 (cut from
  a stale local `stable`) while the host runs 4.14.9 held; apt refuses to
  downgrade. Fixed by merging `origin/stable` (pin 4.14.9) into the branch
  (524fd668); the branch is now origin/stable plus only hw-monitoring files.
  A re-run is needed to finish the rest of the playbook. Lesson (as in
  `feedback_shared_checkout_deploys_wrong_branch`): `git fetch` and compare
  to `origin/stable` before any deploy from a work branch.
- Live checks (read-only, from the monitoring LXC): all 6 targets `up`
  (5 `node_exporter_hw` https + tpot `node_exporter_hw_plain` :8084);
  temperatures present for all six stacks; 0 sensors left with a raw
  chip-path name; the MetricsQL `label_value(..., "scale")` voltage query
  works on pve: +3.3V 3.285 V, +5V 4.98 V, +12V 11.952 V (raw 1.992 V each).

- Run 2 (operator, from the fixed branch): the `--check` dry run failed in
  `docker_live_usage_reporter` (`index_check.status` undefined because the
  uri task is skipped in check mode; a pre-existing check-mode limitation of
  that role, not this project). The real run then passed: ok=141 failed=0,
  smoke test passed, wazuh step clean. **Hardware monitoring is live.**

## Workstation (Phase E) -- written, not yet run

- Playbook `hw-monitoring-workstation.yml` (see plan Phase E). Operator runs it
  on the workstation (needs sudo): `PVE_ENV=pve-test ./with-secrets
  ansible-playbook -i ansible/inventory/inventory.yml
  ansible/00-initial-setup/hw-monitoring-workstation.yml -K`.
- Tested: syntax check; the `--provisioner-password-file <(printf ...)`
  mechanism (with `step crypto keypair` on pve-test). Not tested: the full run.
- After it runs: redeploy monitoring-stack (new scrape target), then name the
  nct6799 sensors.

- Run 1 of the workstation playbook failed at cert issuance: Arch's `step-cli`
  package installs `/usr/bin/step-cli`, not `step` (hidden by `no_log`;
  reproduced by hand). Playbook now calls `step-cli` for issuance and renewal.
  Safe to re-run (the earlier tasks are idempotent).

## Deferred: pve-tiny sensor names (noted 2026-10-17, operator will return to this)

Fans and voltage rails on pve-tiny still carry neutral names ("Fan 2", "Fan 3",
"nct6797 in0".."in14") because the chip cannot say which header or rail is
which and no lm-sensors config exists for the MSI B450 GAMING PLUS MAX. To name
them, read the BIOS Hardware Monitor page and send:
- RPM shown against each fan header (CPU_FAN1/PUMP_FAN1/SYS_FAN*), to match
  fan2 ~1900 RPM and fan3 ~1150 RPM, or which fans are plugged in where;
- any rail values the BIOS shows (CPU core, DRAM, +12V, +5V, +3.3V).
Likely mapping to confirm: in0 CPU Vcore (1.43 V); in2/in3 AVCC/+3.3V (3.36/
3.34 V); in7 3VSB (3.34 V); in8 Vbat (3.31 V); in1 +12V if x12 (raw 1.008 V ->
12.1 V); in4 +5V if x5 (raw 1.016 V -> 5.08 V). The last two are unconfirmed.
If wanted sooner, the fallback is provisional names marked "(unverified)".
Names live in `terraform/lxc/stacks/monitoring-stack/hwmon-hosts.yml`
(`stack: pve-tiny` entries); a redeploy of monitoring-stack applies them.

### workstation (garuda): exporter LIVE 2026-10-17 (operator ran the playbook: ok=13 failed=0)

- Before that: Garuda's `wine-meta` 2-4 conflicted with `lib32-audit`/
  `lib32-libcap` (needed by lib32-pam/lib32-gstreamer) during `pacman -Syu`;
  operator used `--ignore wine-meta` and removed the unused
  plasma-x11-session (Wayland-only). Garuda bug, unrelated to this project.
  Remember `wine-meta` is held until Garuda fixes it.
- Verified: no-auth 401; authenticated scrape 757 lines, hwmon collector only
  (0 cpu/memory/disk/network series). Chips: `platform_nct6775_656` (nct6799),
  `pci0000:00_0000:00:18_3` (k10temp), `nvme_nvme0/1/2`, two `spd5118`
  (`i2c_0_0_0051/0053`), two amdgpu (`0000:00:08_1_...` iGPU,
  `0000:02:00_0_...` dGPU), r8169, mt7921.
- Sensor map written (182 entries total in the file). Dropped as not real/
  duplicate: AUXTIN1 (3 C) and AUXTIN5 (12 C, below ambient), PECI Agent 0
  Calibration, PCH_* (0), TSI0_TEMP (dup of Tctl), empty fan headers
  fan1/3/5/6 and their pwm. Rails `in0..in17` and AUXTIN probes keep neutral
  names; evidence: nct in0 tracks iGPU vddgfx (1.272 vs 1.275 V), so likely CPU
  Vcore. Needs the ASUS board manual/BIOS to name (same deferred work as
  pve-tiny).
- Observation: nvme1 and nvme2 sensor readings up to ~66 C.
- Not yet scraped: needs the monitoring-stack redeploy.

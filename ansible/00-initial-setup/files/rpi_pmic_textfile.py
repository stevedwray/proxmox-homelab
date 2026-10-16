#!/usr/bin/env python3
"""Write Raspberry Pi 5 PMIC rail readings for node_exporter's textfile collector.

Reads `vcgencmd pmic_read_adc` (lines like `  3V3_SYS_A current(1)=0.121A`
and `  3V3_SYS_V volt(9)=3.3045V`) and writes rpi_pmic_current_amps /
rpi_pmic_volts, one series per rail, atomically.
"""
import os
import re
import subprocess
import sys

OUT = sys.argv[1] if len(sys.argv) > 1 else "/var/lib/node_exporter/textfile_collector/rpi_pmic.prom"
VCGENCMD = "/usr/bin/vcgencmd"
LINE = re.compile(r"^\s*(\S+)_([AV])\s+(?:current|volt)\(\d+\)=([0-9.eE+-]+)[AV]\s*$")

raw = subprocess.run([VCGENCMD, "pmic_read_adc"], capture_output=True, text=True, check=True).stdout
cur, volt = [], []
for line in raw.splitlines():
    m = LINE.match(line)
    if not m:
        continue
    rail, kind, value = m.groups()
    (cur if kind == "A" else volt).append(f'{{rail="{rail}"}} {float(value)}')

lines = ["# TYPE rpi_pmic_current_amps gauge"]
lines += [f"rpi_pmic_current_amps{s}" for s in cur]
lines += ["# TYPE rpi_pmic_volts gauge"]
lines += [f"rpi_pmic_volts{s}" for s in volt]

tmp = OUT + ".tmp"
with open(tmp, "w") as fh:
    fh.write("\n".join(lines) + "\n")
os.replace(tmp, OUT)

#!/usr/bin/env python3
"""Publish OpenBao seal status for node_exporter's textfile collector.

Run every minute by openbao-health.timer (deploy-openbao.yml).
/v1/sys/health needs no token. The query string makes it answer 200 in
every state, so the JSON body can always be read (by default it returns
503 when sealed and 501 when uninitialised).

Writes /var/lib/node_exporter/textfile/openbao_health.prom:
  openbao_health_up  1 if the API answered, else 0
  openbao_sealed     1 if sealed or unreachable, else 0
"""
from __future__ import annotations

import json
import ssl
import urllib.request
from pathlib import Path

ADDR = "https://192.168.20.16:8200"
CACERT = "/usr/local/share/ca-certificates/homelab-root.crt"
TEXTFILE = Path("/var/lib/node_exporter/textfile/openbao_health.prom")
QUERY = "standbyok=true&perfstandbyok=true&sealedcode=200&uninitcode=200"


def main() -> int:
    up, sealed = 0, 1
    try:
        ctx = ssl.create_default_context(cafile=CACERT)
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
        with opener.open(f"{ADDR}/v1/sys/health?{QUERY}", timeout=10) as resp:
            body = json.load(resp)
        up = 1
        sealed = 1 if body.get("sealed", True) else 0
    except (OSError, ValueError):
        pass
    lines = [
        "# HELP openbao_health_up 1 if OpenBao's /v1/sys/health answered.",
        "# TYPE openbao_health_up gauge",
        f"openbao_health_up {up}",
        "# HELP openbao_sealed 1 if OpenBao reports sealed or could not be reached.",
        "# TYPE openbao_sealed gauge",
        f"openbao_sealed {sealed}",
    ]
    tmp = TEXTFILE.with_suffix(".prom.tmp")
    tmp.write_text("\n".join(lines) + "\n")
    tmp.replace(TEXTFILE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

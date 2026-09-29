# lxc-scan-and-monitoring-rollout

Redesigns GVM/Greenbone's credentialed (LSC) scanning from ad hoc
root-SSH-key reuse to a dedicated per-host `gvm-scan` account (unique SSH
keypair + unique sudo password per LXC, OpenBao-backed), and extends both
the Wazuh agent and Docker-container-log-to-Graylog forwarding from a
partial pilot to the full ~36-stack production fleet on `pve`.

See `plan.md` for the full design, the operator's 2026-09-29 judgment-call
answers, and the bounded step packets. Status: **planned, not started.**

One open gap: `plan.md`'s `gvm-03` step needs `secrets/manifest.json`
edited, which this planning session's own permission settings blocked
(no Read/Bash access to anything under `secrets/`, even non-secret field
names) — flagged as prose in the plan for whoever executes it.

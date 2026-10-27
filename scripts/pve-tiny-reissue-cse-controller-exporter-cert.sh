#!/usr/bin/env bash
# One-off: reissue the node_exporter TLS certificate on CT 40070 (cse-controller) with the correct IP in its SAN.
#
# The restored certificate (issued 2026-09-18) names 192.168.40.70, the controller's old infra address, so
# VictoriaMetrics (which verifies the scrape by IP) rejects it: "certificate is valid for 192.168.40.70, not
# 192.168.100.70". The node_exporter role only reissues within 30 days of expiry, so it never replaces it.
# This runs the same `step ca certificate` command as the role, with the right --san, using the provisioner
# password file already on the guest (restored from the old source; never printed).
#
# It issues to temporary files, checks the SAN, backs up the old pair under /root, then swaps and restarts the
# exporter. A failure before the swap leaves the old certificate untouched.
#
# Run on the workstation:
#   ssh root@pve-tiny.gibbsgreatly.xyz "pct exec 40070 -- bash -s" < scripts/pve-tiny-reissue-cse-controller-exporter-cert.sh
set -euo pipefail

D=/etc/node_exporter/certs
IP=192.168.100.70
cleanup() { rm -f "$D/new.crt" "$D/new.key"; }
trap cleanup EXIT

echo "== issue to temporary files (same command as the node_exporter role, correct SAN)"
/usr/local/bin/step ca certificate cse-controller "$D/new.crt" "$D/new.key" \
  --san "$IP" --san cse-controller --not-after 2160h \
  --ca-url https://192.168.20.11 --root /usr/local/share/ca-certificates/homelab-root.crt \
  --provisioner homelab-admin --provisioner-password-file /etc/node_exporter/provisioner-password.txt --force >/dev/null

echo "== check the new certificate before using it"
openssl x509 -in "$D/new.crt" -noout -subject -enddate -ext subjectAltName | sed 's/^ *//'
openssl x509 -in "$D/new.crt" -noout -ext subjectAltName | grep -q "IP Address:$IP" || { echo "SAN does not contain $IP; not installing"; exit 1; }

echo "== install (old pair backed up in /root)"
mkdir -p /root/node-exporter-cert-backup-2026-10-27
cp -p "$D/tls.crt" "$D/tls.key" /root/node-exporter-cert-backup-2026-10-27/
mv "$D/new.crt" "$D/tls.crt"; mv "$D/new.key" "$D/tls.key"
chown root:prometheus "$D/tls.crt" "$D/tls.key"; chmod 0640 "$D/tls.crt" "$D/tls.key"
systemctl restart prometheus-node-exporter.service
sleep 2
echo "exporter: $(systemctl is-active prometheus-node-exporter)"

echo "== verify TLS to the IP with the homelab root (401 = TLS fine, login required)"
curl -s --cacert /usr/local/share/ca-certificates/homelab-root.crt -o /dev/null \
  -w "https://$IP:9100 -> %{http_code}\n" --max-time 8 "https://$IP:9100/metrics"

#!/bin/bash
# Self-signed TLS cert for the HUD. Add your hostnames/IPs to the SAN list.
cd "$(dirname "$0")/.."
mkdir -p certs
HOST_IP=${1:-$(ipconfig getifaddr en0 2>/dev/null || echo 127.0.0.1)}

SAN="DNS:jarvis.local,DNS:jarvis,DNS:localhost,IP:127.0.0.1,IP:$HOST_IP"

# Tailscale: the HUD is normally reached over the tailnet, so the MagicDNS name
# and the 100.x address must be in the SAN or every phone/browser shows a cert
# error. Both are added only when tailscale is actually configured.
if command -v tailscale >/dev/null 2>&1; then
  TS_NAME=$(tailscale status --json 2>/dev/null \
    | /usr/bin/python3 -c 'import json,sys;print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null)
  TS_IP=$(tailscale ip -4 2>/dev/null | head -1)
  [ -n "$TS_NAME" ] && SAN="$SAN,DNS:$TS_NAME,DNS:${TS_NAME%%.*}"
  [ -n "$TS_IP" ]   && SAN="$SAN,IP:$TS_IP"
fi

echo "SAN: $SAN"
openssl req -x509 -newkey rsa:2048 -keyout certs/key.pem -out certs/cert.pem -days 825 -nodes \
  -subj "/CN=Jarvis HUD" \
  -addext "subjectAltName=$SAN"
chmod 600 certs/key.pem
cp certs/cert.pem hud/jarvis.cer   # downloadable from the HUD for phones
echo "cert created — trust certs/cert.pem on your devices"

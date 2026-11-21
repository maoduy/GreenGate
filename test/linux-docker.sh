#!/bin/bash
# Integration test of the Linux install inside a throwaway Ubuntu 24.04 container (no systemd:
# the proxy is started by hand the way the unit would). Needs Docker with NET_ADMIN.
#   test/linux-docker.sh [sheet-id]
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
SHEET=${1:-1VtlZ1FJlUmRQ3VDx7Gzlve7LZ-oHo79P9iFbNj-9VCs}
IMG=ubuntu:24.04
docker run --rm -i --cap-add NET_ADMIN --cap-add NET_RAW -e SHEET="$SHEET" -e DEBIAN_FRONTEND=noninteractive \
  -v "$ROOT":/src:ro "$IMG" bash -s <<'IN'
set -euo pipefail
apt-get update -qq >/dev/null
apt-get install -y -qq python3 python3-venv python3-pip nftables curl libnss3-tools ca-certificates sudo iproute2 >/dev/null
useradd -m kid; useradd -m parent
cp -r /src /work && cd /work
# install without starting (no systemd here)
linux/install.sh --sheet "$SHEET" --users kid --no-start
# start the proxy as the unit would
sudo -u greengate /opt/greengate/venv/bin/mitmdump --mode transparent@127.0.0.1:8080 --mode regular@127.0.0.1:8081 \
   --set confdir=/var/lib/greengate/ca -s /opt/greengate/proxy/greengate.py -q > /tmp/mitm.out 2>&1 &
for i in $(seq 1 40); do sleep 2; c=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 -x http://127.0.0.1:8081 http://greengate.local/ || true); [[ "$c" == "200" ]] && break; done
echo "proxy answers: $c"
for i in $(seq 1 45); do grep -q "lists loaded" /var/lib/greengate/greengate.log 2>/dev/null && break; sleep 2; done
grep -E "lists loaded|options" /var/lib/greengate/greengate.log | tail -2 || echo "sheet NOT loaded"
/usr/local/lib/greengate/nft-apply.sh
# trust the CA (install.sh skipped it because the proxy was not running yet)
cp /var/lib/greengate/ca/mitmproxy-ca-cert.pem /usr/local/share/ca-certificates/greengate.crt && update-ca-certificates >/dev/null
echo "--- as kid (transparent, no proxy flag) ---"
t() { printf "%-45s %s\n" "$1" "$(sudo -u kid curl -s -o /dev/null -w '%{http_code}' --max-time 25 -H 'Sec-Fetch-Dest: document' -A 'Mozilla/5.0' "$1")"; }
t https://www.google.com/; t https://example.com/; t http://example.com/; t https://www.youtube.com/shorts/x
sudo -u kid curl -s --max-time 25 -H 'Sec-Fetch-Dest: document' https://example.com/ | grep -o greengate-block
echo "--- as parent (not filtered) ---"
printf "%-45s %s\n" https://example.com/ "$(sudo -u parent curl -s -o /dev/null -w '%{http_code}' --max-time 25 https://example.com/)"
echo "--- QUIC drop for kid ---"
sudo -u kid timeout 3 bash -c 'echo hi > /dev/udp/8.8.8.8/443' 2>&1 && echo "udp443 sent (dropped silently is fine)" || echo "udp443 rejected"
echo "--- other port for kid (must be rejected) ---"
sudo -u kid curl -s -o /dev/null -w '%{http_code} %{errormsg}\n' --max-time 8 http://portquiz.net:8000/ || true
echo "--- latency as kid: direct (nft off) vs transparent (nft on), 6 runs each ---"
m() { for i in 1 2 3 4 5 6; do sudo -u kid curl -s -o /dev/null -w '%{time_total}\n' --max-time 40 -H 'Sec-Fetch-Dest: document' -A 'Mozilla/5.0' "$1"; done | sort -n | sed -n 3p; }
for u in https://www.google.com/ https://en.wikipedia.org/wiki/Main_Page https://www.ted.com/ https://www.youtube.com/ "https://www.youtube.com/watch?v=LmszJQzuAcc"; do
  on=$(m "$u"); /usr/local/lib/greengate/nft-apply.sh --remove >/dev/null; off=$(m "$u"); /usr/local/lib/greengate/nft-apply.sh >/dev/null
  printf "| %-48s | %6.0f ms | %6.0f ms |\n" "$u" "$(echo "$off*1000" | bc -l 2>/dev/null || python3 -c "print($off*1000)")" "$(python3 -c "print($on*1000)")"
done
echo "--- scheduled screenshots: consent + Drive upload against a local mock (SPEC §8) ---"
python3 /work/test/mock_upload.py --port 18796 --root /tmp/shots-mock > /tmp/mock-upload.log 2>&1 &
sleep 1
sudo -u kid /opt/greengate/venv/bin/python /opt/greengate/agent/greengate_agent.py consent --parent --child | tail -1
sudo -u kid /opt/greengate/venv/bin/python /opt/greengate/agent/greengate_agent.py drive --set http://127.0.0.1:18796/exec --test | tail -2
find /tmp/shots-mock -name '*.jpg' | head -2
echo "--- selftest ---"
LISTED=https://www.google.com/ UNLISTED=https://example.com/ /usr/local/lib/greengate/selftest.sh kid || true
echo "--- uninstall ---"
/usr/local/lib/greengate/uninstall.sh | tail -1
ls /opt/greengate 2>&1 | head -1; nft list table inet greengate 2>&1 | head -1
IN

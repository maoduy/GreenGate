#!/bin/bash
# Remove GreenGate from this Linux machine. Keeps nothing but a copy of the history in /root/greengate-backup-<date>.
set -u
[[ $EUID -eq 0 ]] || { echo "Chạy bằng sudo."; exit 1; }
stamp=$(date +%Y%m%d-%H%M%S)
if [[ -d /var/lib/greengate ]]; then mkdir -p "/root/greengate-backup-$stamp"; cp -a /var/lib/greengate/*.json /var/lib/greengate/*.jsonl /var/lib/greengate/*.log "/root/greengate-backup-$stamp/" 2>/dev/null || true; fi
systemctl disable --now greengate-watchdog.timer greengate.service 2>/dev/null || true
/usr/local/lib/greengate/nft-apply.sh --remove 2>/dev/null || nft delete table inet greengate 2>/dev/null || true
rm -f /etc/systemd/system/greengate.service /etc/systemd/system/greengate-watchdog.service /etc/systemd/system/greengate-watchdog.timer
command -v systemctl >/dev/null 2>&1 && systemctl daemon-reload || true
rm -f /usr/local/share/ca-certificates/greengate.crt /etc/pki/ca-trust/source/anchors/greengate.crt
update-ca-certificates >/dev/null 2>&1 || update-ca-trust 2>/dev/null || true
for home in /home/*; do
  u=$(basename "$home"); [[ -f "$home/.pki/nssdb/cert9.db" ]] && sudo -u "$u" certutil -d "sql:$home/.pki/nssdb" -D -n GreenGate >/dev/null 2>&1
done
for d in /usr/lib/firefox /usr/lib64/firefox /etc/firefox /usr/lib/firefox-esr; do
  f="$d/distribution/policies.json"; [[ -f "$f" ]] && grep -q greengate "$f" && rm -f "$f"
done
rm -f /etc/opt/chrome/policies/managed/greengate.json /etc/chromium/policies/managed/greengate.json /etc/opt/edge/policies/managed/greengate.json
rm -f /etc/xdg/autostart/greengate-agent.desktop
pkill -f "greengate_agent.py run" 2>/dev/null || true
rm -rf /opt/greengate /usr/local/lib/greengate /etc/greengate /var/lib/greengate /usr/local/bin/greengate
userdel greengate 2>/dev/null || true
echo "GreenGate đã được gỡ. Bản sao lịch sử: /root/greengate-backup-$stamp"

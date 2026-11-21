#!/bin/bash
# GreenGate for Linux - run as root on the family PC (Ubuntu/Debian/Fedora/Arch; needs systemd and nftables).
#
#   sudo ./install.sh --sheet <link or id> --users an,binh          # filter these accounts
#   sudo ./install.sh --sheet <id> --users an --no-start            # install only (tests)
#
# What it does
#   1. python venv in /opt/greengate with mitmproxy, the addon in /opt/greengate/proxy
#   2. a system account "greengate" and the data dir /var/lib/greengate (log, CA, history)
#   3. systemd service (transparent proxy on 127.0.0.1:8080, control page on 8081) + a 2-minute health timer
#   4. nftables: the filtered accounts' TCP 80/443 go to the proxy, QUIC is dropped, the rest rejected
#   5. the proxy's certificate: system store + each filtered account's NSS database (Chrome/Chromium/Edge)
#      + Firefox enterprise policy. Browsers of other accounts are untouched.
#   6. `greengate` command (update / status / log / pause / resume / test / uninstall)
set -euo pipefail
SHEET=""; USERS=""; START=1; PORT=8080; RELAY=""; CONSENT=0; ALLOWOUT=""; DEVTOOLS=2
while [[ $# -gt 0 ]]; do
  case "$1" in
    --sheet) SHEET="$2"; shift 2;;
    --users) USERS="$2"; shift 2;;
    --port)  PORT="$2"; shift 2;;
    --relay) RELAY="$2"; shift 2;;
    --allow-out) ALLOWOUT="$2"; shift 2;;
    --allow-devtools) DEVTOOLS=0; shift;;   # the child programs (e.g. `flutter run -d chrome` needs DevTools)   # ip:port,... the accounts may reach directly (e.g. a TURN server for calls)
    --no-start) START=0; shift;;
    --consent) CONSENT=1; shift;;      # a parent and the child agreed to scheduled screenshots (drive/README.md)
    *) echo "unknown option $1"; exit 2;;
  esac
done
[[ $EUID -eq 0 ]] || { echo "Chạy bằng sudo."; exit 1; }
[[ -n "$SHEET" ]] || { echo "Thiếu --sheet <link hoặc id Google Sheet>"; exit 2; }
[[ -n "$USERS" ]] || { echo "Thiếu --users <tài khoản,...> (tài khoản của con)"; exit 2; }
SID=$(echo "$SHEET" | sed -nE 's#.*/spreadsheets/d/([A-Za-z0-9_-]{20,}).*#\1#p'); [[ -n "$SID" ]] || SID=$(echo "$SHEET" | sed -nE 's#^([A-Za-z0-9_-]{20,}).*#\1#p')
[[ -n "$SID" ]] || { echo "Đường liên kết Sheet không hợp lệ"; exit 2; }
HERE=$(cd "$(dirname "$0")" && pwd)
SRC=$(cd "$HERE/.." && pwd)                 # repo or extracted package root
say() { echo "[greengate] $*"; }
# no systemd (containers, tests): the unit files are installed but nothing is started
if command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; then HAVE_SYSTEMD=1; else HAVE_SYSTEMD=0; fi
sc() { [[ $HAVE_SYSTEMD -eq 1 ]] || return 0; systemctl "$@"; }

# ---------------------------------------------------------------- 1. packages + venv
say "cài gói hệ thống"
if command -v apt-get >/dev/null; then
  apt-get install -y -qq python3 python3-venv python3-pip nftables curl libnss3-tools ca-certificates >/dev/null
elif command -v dnf >/dev/null; then
  dnf install -y -q python3 nftables curl nss-tools ca-certificates
elif command -v pacman >/dev/null; then
  pacman -Sy --noconfirm --needed python nftables curl nss ca-certificates >/dev/null
fi
install -d -m 755 /opt/greengate /opt/greengate/proxy /usr/local/lib/greengate /etc/greengate
if [[ ! -x /opt/greengate/venv/bin/mitmdump ]]; then
  say "cài mitmproxy (vài phút lần đầu)"
  python3 -m venv /opt/greengate/venv
  /opt/greengate/venv/bin/pip install --disable-pip-version-check -q "mitmproxy==12.2.3"
fi
cp "$SRC/proxy/greengate.py" "$SRC/proxy/policy.py" "$SRC/proxy/timewindow.py" "$SRC/proxy/sheetlog.py" /opt/greengate/proxy/
for f in nft-apply.sh watchdog.sh pause.sh selftest.sh uninstall.sh agent-start.sh; do install -m 755 "$HERE/$f" /usr/local/lib/greengate/$f; done
# the agent (screenshots, history, remote refresh, app rules) + its libraries in the same venv
if [[ -f "$SRC/agent/greengate_agent.py" ]]; then
  install -d /opt/greengate/agent
  cp "$SRC/agent/greengate_agent.py" /opt/greengate/agent/
  cp "$SRC/proxy/timewindow.py" /opt/greengate/agent/
  if ! /opt/greengate/venv/bin/python -c "import nacl, websocket, mss, PIL, requests" 2>/dev/null; then
    say "cài thư viện cho agent"
    /opt/greengate/venv/bin/pip install --disable-pip-version-check -q -r "$SRC/agent/requirements.txt" || say "CẢNH BÁO: không cài được thư viện agent"
  fi
  install -D -m 644 "$SRC/agent/greengate-agent.desktop" /etc/xdg/autostart/greengate-agent.desktop
  sed -i 's#^Exec=.*#Exec=/usr/local/lib/greengate/agent-start.sh#' /etc/xdg/autostart/greengate-agent.desktop
fi
install -m 755 "$HERE/greengate.sh" /usr/local/bin/greengate
install -m 644 "$HERE/greengate.service" "$HERE/greengate-watchdog.service" "$HERE/greengate-watchdog.timer" /etc/systemd/system/
sed -i "s/transparent@127.0.0.1:8080/transparent@127.0.0.1:$PORT/; s/regular@127.0.0.1:8081/regular@127.0.0.1:$((PORT+1))/" /etc/systemd/system/greengate.service

# ---------------------------------------------------------------- 2. account + data dir
id greengate >/dev/null 2>&1 || useradd --system --home /var/lib/greengate --shell /usr/sbin/nologin greengate
install -d -m 750 -o greengate -g greengate /var/lib/greengate /var/lib/greengate/ca
chmod 755 /var/lib/greengate            # the control page reads nothing from here, but the agent reads the log
IFS=',' read -ra ULIST <<< "$USERS"
for u in "${ULIST[@]}"; do id "$u" >/dev/null 2>&1 || say "CẢNH BÁO: không có tài khoản '$u' trên máy này"; done
python3 - "$SID" "$USERS" "$PORT" "$ALLOWOUT" <<'PY'
import json, os, sys
sid, users, port = sys.argv[1], [u.strip() for u in sys.argv[2].split(",") if u.strip()], int(sys.argv[3])
allow = [a.strip() for a in sys.argv[4].split(",") if a.strip()]
if not allow and os.path.exists("/etc/greengate/greengate.json"):   # a reinstall keeps what was allowed before
    try:
        allow = json.load(open("/etc/greengate/greengate.json", encoding="utf-8")).get("allowOut") or []
    except ValueError:
        pass
cfg = {"sheetId": sid, "enforceUsers": users, "dataDir": "/var/lib/greengate",
       "logFile": "/var/lib/greengate/greengate.log", "port": port,
       "urlLog": {"enabled": True, "flushSeconds": 300, "sheetAllRequests": False,
                  "localFile": "/var/lib/greengate/urls.jsonl", "localMaxMB": 20}}
if allow:
    cfg["allowOut"] = allow
open("/etc/greengate/greengate.json", "w", encoding="utf-8").write(json.dumps(cfg, indent=1, ensure_ascii=False))
PY
ln -sf /etc/greengate/greengate.json /opt/greengate/proxy/greengate.json      # the addon reads it next to itself
chmod 644 /etc/greengate/greengate.json
# nftables needs the kernel module and the service, otherwise the rules vanish on reboot
sc enable nftables.service >/dev/null 2>&1 || true

# ---------------------------------------------------------------- 3. start, wait for the CA
sc daemon-reload
sc enable greengate.service greengate-watchdog.timer >/dev/null
[[ $HAVE_SYSTEMD -eq 0 ]] && { START=0; say "không có systemd: dịch vụ không được khởi động tự động"; }
if [[ $START -eq 1 ]]; then
  systemctl restart greengate.service
  say "chờ proxy trả lời"
  up=0
  for i in $(seq 1 40); do
    sleep 2
    c=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 -x "http://127.0.0.1:$((PORT+1))" http://greengate.local/ 2>/dev/null || true)
    if [[ "$c" =~ ^[0-9]{3}$ && "$c" != "000" ]]; then up=1; break; fi
  done
  if [[ $up -eq 0 ]]; then
    say "proxy KHÔNG khởi động được - gỡ luật nftables để máy vẫn vào mạng được"
    /usr/local/lib/greengate/nft-apply.sh --remove || true
    systemctl status greengate.service --no-pager | tail -20 || true
    exit 1
  fi
  # fail-closed: everything is blocked until the sheet has been read once - wait for it
  for i in $(seq 1 30); do grep -q "lists loaded" /var/lib/greengate/greengate.log 2>/dev/null && break; sleep 2; done
  grep -q "lists loaded" /var/lib/greengate/greengate.log 2>/dev/null && say "đã đọc Google Sheet" || say "chưa đọc được Google Sheet (kiểm tra mạng/ID sheet) - mọi trang sẽ bị chặn tới khi đọc được"
  systemctl start greengate-watchdog.timer
fi

# ---------------------------------------------------------------- 4. trust the CA
CER=/var/lib/greengate/ca/mitmproxy-ca-cert.pem
for i in $(seq 1 20); do [[ -f "$CER" ]] && break; sleep 1; done
if [[ -f "$CER" ]]; then
  if [[ -d /usr/local/share/ca-certificates ]]; then
    cp "$CER" /usr/local/share/ca-certificates/greengate.crt && update-ca-certificates >/dev/null 2>&1 || true
  elif [[ -d /etc/pki/ca-trust/source/anchors ]]; then
    cp "$CER" /etc/pki/ca-trust/source/anchors/greengate.crt && update-ca-trust || true
  fi
  # Chrome / Chromium / Edge on Linux read the per-user NSS database, not the system store.
  for u in "${ULIST[@]}"; do
    home=$(getent passwd "$u" | cut -d: -f6); [[ -d "$home" ]] || continue
    install -d -o "$u" -g "$(id -gn "$u")" "$home/.pki/nssdb"
    [[ -f "$home/.pki/nssdb/cert9.db" ]] || sudo -u "$u" certutil -d "sql:$home/.pki/nssdb" -N --empty-password >/dev/null 2>&1 || true
    sudo -u "$u" certutil -d "sql:$home/.pki/nssdb" -D -n GreenGate >/dev/null 2>&1 || true
    # the CA folder is not readable by the child: root opens the file and hands it over on stdin
    sudo -u "$u" certutil -d "sql:$home/.pki/nssdb" -A -t "C,," -n GreenGate -i /dev/stdin < "$CER" >/dev/null 2>&1 && say "chứng chỉ: tài khoản $u (Chrome/Edge)" || say "chứng chỉ: không thêm được vào NSS của $u"
  done
  # Firefox: enterprise policy, every profile, no clicking
  # The snap Firefox (Ubuntu) cannot be written to; it reads /etc/firefox/policies instead.
  [[ -d /snap/firefox ]] && install -d /etc/firefox/policies
  for d in /usr/lib/firefox /usr/lib64/firefox /etc/firefox /usr/lib/firefox-esr; do
    [[ -d "$d" ]] || continue
    install -d "$d/distribution" 2>/dev/null || install -d "$d/policies" 2>/dev/null || continue
    tgt="$d/distribution/policies.json"; [[ -d "$d/distribution" ]] || tgt="$d/policies/policies.json"
    [[ "$d" == /etc/firefox ]] && tgt="$d/policies/policies.json"
    cat > "$tgt" 2>/dev/null <<JSON || { say "chứng chỉ: không ghi được $tgt"; continue; }
{"policies": {"Certificates": {"ImportEnterpriseRoots": true, "Install": ["/usr/local/share/ca-certificates/greengate.crt"]},
              "DisableDeveloperTools": true, "DisablePrivateBrowsing": true, "DNSOverHTTPS": {"Enabled": false, "Locked": true},
              "NetworkPrediction": false}}
JSON
    say "chứng chỉ: Firefox ($tgt)"
  done
else
  say "chưa có chứng chỉ (proxy chưa chạy) - HTTPS sẽ lỗi cho đến khi chạy lại install"
fi
# Chromium policies: no DoH (would hide the SNI from nothing, but keeps DNS plain and simple), no devtools
for d in /etc/opt/chrome/policies/managed /etc/chromium/policies/managed /etc/opt/edge/policies/managed; do
  install -d "$d"
  cat > "$d/greengate.json" <<JSON
{"DnsOverHttpsMode": "off", "DeveloperToolsAvailability": $DEVTOOLS, "IncognitoModeAvailability": 1,
 "BrowserGuestModeEnabled": false, "QuicAllowed": false}
JSON
done

# ---------------------------------------------------------------- 5. agent config per child (relay optional)
for u in "${ULIST[@]}"; do
  home=$(getent passwd "$u" | cut -d: -f6); [[ -d "$home" ]] || continue
  install -d -o "$u" -g "$(id -gn "$u")" -m 700 "$home/.config/greengate"
  acfg="$home/.config/greengate/agent.json"
  if [[ ! -f "$acfg" ]]; then
    printf '{"relay": "%s", "proxyPort": %s, "parents": [], "platform": "linux", "name": "%s - %s", "consent": {}}\n' "$RELAY" "$((PORT+1))" "$(hostname)" "$u" > "$acfg"
    chown "$u:$(id -gn "$u")" "$acfg"; chmod 600 "$acfg"
  fi
  if [[ -n "$RELAY" || $CONSENT -eq 1 ]]; then
    python3 - "$acfg" "$RELAY" "$CONSENT" <<'PY'
import json, sys, time
p, relay, consent = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
d = json.load(open(p))
if relay: d["relay"] = relay
if consent:
    now = time.strftime("%Y-%m-%dT%H:%M:%S"); d["consent"] = {"parent": now, "child": now}
json.dump(d, open(p, "w"), indent=1)
PY
  fi
done
[[ -n "$RELAY" ]] && say "relay: $RELAY - ghép đôi bằng: sudo greengate pair <tài khoản>"

say "xong. Tài khoản được lọc: $USERS. Kiểm tra: greengate status | greengate test"

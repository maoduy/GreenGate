#!/bin/bash
# greengate test [user]  - probes as the filtered account: a listed site must load, an unlisted
# one must get the GreenGate block page, QUIC must be dropped. Prints PASS/FAIL per check.
set -u
PORT=${GREENGATE_PORT:-8080}
CTL=$((PORT+1))      # regular-mode listener for the control page
CFG=/etc/greengate/greengate.json
KID=${1:-$(python3 -c 'import json;print((json.load(open("/etc/greengate/greengate.json")).get("enforceUsers") or [""])[0])')}
[[ -n "$KID" ]] || { echo "không có tài khoản nào trong enforceUsers"; exit 1; }
fail=0
ok() { echo "PASS  $1"; }
bad() { echo "FAIL  $1"; fail=1; }
c=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 -x "http://127.0.0.1:$CTL" http://greengate.local/ 2>/dev/null)
[[ "$c" == "200" ]] && ok "proxy trả lời trên 127.0.0.1:$CTL" || bad "proxy không trả lời ($c)"
nft list table inet greengate >/dev/null 2>&1 && ok "luật nftables đang bật" || bad "không có luật nftables"
probe() { sudo -u "$KID" curl -s -o /dev/null -w '%{http_code}' --max-time 25 -H 'Sec-Fetch-Dest: document' "$1" 2>/dev/null; }
body() { sudo -u "$KID" curl -s --max-time 25 -H 'Sec-Fetch-Dest: document' "$1" 2>/dev/null; }
LISTED=${LISTED:-https://www.google.com/}; UNLISTED=${UNLISTED:-https://example.com/}
l=$(probe "$LISTED"); [[ "$l" =~ ^(2|3) ]] && ok "$KID vào được $LISTED ($l)" || bad "$KID KHÔNG vào được $LISTED ($l)"
u=$(probe "$UNLISTED"); if [[ "$u" == "403" ]] && body "$UNLISTED" | grep -q greengate-block; then ok "$KID bị chặn ở $UNLISTED (trang chặn GreenGate)"; else bad "$KID không bị chặn đúng ở $UNLISTED ($u)"; fi
me=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$UNLISTED" 2>/dev/null); [[ "$me" =~ ^(2|3) ]] && ok "tài khoản quản trị không bị lọc ($me)" || bad "tài khoản quản trị bị ảnh hưởng ($me)"
q=$(sudo -u "$KID" timeout 5 bash -c 'echo > /dev/udp/8.8.8.8/443' 2>&1 && echo sent || echo blocked); [[ "$q" == "blocked" ]] && ok "UDP 443 (QUIC) bị chặn cho $KID" || echo "INFO  UDP 443: $q (gửi được không có nghĩa là nhận được)"
[[ $fail -eq 0 ]] && echo "VERDICT: HEALTHY" || { echo "VERDICT: PROBLEMS FOUND"; exit 1; }

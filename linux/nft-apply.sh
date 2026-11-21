#!/bin/bash
# Route the filtered accounts' web traffic through the proxy with nftables.
#
#   nft-apply.sh            apply the rules for enforceUsers in /etc/greengate/greengate.json
#   nft-apply.sh --remove   remove the GreenGate table
#
# For every enforced uid: TCP 80/443 -> redirect to 127.0.0.1:8080 (mitmproxy transparent mode
# reads the original destination from the socket); UDP 443 (QUIC) is dropped so browsers fall
# back to TCP; everything else that is not DNS, NTP or loopback is rejected, so there is no port
# a VPN or a hand-written client could use to go around the proxy. Other accounts are untouched.
# Note: the filter chain runs at the same hook as the nat chain, before the kernel re-routes the
# redirected packet, so it still sees oifname = eth0 with daddr already 127.0.0.1:$PORT - the
# redirected connection must be accepted explicitly (ct status dnat / daddr 127.0.0.1).
set -e
CFG=${GREENGATE_CFG:-/etc/greengate/greengate.json}
PORT=${GREENGATE_PORT:-8080}
nft delete table inet greengate 2>/dev/null || true
[[ "$1" == "--remove" ]] && exit 0
mapfile -t USERS < <(python3 -c '
import json,sys
try:
    c=json.load(open(sys.argv[1], encoding="utf-8-sig"))
except Exception as e:
    sys.exit("cannot read %s: %s" % (sys.argv[1], e))
print("\n".join(c.get("enforceUsers") or []))' "$CFG")
# Extra outgoing ports the filtered accounts may use, besides the web: "allowOut" in the config,
# e.g. ["103.82.27.25:3478"] for a TURN server (video/voice calls). Each entry is ip:port, both protocols.
ALLOW=$(python3 -c '
import json,sys,ipaddress
c=json.load(open(sys.argv[1], encoding="utf-8-sig"))
for e in c.get("allowOut") or []:
    ip, _, port = str(e).rpartition(":")
    try:
        a = ipaddress.ip_address(ip.strip("[]")); p = int(port)
    except ValueError:
        print("nft-apply: bad allowOut entry %r - skipped" % e, file=sys.stderr); continue
    fam = "ip" if a.version == 4 else "ip6"
    print("    meta skuid @kids %s daddr %s meta l4proto { tcp, udp } th dport %d accept" % (fam, a, p))
' "$CFG")
if [[ ${#USERS[@]} -eq 0 ]]; then
  echo "nft-apply: no enforceUsers in $CFG - nothing is routed through the proxy" >&2
  exit 0
fi
UIDS=()
for u in "${USERS[@]}"; do
  if id -u "$u" >/dev/null 2>&1; then UIDS+=("$(id -u "$u")"); else echo "nft-apply: unknown account '$u' - skipped" >&2; fi
done
[[ ${#UIDS[@]} -eq 0 ]] && exit 0
SET=$(IFS=,; echo "${UIDS[*]}")
nft -f - <<NFT
table inet greengate {
  set kids { type uid; elements = { $SET } }
  chain output {
    type nat hook output priority -100; policy accept;
    meta skuid @kids oifname "lo" return
    meta skuid @kids tcp dport { 80, 443 } redirect to :$PORT
  }
  chain filter {
    type filter hook output priority 0; policy accept;
    meta skuid @kids oifname "lo" accept
    meta skuid @kids ct status dnat accept
    meta skuid @kids ip daddr 127.0.0.1 tcp dport $PORT accept
    meta skuid @kids ip6 daddr ::1 tcp dport $PORT accept
    meta skuid @kids udp dport 53 accept
    meta skuid @kids tcp dport 53 accept
    meta skuid @kids udp dport 123 accept
$ALLOW
    meta skuid @kids udp dport 443 drop
    meta skuid @kids meta l4proto { tcp, udp } reject
  }
}
NFT
echo "nft-apply: routing uid(s) $SET through 127.0.0.1:$PORT"

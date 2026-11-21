#!/bin/bash
# pause.sh [pause] [minutes] | resume | status - lifts the routing (not the service) for a while.
STATE=/var/lib/greengate/paused
[[ "$1" == "pause" ]] && shift
case "$1" in
  resume)  rm -f "$STATE"; /usr/local/lib/greengate/nft-apply.sh; echo "GreenGate: đã bật lại bộ lọc";;
  status)  if [[ -f "$STATE" ]]; then echo "paused: $(cat "$STATE")"; else echo "active"; fi;;
  *)       mins=${1:-0}; [[ "$mins" =~ ^[0-9]+$ ]] || mins=0
           /usr/local/lib/greengate/nft-apply.sh --remove
           if (( mins > 0 )); then
             date -d "+$mins min" > "$STATE"; echo "GreenGate: tạm dừng $mins phút"
             systemd-run --on-active="${mins}m" --unit greengate-resume /usr/local/lib/greengate/pause.sh resume >/dev/null 2>&1 || true
           else
             echo "cho đến khi chạy: greengate resume" > "$STATE"; echo "GreenGate: tạm dừng cho đến khi 'greengate resume'"
           fi;;
esac

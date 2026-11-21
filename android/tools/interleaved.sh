#!/bin/bash
# For each URL: 5 pairs of (VPN off, VPN on) page loads, same warm state. Prints both medians.
runs=${RUNS:-5}
med() { printf "%s\n" "$@" | sort -n | sed -n "$(( ($#+1)/2 ))p"; }
one() { adb logcat -c; adb shell am start -W -n vn.greengate.app/.ProbeActivity --es url "$1" >/dev/null 2>&1
  for t in $(seq 1 160); do l=$(adb logcat -d -s GreenGateProbe:I | grep PAGE | tail -1); [ -n "$l" ] && break; sleep 0.25; done
  echo "$l" | awk '{print $(NF-1)" "$NF}'; }
vpn() { if [ "$1" = on ]; then adb shell am start -W -n vn.greengate.app/.MainActivity --ez start true >/dev/null 2>&1; sleep 3
        else adb shell am start -W -n vn.greengate.app/.MainActivity --ez stop true >/dev/null 2>&1; sleep 3; fi; }
for u in "$@"; do
  off=(); on=(); st_off=""; st_on=""
  for i in $(seq 1 $runs); do
    vpn off; r=$(one "$u"); off+=(${r% *}); st_off="${r#* }"
    vpn on;  r=$(one "$u"); on+=(${r% *});  st_on="${r#* }"
  done
  echo "RESULT $u off_median=$(med "${off[@]}") on_median=$(med "${on[@]}") off=[${off[*]}] on=[${on[*]}] status_off=$st_off status_on=$st_on"
done

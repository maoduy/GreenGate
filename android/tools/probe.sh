#!/bin/bash
# probe.sh page <url> [runs] | probe.sh dns <host> [runs]  -> prints ms per run and median
kind=$1; target=$2; runs=${3:-5}
vals=()
for i in $(seq 1 $runs); do
  adb logcat -c
  if [ "$kind" = page ]; then adb shell am start -W -n vn.greengate.app/.ProbeActivity --es url "$target" >/dev/null 2>&1
  else adb shell am start -W -n vn.greengate.app/.ProbeActivity --es dns "$target" >/dev/null 2>&1; fi
  line=""
  for t in $(seq 1 120); do
    line=$(adb logcat -d -s GreenGateProbe:I 2>/dev/null | grep -E "PAGE|DNS" | tail -1)
    [ -n "$line" ] && break
    sleep 0.25
  done
  ms=$(echo "$line" | awk '{print $(NF-1)}'); st=$(echo "$line" | awk '{print $NF}')
  [ -z "$ms" ] && ms=99999
  vals+=($ms); echo "  run $i: ${ms} ms ($st)" >&2
  sleep 1
done
sorted=($(printf "%s\n" "${vals[@]}" | sort -n)); mid=${sorted[$((runs/2))]}
echo "$kind $target median=${mid}ms all=${vals[*]}"

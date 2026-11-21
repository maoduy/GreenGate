#!/bin/bash
# Sheet-change propagation: add <host> to the local websites.csv, then poll the device's
# resolver until it answers with a real address. Prints seconds from edit to first allowed answer.
host=${1:-example.org}; dir=${2:?sheet dir}
adb logcat -c
t0=$(date +%s.%N)
echo "$host,," >> "$dir/websites.csv"
while true; do
  adb shell am start -W -n vn.greengate.app/.ProbeActivity --es dns "$host" >/dev/null 2>&1
  sleep 1
  line=$(adb logcat -d -s GreenGateProbe:I | grep "DNS $host" | tail -1)
  addr=$(echo "$line" | awk '{print $NF}')
  if [ -n "$addr" ] && [ "$addr" != "0.0.0.0" ] && [[ "$addr" != error* ]]; then
    t1=$(date +%s.%N); printf "propagated in %.1f s -> %s\n" "$(echo "$t1 - $t0" | bc)" "$addr"; break
  fi
  adb logcat -c
  if (( $(echo "$(date +%s.%N) - $t0 > 400" | bc) )); then echo "timeout"; break; fi
done

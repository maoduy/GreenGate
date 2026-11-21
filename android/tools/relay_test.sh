#!/bin/bash
# Pair with the given relay URL (as seen from the emulator), then run the command battery.
# usage: relay_test.sh http://10.0.2.2:18790 http://127.0.0.1:18790
RELAY_EMU=$1; RELAY_HOST=$2; S=${S:-/tmp}
PY=$(dirname "$0")/.venv/bin/python; CLI=$(dirname "$0")/parent_cli.py
rm -f $(dirname "$0")/parent.json
adb shell am start -W -n vn.greengate.app/.MainActivity --es relay "$RELAY_EMU" --ez start true >/dev/null
sleep 2
adb logcat -c
adb shell am start -W -f 0x10008000 -n vn.greengate.app/.MainActivity --ez pair true >/dev/null; sleep 2
# the pairing code is on the device screen; for automation read it from the app log (uiautomator dump is slower)
for t in $(seq 1 40); do
  code=$(adb shell uiautomator dump /sdcard/ui.xml >/dev/null 2>&1; adb shell cat /sdcard/ui.xml | grep -o 'text="[0-9]\{3\} [0-9]\{3\}"' | head -1 | tr -dc '0-9')
  [ -n "$code" ] && break; sleep 1
done
echo "pairing code: $code"
$PY $CLI --relay "$RELAY_HOST" claim "$code" || exit 1
sleep 3
echo "== info"; $PY $CLI info
echo "== status"; $PY $CLI status
echo "== screenshot (screen on, app in foreground)"; adb shell input keyevent KEYCODE_WAKEUP; adb shell am start -W -n vn.greengate.app/.MainActivity >/dev/null; sleep 1; $PY $CLI screenshot
echo "== screenshot (Chrome in foreground)"; adb shell am start -W -a android.intent.action.VIEW -d https://www.wikipedia.org/ >/dev/null; sleep 4; $PY $CLI screenshot
echo "== screenshot (screen off)"; adb shell input keyevent KEYCODE_SLEEP; sleep 2; $PY $CLI screenshot; adb shell input keyevent KEYCODE_WAKEUP
echo "== history"; $PY $CLI history $(date +%m-%Y)
echo "== pause 1"; $PY $CLI pause 1
echo "== resume"; $PY $CLI resume
echo "== refresh"; $PY $CLI refresh | head -3

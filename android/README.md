# GreenGate for Android

Kotlin app, package `vn.greengate.app`. Same Google Sheet as the PC proxy (see `docs/SPEC.md`).

| Part | File | What |
|---|---|---|
| Filter | `GreenGateVpnService.kt` | VpnService that captures only DNS (route to one fake address), answers 0.0.0.0 for blocked names, relays the rest upstream. SafeSearch by answering with forcesafesearch/restrict/strict addresses. |
| Rules | `Rules.kt`, `SheetSync.kt`, `TimeWindow.kt`, `Csv.kt` | Sheet tabs -> immutable rule set, refreshed every `refreshSeconds` (default 60). |
| Category lists | `CategoryLists.kt` | gz lists from the `lists` release, stored as sorted 64-bit hashes (8 bytes/domain). |
| Apps + screenshots | `AppBlockerService.kt` | AccessibilityService: sends blocked apps home, guards our own Settings pages, `takeScreenshot()` on request. |
| Scheduled shots → Drive | `Shots.kt` | SPEC §8: every `screenshotEvery` min (default 15) inside `screenshotHours`, screen on + unlocked, both consents given → JPEG ≤1280 px q60 → POST to the sheet's `uploadUrl` (parents' Apps Script, write-only); queue of ≤200 files on failure; auto-dismissing notification on every capture. Parent `screenshot` commands get a Drive copy too (`reason: parent`). |
| Relay | `Relay.kt`, `Crypto.kt` | WebSocket client, nacl.box with lazysodium, commands per SPEC §5. Plain frames: `register {sheet}` after connect, `hint {kind: refresh}` from the relay → immediate sheet re-read (≤ 1 per 10 s). |
| History | `DnsLog.kt` | SQLite log of (minute, host, blocked, hits); exported as CSV per month. |
| UI | `MainActivity.kt`, `PairActivity.kt` | Setup, permissions, pairing code + QR. |
| Harness | `ProbeActivity.kt`, `tools/` | Measurements, mock relay, parent CLI, local sheet server. |

## Build

```
echo "sdk.dir=$ANDROID_HOME" > local.properties
./gradlew assembleRelease           # signed with keystore/greengate-release.jks (see keystore/README.md)
```

## Test automation (emulator)

```
adb install -r app/build/outputs/apk/release/app-release.apk
adb shell appops set vn.greengate.app ACTIVATE_VPN allow
adb shell settings put secure enabled_accessibility_services vn.greengate.app/vn.greengate.app.AppBlockerService
adb shell settings put secure accessibility_enabled 1
adb shell dpm set-active-admin vn.greengate.app/.AdminReceiver
adb shell am start -n vn.greengate.app/.MainActivity --es sheet <id> --es relay http://10.0.2.2:18790 --ez start true
# optional overrides for tests: --es sheetBase http://10.0.2.2:8765 --es listsBase http://10.0.2.2:8765/lists
# consent for scheduled screenshots (normally the two checkboxes in the app), and an immediate capture:
adb shell am start -f 0x10008000 -n vn.greengate.app/.MainActivity --ez consentParent true --ez consentChild true
adb shell am start -f 0x10008000 -n vn.greengate.app/.MainActivity --ez shotNow true
adb shell pm grant vn.greengate.app android.permission.POST_NOTIFICATIONS
adb shell am start -n vn.greengate.app/.ProbeActivity --es dns example.org      # logcat tag GreenGateProbe
adb shell am start -n vn.greengate.app/.ProbeActivity --es url https://www.google.com/
```

`tools/mock_relay.py` is an in-memory relay with the SPEC §5 API (+ `POST /v1/sheet/<id>/changed`
which sends the `hint` frame to registered devices), `tools/mock_upload.py` mimics the parents'
Apps Script (302 → JSON, files under `<root>/<device>/<day>/`), `tools/parent_cli.py` plays the
parent (pair, screenshot, history, status, pause, resume), `tools/probe.sh` and
`tools/propagation.sh` produce the numbers in `docs/android-report.md`.
`tools/sheet_server.py <dir> [port]` serves a local copy of the five tabs for `sheetBase`.

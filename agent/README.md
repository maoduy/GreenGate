# GreenGate agent (Windows, Linux)

`greengate_agent.py` runs in the child's login session, keeps a WebSocket to the relay and answers the
parent's encrypted commands. Settings still come from the Google Sheet through the proxy.

```
pip install -r agent/requirements.txt
python agent/greengate_agent.py pair --relay https://relay.example --name "Máy của An"   # shows a 6-digit code + QR
python agent/greengate_agent.py run
python agent/greengate_agent.py status
```

Config: Linux `~/.config/greengate/agent.json`, Windows `%ProgramData%\GreenGate\agent-<user>.json`
(`--config` overrides). `proxyPort` (default 8080) is where the local GreenGate proxy listens; the
agent reaches `http://greengate.local/...` only through it, everything else goes direct (`NO_PROXY=*`).

Commands handled: screenshot (mss -> JPEG <= 1280 px, child gets a notification), history (gzipped
`/log.csv?m=MM-yyyy`), refresh (`/update`), status, pause/resume (`greengate pause N` on Windows,
`/usr/local/lib/greengate/pause.sh` on Linux), settings (screenshotEvery, retentionDays -> local
encrypted auto-captures under `<config dir>/shots/`, pruned after retentionDays).

Windows build: `pyinstaller --noconfirm --clean agent/greengate-agent.spec` -> `dist/GreenGate-Agent.exe`.
Linux: `greengate-agent.service` (systemd --user) or `greengate-agent.desktop` (autostart).

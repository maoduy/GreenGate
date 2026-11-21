#!/bin/bash
# Autostart wrapper: runs the GreenGate agent only for the accounts listed in enforceUsers.
CFG=/etc/greengate/greengate.json
me=$(id -un)
python3 - "$CFG" "$me" <<'PY' || exit 0
import json, sys
c = json.load(open(sys.argv[1], encoding="utf-8-sig"))
sys.exit(0 if sys.argv[2] in (c.get("enforceUsers") or []) else 1)
PY
exec /opt/greengate/venv/bin/python /opt/greengate/agent/greengate_agent.py run

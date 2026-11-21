#!/bin/bash
# If the proxy does not answer its own control page, restart it. Logged to the journal.
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 -x http://127.0.0.1:8081 http://greengate.local/ 2>/dev/null)
if [[ "$code" =~ ^[0-9]{3}$ && "$code" != "000" ]]; then exit 0; fi
echo "greengate-watchdog: proxy not answering (got '$code') - restarting greengate.service"
systemctl restart greengate.service

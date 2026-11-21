#!/bin/bash
# /usr/local/bin/greengate - the one command a parent needs on Linux.
#   greengate update | status | json | log | pause [phút] | resume | pair | consent | drive | test | uninstall
case "$1" in
  update)  curl -s --max-time 60 -x http://127.0.0.1:8081 http://greengate.local/update;;
  status)  curl -s --max-time 10 -x http://127.0.0.1:8081 http://greengate.local/ || echo "GreenGate không trả lời trên 127.0.0.1:8081"
           echo; systemctl --no-pager --lines=0 status greengate.service 2>/dev/null | head -3;;
  json)    curl -s --max-time 10 -x http://127.0.0.1:8081 http://greengate.local/status.json;;
  log)     journalctl -u greengate.service -n 30 --no-pager 2>/dev/null; echo "--- /var/lib/greengate/greengate.log"; tail -n 30 /var/lib/greengate/greengate.log 2>/dev/null;;
  pause)   sudo /usr/local/lib/greengate/pause.sh "${2:-0}";;
  pair)    # sudo greengate pair <tài khoản của con> [--relay URL]
           kid="$2"; [[ -n "$kid" ]] || { echo "dùng: sudo greengate pair <tài khoản> [--relay URL]"; exit 2; }
           sudo -u "$kid" /opt/greengate/venv/bin/python /opt/greengate/agent/greengate_agent.py pair --no-wait "${@:3}";;
  consent) # sudo greengate consent <tài khoản của con> [--parent] [--child] [--reset]   (không tham số = hỏi)
           kid="$2"; [[ -n "$kid" ]] || { echo "dùng: sudo greengate consent <tài khoản> [--parent --child]"; exit 2; }
           sudo -u "$kid" /opt/greengate/venv/bin/python /opt/greengate/agent/greengate_agent.py consent "${@:3}";;
  drive)   # sudo greengate drive <tài khoản của con> [--test] [--set URL]   (ảnh định kỳ lên Google Drive, xem drive/README.md)
           kid="$2"; [[ -n "$kid" ]] || { echo "dùng: sudo greengate drive <tài khoản> [--test] [--set URL]"; exit 2; }
           sudo -u "$kid" /opt/greengate/venv/bin/python /opt/greengate/agent/greengate_agent.py drive "${@:3}";;
  resume)  sudo /usr/local/lib/greengate/pause.sh resume;;
  test)    sudo /usr/local/lib/greengate/selftest.sh "${@:2}";;
  uninstall) sudo /usr/local/lib/greengate/uninstall.sh;;
  *) echo "GreenGate: greengate update | status | json | log | pause [phút] | resume | pair <user> | consent <user> | drive <user> [--test] | test | uninstall";;
esac

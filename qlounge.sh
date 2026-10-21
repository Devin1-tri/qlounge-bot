#!/usr/bin/env bash
# Q Lounge bot launcher. Mirrors sirius.sh / uorm.sh on this machine.
#   ./qlounge.sh start | stop | restart | status | once
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SCREEN="qlounge"
PY=/usr/bin/python3

case "${1:-}" in
  start)
    if screen -ls 2>/dev/null | grep -q "[.]${SCREEN}[[:space:]]"; then
      echo "sudah jalan (screen $SCREEN)"
    else
      screen -dmS "$SCREEN" bash -c "cd '$HERE' && $PY dashboard.py"
      sleep 1
      echo "started (screen -r $SCREEN)"
    fi
    ;;
  stop)
    screen -S "$SCREEN" -X quit 2>/dev/null && echo "stopped" || echo "tidak ada yang jalan"
    ;;
  restart)
    "$0" stop; sleep 1; "$0" start
    ;;
  status)
    if screen -ls 2>/dev/null | grep -q "[.]${SCREEN}[[:space:]]"; then
      echo "AKTIF (screen -r $SCREEN)"
    else
      echo "MATI — ./qlounge.sh start"
    fi
    ;;
  once)
    # one pass, no standby: for cron or a quick check
    cd "$HERE" && exec $PY dashboard.py --once
    ;;
  *)
    echo "pakai: $0 {start|stop|restart|status|once}"
    ;;
esac

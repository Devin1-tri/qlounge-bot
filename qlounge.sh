#!/usr/bin/env bash
# Q Lounge bot - jalan manual. Lo yang bikin screen sendiri kalau mau.
#   ./qlounge.sh              -> dashboard standby (default)
#   ./qlounge.sh once         -> satu pass lalu keluar
#   ./qlounge.sh status       -> lihat saldo & status, lalu keluar
#   ./qlounge.sh run          -> sekali jalan semua akun, tanpa dashboard
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PY=/usr/bin/python3
cd "$HERE"

case "${1:-}" in
  once)
    exec "$PY" dashboard.py --once
    ;;
  status)
    exec "$PY" qlounge.py status
    ;;
  run)
    exec "$PY" qlounge.py run
    ;;
  *)
    exec "$PY" dashboard.py "$@"
    ;;
esac

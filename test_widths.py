#!/usr/bin/env python3
"""Render the dashboard at several terminal widths without touching the network.

Stubs snapshot() so the layout can be checked at 40 / 60 / 80 / 120 columns -
the widths the operator actually uses (phone via Termius, and desktop).
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ui  # noqa: E402
import dashboard as d  # noqa: E402

ROWS = [
    {"label": "akun1", "email": "akun1@gmail.com", "uid": "MQX000000000001",
     "level": "Lv.1 STARTER", "points": "285", "avail": "85", "locked": "200",
     "joined": 0, "streak": 1, "checked_in": True, "ok": True,
     "checklist": [{"code": "daily_check_in", "pts": "20", "done": True},
                   {"code": "check_in_bonus", "pts": "100", "done": False}],
     "today": "185", "cap": "500", "posts_unread": 2,
     "last_run": (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()},
    {"label": "akun2", "email": "second@gmail.com", "uid": "MQX000000000001",
     "level": "Lv.1 STARTER", "points": "1200", "avail": "300", "locked": "900",
     "joined": 3, "streak": 12, "checked_in": True, "ok": True,
     "checklist": [{"code": "daily_check_in", "pts": "20", "done": True}],
     "today": "40", "cap": "500", "posts_unread": 0,
     "last_run": (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()},
    {"label": "akun3", "email": "third@gmail.com", "uid": "MQX000000000002",
     "level": "Lv.1 STARTER", "points": "0", "avail": "0", "locked": "0",
     "joined": 0, "streak": 0, "checked_in": False, "ok": False,
     "error": "login gagal 401"},
]


def main():
    import shutil
    widths = [40, 60, 80, 120]
    ui.C.enabled = False           # plain text: measure the real width
    for w in widths:
        orig = d.term_width
        d.term_width = lambda _w=w: _w
        print(f"########## terminal width = {w} ##########")
        out = d.render(ROWS, {"last_pass": "2026-10-21T11:57:36+00:00",
                              "last_result": "ok"},
                       datetime.now(timezone.utc) + timedelta(hours=4),
                       "perubahan: ri*** +5")
        print(out)
        # width audit
        bad = 0
        for line in out.split("\n"):
            if "│" in line or "┌" in line or "└" in line:
                cells = len(line)
                if cells > w:
                    bad += 1
        print(f"--> baris melebihi {w} kolom: {bad}")
        print()
        d.term_width = orig


if __name__ == "__main__":
    main()

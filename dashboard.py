#!/usr/bin/env python3
"""Q Lounge persistent dashboard — a standby daemon in one terminal panel.

Mirrors the shape of the sirius/uorm bots the operator already runs: clear the
screen, draw a boxed panel, run a pass, then sit idle showing the countdown to
the next pass. Ctrl+C stops it; `screen` keeps it alive.

Two passes per day are enough for this app's reward surface (one check-in per
day plus a handful of post reads), so the default cadence is:

  * a "daily" pass at the configured local hour (default 09:00), which does the
    check-in and reads posts, and
  * a light "refresh" pass every few hours that only re-reads state — so the
    panel stays live and a new post is picked up without waiting a full day.

Usage:
    python3 dashboard.py                # standby forever
    python3 dashboard.py --once         # one pass then exit (for cron)
    python3 dashboard.py --daily-at 8   # local hour for the daily pass
"""
import argparse
import json
import os
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ui  # noqa: E402
from qlounge import (api, load_accounts, load_state, save_state, ensure_token,  # noqa: E402
                     action_check_in, action_notices, action_posts, status)
from anti_detection import Pacing, ANSWER_BANK, DailyBudget  # noqa: E402

W = 76
REFRESH_HOURS = 4          # light pass cadence
MASK_EMAIL = False      # show ri***@gmail.com instead of the full address
LOCAL_TZ_OFFSET = timedelta(hours=8)   # CST (UTC+8), the operator's clock


# ------------------------------------------------------------------ helpers --

def local_now():
    return datetime.now(timezone.utc) + LOCAL_TZ_OFFSET


def hms(seconds):
    """Seconds -> '3h 21m' / '4m 09s' / '12s'. Never negative."""
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {sec:02d}s"
    return f"{sec}s"


def c(text, *styles):
    return ui.paint(text, *styles)



# -------------------------------------------------------------------- render --

def _cells(text):
    """Display width of text, treating wide/emoji codepoints as 2 cells."""
    import unicodedata
    n = 0
    for ch in text:
        if unicodedata.combining(ch):
            continue
        n += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    # ✅ / ⏳ / … arrive via variation selectors; treat pairs as 2 cells
    n += text.count("️")
    return n


def render(rows, st, next_at, action_msg=""):
    """Compact dashboard with column separators.

    One account = one row of a table. Columns are fixed-width and separated by
    a vertical rule, so every account lines up and the eye can scan down a
    column instead of re-reading the whole line.
    """
    os.system("clear" if os.environ.get("TERM") else "true")
    now = local_now()

    # column layout: label | points | level | streak | today | posts | next
    COLS = [("akun", 16), ("poin", 7), ("level", 9), ("streak", 7),
            ("hari ini", 10), ("post", 5), ("next", 9)]
    SEP = c("│", ui.C.DIM)

    def row(cells, header=False):
        """cells = list of strings, one per column (widths come from COLS)."""
        parts = []
        for i, (_, w) in enumerate(COLS):
            txt = str(cells[i]) if i < len(cells) else ""
            if header:
                parts.append(c(f"{txt:<{w}}"[:w], ui.C.BOLD, ui.C.C))
            else:
                parts.append(f"{txt:<{w}}"[:w])
            if i < len(COLS) - 1:
                parts.append(SEP)
        return " " + " ".join(parts) + " "

    def hrule(left, mid, right):
        out = [left]
        for i, (_, w) in enumerate(COLS):
            out.append("─" * (w + 2))
            out.append(mid if i < len(COLS) - 1 else right)
        return "".join(out)

    lines = []
    lines.append(c(hrule("┌", "┬", "┐"), ui.C.C))
    title = f" Q LOUNGE BOT  ·  {now:%Y-%m-%d %H:%M:%S}"
    lines.append(c("│", ui.C.C) + c(title, ui.C.BOLD, ui.C.M)
                 + c(" " * max(0, W + 1 - _cells(title)) + "│", ui.C.C))
    lines.append(c(hrule("├", "┼", "┤"), ui.C.C))
    lines.append(c("│", ui.C.C) + row([n for n, _ in COLS], header=True)
                 + c("│", ui.C.C))
    lines.append(c(hrule("├", "┼", "┤"), ui.C.C))

    if not rows:
        msg = " accounts.json kosong — salin accounts.example.json"
        lines.append(c("│", ui.C.C) + c(msg, ui.C.Y)
                     + c(" " * max(0, W + 1 - _cells(msg)) + "│", ui.C.C))

    for r in rows:
        if not r.get("ok"):
            cells = [r["label"][:16], "-", "ERROR", "-", "-", "-", "-"]
            lines.append(c("│", ui.C.C) + row(cells) + c("│", ui.C.C))
            continue

        earned, cap = r.get("today", "0"), r.get("cap", "0")
        frac = 0.0
        try:
            frac = float(earned) / float(cap or 1)
        except Exception:
            pass

        lr = r.get("last_run")
        nxt_txt = "-"
        if lr:
            try:
                dt = datetime.fromisoformat(lr)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                left = (dt + timedelta(days=1)
                        - datetime.now(timezone.utc)).total_seconds()
                nxt_txt = hms(left) if left > 0 else "siap"
            except Exception:
                pass

        cells = [
            r["label"][:16],
            ui.fmt_pts(r["points"]),
            r.get("level", "?").replace("Lv.", "")[:9],
            str(r.get("streak", 0)),
            ui.fmt_pts(r.get("today", "0")),
            str(r.get("posts_unread", 0)),
            nxt_txt[:9],
        ]
        lines.append(c("│", ui.C.C) + row(cells) + c("│", ui.C.C))

    lines.append(c(hrule("├", "┴", "┤"), ui.C.C))

    nxt = (next_at.astimezone(timezone.utc) + LOCAL_TZ_OFFSET
           if next_at else None)
    nxt_txt = f"{nxt:%H:%M:%S}" if nxt else "-"
    left = hms((next_at - datetime.now(timezone.utc)).total_seconds()) if next_at else "-"
    foot = (f" refresh tiap {REFRESH_HOURS:g}j  ·  berikutnya "
            f"{nxt_txt} ({left})")
    lines.append(c("│", ui.C.C) + c(foot, ui.C.DIM)
                 + c(" " * max(0, W + 1 - _cells(foot)) + "│", ui.C.C))
    if action_msg:
        a = f" {action_msg}"
        lines.append(c("│", ui.C.C) + c(a, ui.C.C)
                     + c(" " * max(0, W + 1 - _cells(a)) + "│", ui.C.C))
    last = f" pass terakhir {st.get('last_pass', '-')}"
    lines.append(c("│", ui.C.C) + c(last, ui.C.DIM)
                 + c(" " * max(0, W + 1 - _cells(last)) + "│", ui.C.C))
    hint = " Ctrl+C = stop"
    lines.append(c("│", ui.C.C) + c(hint, ui.C.DIM)
                 + c(" " * max(0, W + 1 - _cells(hint)) + "│", ui.C.C))
    lines.append(c(hrule("└", "─", "┘"), ui.C.C))

    # detail block under the table: only the pending daily work, one line each
    detail = []
    for r in rows:
        if not r.get("ok"):
            continue
        cl = r.get("checklist") or []
        pend = [i for i in cl if not i.get("done")]
        label = f"{r['label']:<16}"
        if pend:
            names = "  ".join(f"{i['code'].replace('_', ' ')} "
                              f"{ui.fmt_pts(i['pts'] or 0)}" for i in pend[:4])
            more = f"  +{len(pend) - 4}" if len(pend) > 4 else ""
            detail.append(c(f"  {label}", ui.C.BOLD, ui.C.W)
                          + c("belum: ", ui.C.DIM) + c(names, ui.C.Y)
                          + (c(more, ui.C.DIM) if more else ""))
        else:
            detail.append(c(f"  {label}", ui.C.BOLD, ui.C.W)
                          + c("semua tugas harian selesai", ui.C.G))
        em = (f"{r.get('email', '?')}  ·  {r.get('uid', '?')}  ·  "
              f"tersedia {ui.fmt_pts(r.get('avail', 0))} / "
              f"terkunci {ui.fmt_pts(r.get('locked', 0))}  ·  "
              f"undangan {r.get('joined', 0)}")
        detail.append(c(" " * 18, ui.C.DIM) + c(em, ui.C.DIM))
    if detail:
        lines.append("")
        lines.extend(detail)

    return "\n".join(lines)


# ----------------------------------------------------------------- gathering --

def snapshot(label, account, mask_email=False):
    """Everything the panel shows for one account, read-only."""
    row = {"label": label,
           "email": ui.mask_email(account["email"]) if mask_email
                    else account["email"],
           "ok": False}
    token = ensure_token(account)
    if not token:
        row["error"] = "login gagal"
        return row

    code, me = api("/auth/me", token=token)
    if code != 200:
        row["error"] = f"auth {code}"
        return row
    row["ok"] = True
    row["uid"] = me.get("membership", {}).get("uid", "?")
    mem = me.get("membership", {})
    row["level"] = f"Lv.{mem.get('level', '?')} {str(mem.get('levelName', '?')).upper()}"
    row["xp"] = mem.get("xp", 0)
    row["next_xp"] = mem.get("nextLevelXp")
    pt = me.get("point", {})
    row["points"] = pt.get("balance", "0")
    row["avail"] = pt.get("available", "0")
    row["locked"] = pt.get("locked", "0")

    code, att = api("/attendance/today", token=token)
    if code == 200:
        row["checked_in"] = bool(att.get("checkedIn"))
        row["streak"] = att.get("streakDays", 0)
        row["quiz"] = (att.get("question") or {}).get("body", "")

    code, earn = api("/rewards/earn-items", token=token)
    if code == 200:
        items = earn if isinstance(earn, list) else []
        done = [i for i in items if i.get("completed")]
        pending = [i for i in items
                   if not i.get("completed") and i.get("section") in ("daily", "one_time")]
        row["earn_done"] = len(done)
        row["earn_total"] = len(items)
        # the checklist the panel draws: daily + one-time items with their state
        row["checklist"] = [{
            "code": i["code"],
            "pts": i.get("pointAmount"),
            "xp": i.get("xpAmount"),
            "done": bool(i.get("completed")),
            "daily": i.get("section") == "daily",
        } for i in items if i.get("section") in ("daily", "one_time")]

    code, posts = api("/community/posts", token=token)
    if code == 200:
        unread = [p for p in posts.get("items", []) if not p.get("read")]
        row["posts_unread"] = len(unread)

    code, inv = api("/invites/sent/summary", token=token)
    if code == 200:
        row["joined"] = inv.get("joinedCount", 0)
        row["inv_pts"] = inv.get("pointsEarned", "0")

    code, today = api("/rewards/earned-today", token=token)
    if code == 200:
        row["today"] = today.get("earnedToday", "0")
        row["cap"] = today.get("dailyPointCap", "0")

    st = load_state(label)
    row["last_run"] = st.get("last_run_at")
    row["last_balance"] = st.get("last_balance")
    return row


# --------------------------------------------------------------------- passes --

def daily_pass(accounts, rows_before):
    """Do the actual daily actions. Returns (results, deltas)."""
    results, deltas = {}, {}
    for acc in accounts:
        label = acc["label"]
        st = load_state(label)
        st["label"] = label
        token = ensure_token(acc)
        if not token:
            results[label] = "login gagal"
            continue
        try:
            pacing = Pacing(acc.get("pacing", {}))
            results[label] = {}
            ok, msg = action_check_in(token, st, pacing)
            results[label]["check_in"] = (ok, msg)
            ok2, msg2 = action_notices(token, st, pacing)
            results[label]["notices"] = (ok2, msg2)
            if acc.get("max_posts_per_run") != 0:
                ok3, msg3 = action_posts(token, st, pacing,
                                         acc.get("max_posts_per_run"))
            else:
                ok3, msg3 = True, "dilewati"
            results[label]["posts"] = (ok3, msg3)
            save_state(label, last_run_at=datetime.now(timezone.utc).isoformat(),
                       last_result={"check_in": ok, "notices": ok2, "posts": ok3})
            # points delta for the footer
            code, me = api("/auth/me", token=token)
            if code == 200:
                bal = me["point"]["balance"]
                prev = st.get("last_balance")
                if prev:
                    try:
                        gain = float(bal) - float(prev)
                        if gain:
                            deltas[label] = f"+{ui.fmt_pts(gain)}"
                    except Exception:
                        pass
                save_state(label, last_balance=bal)
        except Exception as ex:            # noqa: BLE001
            results[label] = f"ERROR {type(ex).__name__}: {ex}"
    return results, deltas


def due_for_daily(label):
    """True when the once-per-day guard would let this account run."""
    ran = load_state(label).get("last_run_at")
    if not ran:
        return True
    try:
        dt = datetime.fromisoformat(ran)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.date() < datetime.now(timezone.utc).date()
    except Exception:
        return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="satu pass lalu keluar")
    ap.add_argument("--daily-at", type=int, default=9,
                    help="jam lokal untuk pass harian (default 9)")
    ap.add_argument("--refresh-hours", type=float, default=REFRESH_HOURS)
    args = ap.parse_args()

    ui.C.reset()
    accounts = load_accounts()
    if not accounts:
        print("accounts.json kosong — salin accounts.example.json")
        return 1

    refresh_hours = args.refresh_hours
    globals()["REFRESH_HOURS"] = refresh_hours

    last_action = ""
    while True:
        rows = [snapshot(a["label"], a, mask_email=MASK_EMAIL) for a in accounts]
        st = {
            "last_pass": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "last_result": "refresh",
        }

        # run the daily pass for any account that has not run today
        due = [a for a in accounts if due_for_daily(a["label"])]
        if due:
            results, deltas = daily_pass(due, rows)
            st["last_result"] = (", ".join(
                f"{k}: {'ok' if v == 'ok' or isinstance(v, dict) else v}"
                for k, v in results.items())) or "ok"
            if deltas:
                st["deltas"] = deltas
                last_action = "perubahan: " + "  ".join(
                    f"{k} {v}" for k, v in deltas.items())
            rows = [snapshot(a["label"], a, mask_email=MASK_EMAIL) for a in accounts]

        next_at = datetime.now(timezone.utc) + timedelta(hours=REFRESH_HOURS)
        print(render(rows, st, next_at, last_action))

        if args.once:
            return 0
        try:
            time.sleep(2)
        except KeyboardInterrupt:
            print("\n[stopped]", flush=True)
            return 0
        # idle loop: just keep the panel fresh with the countdown
        while True:
            try:
                time.sleep(30)
            except KeyboardInterrupt:
                print("\n[stopped]", flush=True)
                return 0
            rows = [snapshot(a["label"], a, mask_email=MASK_EMAIL) for a in accounts]
            nxt = datetime.now(timezone.utc) + timedelta(
                hours=max(0.0, (next_at - datetime.now(timezone.utc)).total_seconds() / 3600.0))
            print(render(rows, st, nxt, last_action))
            if datetime.now(timezone.utc) >= next_at:
                break


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[stopped]", flush=True)

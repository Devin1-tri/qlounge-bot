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
    """Compact dashboard.

    One line per account carries everything that matters, plus a shared footer.
    No per-account boxes - they were what made the old panel feel crowded.
    """
    os.system("clear" if os.environ.get("TERM") else "true")
    now = local_now()
    lines = []

    # header: one rule, one title line, one rule
    lines.append(c("─" * (W + 2), ui.C.DIM))
    lines.append(c(f" Q LOUNGE BOT", ui.C.BOLD, ui.C.M)
                 + c(f"  ·  {now:%Y-%m-%d %H:%M:%S}", ui.C.DIM))
    lines.append(c("─" * (W + 2), ui.C.DIM))

    if not rows:
        lines.append(c(" accounts.json kosong — salin accounts.example.json", ui.C.Y))
        lines.append(c("─" * (W + 2), ui.C.DIM))
        return "\n".join(lines)

    for r in rows:
        if not r.get("ok"):
            lines.append(" " + c(f"{r['label']:<16}", ui.C.BOLD)
                         + c("  ERROR ", ui.C.R)
                         + c(str(r.get("error", "?")), ui.C.DIM))
            continue

        # ---- line 1: label · points · level · streak ----
        pts = ui.fmt_pts(r["points"])
        lvl = r.get("level", "?")
        streak = r.get("streak", 0)
        lines.append(
            " " + c(f"{r['label']:<16}", ui.C.BOLD, ui.C.W)
            + c(f"{pts:>7}", ui.C.BOLD, ui.C.G) + " pts  "
            + c(f"{lvl}", ui.C.C)
            + c(f"  ·  streak {streak}", ui.C.Y if streak else ui.C.DIM))

        # ---- line 2: email · uid · available/locked · invites ----
        email = r.get("email", "?")
        uid = r.get("uid", "?")
        avail = ui.fmt_pts(r.get("avail", 0))
        locked = ui.fmt_pts(r.get("locked", 0))
        joined = r.get("joined", 0)
        lines.append(
            " " + c(" " * 16)
            + c(email, ui.C.DIM) + "  "
            + c(uid, ui.C.DIM) + "  "
            + c("tersedia ", ui.C.DIM) + c(avail, ui.C.W)
            + c(" / terkunci ", ui.C.DIM) + c(locked, ui.C.W)
            + c(f"  ·  undangan {joined}", ui.C.DIM))

        # ---- line 3: daily checklist (compact, only pending shown) ----
        cl = r.get("checklist") or []
        if cl:
            marks = []
            for it in cl:
                if it["done"]:
                    continue                      # done = nothing to say
                pts_i = ui.fmt_pts(it["pts"] or 0)
                if it.get("daily"):
                    marks.append(c(f"{it['code'].replace('_', ' ')} {pts_i}", ui.C.Y))
                else:
                    marks.append(c(f"{it['code'].replace('_', ' ')} {pts_i}", ui.C.DIM))
            if marks:
                lines.append(" " + c(" " * 16)
                             + c("belum: ", ui.C.DIM)
                             + c("  ".join(marks[:3]), ui.C.W)
                             + (c(f"  +{len(marks) - 3}", ui.C.DIM) if len(marks) > 3 else ""))
            elif cl:
                lines.append(" " + c(" " * 16)
                             + c("semua tugas harian selesai", ui.C.G))

        # ---- line 4: today vs cap bar · unread posts · cooldown ----
        earned, cap = r.get("today", "0"), r.get("cap", "0")
        frac = 0.0
        try:
            frac = float(earned) / float(cap or 1)
        except Exception:
            pass
        unread = r.get("posts_unread", 0)
        tail = c(f"post {unread}", ui.C.C if unread else ui.C.DIM)

        lr = r.get("last_run")
        if lr:
            try:
                dt = datetime.fromisoformat(lr)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                left = (dt + timedelta(days=1)
                        - datetime.now(timezone.utc)).total_seconds()
                if left > 0:
                    tail += c(f"  ·  next {hms(left)}", ui.C.Y)
                else:
                    tail += c("  ·  daily siap", ui.C.G)
            except Exception:
                pass

        lines.append(" " + c(" " * 16)
                     + c(f"hari ini {ui.fmt_pts(earned)}", ui.C.W)
                     + c(" " + ui.bar(frac, 18, ui.C.G) + " ", ui.C.DIM)
                     + tail)

    lines.append(c("─" * (W + 2), ui.C.DIM))

    # footer
    nxt = (next_at.astimezone(timezone.utc) + LOCAL_TZ_OFFSET
           if next_at else None)
    nxt_txt = f"{nxt:%H:%M:%S}" if nxt else "-"
    left = hms((next_at - datetime.now(timezone.utc)).total_seconds()) if next_at else "-"
    lines.append(" " + c(f"refresh tiap {REFRESH_HOURS:g}j", ui.C.DIM)
                 + c(f"  ·  pass terakhir {st.get('last_pass', '-')}", ui.C.DIM)
                 + c(f"  ·  berikutnya {nxt_txt} ({left})", ui.C.Y))
    if action_msg:
        lines.append(" " + c(action_msg, ui.C.C))
    lines.append(" " + c("Ctrl+C = stop", ui.C.DIM))
    lines.append(c("─" * (W + 2), ui.C.DIM))
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

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
import fcntl
import json
import os
import sys
import time
import random
import shutil
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ui  # noqa: E402
from qlounge import (api, load_accounts, load_state, save_state, ensure_token,  # noqa: E402
                     action_check_in, action_notices, action_posts, status, log)
from anti_detection import Pacing, ANSWER_BANK, DailyBudget  # noqa: E402

# --------------------------------------------------------------- single lock --
LOCK_PATH = HERE / "state" / "dashboard.lock"


class AlreadyRunning(RuntimeError):
    pass


def acquire_lock():
    """Take an exclusive process lock, or exit loudly.

    WHY: the API rotates the refresh token on every /auth/refresh and rejects
    reuse of the old one with 401 AUTH_REFRESH_TOKEN_REUSED. Two live processes
    therefore fight over one account: the first rotates the token, the second
    presents the now-dead token, gets 401, and burns a full re-login. Nothing
    used to stop a stale screen session and a freshly started one from both
    running. fcntl.flock is released automatically if the process dies, so a
    crashed run never leaves the lock stuck.
    """
    try:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        fh = open(LOCK_PATH, "w")
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fh.write(f"{os.getpid()}\n")
        fh.flush()
        return fh                      # keep the handle alive for the process
    except OSError:
        raise AlreadyRunning(
            f"dashboard sudah jalan (lock: {LOCK_PATH}). "
            "Hentikan yang lama dulu - dua proses berebut refresh token "
            "dan akun bisa kena 401 AUTH_REFRESH_TOKEN_REUSED.")


def term_width():
    """Actual terminal width, no floor - a phone terminal really is ~40 cols."""
    try:
        return shutil.get_terminal_size((80, 24)).columns
    except Exception:
        return 80


W = 76
REFRESH_HOURS = 4          # light pass cadence
MASK_EMAIL = False      # show ri***@gmail.com instead of the full address
LOCAL_TZ_OFFSET = timedelta(hours=8)   # CST (UTC+8), the operator's clock

# column plan for a wide terminal:
#   akun | username | poin | level | streak | hari ini | checkin | post | email | next
# The three task columns are ticked from the daily pass: the chores it ran are
# checked, the ones it could not finish stay open. That replaces the old
# free-text "belum: ..." / "sudah beres, reward belum diklaim" lines, which said
# the same thing in words and were ambiguous to read.
WIDE_COLS = [("akun", 12), ("username", 15), ("poin", 6), ("level", 12),
             ("streak", 6), ("hari ini", 8), ("checkin", 8), ("post", 6),
             ("email", 7), ("next", 8)]
# phone fallback: keep the account and what it owes, drop the rest
NARROW_COLS = [("akun", 10), ("poin", 6), ("checkin", 8), ("post", 6),
               ("email", 7), ("next", 8)]


def plan_cols():
    """Pick the column set that fits this terminal, and trim it if it still doesn't."""
    w = term_width()
    cols = WIDE_COLS if w >= 74 else NARROW_COLS
    # a very narrow terminal drops columns from the right until the rule fits
    while cols and (sum(c[1] for c in cols) + 3 * len(cols) + 1) > w:
        cols = cols[:-1]
    return cols or [("akun", min(12, max(6, w - 2)))]


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



def task_checks(label, row):
    """Tiga kolom tugas harian: checkin / post / email verify reward.

    Tick hanya kalau bot benar-benar sudah beres tugas itu:
      * checkin  -> akun sudah check-in hari ini (attendance.checkedIn)
      * post     -> tidak ada post baru yang belum dibaca
      * email    -> email terverifikasi DAN reward verify_email sudah completed

    Hasil pass harian disimpan di state (task_checks) dan menang atas cek API,
    karena API bisa bilang "selesai" untuk satu hari sementara pass-nya gagal.
    """
    last = load_state(label).get("task_checks") or {}
    if isinstance(last, dict) and any(last.values()):
        return {k: bool(last.get(k)) for k in ("checkin", "post", "email")}
    return {
        "checkin": bool(row.get("checked_in")),
        "post": row.get("posts_unread") == 0,
        "email": bool(row.get("email_verified")) and bool(row.get("email_reward_claimed")),
    }


def tick(ok):
    """Ceklis kolom tugas: [+]/[-] ASCII-only supaya lebar kolom nggak meleset."""
    return c("[+]", ui.C.G, ui.C.BOLD) if ok else c("[-]", ui.C.DIM)


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


def _strip(text):
    """Drop ANSI escape sequences so width math sees the visible text only."""
    import re
    return re.sub(r"\033\[[0-9;]*m", "", text)


def _fit_line(text, limit):
    """Truncate to `limit` chars, keeping ANSI codes intact."""
    if _cells(text) <= limit:
        return text
    # walk chars, skip escape sequences when counting
    out, used, i = [], 0, 0
    while i < len(text):
        if text[i] == "\033":
            j = text.find("m", i)
            if j == -1:
                break
            out.append(text[i:j + 1])
            i = j + 1
            continue
        if used >= limit - 1:
            break
        out.append(text[i])
        used += 1
        i += 1
    return "".join(out) + "\033[0m" if ui.C.enabled else "".join(out) + "…"


def render(rows, st, next_at, action_msg=""):
    """Compact dashboard with column separators.

    One account = one row of a table. Columns are fixed-width and separated by
    a vertical rule, so every account lines up and the eye can scan down a
    column instead of re-reading the whole line.
    """
    # Only clear on an interactive terminal. When stdout is a pipe or a file
    # (screen capture, log redirect, cron), os.system("clear") still emits the
    # escape but the panel then scrolls away - and on some setups it swallows
    # the whole first frame, which looks like "the bot printed nothing".
    if os.environ.get("TERM") and sys.stdout.isatty():
        os.system("clear")
    now = local_now()

    # columns adapt to the terminal: full set on a desktop, trimmed on a phone
    COLS = plan_cols()
    W = sum(w for _, w in COLS) + 3 * len(COLS) + 1
    SEP = c("│", ui.C.DIM)

    def row(cells, header=False):
        """cells = list of strings, one per column (widths come from COLS)."""
        parts = []
        for i, (_, w) in enumerate(COLS):
            txt = str(cells[i]) if i < len(cells) else ""
            if header:
                parts.append(c(f"{txt:<{w}}"[:w], ui.C.BOLD, ui.C.C))
            elif "\033[" in txt:            # already painted (tick cell)
                parts.append(txt + " " * max(0, w - _cells(_strip(txt))))
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

    def panel_line(text, style):
        """One full-width panel row: │ text padded/truncated to W-1 │."""
        return (c("│", ui.C.C) + c(_fit_line(text, W - 1), *style)
                + c("│", ui.C.C))

    lines = []
    lines.append(c(hrule("┌", "┬", "┐"), ui.C.C))
    title = f" Q LOUNGE BOT  ·  {now:%Y-%m-%d %H:%M:%S}"
    lines.append(panel_line(title, (ui.C.BOLD, ui.C.M)))
    lines.append(c(hrule("├", "┼", "┤"), ui.C.C))
    lines.append(c("│", ui.C.C) + row([n for n, _ in COLS], header=True)
                 + c("│", ui.C.C))
    lines.append(c(hrule("├", "┼", "┤"), ui.C.C))

    if not rows:
        lines.append(panel_line(" accounts.json kosong — salin accounts.example.json",
                                (ui.C.Y,)))

    # every column name maps to the value it shows, so a trimmed column set
    # (phone) still gets the right cell instead of a fixed 7-slot list
    def account_cells(r, nxt_txt):
        # level shows "Lv.N NAME" plus XP progress when the API gives both ends
        lvl = r.get("level", "?").replace("Lv.", "")
        xp = r.get("xp")
        need = r.get("next_xp")
        if xp is not None and need:
            lvl = f"{lvl} {xp}/{need}"
        chk = task_checks(r["label"], r)
        return {
            "akun": r["label"][:12],
            "username": (r.get("nickname") or "-")[:15],
            "poin": ui.fmt_pts(r["points"]),
            "level": lvl[:12],
            "streak": str(r.get("streak", 0)),
            "hari ini": ui.fmt_pts(r.get("today", "0")),
            "checkin": tick(chk["checkin"]),
            "post": tick(chk["post"]),
            "email": tick(chk["email"]),
            "next": nxt_txt[:8],
        }

    for r in rows:
        lr = r.get("last_run")
        nxt_txt = "-"
        if lr and r.get("ok"):
            try:
                dt = datetime.fromisoformat(lr)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                left = (dt + timedelta(days=1)
                        - datetime.now(timezone.utc)).total_seconds()
                nxt_txt = hms(left) if left > 0 else "siap"
            except Exception:
                pass

        if not r.get("ok"):
            vals = {k: "-" for k, _ in COLS}
            vals["akun"] = r["label"][:16]
            vals["level"] = "ERROR"
        else:
            vals = account_cells(r, nxt_txt)

        lines.append(c("│", ui.C.C)
                     + row([vals.get(name, "-") for name, _ in COLS])
                     + c("│", ui.C.C))

    lines.append(c(hrule("├", "┴", "┤"), ui.C.C))
    lines.append(c(hrule("└", "─", "┘"), ui.C.C))

    # detail block under the table: identity + XP + the two chores whose reward
    # the app leaves unclaimed by design (they are not to-dos, so they are not
    # in the task columns and must not be spelled out as pending work either)
    detail = []
    for r in rows:
        if not r.get("ok"):
            # an account that failed to log in still gets a row in the detail
            # box, otherwise the panel looks half-rendered instead of "this one
            # needs attention"
            detail.append(c(f"  {r['label']:<12} ", ui.C.BOLD, ui.C.W)
                          + c(f"{r.get('email', '?')}  ·  "
                              f"{r.get('error') or 'tidak bisa dibaca'}  ·  "
                              f"cek accounts.json / koneksi", ui.C.Y))
            continue
        detail.append(c(f"  {r['label']:<12} ", ui.C.BOLD, ui.C.W)
                      + c(f"{r.get('email', '?')}  ·  {r.get('uid', '?')}  ·  "
                          f"tersedia {ui.fmt_pts(r.get('avail', 0))} / "
                          f"terkunci {ui.fmt_pts(r.get('locked', 0))}  ·  "
                          f"undangan {r.get('joined', 0)}", ui.C.DIM))
        # XP progress. Keep both numbers even when xp > nextLevelXp: the API
        # exposes nextLevelXp but no level-up mechanism exists yet (probed 9
        # candidate endpoints, all 404), so the threshold is informational.
        xp, need = r.get("xp"), r.get("next_xp")
        if xp is not None and need:
            nxt_name = r.get("next_level_name") or "?"
            frac = 0.0
            try:
                frac = float(xp) / float(need or 1)
            except Exception:
                pass
            state = (c(f"target {nxt_name} tercapai", ui.C.Y) if frac >= 1.0
                     else c(f"menuju {nxt_name}", ui.C.M))
            detail.append(c(" " * 15, ui.C.DIM)
                          + c("XP ", ui.C.DIM)
                          + c(f"{xp}/{need}", ui.C.W)
                          + c(" " + ui.bar(frac, 14, ui.C.M) + " ", ui.C.DIM)
                          + state)
    if detail:
        # detail block gets its own box, same width as the table above, so the
        # whole panel reads as one framed dashboard instead of loose lines
        lines.append(c(hrule("┌", "─", "┐"), ui.C.C))
        for ln in detail:
            lines.append(panel_line(ln, ()))
        lines.append(c(hrule("└", "─", "┘"), ui.C.C))
    else:
        lines.append("")

    # footer info goes LAST, under the per-account detail: the eye reads
    # accounts first, the "when does it run again" line is reference material.
    # No box around it - the table above already owns the framed area.
    nxt = (next_at.astimezone(timezone.utc) + LOCAL_TZ_OFFSET
           if next_at else None)
    nxt_txt = f"{nxt:%H:%M:%S}" if nxt else "-"
    left = hms((next_at - datetime.now(timezone.utc)).total_seconds()) if next_at else "-"
    lines.append("")
    lines.append(_fit_line(
        c(f" refresh tiap {REFRESH_HOURS:g}j  ·  berikutnya {nxt_txt} ({left})",
          ui.C.DIM), term_width()))
    if action_msg:
        lines.append(_fit_line(c(f" {action_msg}", ui.C.C), term_width()))
    lines.append(_fit_line(
        c(f" pass terakhir {st.get('last_pass', '-')}", ui.C.DIM), term_width()))
    lines.append(_fit_line(c(" Ctrl+C = stop", ui.C.DIM), term_width()))

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
    row["nickname"] = me.get("nickname") or "-"
    row["level"] = f"Lv.{mem.get('level', '?')} {str(mem.get('levelName', '?')).upper()}"
    row["xp"] = mem.get("xp", 0)
    row["next_xp"] = mem.get("nextLevelXp")
    row["next_level_name"] = mem.get("nextLevelName")
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

        # Cross-check against /auth/me: an item can be genuinely satisfied on the
        # account while its reward entry stays unclaimed. emailVerified=true with
        # verify_email completed=false means "email already verified, reward not
        # yet claimed" - showing that as a pending chore would be wrong.
        verified = bool(me.get("emailVerified"))
        claimed = {i["code"] for i in items if i.get("completed")}

        def state_of(code_name):
            if code_name == "verify_email" and verified:
                return "verified"
            if code_name in claimed:
                return "done"
            return "pending"

        row["email_verified"] = verified
        row["email_reward_claimed"] = "verify_email" in claimed
        row["checklist"] = [{
            "code": i["code"],
            "pts": i.get("pointAmount"),
            "xp": i.get("xpAmount"),
            "done": bool(i.get("completed")),
            "daily": i.get("section") == "daily",
            "state": state_of(i["code"]),
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

def after_pass_checks(token, result):
    """Re-read the account right after a pass and decide the three ticks.

    Read fresh instead of trusting the action return values: a chore counts as
    done only when the server agrees (check-in recorded, no unread post left,
    email verified). `result` is still passed so a hard failure on an action
    can never show as a tick.
    """
    chk = {"checkin": False, "post": False, "email": False}

    code, att = api("/attendance/today", token=token)
    if code == 200:
        chk["checkin"] = bool(att.get("checkedIn"))
    if result and not (result.get("check_in") or (False,))[0]:
        chk["checkin"] = False

    code, posts = api("/community/posts", token=token)
    if code == 200:
        chk["post"] = not any(not p.get("read") for p in posts.get("items", []))
    if result and not (result.get("posts") or (False,))[0]:
        chk["post"] = False

    code, me = api("/auth/me", token=token)
    verified = code == 200 and bool(me.get("emailVerified"))
    code, earn = api("/rewards/earn-items", token=token)
    claimed = (isinstance(earn, list) and
               any(i.get("code") == "verify_email" and i.get("completed")
                   for i in earn))
    chk["email"] = bool(verified and claimed)
    return chk


def daily_pass(accounts, rows_before=None):
    """Do the actual daily actions. Returns (results, deltas).

    Accounts are NOT run back to back. Every account except the first is delayed
    by its own random `account_gap` (default 45-150s) before its first request,
    so N accounts never produce an identical burst of check-ins at 09:00:00.
    That burst - same minute, same endpoints, different tokens - is the cheapest
    multi-account signal there is.
    """
    results, deltas = {}, {}
    for i, acc in enumerate(accounts):
        label = acc["label"]
        st = load_state(label)
        st["label"] = label

        if i > 0:
            gap = random.uniform(*acc.get("pacing", {}).get(
                "account_gap", (45, 150)))
            log(f"jeda {gap:.0f}s sebelum akun {label}")
            time.sleep(gap)

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
            # points delta for the footer. Balance is saved first: save_state
            # does a full dict write, so a later call would drop task_checks.
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
            save_state(label, task_checks=after_pass_checks(token, results[label]))
        except Exception as ex:            # noqa: BLE001
            # An exception here means the account did NOT complete, so
            # last_run_at is deliberately left alone and it stays "due" for the
            # next cycle. Log it loudly: storing it only in the results dict is
            # what let the ANSWER_BANK NameError run for two days with a green
            # panel and zero activity.
            msg = f"ERROR {type(ex).__name__}: {ex}"
            results[label] = msg
            log(f"  [!] {label}: {msg}")
    return results, deltas


def due_for_daily(label, now_utc=None):
    """True when this account has not had its daily pass yet today (UTC day)."""
    ran = load_state(label).get("last_run_at")
    if not ran:
        return True
    try:
        dt = datetime.fromisoformat(ran)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now_utc = now_utc or datetime.now(timezone.utc)
        return dt.date() < now_utc.date()
    except Exception:
        return True


def daily_window_open(now_local, daily_at):
    """Is the daily pass allowed to run at this wall-clock time?

    The window is NOT "the hour of daily_at" any more. That made the daemon
    idle for the other ~23.5 hours: an account whose cooldown expired at 10:00
    would sit untouched until 09:00 the next day, which is exactly the
    "no activity at all" symptom. A day is now "done" once the pass has run,
    and it runs as soon as it is due - the anti-burst jitter inside
    daily_pass() is what keeps it from looking like a machine, not a clock.
    """
    return True


def minutes_until_next_local_hour(hour, now_local=None):
    """Minutes from now until the next occurrence of a local wall-clock hour."""
    now_local = now_local or local_now()
    target = now_local.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now_local:
        target += timedelta(days=1)
    return int((target - now_local).total_seconds() // 60)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="satu pass lalu keluar")
    ap.add_argument("--daily-at", type=int, default=9,
                    help="jam lokal untuk pass harian (default 9)")
    ap.add_argument("--refresh-hours", type=float, default=REFRESH_HOURS)
    ap.add_argument("--no-lock", action="store_true",
                    help="lewati lock proses (hanya untuk debug)")
    args = ap.parse_args()

    ui.C.reset()

    # Refuse to run twice. Two live processes race on the rotating refresh token
    # and the loser gets 401 AUTH_REFRESH_TOKEN_REUSED, which costs a full
    # re-login. A stale screen session plus a fresh start is exactly how that
    # happens, so the check is unconditional and the message says why.
    if not args.no_lock:
        try:
            acquire_lock()
        except AlreadyRunning as ex:
            print(f"[!] {ex}", flush=True)
            return 1

    accounts = load_accounts()
    if not accounts:
        print("accounts.json kosong — salin accounts.example.json")
        return 1

    refresh_hours = args.refresh_hours
    globals()["REFRESH_HOURS"] = refresh_hours

    # refresh the three task ticks at startup, so a restarted panel never shows
    # values left over from yesterday's state file
    for acc in accounts:
        token = ensure_token(acc)
        if token:
            try:
                save_state(acc["label"], task_checks=after_pass_checks(token, None))
            except Exception as ex:      # noqa: BLE001
                log(f"task_checks {acc['label']} gagal: {type(ex).__name__}: {ex}")

    last_action = ""
    while True:
        try:
            now_utc = datetime.now(timezone.utc)
            now_local = local_now()

            # ---- the daily pass: at the scheduled local hour, or immediately on a
            # ---- fresh start when today's work has not been done yet.
            # ---- With --once the pass always runs for whatever is due, so a
            # ---- one-shot invocation is not just a status render.
            due = [a for a in accounts if due_for_daily(a["label"], now_utc)]
            first_ever = not load_state(accounts[0]["label"]).get("last_run_at")
            st = {"last_pass": now_utc.isoformat(timespec="seconds"),
                  "last_result": "refresh"}
            if due and daily_window_open(now_local, args.daily_at):
                # Do not start on the hour boundary itself: a check-in timestamped
                # exactly 09:00:00 across several accounts is the loudest pattern
                # available. Shift the whole pass by a few minutes first.
                shift = random.uniform(0, 240) if not first_ever else 0
                if shift > 1:
                    log(f"menunggu {shift:.0f}s sebelum mulai pass harian")
                    time.sleep(shift)
                results, deltas = daily_pass(due)
                st["last_result"] = (", ".join(
                    f"{k}: {'ok' if v == 'ok' or isinstance(v, dict) else v}"
                    for k, v in results.items())) or "ok"
                if deltas:
                    last_action = "perubahan: " + "  ".join(
                        f"{k} {v}" for k, v in deltas.items())

            rows = [snapshot(a["label"], a, mask_email=MASK_EMAIL) for a in accounts]

            # next thing to wait for: the scheduled daily hour, or the refresh tick
            mins_to_daily = minutes_until_next_local_hour(args.daily_at, now_local)
            next_at = now_utc + timedelta(
                minutes=min(mins_to_daily, int(REFRESH_HOURS * 60)))
            print(render(rows, st, next_at, last_action), flush=True)

            if args.once:
                return 0
            # idle: keep the panel live, and fire the daily pass the moment the
            # scheduled hour arrives (checked every 30s, so no missed window)
            while True:
                try:
                    time.sleep(30)
                except KeyboardInterrupt:
                    print("\n[stopped]", flush=True)
                    return 0
                now_local = local_now()
                now_utc = datetime.now(timezone.utc)
                # A day is "done" when the pass has run, not when the clock
                # says 09:xx. Poll for due accounts so a cooldown that expires
                # at any hour gets picked up within 30s instead of waiting for
                # the next 09:00 window.
                if any(due_for_daily(a["label"], now_utc) for a in accounts):
                    due = [a for a in accounts
                           if due_for_daily(a["label"], now_utc)]
                    shift = random.uniform(0, 240)
                    log(f"menunggu {shift:.0f}s sebelum mulai pass harian")
                    time.sleep(shift)
                    due = [a for a in accounts
                           if due_for_daily(a["label"],
                                            datetime.now(timezone.utc))]
                    results, deltas = daily_pass(due)
                    if deltas:
                        last_action = "perubahan: " + "  ".join(
                            f"{k} {v}" for k, v in deltas.items())
                    break                  # redraw with fresh numbers
                if datetime.now(timezone.utc) >= next_at:
                    break
        except KeyboardInterrupt:
            print("\n[stopped]", flush=True)
            return 0
        except Exception as ex:            # noqa: BLE001
            # A standby daemon must not die on one bad cycle: log it, keep the
            # panel, and retry after the refresh interval.
            log(f"cycle error: {type(ex).__name__}: {ex}")
            time.sleep(60)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[stopped]", flush=True)

#!/usr/bin/env python3
"""Terminal UI for the Q Lounge bot.

ANSI only, no dependencies. Two things live here:

  * `C` / icons / `bar()` — the primitives every message uses.
  * `Dashboard` — a live panel that redraws in place (single screen, never
    scrolls) so a long multi-account run reads like one evolving card.

Every colour degrades gracefully: `C.enabled` is False when stdout is not a TTY
(pipes, cron, `> file`), when NO_COLOR/TERM=dumb is set, or on Windows without
ANSI support — in that case the same layout is printed with no escape codes, so
redirecting to a log still produces readable output.
"""
import os
import shutil
import sys
import time


# ------------------------------------------------------------------- colour --

class _Colors:
    R = "\033[91m"      # bright red
    G = "\033[92m"      # bright green
    Y = "\033[93m"      # bright yellow
    B = "\033[94m"      # bright blue
    M = "\033[95m"      # bright magenta
    C = "\033[96m"      # bright cyan
    W = "\033[97m"      # bright white
    DIM = "\033[2m"
    BOLD = "\033[1m"
    ITAL = "\033[3m"
    RST = "\033[0m"

    # background variants, used for the header band
    BG_BLUE = "\033[44m"
    BG_MAG = "\033[45m"

    def __init__(self):
        self.enabled = self._detect()

    @staticmethod
    def _detect():
        if os.environ.get("NO_COLOR"):
            return False
        if os.environ.get("TERM") == "dumb":
            return False
        if os.name == "nt" and not os.environ.get("ANSICON"):
            return False
        try:
            return sys.stdout.isatty()
        except Exception:
            return False

    def reset(self):
        self.enabled = self._detect()


C = _Colors()


def paint(text, *styles):
    """Wrap text in the given colour/style codes (no-ops when disabled)."""
    if not C.enabled:
        return text
    return "".join(styles) + text + C.RST


def supports_emoji():
    """Emoji misrender on some terminals/Windows code pages; fall back to ASCII."""
    if os.name == "nt":
        return False
    if os.environ.get("LANG", "").lower().startswith(("c", "posix")):
        return False
    return True


_EMOJI = supports_emoji()


def icon(name):
    """Pick an emoji or an ASCII twin for the same concept."""
    table = {
        "star":   ("✦", "*"),
        "coin":   ("◈", "$"),
        "fire":   ("▲", "^"),
        "book":   ("▤", "#"),
        "bell":   ("◔", "@"),
        "ok":     ("✔", "+"),
        "fail":   ("✖", "x"),
        "skip":   ("–", "-"),
        "clock":  ("◷", "~"),
        "user":   ("◉", "@"),
        "spark":  ("✧", "*"),
        "lock":   ("▮", "="),
        "wallet": ("▣", "W"),
    }
    a, b = table.get(name, ("•", "-"))
    return a if _EMOJI else b


# ------------------------------------------------------------------ layout --

def width(default=76):
    try:
        return max(52, min(shutil.get_terminal_size((default, 24)).columns, 96))
    except Exception:
        return default


def rule(ch="─", color=None):
    if _EMOJI:
        line = ch * width()
    else:                      # keep the ASCII fallback exactly aligned
        line = ch * width()
    return paint(line, color or C.DIM)


def header(title, subtitle=None, band=True):
    w = width()
    lines = []
    if band and C.enabled:
        lines.append(paint(" " * w, C.BG_MAG, C.W))
    t = f" {icon('spark')}  {title}"
    lines.append(paint(t, C.BOLD, C.M) if C.enabled else t)
    if subtitle:
        s = f"    {subtitle}"
        lines.append(paint(s, C.DIM) if C.enabled else s)
    lines.append(rule())
    return "\n".join(lines)


def section(title):
    if C.enabled:
        return paint(f" {title}", C.BOLD, C.C)
    return f" {title}"


def bar(fraction, w=24, color=None):
    """A filled progress bar. `fraction` may exceed 1 (it is clamped)."""
    try:
        f = max(0.0, min(float(fraction), 1.0))
    except Exception:
        f = 0.0
    filled = int(round(f * w))
    if filled == 0 and f > 0:
        filled = 1
    fill, empty = "█", "░"
    if not _EMOJI:
        fill, empty = "#", "."
    return paint(fill * filled, color or C.G) + paint(empty * (w - filled), C.DIM)


def fmt_pts(value):
    """100.00000 -> 100 ; keeps a couple of decimals only when needed."""
    try:
        v = float(value)
    except Exception:
        return str(value)
    if abs(v - round(v)) < 0.005:
        return f"{int(round(v)):,}"
    return f"{v:,.2f}"


def kv(label, value, lw=18, vstyle=None):
    pad = " " * max(1, lw - len(label))
    lab = paint(label + pad, C.DIM) if C.enabled else label + pad
    val = paint(str(value), *(vstyle or (C.W,))) if vstyle else str(value)
    return f"  {lab}{val}"


def mask_email(email):
    """a***@gmail.com — enough to tell accounts apart in a dashboard."""
    if "@" not in email:
        return email
    user, dom = email.split("@", 1)
    if len(user) <= 2:
        return user[0] + "***@" + dom
    return user[:2] + "***@" + dom


# ---------------------------------------------------------------- dashboard --

# icon reflects the outcome, not the state keyword's spelling
ICON_FOR = {"ok": "ok", "err": "fail", "fail": "fail", "skip": "skip",
            "run": "clock", "wait": "clock"}


class Dashboard:
    """A live, in-place redrawn panel for one multi-account run.

    Rewrites the same block of lines instead of appending, so the output stays
    a single card no matter how many accounts are processed. Falls back to
    plain appended lines when not on a TTY.
    """

    def __init__(self, title, accounts):
        self.title = title
        self.accounts = accounts
        self.rows = []
        self.done = 0
        self._last_len = 0
        self.started = time.time()
        self._tty = C.enabled and sys.stdout.isatty()

    def _render(self):
        w = width()
        out = [paint(f" {self.title}", C.BOLD, C.M), rule()]
        for r in self.rows:
            out.append(self._row(r))
        frac = self.done / max(1, len(self.accounts))
        out.append(paint(f"  progres  {bar(frac)}  {self.done}/{len(self.accounts)} akun",
                         C.DIM))
        return "\n".join(out)

    def _row(self, r):
        label = r.get("label", "?")[:16].ljust(16)
        state = r.get("state", "wait")
        pal = {"ok": C.G, "err": C.R, "fail": C.R, "skip": C.Y,
               "run": C.C, "wait": C.DIM}
        st = paint(f"{icon(ICON_FOR.get(state, 'clock'))} "
                   f"{state:<5}", pal.get(state, C.W))
        detail = r.get("detail", "")
        return f"  {paint(label, C.BOLD, C.W)}  {st}  {paint(detail, C.DIM)}"

    def start(self):
        if self._tty:
            sys.stdout.write("\033[?25l")          # hide cursor
            sys.stdout.flush()
        return self

    def set(self, label, state, detail=""):
        for r in self.rows:
            if r["label"] == label:
                r.update(state=state, detail=detail)
                break
        else:
            self.rows.append({"label": label, "state": state, "detail": detail})
        self.flush()

    def complete(self, label, state=None, detail=None):
        """Mark an account finished.

        `state`/`detail` default to keeping whatever `set()` already recorded, so
        calling complete(label) never wipes the detail that made the run worth
        reading.
        """
        for r in self.rows:
            if r["label"] == label:
                if state:
                    r["state"] = state
                if detail is not None:
                    r["detail"] = detail
                break
        else:
            self.rows.append({"label": label, "state": state or "ok",
                              "detail": detail or ""})
        self.done += 1
        self.flush()

    def annotate(self, label, suffix):
        """Append to a row's detail without touching its state."""
        for r in self.rows:
            if r["label"] == label:
                r["detail"] = (r.get("detail", "") or "") + suffix
                break
        self.flush()

    def flush(self):
        text = self._render()
        if not self._tty:
            # non-interactive: print the current row only, so logs stay clean
            return
        if self._last_len:
            sys.stdout.write(f"\033[{self._last_len}A")   # cursor to top
        sys.stdout.write("\033[J" + text + "\n")
        sys.stdout.flush()
        self._last_len = text.count("\n") + 1

    def close(self, extra=None):
        if self._tty:
            sys.stdout.write("\033[?25h")          # restore cursor
            sys.stdout.flush()
        elapsed = time.time() - self.started
        tail = extra or []
        print()
        print(section("Ringkasan"))
        for line in tail:
            print("  " + line)
        print(f"  {paint('selesai dalam', C.DIM)} {elapsed:.0f}s")


# ------------------------------------------------------------- account card --

def account_card(label, email, me=None, attendance=None, today=None,
                 invites=None, results=None):
    """The pretty per-account block shown after a run."""
    print()
    print(header(f"{label}", mask_email(email)))
    if not me:
        print("  " + paint("tidak bisa membaca profil", C.R))
        return

    mem = me.get("membership", {})
    pt = me.get("point", {})
    uid = mem.get("uid", "?")
    lvl = mem.get("level", "?")
    lname = mem.get("levelName", "?")

    # membership line with an XP bar toward the next level
    xp = mem.get("xp", 0) or 0
    nxt = mem.get("nextLevelXp")
    xpn = (f"XP {xp}/{nxt}" if nxt else f"XP {xp}")
    print(f"  {paint(uid, C.BOLD, C.Y)}  {paint(f'Lv.{lvl} {lname}', C.C)}"
          f"   {paint(xpn, C.DIM)}")
    print()

    # points block
    bal = fmt_pts(pt.get("balance", 0))
    avail = fmt_pts(pt.get("available", 0))
    locked = fmt_pts(pt.get("locked", 0))
    print(f"  {paint(icon('coin') + ' Poin', C.BOLD)}  "
          f"{paint(bal, C.BOLD, C.G)}   "
          f"{paint('tersedia', C.DIM)} {paint(avail, C.G)}   "
          f"{paint('terkunci', C.DIM)} {paint(locked, C.Y)}")
    print()

    # actions
    if results:
        print("  " + section("Aksi hari ini"))
        keys = [("check_in", "check-in", icon("fire")),
                ("posts", "post dibaca", icon("book")),
                ("notices", "notice", icon("bell"))]
        for k, name, ic in keys:
            r = results.get(k)
            if r is None:
                continue
            ok, msg = r
            mark = paint(f"{icon('ok') if ok else icon('fail')}",
                         C.G if ok else C.R)
            print(f"    {mark} {paint(name.ljust(14), C.W)} {paint(str(msg), C.DIM)}")
        print()

    # attendance / streak
    if attendance:
        streak = attendance.get("streakDays", 0)
        done = attendance.get("checkedIn")
        mark = paint(icon("ok"), C.G) if done else paint(icon("skip"), C.Y)
        print(f"  {mark} {paint('streak', C.W)} {paint(str(streak) + ' hari', C.C)}"
              f"    {paint('bulan ini', C.DIM)} "
              f"{paint(fmt_pts(attendance.get('monthPoints', 0)) + ' pts', C.W)}")
    if today:
        e = fmt_pts(today.get("earnedToday", 0))
        cap = fmt_pts(today.get("dailyPointCap", 0))
        frac = 0
        try:
            frac = float(today.get("earnedToday", 0)) / float(today.get("dailyPointCap", 1))
        except Exception:
            pass
        print(f"  {paint('hari ini', C.W)} {paint(e + ' pts', C.G)} "
              f"{bar(frac, 20, C.G)} {paint('/ ' + cap, C.DIM)}")
    if invites:
        j = invites.get("joinedCount", 0)
        pe = fmt_pts(invites.get("pointsEarned", 0))
        print(f"  {paint('undangan', C.W)} {paint(str(j) + ' orang', C.C)}"
              f"   {paint('+' + pe + ' pts', C.G)}")
    print(paint("  " + "─" * (width() - 2), C.DIM))


# ----------------------------------------------------------------- banners --

def banner_run(total):
    print(header(f"Q Lounge Daily · {total} akun", "menjalankan aksi harian"))
    print()


def banner_done(total_points_gained, accounts):
    print()
    print(header("Selesai"))
    gained = paint(f"+{fmt_pts(total_points_gained)} pts", C.BOLD, C.G)
    print(f"  {icon('coin')} total diperoleh  {gained}")
    if accounts:
        print(f"  {icon('user')} akun diproses   {paint(str(accounts), C.W)}")
    print()


def banner_skip(label, reason):
    print(f"  {paint(icon('skip'), C.Y)} {paint(label.ljust(18), C.W)} "
          f"{paint(reason, C.DIM)}")

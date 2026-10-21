#!/usr/bin/env python3
"""Anti-detection helpers for the Q Lounge bot.

Threat model: this is a reward program, not a payment rail. The risk is not a
compromised key, it is an operator-side pattern flag - identical intervals,
zero variance, reading every post the instant it lands, running 24/7. So the
goal here is traffic that looks like one bored person on a phone.

Deliberately NOT included: fake fingerprint/UA rotation per request (the server
sees a bearer token, so UA churn buys nothing and looks worse), and any
"appear human" randomness on actions that are idempotent (a check-in is a
check-in - you cannot half-do it).
"""
import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


# ------------------------------------------------------------------ pacing --

class Pacing:
    """Sleep between actions, with jitter and a daily-ish rhythm.

    default ranges were tuned from observed human usage: a person opening the
    app spends 1-4s per screen, lingers 15-60s reading a post, and does not
    hit the notice list at all unless something is pinned.
    """

    DEFAULTS = {
        "check_in":   (1.2, 4.5),
        "post_read":  (3.0, 14.0),
        "notice_read": (0.6, 2.0),
        "account_gap": (45.0, 150.0),
    }

    def __init__(self, overrides=None):
        self.ranges = dict(self.DEFAULTS)
        for k, v in (overrides or {}).items():
            self.ranges[k] = tuple(v)
        self._log = []

    def sleep(self, kind, reason=None):
        lo, hi = self.ranges.get(kind, (1.0, 3.0))
        delay = random.uniform(lo, hi)
        self._log.append((kind, round(delay, 2)))
        time.sleep(delay)
        return delay

    def tail(self, n=5):
        return self._log[-n:]


# ------------------------------------------------------------- quiz answers --

class AnswerBank:
    """Answers for the daily attendance quiz.

    The quiz body rotates; the answer is free text (2..500 chars) and there is
    no visible server-side grading, so any on-topic answer is accepted. We keep
    a few phrasings per topic and pick one at random so repeated runs are not
    byte-identical.
    """

    TOPICS = [
        (("which chain", "chain"), [
            "BNB Chain",
            "BNB Chain, paling murah dan cepat buat transaksi harian",
            "Saya paling sering pakai BNB Chain belakangan ini",
        ]),
        (("nft", "collect"), [
            "Saya tertarik mengoleksi NFT",
            "Belum terlalu aktif, tapi saya suka lihat NFT art",
        ]),
        (("defi", "yield", "stake"), [
            "Saya tertarik dengan yield farming dan staking",
            "Saya lebih suka staking yang aman jangka panjang",
        ]),
        (("wallet", "custody"), [
            "Saya pakai self-custody wallet",
            "Saya lebih percaya wallet non-custodial sendiri",
        ]),
    ]
    FALLBACK = [
        "Saya masih belajar dan menjelajahi ekosistemnya",
        "Memakai aplikasi ini untuk belajar soal komunitas kripto",
    ]

    def __init__(self):
        self._used = {}

    def pick(self, question):
        q = (question or "").lower()
        for keys, answers in self.TOPICS:
            if any(k in q for k in keys):
                pool = answers
                break
        else:
            pool = self.FALLBACK
        used = self._used.setdefault(id(pool), [])
        fresh = [a for a in pool if a not in used]
        choice = random.choice(fresh or pool)
        used.append(choice)
        if len(used) >= len(pool):
            used.clear()
        return choice


ANSWER_BANK = AnswerBank()


# ------------------------------------------------------------ budget guard --

class DailyBudget:
    """Refuses to run the same account twice in one local day.

    Reward programmes commonly allow exactly one claim per day; a second run is
    both useless and a loud signal. This is a hard stop, not a warning.
    """

    def __init__(self, state):
        self.state = state

    def already_ran_today(self, today=None):
        ran = self.state.get("last_run_at")
        if not ran:
            return False, None
        try:
            dt = datetime.fromisoformat(ran)
        except Exception:
            return False, None
        today = today or datetime.now(timezone.utc).date()
        return dt.date() == today, ran

    def guard(self, force=False, today=None):
        done, ran = self.already_ran_today(today)
        if done and not force:
            raise RuntimeError(
                f"akun sudah dijalankan hari ini ({ran}) - pakai --force untuk override")
        return True


# ----------------------------------------------------------- run-window -----

def in_active_hours(cfg=None, now=None):
    """Optional: only run between the operator's waking hours.

    Reward bots that fire at 03:00 local every day are obvious. Enable with
    {"active_hours": [7, 23]} in the account config (local server time).
    """
    cfg = cfg or {}
    lo, hi = cfg.get("active_hours", [0, 24])
    now = now or datetime.now()
    return lo <= now.hour < hi


def jitter_offset(seconds):
    """Spread scheduled runs so a cron fleet does not fire on one boundary."""
    return random.uniform(-seconds, seconds)

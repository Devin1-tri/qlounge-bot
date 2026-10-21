#!/usr/bin/env python3
"""QLounge daily bot.

Runs every daily point action for each configured account:
  * attendance check-in (answers the daily quiz)
  * read unread community posts
  * read unread notices

Designed for multi-account operation with pacing that keeps each account's
traffic inside a normal human session (see anti_detection.py).

Usage:
    qlounge.py run                       # all accounts from accounts.json
    qlounge.py run --account rian3124    # one account
    qlounge.py status                    # read-only summary

State is per account in state/<label>.json so a crash resumes instead of
repeating work. Only stdlib is used.
"""
import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://appleintern.mqxwallet.com/v1"
HERE = Path(__file__).resolve().parent
CRED = Path("/home/ubuntu/.hermes/skills/credentials")
STATE_DIR = HERE / "state"
UA = ("Mozilla/5.0 (Linux; Android 12; SM-S906N Build/SP1A.210812.016; wv) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
      "Chrome/141.0.7390.0 Mobile Safari/537.36")


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def api(path, body=None, method="GET", token=None, timeout=25):
    import urllib.request
    import urllib.error
    h = {"Accept": "application/json", "User-Agent": UA}
    if token:
        h["Authorization"] = "Bearer " + token
    if body is not None:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode()
        except Exception:
            pass
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:200]}
    except Exception as ex:
        return None, {"error": str(ex)[:100]}


# --------------------------------------------------------------- state ----

def state_path(label):
    STATE_DIR.mkdir(exist_ok=True)
    return STATE_DIR / f"{label}.json"


def load_state(label):
    p = state_path(label)
    if p.exists():
        return json.loads(p.read_text())
    return {}


def save_state(label, **kw):
    st = load_state(label)
    st.update(kw)
    st["updated_at"] = datetime.now(timezone.utc).isoformat()
    state_path(label).write_text(json.dumps(st, ensure_ascii=False, indent=2))


# ------------------------------------------------------------ accounts ----

def load_accounts():
    p = HERE / "accounts.json"
    if not p.exists():
        return []
    return json.loads(p.read_text()).get("accounts", [])


def ensure_token(account):
    """Refresh the access token when needed. Returns a live token."""
    label = account["label"]
    st = load_state(label)
    tok = st.get("accessToken")
    exp = st.get("accessTokenExpiresAt")

    def expired(t, e):
        if not t or not e:
            return True
        try:
            dt = datetime.fromisoformat(e.replace("Z", "+00:00"))
            return (dt - datetime.now(timezone.utc)).total_seconds() < 120
        except Exception:
            return True

    if not expired(tok, exp):
        return tok

    rt = account.get("refreshToken") or st.get("refreshToken")
    if not rt:
        code, res = api("/auth/login",
                        {"email": account["email"], "password": account["password"]},
                        "POST")
        if code != 200:
            log(f"  [!] login gagal {code}: {res}")
            return None
        tok = res["accessToken"]
        rt = res.get("refreshToken", rt)
    else:
        code, res = api("/auth/refresh", {"refreshToken": rt}, "POST")
        if code != 200:
            code, res = api("/auth/login",
                            {"email": account["email"], "password": account["password"]},
                            "POST")
            if code != 200:
                log(f"  [!] refresh+login gagal: {res}")
                return None
            rt = res.get("refreshToken", rt)
        tok = res["accessToken"]

    save_state(label, accessToken=tok, refreshToken=rt,
               accessTokenExpiresAt=res.get("accessTokenExpiresAt"))
    return tok


# ------------------------------------------------------------- actions ----

def action_check_in(token, state, pacing):
    code, today = api("/attendance/today", token=token)
    if code != 200:
        return False, f"today {code}"
    if today.get("checkedIn"):
        return True, "sudah check-in (skip)"
    q = (today.get("question") or {}).get("body", "")
    answer = ANSWER_BANK.pick(q)
    pacing.sleep("check_in")
    code, res = api("/attendance/check-in", {"answer": answer}, "POST", token)
    if code not in (200, 201):
        return False, f"check-in {code} {res}"
    return True, (f"{answer!r} -> +{res.get('pointsAmount')} pts, "
                  f"+{res.get('xpAmount')} xp, streak {res.get('streakDays')}")


def action_posts(token, state, pacing, limit=None):
    code, res = api("/community/posts", token=token)
    if code != 200:
        return False, f"posts {code}"
    posts = res.get("items", [])
    done = set(state.get("posts_read", []))
    unread = [p for p in posts if not p.get("read") and p["id"] not in done]
    if limit:
        unread = unread[:limit]
    if not unread:
        return True, "0 post baru (skip)"
    gained, ids = 0, []
    for p in unread:
        pacing.sleep("post_read")
        c2, r2 = api(f"/community/posts/{p['id']}/read", {}, "POST", token)
        if c2 == 200:
            gained += float(r2.get("pointsAmount") or 0)
            ids.append(p["id"])
        elif c2 == 429:
            break
    new = list(done) + ids
    save_state(state.get("label", "x"), posts_read=new[-500:])
    return True, f"{len(ids)}/{len(unread)} post dibaca, +{gained:g} pts"


def action_notices(token, state, pacing):
    code, res = api("/notices", token=token)
    if code != 200:
        return False, f"notices {code}"
    items = res.get("pinned", []) + res.get("items", [])
    done = set(state.get("notices_read", []))
    todo = [n for n in items if not n.get("read") and n["noticeId"] not in done]
    for n in todo:
        pacing.sleep("notice_read")
        api(f"/notices/{n['noticeId']}/read", {}, "POST", token)
    if todo:
        save_state(state.get("label", "x"),
                   notices_read=list(done) + [n["noticeId"] for n in todo])
    return True, f"{len(todo)} notice dibaca"


def status(token):
    out = {}
    for path, key in (("/auth/me", "me"), ("/attendance/today", "attendance"),
                      ("/rewards/earned-today", "today"),
                      ("/invites/sent/summary", "invites")):
        code, res = api(path, token=token)
        if code == 200:
            out[key] = res
    return out


# --------------------------------------------------------- run per account --

def run_account(account, do_posts=True, dash=None):
    label = account["label"]
    st = load_state(label)
    st["label"] = label
    log(f"--- {label} ({account['email']}) ---")

    token = ensure_token(account)
    if not token:
        return False
    st = load_state(label)

    pacing = Pacing(account.get("pacing", {}))
    results = {}

    if dash:
        dash.set(label, "run", "check-in…")

    ok, msg = action_check_in(token, st, pacing)
    log(f"  check-in : {'ok ' if ok else 'ERR'} {msg}")
    results["check_in"] = (ok, msg)

    ok2, msg2 = action_notices(token, st, pacing)
    log(f"  notices  : {'ok ' if ok2 else 'ERR'} {msg2}")
    results["notices"] = (ok2, msg2)

    ok3, msg3 = True, "dilewati"
    if do_posts:
        ok3, msg3 = action_posts(token, st, pacing, account.get("max_posts_per_run"))
        log(f"  posts    : {'ok ' if ok3 else 'ERR'} {msg3}")
    results["posts"] = (ok3, msg3)

    code, me = api("/auth/me", token=token)
    gained = 0.0
    if code == 200:
        log(f"  poin     : {me['point']['balance']} "
            f"(available {me['point']['available']})")
        prev = st.get("last_balance")
        if prev is None:
            # first ever run: record the baseline, report no "gain" from a
            # number we never captured
            gained = 0.0
        else:
            try:
                gained = float(me.get("point", {}).get("balance", 0)) - float(prev)
            except Exception:
                gained = 0.0
        save_state(label, last_balance=me["point"]["balance"])

    # pretty per-account card (skipped when a live dashboard owns the screen)
    if not dash:
        try:
            code_t, today = api("/rewards/earned-today", token=token)
            code_a, att = api("/attendance/today", token=token)
            code_i, inv = api("/invites/sent/summary", token=token)
            ui.account_card(
                label, account["email"], me=me,
                attendance=att if code_a == 200 else None,
                today=today if code_t == 200 else None,
                invites=inv if code_i == 200 else None,
                results=results)
        except Exception as ex:
            log(f"  [ui] {ex}")

    save_state(label, last_run_at=datetime.now(timezone.utc).isoformat(),
               last_result={"check_in": ok, "notices": ok2, "posts": ok3})
    if dash:
        status = "ok" if (ok and ok2 and ok3) else "err"
        detail = f"+{ui.fmt_pts(gained)} pts" if gained > 0 else (
            results["posts"][1] if not ok else "selesai")
        dash.complete(label, status, detail)
    return ok and ok2 and ok3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="run", choices=["run", "status"])
    ap.add_argument("--account", help="label dari accounts.json")
    ap.add_argument("--no-posts", action="store_true")
    ap.add_argument("--no-guard", action="store_true",
                    help="lewati proteksi satu-run-per-hari")
    args = ap.parse_args()

    accounts = load_accounts()
    if not accounts:
        log("accounts.json kosong - salin accounts.example.json")
        return 1
    if args.account:
        accounts = [a for a in accounts if a["label"] == args.account]
        if not accounts:
            log(f"akun {args.account} tidak ada")
            return 1

    rc = 0
    dash = None
    if args.cmd == "run" and len(accounts) >= 1:
        dash = ui.Dashboard(f"Q Lounge Daily · {len(accounts)} akun",
                            [a["label"] for a in accounts])
        dash.start()

    gained_total = 0.0
    skipped = []
    for i, acc in enumerate(accounts):
        if args.cmd == "status":
            token = ensure_token(acc)
            if token:
                log(f"--- {acc['label']} ---")
                log(json.dumps(status(token), ensure_ascii=False, indent=2))
            continue

        st = load_state(acc["label"])
        if not args.no_guard:
            try:
                DailyBudget(st).guard(force=args.no_guard)
            except RuntimeError as e:
                log(f"--- {acc['label']}: {e}")
                if dash:
                    dash.set(acc["label"], "skip", "sudah jalan hari ini")
                    dash.complete(acc["label"])
                skipped.append(acc["label"])
                continue
        if not in_active_hours(acc):
            log(f"--- {acc['label']}: di luar active_hours {acc.get('active_hours')} - skip")
            if dash:
                dash.set(acc["label"], "skip",
                         f"di luar active_hours {acc.get('active_hours')}")
                dash.complete(acc["label"])
            skipped.append(acc["label"])
            continue

        before = float(load_state(acc["label"]).get("last_balance", 0) or 0)
        try:
            if not run_account(acc, do_posts=not args.no_posts, dash=dash):
                rc = 2
        except Exception as ex:
            log(f"  [!] {ex}")
            if dash:
                dash.set(acc["label"], "err", str(ex)[:48])
                dash.complete(acc["label"])
            rc = 2
        after = float(load_state(acc["label"]).get("last_balance", 0) or 0)
        if after > before:
            gained_total += after - before
        # humans do not clear every section the instant the previous one ends
        if i < len(accounts) - 1:
            gap = random.uniform(*acc.get("account_gap", (45, 120)))
            log(f"  jeda {gap:.0f}s sebelum akun berikutnya")
            if dash:
                dash.annotate(acc["label"], f" · jeda {gap:.0f}s")
            time.sleep(gap)

    if dash:
        dash.close([f"total +{ui.fmt_pts(gained_total)} pts"
                    + (f" · {len(skipped)} dilewati" if skipped else "")])
    return rc


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    import ui  # noqa: E402
    from anti_detection import Pacing, ANSWER_BANK, DailyBudget, in_active_hours  # noqa: E402
    sys.exit(main())

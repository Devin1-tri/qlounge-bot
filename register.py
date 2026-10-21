#!/usr/bin/env python3
"""Auto-register a Q Lounge account using an email inbox we control.

Flow: start -> read OTP from IMAP -> verify -> complete.

This handles the *API* half of registration. It does NOT apply an invite code:
invites bind through the Play Install Referrer (the app must be installed from
the share link), so an account created here has no inviter and no app wallet.
See README.

Usage:
    python3 register.py --email a@b.com --password 'Passw0rd!x' [--invite CODE]
"""
import argparse
import email
import imaplib
import json
import re
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from qlounge import api  # noqa: E402

CRED_DIR = Path("/home/ubuntu/.hermes/skills/credentials")


def wait_otp(imap_host, user, app_pw, subject_hint="Q Lounge", timeout=180):
    """Poll the inbox for a 6-digit code, newest first.

    Returns the code, or None on timeout. Deletes nothing.
    """
    deadline = time.time() + timeout
    seen_uids = set()
    while time.time() < deadline:
        try:
            m = imaplib.IMAP4_SSL(imap_host, 993)
            m.login(user, app_pw)
            m.select("INBOX")
            typ, data = m.search(None, "UNSEEN")
            for uid in data[0].split()[::-1]:
                if uid in seen_uids:
                    continue
                seen_uids.add(uid)
                typ, msg_data = m.fetch(uid, "(RFC822)")
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                subj = str(msg.get("Subject", ""))
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body += part.get_payload(decode=True).decode(
                                "utf-8", "replace")
                else:
                    body = msg.get_payload(decode=True).decode("utf-8", "replace")
                if subject_hint.lower() in (subj + body).lower():
                    m2 = re.search(r"\b(\d{6})\b", body)
                    if m2:
                        m.logout()
                        return m2.group(1)
            m.logout()
        except Exception as ex:
            print(f"  [imap] {ex}")
        time.sleep(6)
    return None


def register(email_addr, password, inbox=None, invite=None, timeout=180):
    code, res = api("/auth/sign-up/start",
                    {"email": email_addr, "agreedToTerms": True}, "POST")
    if code == 409:
        return False, "email sudah terdaftar — hapus akun dulu (DELETE /auth/me)"
    if code != 202:
        return False, f"start gagal {code} {res}"

    otp = None
    if inbox:
        imap_host, user, app_pw = inbox
        print(f"  menunggu OTP di {user} ...")
        otp = wait_otp(imap_host, user, app_pw, timeout=timeout)
        if not otp:
            return False, "OTP tidak datang dalam batas waktu"
    else:
        otp = input("  OTP dari email: ").strip()
    print(f"  OTP: {otp}")

    code, res = api("/auth/sign-up/verify",
                    {"email": email_addr, "code": otp}, "POST")
    if code != 200:
        return False, f"verify gagal {code} {res}"
    ticket = res["ticket"]

    body = {"signupTicket": ticket, "password": password}
    if invite:
        body["inviteCode"] = invite
    code, res = api("/auth/sign-up/complete", body, "POST")
    if code not in (200, 201):
        return False, f"complete gagal {code} {res}"
    return True, res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--invite", help="kode invite (tidak ter-apply lewat API)")
    ap.add_argument("--label", help="label akun untuk accounts.json")
    ap.add_argument("--inbox", action="store_true",
                    help="baca OTP otomatis dari kredensial gmail-<email>.json")
    args = ap.parse_args()

    inbox = None
    if args.inbox:
        slug = args.email.split("@")[0]
        cand = list(CRED_DIR.glob(f"gmail-{slug}*.json"))
        if not cand:
            print(f"  [!] kredensial inbox tidak ada untuk {args.email}")
            return 1
        c = json.loads(cand[0].read_text())
        inbox = (c.get("imap_host", "imap.gmail.com"), c.get("email"), c.get("app_password"))

    ok, res = register(args.email, args.password, inbox, args.invite)
    print(("\n[+] DAFTAR OK\n" if ok else "\n[!] GAGAL: ") + json.dumps(res, ensure_ascii=False)[:400])
    if not ok:
        return 1

    # append to accounts.json so the daily bot picks it up
    acc_file = Path(__file__).resolve().parent / "accounts.json"
    cfg = json.loads(acc_file.read_text()) if acc_file.exists() else {"accounts": []}
    label = args.label or args.email.split("@")[0]
    if not any(a["label"] == label for a in cfg["accounts"]):
        cfg["accounts"].append({
            "label": label, "email": args.email, "password": args.password,
            "max_posts_per_run": 4,
            "pacing": {"check_in": [1.2, 4.5], "post_read": [3.0, 14.0],
                       "notice_read": [0.6, 2.0], "account_gap": [45.0, 150.0]},
            "active_hours": [7, 23],
        })
        acc_file.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
        print(f"[+] akun '{label}' ditambahkan ke accounts.json")
    user = res.get("user", {})
    print(f"    uid={user.get('membership', {}).get('uid')} "
          f"wallet={user.get('walletAddress')} "
          f"invite={'YA' if user.get('inviter') else 'TIDAK (normal untuk register API)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Render every UI element so the layout can be eyeballed in isolation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ui  # noqa: E402


def main():
    print(f"colour enabled: {ui.C.enabled} | emoji: {ui._EMOJI} | width: {ui.width()}")
    print()
    ui.banner_run(3)

    d = ui.Dashboard("Menjalankan akun", ["akun1", "akun2", "akun3"])
    d.start()
    d.set("akun1", "run", "check-in…")
    import time
    time.sleep(0.4)
    d.set("akun1", "ok", "+25 pts · 4 post")
    d.complete("akun1")
    time.sleep(0.3)
    d.set("akun2", "err", "login gagal 401")
    d.complete("akun2")
    time.sleep(0.3)
    d.set("akun3", "skip", "sudah jalan hari ini")
    d.complete("akun3")
    d.close(["selesai 1 akun, 1 gagal, 1 dilewati"])
    ui.account_card(
        "akun1", "akun1@gmail.com",
        me={"membership": {"uid": "MQX000000000001", "level": 1,
                           "levelName": "STARTER", "xp": 12, "nextLevelXp": 99,
                           "pointMultiplier": "1.0000"},
            "point": {"balance": "260.00000", "available": "60.00000",
                      "locked": "200.00000"}},
        attendance={"streakDays": 3, "checkedIn": True, "monthPoints": "80.00000"},
        today={"earnedToday": "45.00000", "dailyPointCap": "500.00000"},
        invites={"joinedCount": 2, "pointsEarned": "200.00000"},
        results={"check_in": (True, "+20 pts, streak 3"),
                 "posts": (True, "4 post · +20 pts"),
                 "notices": (True, "1 dibaca")},
    )

    # a card with a failed action and a missing attendance payload
    ui.account_card(
        "akun2", "second@gmail.com",
        me={"membership": {"uid": "MQX000000000000", "level": 1,
                           "levelName": "STARTER", "xp": 0, "nextLevelXp": 99},
            "point": {"balance": "100.00000", "available": "0.00000",
                      "locked": "100.00000"}},
        results={"check_in": (False, "429 rate limited"),
                 "posts": (True, "0 post baru"),
                 "notices": (True, "0 notice")},
    )

    ui.banner_skip("akun3", "di luar active_hours [7, 23]")
    ui.banner_done(65, 2)

    print(ui.header("Tabel warna"))
    print("  " + " ".join(ui.paint("██", getattr(ui.C, n))
                          for n in ("R", "G", "Y", "B", "M", "C", "W")))
    print("  " + " ".join(ui.paint("██", ui.C.DIM), ui.paint("bold", ui.C.BOLD),
                          ui.paint("italic", ui.C.ITAL)))
    print("  " + ui.rule("═", ui.C.M))
    print("  " + ui.kv("contoh label", "nilainya", vstyle=(ui.C.G,)))
    print("  " + ui.kv("poin", ui.fmt_pts("100.00000")))
    print("  " + ui.kv("desimal", ui.fmt_pts("33.50000")))


if __name__ == "__main__":
    main()

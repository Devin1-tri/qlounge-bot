# Q Lounge Daily Bot

Automasi aktivitas harian **Q Lounge** (`com.djmaxrex.qlounge`) — aplikasi
komunitas berbasis Expo/React Native dengan backend di
`https://appleintern.mqxwallet.com/v1`.

Bot ini menjalankan semua aksi yang memberi poin, mendukung **multi akun**, dan
dirancang supaya pola trafiknya tetap mirip pemakaian manusia normal.

> ⚠️ **Pendaftaran akun dilakukan manual, bukan oleh bot ini.** Lihat
> [Cara kerja](#cara-kerja) — alasannya teknis, bukan pilihan gaya.
> Repo ini juga tidak menyertakan kredensial. Semua endpoint dibalik dari APK
> publik; tidak ada exploit, tidak ada bypass server-side — hanya otomasi hal
> yang memang bisa dilakukan user di aplikasi.

## Yang dikerjakan

| Aksi | Endpoint | Hadiah |
|---|---|---|
| Check-in harian (ikut kuis) | `POST /attendance/check-in` | 20 pts + 2 XP |
| Baca post komunitas | `POST /community/posts/<id>/read` | 5 pts + 10 XP per post |
| Baca pengumuman | `POST /notices/<id>/read` | — |
| Streak 15 hari | otomatis dari check-in | 150 pts |

Verifikasi nyata (2026-10-21): check-in `201` +20 pts, 8 post terbaca +40 pts,
saldo 200 → 260.

## Cara kerja

```
Akun dibuat manual di HP  →  invite ter-apply + wallet terbentuk
        ↓
   isi accounts.json      →  email + password + label
        ↓
  python3 qlounge.py run  →  check-in, baca post, baca notice
```

**Kenapa pendaftaran tidak diautomasi?** Q Lounge mengikat invite lewat **Play
Install Referrer**: link share `https://affiliate.dj-maxrex.com/i/<code>`
mengarah ke Play Store dengan `?referrer=invite%3D<code>`, dan aplikasi
membacanya lewat `getInstallReferrerAsync()`. Sign-up lewat API
(`/auth/sign-up/*`) tidak pernah melihat referrer itu, jadi akun hasil API:

- tidak punya `inviter` di `/auth/me`
- tidak dapat bonus `invite_accepted`
- `hasWallet: false` — aplikasinya yang membuat wallet saat install

Dibuktikan langsung: akun yang sama, dua cara daftar. Via HP → `hasWallet:true`
dan `invite_accepted` +100 di `/points/transactions`. Via API → tidak ada
keduanya. Kalau mau bonus invite, **install dari link share**; kalau mau bot
yang jalan, akunnya harus didaftarkan manual dulu.

`register.py` di repo ini adalah eksperimen yang mendokumentasikan temuan itu;
bot utamanya `qlounge.py`.

## Pasang

```bash
git clone https://github.com/Devin1-tri/qlounge-bot.git
cd qlounge-bot
cp accounts.example.json accounts.json
# edit accounts.json: email, password, label
```

Tidak perlu dependency eksternal — Python 3 standar saja.

## Pakai

```bash
python3 qlounge.py run                       # semua akun
python3 qlounge.py run --account akun1    # satu akun
python3 qlounge.py status                    # lihat saldo & status
python3 qlounge.py run --no-posts            # cek-in saja, jangan baca post
python3 qlounge.py run --no-guard            # paksa jalan walau sudah jalan hari ini
```

## Multi akun

Tiap akun cuma butuh **3 baris**. Setelan yang sama untuk semua akun ditaruh
sekali di `defaults`:

```json
{
  "accounts": [
    { "label": "akun1", "email": "a1@gmail.com", "password": "..." },
    { "label": "akun2", "email": "a2@gmail.com", "password": "..." }
  ],
  "defaults": {
    "max_posts_per_run": 4,
    "account_gap": [45, 150],
    "check_in": [1.2, 4.5],
    "post_read": [3, 14],
    "notice_read": [0.6, 2]
  }
}
```

`load_accounts()` menggabungkan `defaults` ke setiap akun, jadi nambah akun =
tambah 3 baris. Kalau satu akun butuh setelan beda, taruh field itu di dalam
objek akunnya — nilainya menimpa `defaults`:

```json
{ "label": "akun2", "email": "a2@gmail.com", "password": "...",
  "account_gap": [300, 600], "max_posts_per_run": 1 }
```

Bot menyusul berurutan, dengan jeda acak antarakun (`account_gap`) sebelum
pindah ke akun berikutnya. Progres tiap akun disimpan di `state/<label>.json`
supaya run yang terputus bisa lanjut, bukan mengulang dari nol.

## Anti-deteksi

Bot perilakunya dikunci ke pola pemakaian manusia. Detailnya ada di
`anti_detection.py`; ringkasnya:

- **Jeda acak antar aksi** (`pacing`) — check-in 1.2–4.5 s, baca post 3–14 s,
  notice 0.6–2 s. Tidak ada dua aksi yang berjarak identik.
- **Pemisah antarakun** 45–150 s, jadi 5 akun tidak selesai dalam 2 menit.
- **Jendela waktu aktif** (`active_hours`, default 07–23) — program reward tidak
  jalan tengah malam.
- **Proteksi satu run per hari** (`DailyBudget`) — klaim kedua di hari yang sama
  tidak berguna dan justru mencolok. Di-hard-stop, bukan warning.
- **Jawaban kuis bervariasi** (`AnswerBank`) — pertanyaan diacak, jawaban
  dipilih dari beberapa variasi wajar, jadi tidak pernah byte-identik.
- **UA Android asli**, tidak dirotasi per request — server hanya melihat bearer
  token, jadi UA churn tidak menambah rasa aman dan justru terlihat aneh.

Yang sengaja **tidak** dilakukan: rotasi fingerprint palsu, header palsu, atau
usaha menipu limit yang dipaksakan server. Semua aksi adalah hal yang bisa
dilakukan user biasa.

## Struktur

```
qlounge.py            bot utama (run / status)
dashboard.py          dashboard standby (kaya sirius/uorm)
qlounge.sh            launcher screen: start/stop/status/once
anti_detection.py     pacing, jawaban kuis, budget guard, jam aktif
register.py           eksperimen pendaftaran otomatis + temuan kenapa gagal
accounts.json         kredensial (gitignored)
accounts.example.json template
state/<label>.json    progres per akun
```

## Menjalankan manual / di screen

```bash
# sekali jalan
python3 qlounge.py run

# or put it in a screen so it stays alive
screen -dmS qlounge bash -c 'cd ~/bot/qlounge && python3 qlounge.py run >> bot.log 2>&1'
screen -r qlounge
```

### Dashboard standby (recommended)

`dashboard.py` is a standby daemon in the shape of the sirius/uorm bots: it draws a
boxed panel, runs the daily pass for any account that has not run today, then sits
idle showing the countdown to the next pass. It does **not** exit when the work is
done — Ctrl+C stops it, `screen` keeps it alive.

```bash
./qlounge.sh start          # launch inside a screen session
./qlounge.sh status
./qlounge.sh once           # one pass then exit (for cron)
./qlounge.sh stop
screen -r qlounge           # attach and watch

python3 dashboard.py --once                # one pass, no standby
python3 dashboard.py --refresh-hours 2     # more frequent refresh pass
```

The panel shows, per account: email, membership UID, level, streak, points
(balance / available / locked), a **daily checklist** of every earnable item with
its state (`✔` done, `!` daily pending, `-` one-time pending), today's earnings
against the daily cap as a bar, unread post count, and the **cooldown** to the
next daily pass. The footer carries the last pass time, points changed, and the
next pass countdown.

Two passes matter: a **daily** pass (check-in + posts, once per day per account,
enforced) and a light **refresh** pass every 4 h that only re-reads state so a
newly published post is picked up without waiting a full day.

## Catatan teknis

- Access token hidupnya ~15 menit; bot refresh otomatis pakai `refreshToken`
  (atau login ulang kalau tidak ada).
- Poin baru biasanya masuk dalam status `locked` dan terbuka bertahap setelah
  check-in — itu perilaku server, bukan bug.
- Endpoint penghapusan akun: `POST /auth/me/deletion/email/start` →
  `/verify` → `DELETE /auth/me {ticket}`.

## Legal

Otomasi akun sendiri melanggar atau tidaknya ToS adalah tanggung jawab
pemakainya. Repo ini disediakan sebagai apa adanya, tanpa jaminan.

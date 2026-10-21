# Q Lounge Daily Bot

Automasi aktivitas harian **Q Lounge** (`com.djmaxrex.qlounge`) — aplikasi
komunitas berbasis Expo/React Native dengan backend di
`https://appleintern.mqxwallet.com/v1`.

Bot ini menjalankan semua aksi yang memberi poin, mendukung **multi akun**, dan
dirancang supaya pola trafiknya tetap mirip pemakaian manusia normal.

> ⚠️ **Kamu perlu akun sendiri.** Repo ini tidak menyertakan kredensial.
> Semua endpoint dibalik dari APK publik; tidak ada exploit, tidak ada bypass
> server-side — hanya otomasi hal yang memang bisa dilakukan user di aplikasi.

## Yang dikerjakan

| Aksi | Endpoint | Hadiah |
|---|---|---|
| Check-in harian (ikut kuis) | `POST /attendance/check-in` | 20 pts + 2 XP |
| Baca post komunitas | `POST /community/posts/<id>/read` | 5 pts + 10 XP per post |
| Baca pengumuman | `POST /notices/<id>/read` | — |
| Streak 15 hari | otomatis dari check-in | 150 pts |

Verifikasi nyata (2026-10-21): check-in `201` +20 pts, 8 post terbaca +40 pts,
saldo 200 → 260.

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
python3 qlounge.py run --account rian3124    # satu akun
python3 qlounge.py status                    # lihat saldo & status
python3 qlounge.py run --no-posts            # cek-in saja, jangan baca post
python3 qlounge.py run --no-guard            # paksa jalan walau sudah jalan hari ini
```

## Multi akun

Tambah entri di `accounts.json`:

```json
{
  "accounts": [
    { "label": "akun1", "email": "a1@gmail.com", "password": "...", "max_posts_per_run": 4 },
    { "label": "akun2", "email": "a2@gmail.com", "password": "...", "max_posts_per_run": 3 }
  ]
}
```

Bot menyusul berurutan, dengan jeda acak antarakun (`account_gap`) sebelum
pindah ke akun berikutnya.

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
qlounge.py           bot utama (run / status)
anti_detection.py    pacing, jawaban kuis, budget guard, jam aktif
accounts.json        kredensial (gitignored)
accounts.example.json  template
state/<label>.json   progres per akun supaya aman kalau terputus
```

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

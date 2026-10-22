# Q Lounge Daily Bot

Otomasi aktivitas harian **Q Lounge** (`com.djmaxrex.qlounge`) — aplikasi
komunitas berbasis Expo/React Native dengan backend di
`https://appleintern.mqxwallet.com/v1`.

Bot ini mengerjakan check-in harian, membaca post dan pengumuman, mendukung
**multi akun**, dan mengatur polanya supaya mirip pemakaian manusia normal.

> ## ⚠️ BACA DULU: PENDAFTARAN AKUN HARUS MANUAL
>
> **Bot ini tidak bisa mendaftarkan akun baru.** Lo harus daftar sendiri di
> aplikasi (HP atau emulator) pakai email + password, **lalu** masukkan
> kredensial itu ke `accounts.json`.
>
> Ini bukan keterbatasan yang sengaja dipasang, tapi memang tidak bisa:
> Q Lounge mengikat bonus invite lewat **Play Install Referrer**. Link share
> `https://affiliate.dj-maxrex.com/i/<kode>` mengarah ke Play Store dengan
> `?referrer=invite%3D<kode>`, dan aplikasi membacanya waktu pertama dibuka.
> Sign-up lewat API (`/auth/sign-up/*`) tidak pernah melihat referrer itu,
> jadi akun hasil API:
>
> - tidak punya `inviter` di `/auth/me`
> - tidak dapat bonus `invite_accepted` (+100 poin)
> - `hasWallet: false` — aplikasinya yang membuat wallet saat install
>
> Sudah dibuktikan dengan akun yang sama, dua cara daftar: lewat HP →
> `hasWallet:true` + `invite_accepted` tercatat. Lewat API → tidak ada
> keduanya. Jadi kalau mau bonus invite, **install dari link share**; kalau
> mau pakai bot, daftar manual dulu.

---

## Daftar isi

- [Yang dikerjakan bot](#yang-dikerjakan-bot)
- [Yang TIDAK bisa dikerjakan bot](#yang-tidak-bisa-dikerjakan-bot)
- [Pasang](#pasang)
- [Cara pakai](#cara-pakai)
- [Multi akun](#multi-akun)
- [Mode standby (dashboard)](#mode-standby-dashboard)
- [Anti-deteksi](#anti-deteksi)
- [Struktur file](#struktur-file)
- [Catatan teknis](#catatan-teknis)
- [Troubleshooting](#troubleshooting)
- [Legal](#legal)

---

## Yang dikerjakan bot

| Aksi | Endpoint | Hadiah |
|---|---|---|
| Check-in harian (ikut kuis) | `POST /attendance/check-in` | 20 pts + 2 XP |
| Baca post komunitas | `POST /community/posts/<id>/read` | 5 pts + 10 XP per post |
| Baca pengumuman | `POST /notices/<id>/read` | — |
| Naik level | otomatis dari XP | — |

Bot mengerjakan ini **sekali per hari per akun** (default jam 09:00 waktu
lokal), lalu refresh tampilan tiap 4 jam.

Verifikasi nyata pada akun uji: check-in `201` +20 pts, 15/15 post terbaca
+75 pts, saldo 230 → 325 dalam satu pass.

> **Catatan soal level:** API mengekspos `level`, `xp`, `nextLevelXp`, dan
> `nextLevelName`, tapi **belum ada mekanisme level-up** — sudah diprobe 9
> kemungkinan endpoint, semuanya 404, dan di aplikasi juga tidak ada tombol.
> Jadi wajar kalau XP sudah lewat `nextLevelXp` tapi level masih sama. Dashboard
> menampilkan angka apa adanya (`189/99`) supaya otomatis benar kalau fiturnya
> nanti nyala.

## Yang TIDAK bisa dikerjakan bot

Ini **by design**, bukan kelalaian. Jangan buang waktu mencari tombolnya:

| Item | Kenapa |
|---|---|
| `verify_email` (20 pts) | Tidak ada endpoint claim. Reward-nya otomatis server-side, atau memang tidak akan masuk. |
| `check_in_bonus` (100 pts) | Butuh streak check-in 7 hari berturut-turut. |
| `streak_15` (150 pts) | Butuh streak 15 hari. |
| `invite_sent` (100 pts/orang) | Butuh orang daftar lewat link invite lo. |
| Ganti nickname / foto profil | Aksi sekali (+30 pts). Tidak worth diotomasiin. |

---

## Pasang

Butuh: **Python 3** (3.8+) dan **git**. Tidak ada dependency eksternal —
semua pakai standard library.

```bash
git clone https://github.com/Devin1-tri/qlounge-bot.git
cd qlounge-bot
cp accounts.example.json accounts.json
```

Lalu edit `accounts.json`, isi email + password akun Q Lounge lo:

```json
{
  "accounts": [
    {
      "label": "akun1",
      "email": "email-kamu@gmail.com",
      "password": "password-kamu"
    }
  ],
  "defaults": {
    "max_posts_per_run": null,
    "account_gap": [45, 150],
    "check_in": [1.2, 4.5],
    "post_read": [3, 14],
    "notice_read": [0.6, 2]
  }
}
```

> `accounts.json` sudah masuk `.gitignore` — kredensial lo nggak akan
> ter-commit. Jangan pernah hapus baris itu.

---

## Cara pakai

### Sekali jalan

```bash
./qlounge.sh run          # semua akun, sekali jalan, lalu keluar
```

Atau langsung:

```bash
python3 qlounge.py run                 # semua akun
python3 qlounge.py run --account akun1 # satu akun
python3 qlounge.py status              # lihat saldo & status saja
```

### Opsi berguna

```bash
python3 qlounge.py run --no-posts    # check-in saja, jangan baca post
python3 qlounge.py run --no-guard    # paksa jalan walau sudah jalan hari ini
```

### Mode standby (dashboard) — rekomendasi

Ini mode yang dipakai kalau lo mau ditinggal jalan terus (di `screen`):

```bash
screen -S qlounge          # bikin screen sendiri
./qlounge.sh               # default = dashboard standby
# Ctrl+A lalu D untuk detach
```

Dashboard akan:
1. Gambar panel status
2. Diam, refresh tampilan tiap 4 jam
3. Pas jam 09:00 lokal → **jalanin pass sendiri** (check-in + semua post baru)
4. Update panel, lalu diam lagi sampai besok

Tidak ada input manual. Berhenti dengan `Ctrl+C`.

Opsi dashboard:

```bash
python3 dashboard.py --once              # satu pass lalu keluar (buat tes/cron)
python3 dashboard.py --daily-at 20       # ganti jam pass harian (default 9)
python3 dashboard.py --refresh-hours 2   # refresh lebih sering
```

Contoh tampilan:

```
┌────────────────┬──────────────────┬─────────┬───────────────┬─────────┐
│ Q LOUNGE BOT  ·  2026-10-22 13:59:31                                        │
├────────────────┼──────────────────┼─────────┼───────────────┼─────────┤
│ akun           │ username         │ poin    │ level         │ streak  │
├────────────────┼──────────────────┼─────────┼───────────────┼─────────┤
│ akun1          │ NamLo            │ 545     │ 1 STARTER 189 │ 2       │
│ akun2          │ AkunDua          │ 325     │ 1 STARTER 157 │ 1       │
├────────────────┴──────────────────┴─────────┴───────────────┴─────────┤
│ refresh tiap 4j  ·  berikutnya 17:59:31 (3h 59m)                          │
│ pass terakhir 2026-10-22T05:59:31+00:00                                    │
│ Ctrl+C = stop                                                              │
└──────────────────────────────────────────────────────────────────────────┘

  akun1          belum: check in bonus 100  daily post read 5
                  akun1@gmail.com  ·  MQX000000000001  ·  tersedia 145 / terkunci 400  ·  undangan 2
                  XP 189/99 ██████████████ siap naik
```

Panel otomatis menyesuaikan lebar terminal — di HP (~40 kolom) kolom yang
tidak muat dibuang supaya tidak rusak.

---

## Multi akun

Tiap akun cuma butuh **3 baris**. Setelan yang sama ditaruh sekali di
`defaults`:

```json
{
  "accounts": [
    { "label": "akun1", "email": "a1@gmail.com", "password": "..." },
    { "label": "akun2", "email": "a2@gmail.com", "password": "..." }
  ],
  "defaults": {
    "max_posts_per_run": null,
    "account_gap": [45, 150]
  }
}
```

`load_accounts()` menggabungkan `defaults` ke setiap akun. Kalau satu akun
butuh setelan beda, taruh field itu di objek akunnya:

```json
{ "label": "akun2", "email": "a2@gmail.com", "password": "...",
  "account_gap": [300, 600], "max_posts_per_run": 1 }
```

### Yang terjadi dengan banyak akun

Bot **tidak** menjalankan semua akun bersamaan. Urutannya:

```
1. Jeda awal 0-240 detik (random)
   → biar nggak tepat jam 09:00:00

2. Akun1: check-in → notice → semua post baru
3. Jeda 45-150 detik (random, dari account_gap akun2)
4. Akun2: check-in → notice → semua post baru
```

Jadi 5 akun selesai dalam ~6 menit, bukan 5 detik.

---

## Anti-deteksi

Bot dikunci ke pola pemakaian manusia. Detailnya di `anti_detection.py`;
ringkasnya:

- **Jeda acak antar aksi** — check-in 1.2–4.5 s, baca post 3–14 s, notice
  0.6–2 s. Tidak ada dua aksi yang berjarak identik.
- **Jeda antarakun** 45–150 s (bisa diatur per akun lewat `account_gap`).
- **Geser dari batas jam** — pass harian ditunda random 0–240 detik, jadi
  check-in nggak pernah berkop tepat 09:00:00.
- **Proteksi satu run per hari** (`DailyBudget`) — klaim kedua di hari yang
  sama tidak berguna dan justru mencolok. Di-hard-stop, bukan warning.
- **Jawaban kuis bervariasi** (`AnswerBank`) — pertanyaan diacak, jawaban
  dipilih dari beberapa variasi wajar, jadi tidak pernah byte-identik.
- **UA Android asli**, tidak dirotasi per request.

Yang sengaja **tidak** dilakukan: rotasi fingerprint palsu, header palsu,
atau usaha menipu limit yang dipaksakan server. Semua aksi adalah hal yang
bisa dilakukan user biasa di aplikasi.

---

## Struktur file

```
qlounge.py            bot sekali-jalan (run / status)
dashboard.py          dashboard standby (mode rekomendasi)
qlounge.sh            dispatcher tipis: run | status | once | (default) dashboard
ui.py                 warna, ikon, progress bar, kolom adaptif
anti_detection.py     pacing, jawaban kuis, budget guard
register.py           eksperimen pendaftaran otomatis + kenapa gagal
accounts.json         kredensial lo (gitignored — JANGAN commit)
accounts.example.json template
state/<label>.json    progres per akun (token, saldo terakhir, post terbaca)
demo_ui.py            render semua elemen UI buat cek layout
test_widths.py        cek tampilan di lebar terminal 40/60/80/120
```

---

## Catatan teknis

- Access token hidupnya ~15 menit; bot refresh otomatis pakai `refreshToken`,
  atau login ulang kalau token sudah mati.
- Poin baru biasanya masuk dalam status `locked` dan terbuka bertahap setelah
  check-in — itu perilaku server, bukan bug.
- Post hanya bisa dibaca **sekali seumur hidup** (5 poin per post), bukan per
  hari. Kalau semua post sudah dibaca, berikutnya nunggu post baru dipublish.
- Endpoint penghapusan akun (kalau perlu):
  `POST /auth/me/deletion/email/start` → `/verify` → `DELETE /auth/me {ticket}`

---

## Troubleshooting

| Gejala | Sebab | Solusi |
|---|---|---|
| `accounts.json kosong` | file belum dibuat | `cp accounts.example.json accounts.json` |
| Login gagal / `login gagal` | email/password salah | cek `accounts.json` |
| Akun dilewati, "sudah dijalankan hari ini" | guard 1×/hari | `--no-guard` kalau mau paksa |
| Panel tidak muncul warna | output bukan terminal | jalan langsung di terminal / screen |
| Tabel rusak di HP | terminal sempit | sudah otomatis adaptif; kalau masih rusak, perlebar terminal |
| Bot mati sendiri | proses child dari session lain | pakai `screen` biar lepas dari session |
| `ModuleNotFoundError` | Python terlalu lama | butuh Python 3.8+ |

---

## Legal

Otomasi akun sendiri melanggar atau tidaknya ToS adalah tanggung jawab
pemakainya. Repo ini disediakan sebagai apa adanya, tanpa jaminan.

Semua endpoint dibalik dari APK publik. Tidak ada exploit, tidak ada bypass
server-side — hanya otomasi hal yang memang bisa dilakukan user di aplikasi.

# Q Lounge Daily Bot

Otomasi aktivitas harian **Q Lounge** (`com.djmaxrex.qlounge`) — aplikasi
komunitas berbasis Expo/React Native dengan backend di
`https://appleintern.mqxwallet.com/v1`.

Bot ini mengerjakan check-in harian, membaca post dan pengumuman, mendukung
**multi akun**, dan mengatur polanya supaya mirip pemakaian manusia normal.

**Cuma butuh satu perintah: `python3 dashboard.py`.**

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
| `verify_email` (20 pts) | Tidak ada endpoint claim. Sudah diprobe 10 kandidat path claim, semua 404; di bundle aplikasi cuma ada `/auth/email/claim/start|verify` yang itu alur verifikasi email, bukan claim reward. Reward-nya keputusannya server-side. |
| `check_in_bonus` (100 pts) | Butuh streak check-in 7 hari berturut-turut. |
| `streak_15` (150 pts) | Butuh streak 15 hari. |
| `invite_sent` (100 pts/orang) | Butuh orang daftar lewat link invite lo. |
| Ganti nickname / foto profil | Aksi sekali (+30 pts). Tidak worth diotomasiin. |

---

## Pasang

Butuh: **Python 3** (3.8+, tanpa dependency eksternal) dan **git**.

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

`label` harus unik — dipakai sebagai nama file di `state/`.

> `accounts.json` dan `state/` sudah masuk `.gitignore`, jadi kredensial dan
> token lo nggak akan ter-commit. Jangan hapus baris itu.

---

## Cara pakai

### Standby (mode normal — cukup ini)

```bash
python3 dashboard.py
```

Itu aja. Bot akan:

1. Gambar panel status tiap akun
2. Diam, refresh tampilan tiap 4 jam
3. Pas jam 09:00 lokal → **jalanin pass sendiri** (check-in + semua post baru)
4. Update panel, lalu diam lagi sampai besok

Tidak ada input manual. Berhenti dengan `Ctrl+C`.

Kalau mau ditinggal di VPS / SSH, jalankan di dalam `screen` biar nggak mati
saat koneksi putus:

```bash
screen -S qlounge
python3 dashboard.py
# Ctrl+A lalu D untuk detach, `screen -r qlounge` untuk balik
```

### Opsi dashboard

```bash
python3 dashboard.py --once              # satu pass lalu keluar (buat tes/cron)
python3 dashboard.py --daily-at 20       # ganti jam pass harian (default 9)
python3 dashboard.py --refresh-hours 2   # refresh lebih sering
```

### Mode lain (kalau perlu)

Biasanya nggak perlu, tapi kalau mau satu kali jalan tanpa panel:

```bash
python3 qlounge.py run                  # sekali jalan semua akun, lalu keluar
python3 qlounge.py run --account akun1  # satu akun saja
python3 qlounge.py run --no-posts       # check-in saja, jangan baca post
python3 qlounge.py run --no-guard       # paksa walau sudah jalan hari ini
python3 qlounge.py status               # lihat saldo & status mentah
```

### Contoh tampilan

```
┌──────────────┬─────────────────┬────────┬──────────────┬────────┬──────────┬──────────┬────────┬─────────┬──────────┐
│ akun         │ username        │ poin   │ level        │ streak │ hari ini │ checkin  │ post   │ email   │ next     │
├──────────────┼─────────────────┼────────┼──────────────┼────────┼──────────┼──────────┼────────┼─────────┼──────────┤
│ akun1        │ NamLo           │ 545    │ 1 STARTER 18 │ 2      │ 60       │ [+]      │ [+]    │ [-]     │ 20h 26m  │
│ akun2        │ AkunDua         │ 325    │ 1 STARTER 15 │ 1      │ 225      │ [+]      │ [+]    │ [-]     │ 21h 14m  │
└──────────────┴─────────────────┴────────┴──────────────┴────────┴──────────┴──────────┴────────┴─────────┴──────────┘

┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  akun1        akun1@gmail.com    MQX000000000001    tersedia 145 / terkunci 400    undangan 2                          │
│               XP 189/99  target LEARNER tercapai                                                                     │
│  akun2        akun2@gmail.com    MQX000000000002    tersedia 125 / terkunci 200    undangan 0                          │
│               XP 157/99  target LEARNER tercapai                                                                     │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

 refresh tiap 4j  ·  berikutnya 19:02:52 (3h 59m)
 pass terakhir 2026-10-22T07:02:52+00:00
 Ctrl+C = stop
```

### Arti tiga kolom ceklis

Isinya **hasil pass harian bot**, bukan tebakan:

| Kolom | `[+]` artinya |
|---|---|
| `checkin` | check-in hari ini tercatat di server (`attendance.checkedIn = true`), bonus harian sudah masuk |
| `post` | nol post baru yang belum dibaca |
| `email` | email verified **dan** reward `verify_email` sudah `completed` |

`[-]` = belum selesai. Bot re-read server setelah pass dan menyimpan hasilnya
ke `state/<label>.json` (`task_checks`); kalau aksinya error, tick dipaksa
`[-]` — jadi `[+]` nggak pernah muncul tanpa konfirmasi server.

Catatan: `[-]` di kolom `email` **bukan** berarti tugasnya belum dikerjakan.
Kedua akun uji email-nya sudah verified, tapi reward 20 poinnya belum ada
endpoint claim-nya (lihat [tabel di atas](#yang-tidak-bisa-dikerjakan-bot)).

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
dashboard.py          dashboard standby — SATU-SATUNYA yang perlu dijalankan
qlounge.py            mesin aksi (run / status), dipakai dashboard
ui.py                 warna, ikon, progress bar, kolom adaptif
anti_detection.py     pacing, jawaban kuis, budget guard
register.py           eksperimen pendaftaran otomatis + kenapa gagal
accounts.json         kredensial lo (gitignored — JANGAN commit)
accounts.example.json template
state/<label>.json    progres per akun (token, saldo, post terbaca, task_checks)
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
- `state/` gitignored: di mesin lain bot login ulang sendiri dan mengisi
  `task_checks` di pass pertama. Nggak perlu copy state.
- Endpoint penghapusan akun (kalau perlu):
  `POST /auth/me/deletion/email/start` → `/verify` → `DELETE /auth/me {ticket}`

---

## Troubleshooting

| Gejala | Sebab | Solusi |
|---|---|---|
| `accounts.json kosong` | file belum dibuat | `cp accounts.example.json accounts.json` |
| Login gagal / `login gagal` | email/password salah | cek `accounts.json` |
| Akun dilewati, "sudah dijalankan hari ini" | guard 1×/hari | `python3 qlounge.py run --no-guard` kalau mau paksa |
| Panel tidak muncul warna | output bukan terminal | jalan langsung di terminal / screen |
| Tabel rusak di sempit | terminal < lebar kolom | sudah otomatis adaptif; kalau masih rusak, perlebar terminal |
| Bot mati saat SSH putus | proses ikut session | jalankan di dalam `screen` |
| `ModuleNotFoundError` | Python terlalu lama | butuh Python 3.8+ |

---

## Legal

Otomasi akun sendiri melanggar atau tidaknya ToS adalah tanggung jawab
pemakainya. Repo ini disediakan sebagai apa adanya, tanpa jaminan.

Semua endpoint dibalik dari APK publik. Tidak ada exploit, tidak ada bypass
server-side — hanya otomasi hal yang memang bisa dilakukan user di aplikasi.

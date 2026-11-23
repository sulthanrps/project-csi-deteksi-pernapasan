# Case B — Pemantauan laju napas dengan Wi-Fi CSI

Proyek ini mengolah rekaman IQ HackRF One 20 Msps dalam mode penerima. Mulai dari [panduan praktikum](panduan_pengerjaan_case_b_wi_fi_sensing_csi_hackrf_one.md). Luluskan uji baseline ruang kosong sebelum mengambil data subjek.

## Persiapan

Dari direktori proyek, siapkan Python 3.10 atau lebih baru dan instal dependensi. Instal juga `hackrf_tools` melalui pengelola paket sistem.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
hackrf_info
```

Gunakan router atau hotspot milik kelompok dan catat pengaturan gain tetap. Perintah proyek ini memakai kanal primer 149 (5745 MHz). HackRF merekam dengan sample rate 20 Msps dan filter 20 MHz ketika jaringan Wi-Fi menggunakan lebar kanal 80 MHz. Saat merekam, bangkitkan trafik stabil dari perangkat yang terhubung ke router kelompok. Untuk sesi dengan subjek, gunakan persetujuan tertulis dan kode anonim. Skrip mengolah sinyal dan preamble tanpa mendekode payload.

## 1. Validasi baseline

```bash
hackrf_transfer -r data/contoh_cs8/uji_1s_kanal149.cs8 \
  -f 5745000000 -s 20000000 -b 20000000 -l 40 -g 26 -a 0 -n 20000000
python kode/cek_clipping.py data/contoh_cs8/uji_1s_kanal149.cs8 --grafik hasil/grafik/uji_1s_kanal149.png
```

Periksa envelope. Burst harus terlihat di atas lantai derau dan persentase komponen di rel ADC harus mendekati 0%. Sesuaikan gain bila perlu dan kunci nilai yang lolos. Rekam ruangan kosong selama 60 detik:

```bash
hackrf_transfer -r data/contoh_cs8/B_baseline149_P0_kosong.cs8 \
  -f 5745000000 -s 20000000 -b 20000000 -l 40 -g 26 -a 0 -n 1200000000
python kode/csi_ekstrak.py data/contoh_cs8/B_baseline149_P0_kosong.cs8 \
  --label kosong -o hasil/tabel/kalibrasi_kandidat_kanal149.csv
```

Keluaran awal memuat semua kandidat OFDM yang lolos ambang korelasi. Pada rekaman kalibrasi, amati sebaran kolom `rssi_dbfs`, `cfo_hz` dan `burst_us`. Gunakan pengukuran sumber terkendali untuk mengenali klaster target dan ulangi ekstraksi dengan rentang yang sesuai. Set `--rssi MIN MAKS`, `--cfo MIN MAKS` dan/atau `--burst-us MIN MAKS` berdasarkan pengukuran. Tambahkan `--plot-baseline hasil/grafik/baseline.png` untuk memeriksa amplitudo antarpaket. Jika klaster sumber tumpang tindih, benahi penempatan atau trafik lalu ulangi kalibrasi. Penyaringan rentang merupakan perkiraan identitas sumber.

Verifikasi minimal 20 paket target dengan `rho > 0.6`, minimal 5 paket/s selama rekaman dan kurva amplitudo yang konsisten (panduan memberi contoh median koefisien variasi di bawah 10%). Durasi burst bawaan 24 µs dan ambang energi 10 dB di atas persentil ke-25 daya blok. Lihat `--help` untuk menyesuaikan parameter deteksi jika kondisi rekaman menuntutnya.

## 2. Rekam lima skenario Case B

Rekam masing-masing skenario selama 60 detik setelah baseline lulus. Gunakan posisi TX, RX dan kursi yang sama. Nyalakan trafik terkendali sebelum perekaman dan gunakan kanal serta gain hasil baseline. Untuk sesi rutin, alirkan IQ langsung ke ekstraktor. Perkiraan ukuran CSV pada 10–30 paket valid/s adalah 0,4–1,5 MB per sesi.

### Siapkan perintah rekam

Dari root proyek, jalankan blok ini sekali di Bash atau Zsh setelah mengaktifkan `.venv`. Ubah frekuensi dan gain bila hasil baseline memakai setelan berbeda. Isi array `FILTER_TX` dengan argumen rentang pemancar yang ditetapkan saat kalibrasi. Gunakan setelan yang sama untuk seluruh skenario dalam satu rangkaian.

```bash
set -o pipefail
FREQ_HZ=5745000000
LNA=40
VGA=26
AMP=0
FILTER_TX=()
# Isi FILTER_TX dengan opsi --rssi, --cfo dan/atau --burst-us yang lolos kalibrasi.

rekam_sesi() {
  local sesi="$1" subjek="$2" skenario="$3"
  shift 3
  local nama="B_${sesi}_${subjek}_${skenario}"

  hackrf_transfer -r - \
    -f "$FREQ_HZ" -s 20000000 -b 20000000 -l "$LNA" -g "$VGA" -a "$AMP" -n 1200000000 \
    | python kode/csi_ekstrak.py - --jumlah-sampel 1200000000 \
        --label "$skenario" -o "data/csi/$nama.csv" "${FILTER_TX[@]}" "$@"
}
```

Jika kalibrasi menetapkan rentang RSSI, masukkan dua angka batasnya saat menjalankan `read -r RSSI_MIN RSSI_MAKS`, lalu jalankan `FILTER_TX=(--rssi "$RSSI_MIN" "$RSSI_MAKS")`. Tambahkan batas CFO atau durasi burst ke array jika hasil kalibrasi memerlukannya. Array kosong menerima semua kandidat OFDM yang lolos korelasi.

### Jalankan satu per satu

Mulai hitungan stopwatch pada awal penerimaan IQ. Minta pengamat menyelaraskan aba-aba, metronom, dan catatan waktu dengan awal rekaman. Untuk napas berirama, satu ketukan menandai awal satu siklus tarik dan buang napas. Subjek duduk tenang di kursi yang ditandai.

| Skenario | Perintah | Selama 60 detik | Catatan ground truth |
| --- | --- | --- | --- |
| Ruang kosong | `rekam_sesi sesi2 P0 kosong --plot-baseline hasil/grafik/B_sesi2_P0_konsistensi.png` | Kosongkan ruangan. Pertahankan trafik dan hindari orang melintas. | Kosongkan `gt_bpm`. Catat jika ada gerakan atau orang lewat. |
| Napas lambat | `rekam_sesi sesi2 P1 bpm_10` | Metronom 10 BPM, satu siklus setiap 6 detik. | Catat laju teramati jika diukur. Protokol memakai target 10 BPM jika kolom kosong. |
| Napas normal | `rekam_sesi sesi2 P1 bpm_15` | Metronom 15 BPM, satu siklus setiap 4 detik. | Catat laju teramati jika diukur. Target bawaan 15 BPM. |
| Napas cepat | `rekam_sesi sesi2 P1 bpm_20` | Metronom 20 BPM, satu siklus setiap 3 detik. | Catat laju teramati jika diukur. Target bawaan 20 BPM. |
| Apnea | `rekam_sesi sesi2 P1 apnea` | Bernapas 15 BPM hingga detik 20, tahan napas hingga detik 35, lalu bernapas 15 BPM hingga selesai. Subjek boleh menghentikan sesi kapan saja. | Kosongkan `gt_bpm` di log. Catat detik aktual mulai dan selesai tahan napas. |

Gunakan kode subjek anonim dan ganti `sesi2` menjadi `sesi3` dan seterusnya untuk pengulangan agar CSV lama tetap tersimpan. Periksa durasi aktual dan laju paket target minimal 5 paket/s. Jika laju rendah atau paket bercampur, catat kondisinya dan ulangi setelah penyesuaian. Samakan `--jumlah-sampel` dan `-n` untuk melaporkan selisih durasi terhadap target 60 detik. Opsi `-r -` mengirim IQ melalui stdout. [Dokumentasi sumber hackrf_transfer](https://github.com/greatscottgadgets/hackrf/blob/main/host/hackrf-tools/src/hackrf_transfer.c)

Jika USB putus setelah mengirim sampel IQ, CSV tetap disimpan dengan nama sesi di `data/csi/`. Catat durasi aktual di log. Terminal tetap melaporkan kegagalan HackRF karena `pipefail` aktif. Analisis batch membaca CSV tersebut seperti sesi lain dan memberi status gagal jika paket belum mencakup jendela FFT 30 detik. Jendela bawaannya dari detik 15 hingga 45. Tambahkan `--wajib-lengkap` jika suatu pengambilan harus mencapai jumlah sampel yang ditargetkan.

CSV menyimpan hasil ekstraksi. Ekstraksi ulang dengan parameter berbeda membutuhkan IQ mentah. Untuk 1–2 contoh CS8 per skenario yang diminta panduan, gunakan `hackrf_transfer -r data/contoh_cs8/<nama_sesi>.cs8`, lalu jalankan ekstraktor dengan nama berkas tersebut seperti pada baseline. CS8 lengkap 60 detik berukuran sekitar 2,4 GB. Tambahkan `--fase` pada ekstraktor bila perlu menyimpan fase mentah CSI.

### Catat satu baris log per rekaman

Isi [log sesi](data/log_sesi.csv) dengan nama CSV atau CS8 yang memiliki nama dasar sama, tanggal dan jam mulai, kanal dan gain, kode subjek, label skenario, durasi aktual, jarak ke garis LOS, orientasi, serta kondisi ruangan. Di `catatan_ruangan`, tulis waktu gangguan, cara memperoleh ground truth, dan alasan pengulangan bila ada. Untuk laju napas terukur, amati ritme yang mencakup jendela FFT detik 15–45. Catat jumlah siklus lengkap dan waktu dari awal siklus pertama hingga akhir siklus terakhir. Hitung `gt_bpm` sebagai jumlah siklus × 60 ÷ durasi dalam detik.

Di [jadwal protokol](data/jadwal_protokol.csv), baris dengan `nama_file` kosong berlaku sebagai jadwal bawaan. Jika waktu apnea aktual berbeda, tambahkan satu set lengkap interval khusus sesi. Contoh berikut memakai detik 21,3 untuk mulai menahan napas dan detik 34,8 untuk kembali bernapas.

```csv
apnea,0,21.3,napas,15,B_sesi2_P1_apnea.csv
apnea,21.3,34.8,tahan_napas,0,B_sesi2_P1_apnea.csv
apnea,34.8,60,napas,15,B_sesi2_P1_apnea.csv
```

Pakai titik untuk desimal. Waktu selalu dihitung sejak awal rekaman. Skrip memakai interval khusus bila nama dasar berkasnya cocok.

## 3. Hasil analisis

Setelah CSV siap, jalankan analisis dan eksplorasi dari root. Simpan kandidat kalibrasi di luar `data/csi/` karena skrip batch membaca seluruh CSV di folder itu.

```bash
python kode/analisis_napas.py
python kode/eksplorasi.py
```

- `hasil/grafik/` berisi time-series, spektrum CSI dan RSSI pada jendela detik 15–45, dan STFT 12 detik untuk sesi apnea.
- `hasil/tabel/estimasi_sesi.csv` melaporkan laju paket, gap maksimum, puncak spektral, skor pemilihan dan galat terhadap ground truth. Pada skenario kosong dan apnea, puncak merupakan diagnostik spektrum. Periksa laju rendah, celah panjang dan sinyal datar saat membahas kondisi gagal.
- `hasil/tabel/ringkasan_mae.csv` membandingkan MAE CSI dan RSSI pada sesi berpasangan dengan ground truth. Periksa apakah hasil mencakup tiga ritme.
- Eksplorasi membandingkan paket asli dengan penjarangan deterministik ke target 5, 9,77 dan 15 paket/s. Kolom `laju_aktual_hz` menunjukkan paket yang benar-benar tersedia. Angka 9,77 paket/s menyimulasikan kepadatan beacon AP. Grafik MAE memakai sesi yang berhasil di semua kondisi.

Untuk memeriksa satu rekaman sebelum menjalankan semuanya, berikan jalur CSV dan direktori keluaran terpisah:

```bash
python kode/analisis_napas.py data/csi/B_sesi2_P1_apnea.csv \
  --grafik hasil/cek_sesi/grafik --tabel hasil/cek_sesi/tabel
```

CSV CSI menyertakan 52 amplitudo, waktu awal simbol L-LTF, RSSI relatif ke skala ADC, CFO, korelasi, durasi burst dan label. Analisis menyamakan grid 10 Hz, filter Hampel, detrending, band-pass 0,08–0,60 Hz dan FFT bagi CSI serta RSSI. Subcarrier dipilih dari rasio daya puncak terhadap daya rata-rata pada 0,10–0,50 Hz. Ground truth digunakan saat menghitung galat. Resolusi alami FFT 30 detik sekitar 2 BPM.

Ekstraksi memakai urutan L-LTF IEEE 802.11 pada persamaan 17-8. [IEEE Std 802.11-2007](https://people.iith.ac.in/tbr/teaching/docs/802.11-2007.pdf)

## 4. Bahan untuk menyusun laporan akhir

| Bahan | Isi yang diperlukan |
| --- | --- |
| `data/csi/` | CSV valid untuk ruang kosong, 10 BPM, 15 BPM, 20 BPM dan apnea. Sertakan pengulangan yang tersedia dan beri konteks untuk sesi gagal di log. |
| `data/log_sesi.csv` | Satu baris per rekaman. Catat ground truth terukur untuk tiga ritme jika tersedia, atau tandai bahwa metronom menjadi acuan. Catat jam, kanal, gain, kode subjek, jarak dan gangguan. |
| `data/jadwal_protokol.csv` | Jadwal dan waktu aktual apnea per sesi jika menyimpang dari jadwal bawaan. |
| Bukti baseline | Grafik envelope/clipping, jumlah paket target dengan `rho > 0.6`, laju paket, plot amplitudo subcarrier, median koefisien variasi, serta rentang filter pemancar yang dipakai. |
| Denah aktual | Jarak TX–RX, tinggi antena, jarak kursi ke LOS, orientasi subjek, posisi perangkat, dan kondisi ruangan. Sketsa berukuran sudah cukup. |

Dari bahan ini, laporan dapat memuat spektrum FFT dan time-series kelima skenario, tabel estimasi dan MAE CSI dibanding RSSI untuk 10/15/20 BPM, STFT apnea dengan penanda interval aktual, eksplorasi penjarangan paket, dan analisis sesi yang meleset berdasarkan gap paket serta kondisi ruangan. Folder `hasil/` boleh ikut diberikan jika analisis sudah dijalankan. Contoh CS8 tetap berguna untuk arsip dan ekstraksi ulang.

- [Proposal](proposal.pdf) memuat hipotesis, denah, metode dan target pengukuran.
- [Laporan](laporan.pdf) menyediakan kerangka pengisian hasil, pembahasan kegagalan dan evaluasi.
- [Slide](slide.pdf) memuat alur presentasi dan demo lima menit.

Isi log dan dokumen hasil setelah pengukuran. Data eksperimen dan umpan balik pitch belum tersedia di proyek ini.

# Panduan Pengerjaan Case B: Pemantauan Laju Napas Berbasis Wi-Fi CSI (HackRF One)

Panduan ini disusun sebagai acuan langkah demi langkah untuk mengerjakan **Case B (Pemantauan Laju Napas / Breathing Rate Monitoring)** pada mata kuliah Jaringan Nirkabel menggunakan perangkat **HackRF One (receive-only)** dan **Python 3**.

Sebelum masuk ke eksperimen inti Case B, kelompok **wajib menyelesaikan dan memvalidasi tahap Baseline (Pipeline Dasar)** untuk memastikan sinyal Wi-Fi, kualitas estimasi CSI, dan keterbatasan perangkat keras telah terkendali dengan benar.

---

## 1. Prasyarat Perangkat, Lingkungan, dan Etika

### 1.1 Perangkat Keras
* **HackRF One** + antena Wi-Fi yang sesuai dengan pita frekuensi (2.4 GHz atau 5 GHz).
* **Pemancar Wi-Fi terkendali** milik kelompok (hotspot HP atau router portabel dengan kanal yang dapat dikunci). Sangat disarankan menggunakan pemancar sendiri agar kanal tidak berpindah otomatis oleh RRM seperti pada AP kampus.
* **Laptop pemroses** (Linux/macOS/Windows) dengan ruang penyimpanan lega (minimal 10--20 GB kosong untuk buffer rekaman sementara).
* **Alat bantu eksperimen**: meteran, lakban/penanda lantai, aplikasi metronom (untuk ground truth laju napas), dan stopwatch.

### 1.2 Perangkat Lunak
Pastikan `hackrf_tools` (`hackrf_transfer`) dan pustaka Python 3 berikut telah terpasang:

```bash
# Cek instalasi HackRF
hackrf_info

# Instalasi pustaka Python
pip install numpy scipy matplotlib scikit-learn pandas
```

### 1.3 Memahami Batasan HackRF One
Karakteristik berikut harus diperhitungkan sejak tahap baseline:
1. **Receive-only (Half-duplex)**: HackRF hanya menerima paket Wi-Fi yang dipancarkan perangkat lain.
2. **Sample rate $20\text{ Msps}$**: Tepat untuk 1 primary channel Wi-Fi selebar $20\text{ MHz}$.
3. **ADC 8-bit**: Rentang dinamis terbatas. Nilai gain (`-l` dan `-g`) **wajib dikunci** agar tidak terjadi *clipping* dan agar amplitudo $|H[k]|$ antarrekaman dapat dibandingkan secara adil (keuntungannya: tidak ada AGC otomatis per paket).
4. **Satu antena penerima**: Analisis bertumpu pada amplitudo $|H[k]|$ dan fase tersanitasi (*sanitized phase*).
5. **Offset clock $\pm 20\text{ ppm}$**: Menyebabkan *Carrier Frequency Offset* (CFO) hingga puluhan kHz di pita $5\text{ GHz}$, sehingga koreksi CFO bersifat wajib.
6. **Ukuran data $40\text{ MB/detik}$**: Rekaman 60 detik menghasilkan berkas `.cs8` sebesar $2.4\text{ GB}$. Ekstraksi CSI harus segera dilakukan setelah sesi selesai agar penyimpanan tidak penuh.

### 1.4 Keselamatan, Regulasi, dan Etika
* **Dilarang keras** menggunakan mode pemancar (`hackrf_transfer -t`) tanpa izin tertulis dosen.
* Gunakan pemancar Wi-Fi standar bersertifikat (router/hotspot) pada pengaturan normal.
* **Jangan mendekode payload** trafik jaringan orang lain; olah hanya preamble (CSI), daya (RSSI), dan stempel waktu.
* Setiap subjek manusia harus memberikan persetujuan tertulis dan identitasnya disamarkan dengan kode anonim (`P1`, `P2`, dst.).

---

## 2. Struktur Folder Proyek

Gunakan struktur direktori berikut agar dokumentasi, kode, dan dataset terorganisasi dengan rapi:

```text
kelompok_X_caseB/
├── README.md                 # Panduan ini & cara menjalankan skrip
├── proposal.pdf              # Proposal akhir Minggu 1
├── kode/
│   ├── cek_clipping.py       # Skrip validasi sinyal mentah 1 detik
│   ├── csi_ekstrak.py        # Pipeline baseline: .cs8 -> CSI .csv/.npy
│   ├── analisis_napas.py     # Pipeline Case B: filter, pilih subcarrier, FFT, MAE, RSSI
│   └── eksplorasi.py         # Skrip eksperimen eksplorasi tambahan
├── data/
│   ├── log_sesi.csv          # Catatan waktu, kanal, gain, subjek, kondisi ruang
│   ├── jadwal_protokol.csv   # Jadwal skenario & ground truth (BPM / waktu apnea)
│   ├── csi/                  # Hasil ekstraksi CSI format bersama (.csv / .npy)
│   └── contoh_cs8/           # Simpan 1--2 berkas .cs8 mentah per skenario saja
├── hasil/
│   ├── grafik/               # Plot spektrum FFT, time-series, perbandingan RSSI (.png)
│   └── tabel/                # Tabel MAE & ringkasan metrik (.csv)
├── laporan.pdf               # Laporan akhir (maksimal 10 halaman)
└── slide.pdf                 # Slide presentasi & demo
```

---

## 3. Tahap Baseline (WAJIB Sebelum Masuk Case B)

Tahap ini dikerjakan pada **Minggu 1** dan menjadi fondasi penilaian (bobot pipeline & kualitas data 25%). Jangan mengambil data eksperimen Case B sebelum seluruh langkah validasi baseline di bawah ini lulus.

### 3.1 Memilih Pita Frekuensi dan Sumber Paket

| Aspek | Pita $2.4\text{ GHz}$ (Kanal 1, 6, 11) | Pita $5\text{ GHz}$ (misal Kanal 36, 40, 149, 157) |
| :--- | :--- | :--- |
| Panjang gelombang ($\lambda$) | $\approx 12.3\text{ cm}$ | $\approx 5.2 - 5.8\text{ cm}$ |
| Ketersediaan L-LTF | **Hati-hati!** Frame 802.11b (DSSS/CCK: 1, 2, 5.5, 11 Mbps) **tidak memiliki L-LTF** | **Pasti ada** (semua frame $5\text{ GHz}$ menggunakan OFDM) |
| Sensitivitas gerak napas | Lebih rendah ($\lambda$ lebih panjang) | **Lebih tinggi** (pergeseran dada beberapa mm menghasilkan perubahan fase relatif lebih besar) |
| Kebutuhan laju paket Case B | Minimal $5\text{ paket/s}$ (disarankan $15 - 30\text{ paket/s}$ untuk margin aman) | Minimal $5\text{ paket/s}$ (disarankan $15 - 30\text{ paket/s}$ untuk margin aman) |

> **Rekomendasi untuk Case B**: Gunakan **pita $5\text{ GHz}$** (misalnya kanal 36 pada $5180\text{ MHz}$ atau kanal 149 pada $5745\text{ MHz}$) jika hotspot/router mendukung. Jika tetap memilih $2.4\text{ GHz}$, Anda **wajib membuktikan pada tahap baseline** bahwa paket dari hotspot menghasilkan L-LTF valid ($\rho > 0.6$).

**Membangkitkan trafik terkendali**:
Hubungkan laptop ke hotspot/router kelompok, lalu jalankan `ping` secara stabil dengan interval sekitar $0.05\text{ s}$ ($20\text{ paket/s}$) atau $0.1\text{ s}$ ($10\text{ paket/s}$):

```bash
# Contoh membangkitkan trafik ~20 ping/detik ke IP gateway hotspot
ping -i 0.05 192.168.43.1
```

*(Catatan: Untuk Case B, laju paket minimum teoritis hanyalah $5\text{ paket/s}$ karena frekuensi napas $< 1\text{ Hz}$. Namun, trafik $10 - 20\text{ paket/s}$ membuat interpolasi dan penapisan noise jauh lebih stabil.)*

### 3.2 Daftar Periksa Sebelum Merekam (*Pre-Recording Checklist*)
Selalu pastikan daftar berikut sebelum menekan `Enter`:
- [ ] Antena sudah terpasang kencang pada port HackRF One.
- [ ] Kanal pemancar sudah diverifikasi dengan `scan_point.py` atau aplikasi Wi-Fi Analyzer.
- [ ] Parameter `-f` diisi dengan **frekuensi tengah primary channel $20\text{ MHz}$** (bukan tengah kanal $40/80\text{ MHz}$). Rumus $5\text{ GHz}$: $f = 5000 + 5 \times \text{nomor\_kanal}\text{ (MHz)}$.
- [ ] Nilai gain (`-l`, `-g`, `-a`) sama dengan sesi pembanding dan dicatat di `data/log_sesi.csv`.
- [ ] Ruang penyimpanan cukup ($40\text{ MB/detik} \approx 2.4\text{ GB}$ per rekaman 60 detik).
- [ ] Posisi pemancar, HackRF, dan titik duduk subjek sudah ditandai di lantai dengan lakban.
- [ ] Kondisi ruangan dicatat (jumlah orang, status pintu, potensi gangguan orang lewat).

### 3.3 Uji Rekam 1 Detik dan Cek Clipping
Lakukan uji rekam singkat selama 1 detik (`-n 20000000`) terlebih dahulu untuk memastikan tidak ada *clipping* pada ADC 8-bit.

```bash
# Contoh: Kanal 36 (5180 MHz), 20 Msps, gain rekomendasi (-l 40 -g 26 -a 0), durasi 1 detik
hackrf_transfer -r data/contoh_cs8/uji_1s.cs8 \
  -f 5180000000 -s 20000000 -b 20000000 \
  -l 40 -g 26 -a 0 -n 20000000
```

Jalankan pemeriksaan *clipping* sederhana di Python:

```python
import numpy as np

raw = np.fromfile("data/contoh_cs8/uji_1s.cs8", dtype=np.int8)
clip_ratio = np.mean(np.abs(raw) >= 127) * 100
print(f"Min: {raw.min()}, Max: {raw.max()}, Persentase Clipping: {clip_ratio:.4f}%")
```

* **Kriteria lulus**: Nilai tidak menumpuk di $\pm 127$ (persentase clipping mendekati $0\%$), dan sinyal burst tampak jelas di atas *noise floor*. Jika terjadi *clipping*, turunkan `-g` (misal dari `26` ke `18` atau `16`) lalu kunci nilai tersebut untuk seluruh eksperimen berikutnya.

### 3.4 Pipeline Ekstraksi CSI Dasar
Alur pemrosesan dari berkas mentah `.cs8` ke matriks CSI adalah:

$$\text{.cs8} \rightarrow \text{Deteksi Burst} \rightarrow \text{Cari L-LTF } (\rho > 0.6) \rightarrow \text{Koreksi CFO} \rightarrow \text{FFT \& Estimasi } H[k] \rightarrow \text{Filter Pemancar Target} \rightarrow \text{Simpan CSV/NPY}$$

1. **Deteksi Burst**: Gunakan `occupancy.py --simpan-burst` atau detektor energi (rata-rata daya jendela $1\ \mu\text{s}$ dengan ambang sekitar $10\text{ dB}$ di atas *noise floor*, durasi minimal $24\ \mu\text{s}$).
2. **Pencarian L-LTF & Estimasi CSI**: Gunakan implementasi acuan berikut pada setiap potongan burst (`seg = iq[awal_burst - 20 : awal_burst + 400]`):

```python
import numpy as np

# L-LTF domain frekuensi, subcarrier -26..+26 (IEEE 802.11)
L = np.array([
    1, 1, -1, -1, 1, 1, -1, 1, -1, 1, 1, 1, 1, 1, 1, -1, -1, 1, 1, -1, 1, -1, 1, 1, 1, 1,
    0,
    1, -1, -1, 1, 1, -1, 1, -1, 1, -1, -1, -1, -1, -1, 1, 1, -1, -1, 1, -1, 1, -1, 1, 1, 1, 1
], dtype=float)

K = np.arange(-26, 27)
X = np.zeros(64, dtype=complex)
X[K % 64] = L
ltf = np.fft.ifft(X)          # 1 simbol LTF (64 sampel)
IDX = K[K != 0] % 64          # 52 subcarrier terisi (tanpa DC)

def baca_cs8(path, mulai_s=0.0, durasi_s=1.0, fs=20e6):
    off = int(mulai_s * fs) * 2
    raw = np.fromfile(path, np.int8, count=int(durasi_s * fs) * 2, offset=off)
    return (raw[0::2] + 1j * raw[1::2]).astype(np.complex64) / 128.0

def cari_ltf(seg):
    """Mencari indeks awal simbol LTF pertama pada potongan burst."""
    e = np.sqrt(np.convolve(np.abs(seg) ** 2, np.ones(64), "valid"))
    rho = np.abs(np.correlate(seg, ltf, "valid")) / (np.linalg.norm(ltf) * e + 1e-12)
    i = int(np.argmax(rho))
    # Terdapat dua puncak berjarak 64 sampel; pastikan mengambil puncak pertama
    if i >= 64 and rho[i - 64] > 0.7 * rho[i]:
        i -= 64
    return i, float(rho[i])

def csi_dari_ltf(seg, i, fs=20e6):
    """Koreksi fine CFO dan estimasi Least Squares H[k] pada 52 subcarrier."""
    s1, s2 = seg[i : i + 64], seg[i + 64 : i + 128]
    cfo = np.angle(np.vdot(s1, s2)) / 64.0  # rad/sampel
    s = seg[i : i + 128] * np.exp(-1j * cfo * np.arange(128))
    Y = (np.fft.fft(s[:64]) + np.fft.fft(s[64:])) / 2.0
    H = Y[IDX] / X[IDX]
    cfo_hz = cfo * fs / (2 * np.pi)
    return H, float(cfo_hz)
```

*(Catatan: Fine CFO dari L-LTF andal hingga $\pm 156\text{ kHz}$. Jika estimasi CFO melebihi batas tersebut, lakukan koreksi coarse CFO terlebih dahulu dari L-STF dengan periode 16 sampel.)*

3. **Pemisahan Pemancar Target (Sangat Penting!)**:
   HackRF menerima seluruh paket pada kanal tersebut, termasuk paket *ping request* dari laptop pengirim maupun paket AP tetangga. Jika paket dari laptop dan hotspot tercampur, lintasan sinyalnya berbeda dan akan merusak osilasi napas. Pisahkan pemancar target dengan menganalisis klaster:
   * **Level daya (`rssi_dbfs`)**: Jarak TX target ke HackRF konstan sehingga RSSI membentuk pita yang jelas.
   * **Nilai `cfo_hz`** dan **durasi burst**: Verifikasi sebarannya pada rekaman statis.
   * *(Opsional lanjutan)*: Dekode L-SIG atau gunakan `gr-ieee802-11` untuk menyaring berdasarkan MAC address.

4. **Format Keluaran Bersama**:
   Simpan hasil ekstraksi setiap sesi ke `data/csi/<nama_sesi>.csv` (atau `.npy`) dengan kolom standar berikut:

   | Kolom | Keterangan |
   | :--- | :--- |
   | `t_s` | Waktu kedatangan paket sejak awal rekaman (detik) |
   | `rssi_dbfs` | Daya rata-rata simbol L-LTF (dBFS) |
   | `cfo_hz` | Estimasi CFO (Hz) |
   | `rho` | Nilai korelasi L-LTF ($0$ sampai $1$; ambil yang $> 0.6$) |
   | `amp_k-26` ... `amp_k26` | Amplitudo $|H[k]|$ untuk 52 subcarrier |
   | `fasa_k-26` ... `fasa_k26` | Fase mentah $\arg H[k]$ (opsional; wajib disanitasi sebelum dipakai) |
   | `label` | Kelas/skenario sesuai `jadwal_protokol.csv` |

### 3.5 Kriteria Lulus Tahap Baseline (Checkpoint Minggu 1)
Sebelum beralih ke Case B, pastikan kelompok sudah mendapatkan hasil berikut pada uji baseline ruang kosong:
1. Minimal **20 paket valid** dengan korelasi $\rho > 0.6$ berhasil diekstrak.
2. **Laju paket aktual** dari pemancar target terukur dan memenuhi kebutuhan Case B ($\ge 5\text{ paket/s}$, idealnya $10 - 20\text{ paket/s}$).
3. **Plot amplitudo $|H[k]|$ statis** pada ruang kosong menunjukkan bentuk kurva subcarrier yang konsisten antarpaket (koefisien variasi rendah, misal $< 10\%$).
4. **Manajemen disk berjalan**: Skrip ekstraksi dapat mengubah `.cs8` ke `.csv` secara otomatis sehingga berkas `.cs8` lama dapat segera dihapus (sisakan 1--2 sampel saja).

---

## 4. Panduan Eksekusi Case B: Pemantauan Laju Napas

### 4.1 Pertanyaan Riset dan Prinsip Fisika
* **Pertanyaan Utama**: Seberapa akurat laju napas (napas per menit / BPM) dapat diestimasi dari CSI menggunakan satu HackRF One, dan pada kondisi apa estimasi tersebut gagal?
* **Prinsip Fisika**: Saat bernapas, rongga dada bergerak naik-turun beberapa milimeter secara periodik. Perubahan panjang lintasan pantulan $L(t)$ ini menyebabkan interferensi konstruktif dan destruktif antara lintasan statis ($H_{\text{statis}}$) dan lintasan dinamis:
  $$H(t) = H_{\text{statis}} + a \cdot e^{-j 2 \pi L(t) / \lambda}$$
  Akibatnya, amplitudo $|H[k]|$ berosilasi pada frekuensi napas manusia, yaitu **$0.1\text{ Hz}$ hingga $0.5\text{ Hz}$** (setara **$6$ hingga $30\text{ BPM}$**). Karena geometri lintasan berbeda untuk tiap panjang gelombang subcarrier, sebagian subcarrier akan jauh lebih sensitif menangkap osilasi napas dibanding subcarrier lainnya.

### 4.2 Tata Letak Eksperimen (Denah)
Letakkan pemancar (TX) dan HackRF One (RX) pada **ketinggian sekitar $1\text{ m}$** dengan jarak pisah **$3 - 5\text{ m}$**. Subjek duduk tenang di kursi pada jarak **$1 - 2\text{ m}$ dari garis *Line of Sight* (LOS)**, menghadap garis LOS.

```text
          |<-------------- 3 m sampai 5 m -------------->|
   +------+                                              +------+
   |  TX  | =============== Garis LOS ================== |  RX  |
   |(Hotsp)|                   |                         |(HackRF)
   +------+                    |                         +------+
   (h = 1 m)              1 m - 2 m                      (h = 1 m)
                               |
                           [ Subjek ]
                         (Duduk diam,
                        menghadap LOS)
```

*(Tandai kaki meja TX, posisi antena RX, dan kaki kursi subjek menggunakan lakban agar geometri identik pada setiap sesi.)*

### 4.3 Skenario Pengambilan Data dan Ground Truth
Setiap sesi direkam minimal **60 detik** (`-n 1200000000` pada $20\text{ Msps}$) agar tersedia cukup ruang untuk jendela FFT 30 detik dan pemangkasan transien awal/akhir.

**Konvensi penamaan berkas**: `B_{sesi}_{subjek}_{skenario}.cs8`

| No | Skenario | Kode Label | Durasi | Ground Truth & Instruksi |
| :--- | :--- | :--- | :--- | :--- |
| 1 | **Ruang kosong** (Baseline) | `kosong` | $60\text{ s}$ | Tidak ada orang di ruangan (pastikan tidak ada yang melintas). |
| 2 | **Napas lambat** | `bpm_10` | $60\text{ s}$ | Subjek bernapas mengikuti ketukan metronom $10\text{ BPM}$ (1 siklus tiap $6\text{ s}$). |
| 3 | **Napas normal** | `bpm_15` | $60\text{ s}$ | Subjek bernapas mengikuti ketukan metronom $15\text{ BPM}$ (1 siklus tiap $4\text{ s}$). |
| 4 | **Napas cepat** | `bpm_20` | $60\text{ s}$ | Subjek bernapas mengikuti ketukan metronom $20\text{ BPM}$ (1 siklus tiap $3\text{ s}$). |
| 5 | **Menahan napas (Apnea)** | `apnea` | $60\text{ s}$ | Jadwal terencana: misal $0 - 20\text{ s}$ napas normal ($15\text{ BPM}$), $20 - 35\text{ s}$ **tahan napas ($15\text{ s}$)**, $35 - 60\text{ s}$ napas normal kembali. |

> **Tips Ground Truth**: Selain metronom, seorang pengamat dapat ikut menghitung siklus napas aktual secara manual (atau memakai video yang disetujui subjek hanya untuk pelabelan) guna memverifikasi bahwa subjek benar-benar mengikuti ritme metronom. Ulangi pengambilan data pada sesi berbeda (dan idealnya lebih dari 1 subjek) agar evaluasi sahih.

**Contoh perintah perekaman satu sesi (60 detik, Kanal 36)**:
```bash
hackrf_transfer -r data/contoh_cs8/B_sesi1_P1_bpm15.cs8 \
  -f 5180000000 -s 20000000 -b 20000000 \
  -l 40 -g 26 -a 0 -n 1200000000
```

Catat metadata setiap rekaman ke `data/log_sesi.csv` (contoh kolom: `nama_file, tanggal, jam_mulai, kanal, freq_hz, lna_l, vga_g, subjek, skenario, gt_bpm, catatan_ruangan`).

### 4.4 Pipeline Pemrosesan Sinyal Khusus Case B

Setelah berkas `.cs8` diekstrak menjadi `.csv` lewat pipeline baseline, lakukan langkah pemrosesan sinyal berikut di `kode/analisis_napas.py`:

#### Langkah 1: Resampling ke Grid Waktu Seragam
Kedatangan paket Wi-Fi bersifat tidak teratur (*irregular*). Lakukan interpolasi linear (atau kubik) pada deret waktu $|H[k]|$ dan `rssi_dbfs` ke frekuensi sampling seragam $f_s$ (misalnya $f_s = 10\text{ Hz}$ atau $20\text{ Hz}$).
* **Wajib dilaporkan**: Laju paket aktual rata-rata (paket/s) dan celah waktu (*gap*) terpanjang pada setiap sesi.

#### Langkah 2: Pembersihan Outlier dan Penapisan Frekuensi
1. **Hampel Filter**: Hapus lonjakan ekstrem (*outlier*) per subcarrier akibat interferensi sesaat.
2. **Penghapusan komponen DC (*Detrending*)**: Kurangkan nilai rata-rata (atau tren linear lambat) pada tiap subcarrier.
3. **Band-Pass Filter**: Terapkan filter *Butterworth* (zero-phase dengan `scipy.signal.filtfilt`) pada pita frekuensi napas, yaitu **$0.1\text{ Hz}$ hingga $0.5\text{ Hz}$** (atau sedikit dilebarkan ke $0.08 - 0.6\text{ Hz}$ agar tepi pita 6--30 BPM tidak teredam).

#### Langkah 3: Pemilihan Subcarrier Sensitif (Tanpa *Data Leakage*!)
Tidak semua dari 52 subcarrier sensitif terhadap gerakan dada. Namun, **DILARANG** memilih subcarrier dengan cara mengintip subcarrier mana yang paling dekat dengan *ground truth* data uji!

Gunakan salah satu metode **tanpa pengawasan (*unsupervised*)** yang sahih berikut:
* **Metode A — Rasio Energi / Periodisitas Pita Napas (*Breath-to-Noise Ratio* / BNR)**:
  Untuk setiap subcarrier $k$, hitung spektrum daya (PSD/FFT). Hitung rasio antara energi puncak dominan pada pita napas ($0.1 - 0.5\text{ Hz}$) terhadap rata-rata energi total pada pita tersebut (atau pita di luar napas). Pilih subcarrier (atau rata-rata top-$N$ subcarrier) dengan skor BNR tertinggi.
* **Metode B — Variansi / PCA**:
  Pilih subcarrier dengan variansi tertinggi setelah band-pass filter, atau terapkan PCA pada 52 subcarrier tersaring lalu pilih komponen utama dengan skor periodisitas (autokorelasi/BNR) tertinggi (catatan: periksa apakah PC1 didominasi *common-mode noise*; pada metode CARM, PC1 sering dibuang dan PC2--PC6 dianalisis).

#### Langkah 4: Estimasi Laju Napas dengan FFT Jendela 30 Detik
* Ambil jendela sinyal sepanjang **$T = 30\text{ detik}$** (misalnya detik ke-15 sampai ke-45 untuk menghindari artefak gerakan di awal/akhir rekaman).
* Resolusi frekuensi alami jendela $30\text{ s}$ adalah:
  $$\Delta f = \frac{1}{30\text{ s}} \approx 0.0333\text{ Hz} \approx 2\text{ BPM}$$
* Terapkan fungsi jendela (*Hann* atau *Hamming window*) untuk menekan *spectral leakage*, lalu lakukan FFT (dapat ditambah *zero-padding* agar lokasi puncak lebih halus).
* Cari frekuensi puncak $f_{\text{peak}}$ di rentang $0.1 - 0.5\text{ Hz}$ dan konversikan ke BPM:
  $$\widehat{\text{BPM}} = 60 \times f_{\text{peak}}$$

#### Langkah 5: Evaluasi Kuantitatif dan Perbandingan dengan RSSI
1. Hitung **Galat Absolut Rata-Rata (MAE)** terhadap *ground truth* pada minimal 3 laju napas berbeda:
   $$\text{MAE} = \frac{1}{N} \sum_{i=1}^{N} \left| \widehat{\text{BPM}}_i - \text{BPM}_{\text{GT}, i} \right|$$
2. Jalankan **pipeline yang persis sama** (resampling, Hampel, band-pass $0.1 - 0.5\text{ Hz}$, FFT 30 s) pada deret waktu **`rssi_dbfs`**. Bandingkan spektrum dan nilai MAE antara CSI dan RSSI.
3. Bandingkan puncak spektrum kondisi **bernapas** terhadap kondisi **ruang kosong** dan **menahan napas (apnea)** (gunakan *Short-Time Fourier Transform* / jendela geser untuk melihat hilangnya puncak saat subjek menahan napas selama 15 detik).

---

## 5. Target Minimal dan Ruang Eksplorasi

### 5.1 Target Minimal (Wajib Tercapai)
- [ ] **Grafik Spektrum FFT (jendela 30 s)** dari $|H[k]|$ subcarrier terpilih untuk tiap skenario (ruang kosong, apnea, dan minimal 3 laju napas), dengan penanda puncak frekuensi napas yang jelas.
- [ ] **Tabel Estimasi Laju Napas dan MAE (BPM)** terhadap *ground truth* pada minimal 3 laju napas berbeda (misal 10, 15, 20 BPM).
- [ ] **Analisis Pembanding RSSI**: Bukti kuantitatif dan visual apakah RSSI saja dapat menangkap napas dibandingkan CSI.
- [ ] **Analisis Kondisi Gagal**: Pembahasan jujur pada kondisi apa estimasi CSI meleset (misal gerakan kecil tubuh, jarak terlalu jauh, atau *gap* paket terlalu lebar).

### 5.2 Ide Eksplorasi (Pilih Minimal 1 untuk Nilai Tambah 15%)
Nilai tertinggi diberikan pada eksplorasi yang diuji secara terukur dengan angka (hasil negatif yang dianalisis secara ilmiah tetap bernilai tinggi):
1. **Pengaruh Jarak dan Orientasi**: Bandingkan MAE pada jarak $1\text{ m}$, $2\text{ m}$, $3\text{ m}$ dari garis LOS, serta posisi menghadap LOS vs membelakangi/menyamping LOS.
2. **Detektor Apnea Otomatis**: Bangun detektor berbasis jendela geser (STFT/energi pita $0.1 - 0.5\text{ Hz}$) untuk mendeteksi segmen henti napas 15 detik secara otomatis dan ukur *precision/recall* waktunya.
3. **Beacon AP Saja vs Hotspot Terkendali**: Uji apakah beacon AP standar ($\approx 9.77\text{ paket/s}$) cukup akurat untuk estimasi napas dibandingkan hotspot bertrafik `ping` (dapat juga disimulasikan lewat *downsampling*).
4. **Dua Subjek Sekaligus**: Dua orang duduk dekat garis LOS bernapas pada laju berbeda (misal $10\text{ BPM}$ dan $20\text{ BPM}$); uji apakah dua puncak terpisah muncul pada spektrum FFT.
5. **Eksplorasi Fase Tersanitasi**: Bandingkan estimasi napas dari amplitudo $|H[k]|$ vs fase tersanitasi (setelah *unwrap* dan pengurangan regresi linear $a \cdot k + b$ terhadap indeks subcarrier $k$).
6. **Detak Jantung ($1 - 2\text{ Hz}$)**: Eksplorasi menantang saat subjek menahan napas 15--20 detik; analisis apakah harmonik napas atau noise lantai menghalangi deteksi detak jantung.

---

## 6. Kesalahan Umum (*Pitfalls*) dan Troubleshooting

| Masalah / Kesalahan | Penyebab Umum | Solusi |
| :--- | :--- | :--- |
| **Tidak ada paket valid ($\rho > 0.6$ nol)** | Menggunakan $2.4\text{ GHz}$ yang mengirim frame 802.11b (DSSS/CCK), salah frekuensi `-f`, atau antena lupa dipasang. | Pindah ke pita $5\text{ GHz}$, cek kanal dengan `scan_point.py`, pastikan `-f` adalah primary channel $20\text{ MHz}$ dan antena terpasang. |
| **Puncak napas hilang/tertutup noise** | Subjek bergerak kecil (menggaruk, menoleh, menggoyang kaki) atau ada orang lewat di ruangan. | Instruksikan subjek duduk sangat diam dan bersandar; tandai waktu gangguan di log; potong segmen bersih atau ulangi sesi. |
| **Resolusi BPM kasar / meleset jauh** | Jendela FFT terlalu pendek (misal hanya 10 detik $\rightarrow \Delta f = 6\text{ BPM}$). | Gunakan jendela minimal **$30\text{ detik}$** ($\Delta f = 2\text{ BPM}$) atau lebih panjang. |
| **Amplitudo $|H[k]|$ melompat-lompat acak** | Paket dari laptop (`ping request`) tercampur dengan paket dari hotspot (`ping reply`), atau gain diubah di tengah eksperimen. | Saring pemancar target berdasarkan klaster `rssi_dbfs` / `cfo_hz` dan kunci nilai `-l` dan `-g`. |
| **Akurasi tinggi tapi tidak sahih (*Data Leakage*)** | Subcarrier terbaik dipilih dengan melihat mana yang paling cocok dengan *ground truth* data uji. | Gunakan metrik pemilihan subcarrier *unsupervised* (misal BNR / periodisitas) atau pilih berdasarkan sesi kalibrasi terpisah. |
| **Hard disk cepat penuh** | Lupa menghapus berkas `.cs8` ($2.4\text{ GB}$ per menit). | Segera jalankan `csi_ekstrak.py` setelah merekam, verifikasi hasil `.csv`, simpan 1--2 contoh `.cs8`, lalu hapus sisanya. |

---

## 7. Jadwal Kerja dan Checklist Luaran

### Jadwal Singkat
* **Minggu 1 (Baseline & Proposal)**: Validasi pipeline CSI ($\ge 20$ paket $\rho > 0.6$), uji laju paket, pitch silang, dan kumpulkan `proposal.pdf` (1--2 halaman).
* **Minggu 2 (Eksekusi Case B)**: Pengambilan seluruh skenario data, ekstraksi CSI ke format bersama, analisis target minimal + eksplorasi, dan *checkpoint* tengah minggu bersama dosen.
* **Minggu 3 (Presentasi & Demo)**: Presentasi 15 menit, demo langsung 5 menit (rekam di kelas $\rightarrow$ tampilkan CSI & estimasi laju napas), serta tanya jawab silang 10 menit.

### Checklist Luaran Akhir
- [ ] `proposal.pdf` (dengan hipotesis terukur, denah, metrik angka, dan tanggapan kritik kelompok lain).
- [ ] Kode end-to-end (`kode/`) yang dapat dijalankan ulang dari `.cs8` hingga grafik akhir.
- [ ] Dataset (`data/`): berkas CSI format bersama (`.csv`/`.npy`), `log_sesi.csv`, `jadwal_protokol.csv`, dan minimal 1 contoh `.cs8` mentah per skenario.
- [ ] `laporan.pdf` (maksimal 10 halaman: latar belakang, metode, hasil angka, pembanding RSSI, eksplorasi, keterbatasan, saran).
- [ ] `slide.pdf` + kesiapan skrip demo langsung berdurasi 5 menit.
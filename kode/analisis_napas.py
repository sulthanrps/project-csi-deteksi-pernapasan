"""Estimasi laju napas dari CSI dan RSSI, lalu simpan grafik dan tabel evaluasi."""
import argparse
import csv
from pathlib import Path

import numpy as np

from cek_clipping import ROOT
from csi_ekstrak import AMP, K

BAND = (0.1, 0.5)
WINDOW = 30
GRAFIK = ROOT / "hasil/grafik"
TABEL = ROOT / "hasil/tabel"
LOG = ROOT / "data/log_sesi.csv"
PROTOKOL = ROOT / "data/jadwal_protokol.csv"


def baca_tabel(path):
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def tulis_tabel(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def baca_csi(path):
    rows = baca_tabel(path)
    if len(rows) < 2:
        raise ValueError("Minimal dua paket CSI diperlukan.")
    try:
        values = np.array([[float(r[col]) for col in ("t_s", *AMP, "rssi_dbfs")] for r in rows])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("CSV harus berisi t_s, rssi_dbfs dan 52 amplitudo numerik.") from exc
    if not np.isfinite(values).all() or values[:, 0].min() < 0:
        raise ValueError("Waktu dan nilai sinyal harus berhingga, dengan waktu ≥ 0.")
    labels = {r.get("label", "").strip() for r in rows} - {""}
    if len(labels) > 1:
        raise ValueError("Satu CSV harus berisi satu label sesi.")
    values = values[np.argsort(values[:, 0], kind="stable")]
    time, idx, counts = np.unique(values[:, 0], return_index=True, return_counts=True)
    series = np.add.reduceat(values[:, 1:], idx, axis=0) / counts[:, None]
    if len(time) < 2:
        raise ValueError("Perlu setidaknya dua stempel waktu berbeda.")
    return time, series, next(iter(labels), "")


def metadata(path, label, logs, schedule):
    row = logs.get(path.stem, {})
    scenario = row.get("skenario") or label or "tanpa_label"
    if scenario == "tanpa_label":
        scenario = next((name for name, _ in schedule if path.stem.endswith(f"_{name}")), scenario)
    intervals = schedule.get((scenario, path.stem), schedule.get((scenario, ""), []))
    gt = row.get("gt_bpm")
    steady = len(intervals) == 1 and intervals[0]["kondisi"] == "napas"
    if steady and not gt:
        gt = intervals[0]["gt_bpm"]
    gt_bpm = float(gt) if gt and (steady or not intervals) else None
    duration = float(row["durasi_s"]) if row.get("durasi_s") else None
    if gt_bpm is not None and (not np.isfinite(gt_bpm) or gt_bpm <= 0):
        raise ValueError("gt_bpm untuk sesi napas harus positif dan berhingga.")
    if duration is not None and (not np.isfinite(duration) or duration <= 0):
        raise ValueError("durasi_s harus positif dan berhingga.")
    return scenario, intervals, gt_bpm, duration


def hampel(values, half_width):
    padded = np.pad(values, ((half_width, half_width), (0, 0)), mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, 2 * half_width + 1, axis=0)
    median = np.median(windows, axis=-1)
    mad = np.median(np.abs(windows - median[..., None]), axis=-1)
    outlier = np.abs(values - median) > 3 * 1.4826 * np.maximum(mad, 1e-12)
    return np.where(outlier, median, values)


def siapkan(time, series, fs):
    from scipy.signal import butter, detrend, sosfiltfilt

    steps = np.arange(int(np.ceil(time[0] * fs)), int(np.floor(time[-1] * fs)) + 1)
    grid = steps / fs
    if len(grid) < WINDOW * fs:
        raise ValueError("Cakupan paket kurang dari 30 detik pada grid waktu.")
    interpolated = np.column_stack([np.interp(grid, time, col) for col in series.T])
    clean = detrend(hampel(interpolated, max(2, round(fs / 2))), axis=0)
    sos = butter(3, (0.08, 0.6), btype="bandpass", fs=fs, output="sos")
    return grid, sosfiltfilt(sos, clean, axis=0)


def spektrum(values, fs):
    n = len(values)
    window = np.hanning(n)[:, None]
    nfft = 2 ** int(np.ceil(np.log2(8 * n)))
    fft = np.fft.rfft((values - values.mean(axis=0)) * window, n=nfft, axis=0)
    return np.fft.rfftfreq(nfft, d=1 / fs), np.abs(fft / window.sum())**2


def estimasi(time, series, fs, start):
    grid, filtered = siapkan(time, series, fs)
    first = int(np.searchsorted(grid, start - 1e-9))
    count = WINDOW * fs
    if first >= len(grid) or abs(grid[first] - start) >= 1 / fs + 1e-9 or first + count > len(grid):
        raise ValueError(f"Paket tidak mencakup jendela 30 detik mulai {start:g} s.")
    freq, power = spektrum(filtered[first:first + count], fs)
    in_band = (freq >= BAND[0]) & (freq <= BAND[1])
    band_power = power[in_band]
    peak = band_power.max(axis=0)
    average = band_power.mean(axis=0)
    bnr = np.divide(peak, average, out=np.zeros_like(peak), where=average > 1e-20)
    # Pilih subcarrier memakai spektrum CSI saja. RSSI diproses pada kolom terakhir.
    best = int(np.argmax(bnr[:-1]))
    selected = [best, len(AMP)]
    peaks = np.where(bnr[selected] > 0, freq[in_band][band_power[:, selected].argmax(axis=0)], np.nan)
    return grid, filtered[:, selected], freq, power[:, selected], peaks, bnr[selected], best


def pyplot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def grafik_sesi(path, title, result, intervals, start, fs):
    plt = pyplot()
    time, filtered, freq, power, peaks, _, best = result
    fig, axes = plt.subplots(2, 2, figsize=(11, 6), layout="constrained")
    for col, (name, unit) in enumerate(((f"CSI k={K[best]:+d}", "|H[k]|"), ("RSSI", "dB"))):
        ax = axes[0, col]
        ax.plot(time, filtered[:, col], linewidth=0.85)
        ax.axvspan(start, start + WINDOW, alpha=0.12, color="tab:blue", label="Jendela FFT")
        for interval in intervals:
            if interval["kondisi"] == "tahan_napas":
                ax.axvspan(float(interval["mulai_s"]), float(interval["akhir_s"]),
                           color="tab:orange", alpha=0.24, label="Jadwal tahan napas")
        ax.set(title=name, xlabel="Waktu (s)", ylabel=f"Sinyal tersaring ({unit})")
        ax.legend(loc="upper right", fontsize=8)
        ax = axes[1, col]
        in_display = (freq >= 0.05) & (freq <= 0.65)
        ax.plot(freq[in_display] * 60, power[in_display, col])
        ax.axvspan(BAND[0] * 60, BAND[1] * 60, alpha=0.1, color="tab:blue")
        if np.isfinite(peaks[col]):
            ax.axvline(peaks[col] * 60, color="tab:red", linestyle="--",
                       label=f"Puncak {peaks[col] * 60:.2f} BPM")
            ax.legend(loc="upper right", fontsize=8)
        ax.set(xlabel="Frekuensi (BPM)", ylabel=f"Daya spektral ({unit}²)")
    fig.suptitle(f"{title} · FFT {WINDOW} s · grid {fs} Hz")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def grafik_apnea(path, result, intervals, fs):
    from scipy.signal import stft

    plt = pyplot()
    time, filtered, *_ = result
    length = 12 * fs
    freq, centers, values = stft(filtered.T, fs=fs, nperseg=length, noverlap=length - fs,
                                 nfft=4 * length, boundary=None, padded=False)
    band = (freq >= BAND[0]) & (freq <= BAND[1])
    power = np.abs(values[:, band, :])**2
    fig, axes = plt.subplots(2, 2, figsize=(11, 6), sharex=True, layout="constrained")
    for row, name in enumerate(("CSI", "RSSI")):
        x = centers + time[0]
        im = axes[row, 0].pcolormesh(x, freq[band] * 60, 10 * np.log10(power[row] + 1e-20),
                                     shading="auto")
        fig.colorbar(im, ax=axes[row, 0], label="Daya (dB, skala masing-masing)")
        axes[row, 0].set(title=f"{name} · STFT 12 s", ylabel="Frekuensi (BPM)")
        axes[row, 1].plot(x, power[row].sum(axis=0))
        axes[row, 1].set(title=f"{name} · energi pita napas", ylabel="Energi spektral")
        for ax in axes[row]:
            for interval in intervals:
                if interval["kondisi"] == "tahan_napas":
                    ax.axvspan(float(interval["mulai_s"]), float(interval["akhir_s"]),
                               color="tab:orange", alpha=0.25)
    for ax in axes[-1]:
        ax.set_xlabel("Waktu (s)")
    fig.savefig(path, dpi=160)
    plt.close(fig)


def baca_metadata(log_path, protocol_path):
    logs = {}
    for row in baca_tabel(log_path):
        key = Path(row["nama_file"]).stem
        if key in logs:
            raise ValueError(f"Nama sesi ganda di log: {key}")
        logs[key] = row
    schedule = {}
    for row in baca_tabel(protocol_path):
        session = Path((row.get("nama_file") or "").strip()).stem
        schedule.setdefault((row["skenario"], session), []).append(row)
    return logs, schedule


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path, nargs="*", help="Default: semua CSV di data/csi.")
    parser.add_argument("--log", type=Path, default=LOG)
    parser.add_argument("--protokol", type=Path, default=PROTOKOL)
    parser.add_argument("--grafik", type=Path, default=GRAFIK)
    parser.add_argument("--tabel", type=Path, default=TABEL)
    parser.add_argument("--fs", type=int, default=10, help="Frekuensi grid waktu (Hz).")
    parser.add_argument("--mulai", type=float, default=15, help="Awal jendela FFT dalam detik.")
    args = parser.parse_args()
    if args.fs < 2 or not np.isfinite(args.mulai) or args.mulai < 0:
        parser.error("fs harus ≥ 2 Hz dan waktu mulai harus berhingga serta ≥ 0.")
    inputs = args.inputs or sorted((ROOT / "data/csi").glob("*.csv"))
    if not inputs:
        parser.error("Belum ada CSV CSI. Jalankan kode/csi_ekstrak.py dahulu.")
    if len({path.stem for path in inputs}) != len(inputs):
        parser.error("Nama sesi harus unik untuk setiap CSV.")
    try:
        logs, schedule = baca_metadata(args.log, args.protokol)
    except (OSError, KeyError, ValueError) as exc:
        parser.error(str(exc))

    rows = []
    for path in inputs:
        row = {"sesi": path.stem}
        rows.append(row)
        try:
            time, series, label = baca_csi(path)
            scenario, intervals, gt, duration = metadata(path, label, logs, schedule)
            span = time[-1] - time[0]
            rate = len(time) / duration if duration else (len(time) - 1) / span
            gap = np.diff(time).max()
            row.update(skenario=scenario, gt_bpm=gt, jumlah_paket=len(time), laju_paket_hz=rate,
                       dasar_laju="durasi_rekaman" if duration else "rentang_paket",
                       gap_maks_s=gap)
            result = estimasi(time, series, args.fs, args.mulai)
            _, _, freq, power, peaks, bnr, best = result
            in_band = (freq >= BAND[0]) & (freq <= BAND[1])
            peak_power = power[in_band].max(axis=0)
            bpm = [float(p * 60) if np.isfinite(p) else None for p in peaks]
            row.update(subcarrier=int(K[best]), puncak_csi_bpm=bpm[0], puncak_rssi_bpm=bpm[1],
                       skor_csi=bnr[0], skor_rssi=bnr[1],
                       daya_puncak_csi=peak_power[0], daya_puncak_rssi=peak_power[1])
            for method, value in zip(("csi", "rssi"), bpm):
                if scenario not in ("kosong", "apnea"):
                    row[f"estimasi_{method}_bpm"] = value
                if gt is not None and value is not None:
                    row[f"galat_{method}_bpm"] = abs(value - gt)
            grafik_sesi(args.grafik / f"{path.stem}.png", path.stem, result, intervals, args.mulai, args.fs)
            if any(r["kondisi"] == "tahan_napas" for r in intervals):
                grafik_apnea(args.grafik / f"{path.stem}_stft.png", result, intervals, args.fs)
            flags = [text for condition, text in ((rate < 5, "laju_paket_rendah"),
                                                   (gap > 1, "gap_lebih_dari_1_s"),
                                                   (any(v is None for v in bpm), "sinyal_datar")) if condition]
            row["status"] = ", ".join(flags) or "ok"
        except (OSError, KeyError, ValueError) as exc:
            row["status"] = f"gagal: {exc}"
        print(f"{path.stem}: {row['status']}")

    fields = ["sesi", "skenario", "gt_bpm", "jumlah_paket", "laju_paket_hz", "dasar_laju", "gap_maks_s",
              "subcarrier", "skor_csi", "skor_rssi", "puncak_csi_bpm", "puncak_rssi_bpm",
              "daya_puncak_csi", "daya_puncak_rssi", "estimasi_csi_bpm", "estimasi_rssi_bpm",
              "galat_csi_bpm", "galat_rssi_bpm", "status"]
    tulis_tabel(args.tabel / "estimasi_sesi.csv", rows, fields)
    evaluated = [r for r in rows if not r["status"].startswith("gagal")
                 and "galat_csi_bpm" in r and "galat_rssi_bpm" in r]
    groups = [("semua", evaluated)]
    for gt in sorted({r["gt_bpm"] for r in evaluated}):
        groups.append((gt, [r for r in evaluated if r["gt_bpm"] == gt]))
    summary = []
    for group, selected in groups:
        summary.append({"gt_bpm": group, "jumlah_sesi": len(selected),
                        "mae_csi_bpm": np.mean([r["galat_csi_bpm"] for r in selected]) if selected else "",
                        "mae_rssi_bpm": np.mean([r["galat_rssi_bpm"] for r in selected]) if selected else ""})
    tulis_tabel(args.tabel / "ringkasan_mae.csv", summary, summary[0].keys())
    print(f"{len(evaluated)} sesi berpasangan dengan GT | hasil: {args.tabel}")
    return int(any(r["status"].startswith("gagal") for r in rows))


if __name__ == "__main__":
    raise SystemExit(main())

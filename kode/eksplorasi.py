"""Ukur pengaruh penjarangan paket terhadap akurasi CSI dan RSSI."""
import argparse
from pathlib import Path

import numpy as np

from analisis_napas import (
    GRAFIK, LOG, PROTOKOL, TABEL, baca_csi, baca_metadata, estimasi, metadata,
    pyplot, tulis_tabel,
)
from cek_clipping import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path, nargs="*", help="Default: semua CSV di data/csi.")
    parser.add_argument("--log", type=Path, default=LOG)
    parser.add_argument("--protokol", type=Path, default=PROTOKOL)
    parser.add_argument("--laju", type=float, nargs="+", default=[5, 9.77, 15])
    parser.add_argument("--tabel", type=Path, default=TABEL / "eksplorasi_downsampling.csv")
    parser.add_argument("--grafik", type=Path, default=GRAFIK / "eksplorasi_downsampling.png")
    args = parser.parse_args()
    if not np.isfinite(args.laju).all() or min(args.laju) <= 0:
        parser.error("Setiap laju penjarangan harus positif dan berhingga.")
    inputs = args.inputs or sorted((ROOT / "data/csi").glob("*.csv"))
    if not inputs:
        parser.error("Belum ada CSV CSI.")
    if len({path.stem for path in inputs}) != len(inputs):
        parser.error("Nama sesi harus unik untuk setiap CSV.")
    try:
        logs, schedule = baca_metadata(args.log, args.protokol)
    except (OSError, KeyError, ValueError) as exc:
        parser.error(str(exc))

    rows = []
    targets = [None, *sorted(set(args.laju))]
    for path in inputs:
        try:
            time, series, label = baca_csi(path)
            scenario, _, gt, duration = metadata(path, label, logs, schedule)
        except (OSError, KeyError, ValueError) as exc:
            parser.error(f"{path}: {exc}")
        if gt is None:
            continue
        for target in targets:
            # Pertahankan paket pertama di setiap bin waktu. Bin kosong tetap kosong.
            indices = np.arange(len(time)) if target is None else np.unique(
                np.floor(time * target), return_index=True
            )[1]
            t = time[indices]
            row = {"sesi": path.stem, "skenario": scenario, "gt_bpm": gt,
                   "target_hz": "" if target is None else target, "jumlah_paket": len(t)}
            rows.append(row)
            if len(t) < 2:
                row["status"] = "paket_kurang"
                continue
            row["laju_aktual_hz"] = len(t) / duration if duration else (len(t) - 1) / (t[-1] - t[0])
            row["gap_maks_s"] = np.diff(t).max()
            try:
                _, _, _, _, peaks, _, _ = estimasi(t, series[indices], fs=10, start=15)
            except ValueError as exc:
                row["status"] = str(exc)
                continue
            if not np.isfinite(peaks).all():
                row["status"] = "sinyal_datar"
                continue
            row["csi_bpm"], row["rssi_bpm"] = peaks * 60
            row["galat_csi_bpm"], row["galat_rssi_bpm"] = np.abs(peaks * 60 - gt)
            row["status"] = "ok"

    if not rows:
        parser.error("Perlu setidaknya satu sesi napas dengan ground truth.")
    fields = ["sesi", "skenario", "gt_bpm", "target_hz", "jumlah_paket", "laju_aktual_hz",
              "gap_maks_s", "csi_bpm", "rssi_bpm", "galat_csi_bpm", "galat_rssi_bpm", "status"]
    tulis_tabel(args.tabel, rows, fields)

    # Bandingkan kondisi pada himpunan sesi yang sama.
    valid = [r for r in rows if r["status"] == "ok"]
    coverage = {}
    for row in valid:
        coverage.setdefault(row["sesi"], set()).add(row["target_hz"])
    complete = {session for session, rates in coverage.items() if len(rates) == len(targets)}
    if not complete:
        print(f"{args.tabel} | Tidak ada sesi yang berhasil di semua kondisi laju.")
        return 1
    plt = pyplot()
    fig, ax = plt.subplots(layout="constrained")
    for name in ("csi", "rssi"):
        means = []
        for target in targets:
            selected = [r for r in valid if r["sesi"] in complete
                        and r["target_hz"] == ("" if target is None else target)]
            means.append(np.mean([r[f"galat_{name}_bpm"] for r in selected]))
        ax.plot(range(len(targets)), means, marker="o", label=name.upper())
    ax.set_xticks(range(len(targets)), ["Asli", *(f"{value:g}" for value in targets[1:])])
    ax.set(xlabel="Target penjarangan (paket/s)", ylabel="MAE (BPM)",
           title=f"Penjarangan paket · {len(complete)} sesi berpasangan")
    ax.legend()
    args.grafik.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.grafik, dpi=160)
    plt.close(fig)
    print(args.tabel)
    print(args.grafik)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

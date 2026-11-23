"""Ekstrak 52 subcarrier CSI dari CS8 20 Msps, melalui berkas atau stdin."""
import argparse
import csv
import sys
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np

from cek_clipping import FS, ROOT, daya_dbfs

# IEEE 802.11, L-LTF dengan urutan -26 sampai +26.
K = np.r_[np.arange(-26, 0), np.arange(1, 27)]
X = np.zeros(64)
X[K % 64] = [
    1, 1, -1, -1, 1, 1, -1, 1, -1, 1, 1, 1, 1, 1, 1, -1, -1, 1, 1, -1, 1, -1, 1, 1, 1, 1,
    1, -1, -1, 1, 1, -1, 1, -1, 1, -1, -1, -1, -1, -1, 1, 1, -1, -1, 1, -1, 1, -1, 1, 1, 1, 1,
]
LTF = np.fft.ifft(X)
AMP = [f"amp_k{k}" for k in K]
FASE = [f"fasa_k{k}" for k in K]
BIN = 20
BLOCK = 1_000_000
LOOKAHEAD = 400


class PembacaIQ:
    def __init__(self, stream):
        self.stream = stream
        self.jumlah_sampel = 0

    def baca_blok(self):
        raw = self.stream.read(2 * BLOCK)
        if len(raw) % 2:
            raise ValueError("CS8 harus berisi pasangan I/Q int8 yang lengkap.")
        samples = np.frombuffer(raw, dtype=np.int8).reshape(-1, 2)
        self.jumlah_sampel += len(samples)
        return samples


@dataclass
class Burst:
    start: int
    end: int
    preamble: np.ndarray


def deteksi_burst(reader, ambang_db, min_us):
    """Kelompokkan bin daya 1 µs, termasuk burst yang melintasi batas blok."""
    pending = None
    previous = np.empty((0, 2), dtype=np.int8)
    base = 0
    block = reader.baca_blok()
    while len(block):
        following = reader.baca_blok()
        bins = len(block) // BIN
        if not bins:
            break
        power = np.square(block[:bins * BIN].astype(np.float32) / 128)
        power = power.reshape(bins, BIN * 2).sum(axis=1) / BIN
        floor = max(np.quantile(power, 0.25), 1 / 128**2)
        active = power > floor * 10**(ambang_db / 10)
        edges = np.flatnonzero(np.diff(np.r_[False, active, False])) * BIN + base
        if len(edges):
            context = np.concatenate((previous, block, following[:LOOKAHEAD]))
        for start, end in edges.reshape(-1, 2):
            if pending is not None and start - pending.end <= 3 * BIN:
                pending.end = end
                continue
            if pending is not None and pending.end - pending.start >= min_us * BIN:
                yield pending
            offset = len(previous) + start - base
            preamble = context[max(0, offset - BIN):offset + LOOKAHEAD].copy()
            pending = Burst(start, end, preamble)

        if pending is not None and base + bins * BIN - pending.end > 3 * BIN:
            if pending.end - pending.start >= min_us * BIN:
                yield pending
            pending = None
        previous = block[-BIN:].copy()
        base += len(block)
        block = following

    if pending is not None and pending.end - pending.start >= min_us * BIN:
        yield pending


def cari_ltf(seg):
    """Skor timing memakai dua simbol identik L-LTF yang berjarak 64 sampel."""
    energy = np.sqrt(np.convolve(np.abs(seg)**2, np.ones(64), "valid"))
    rho = np.abs(np.correlate(seg, LTF, "valid")) / (np.linalg.norm(LTF) * energy + 1e-12)
    score = np.minimum(rho[:-64], rho[64:])
    index = int(np.argmax(score))
    return index, float(min(score[index], 1))


def estimasi(burst):
    left = max(0, burst.start - BIN)
    raw = burst.preamble.astype(np.float32)
    if len(raw) < 128:
        return None
    seg = (raw[:, 0] + 1j * raw[:, 1]) / 128
    offset = burst.start - left
    stf = seg[offset + 16:offset + 136]
    pair = np.vdot(stf[:-16], stf[16:])
    coarse = np.angle(pair) / 16
    corrected = seg * np.exp(-1j * coarse * np.arange(len(seg)))
    i, rho = cari_ltf(corrected)
    # STF yang terpotong atau interferensi dapat memberi estimasi kasar yang buruk.
    fallback_i, fallback_rho = cari_ltf(seg)
    if fallback_rho > rho:
        coarse, corrected, i, rho = 0, seg, fallback_i, fallback_rho
    symbols = corrected[i:i + 128]
    fine = np.angle(np.vdot(symbols[:64], symbols[64:])) / 64
    symbols = symbols * np.exp(-1j * fine * np.arange(128))
    channel = np.fft.fft(symbols.reshape(2, 64)).mean(axis=0)
    csi = channel[K % 64] / X[K % 64]
    rssi = float(daya_dbfs(np.mean(np.abs(symbols)**2)))
    cfo = (coarse + fine) * FS / (2 * np.pi)
    return (left + i) / FS, rssi, cfo, rho, csi


def dalam(value, bounds):
    return bounds is None or bounds[0] <= value <= bounds[1]


def grafik_baseline(amplitudes, path):
    if not len(amplitudes):
        return
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(layout="constrained")
    for row in amplitudes[:100]:
        ax.plot(K, row, color="tab:blue", alpha=0.12)
    ax.plot(K, np.median(amplitudes, axis=0), color="black", label="Median")
    ax.set(xlabel="Indeks subcarrier", ylabel="|H[k]|", title="Konsistensi CSI ruang kosong")
    ax.legend()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Berkas CS8 atau '-' untuk membaca stdin.")
    parser.add_argument("-o", "--output", type=Path, help="CSV keluaran. Default: data/csi/<nama>.csv.")
    parser.add_argument("--jumlah-sampel", type=int, help="Jumlah sampel IQ yang ditargetkan.")
    duration_mode = parser.add_mutually_exclusive_group()
    duration_mode.add_argument("--wajib-lengkap", action="store_true",
                               help="Tolak rekaman yang lebih pendek dari --jumlah-sampel.")
    duration_mode.add_argument("--terima-parsial", dest="wajib_lengkap", action="store_false",
                               help=argparse.SUPPRESS)
    parser.set_defaults(wajib_lengkap=False)
    parser.add_argument("--label", default="")
    parser.add_argument("--fase", action="store_true")
    parser.add_argument("--ambang-db", type=float, default=10)
    parser.add_argument("--min-burst-us", type=float, default=24)
    parser.add_argument("--min-rho", type=float, default=0.6)
    parser.add_argument("--rssi", type=float, nargs=2, metavar=("MIN", "MAKS"))
    parser.add_argument("--cfo", type=float, nargs=2, metavar=("MIN", "MAKS"))
    parser.add_argument("--burst-us", type=float, nargs=2, metavar=("MIN", "MAKS"))
    parser.add_argument("--plot-baseline", type=Path)
    args = parser.parse_args()
    if (not 0 <= args.min_rho < 1
            or not np.isfinite([args.ambang_db, args.min_burst_us]).all()
            or args.min_burst_us <= 0):
        parser.error("Periksa ambang deteksi, durasi burst dan rho.")
    for bounds in (args.rssi, args.cfo, args.burst_us):
        if bounds is not None and (not np.isfinite(bounds).all() or bounds[0] > bounds[1]):
            parser.error("Rentang filter harus berhingga dengan MIN ≤ MAKS.")
    if args.jumlah_sampel is not None and args.jumlah_sampel <= 0:
        parser.error("--jumlah-sampel harus positif.")
    if args.wajib_lengkap and args.jumlah_sampel is None:
        parser.error("--wajib-lengkap memerlukan --jumlah-sampel.")

    via_stdin = args.input == "-"
    if via_stdin and (not args.output or sys.stdin.isatty()):
        parser.error("Input '-' membutuhkan aliran IQ dari stdin dan nama CSV melalui -o.")
    input_path = None if via_stdin else Path(args.input)
    output = args.output or ROOT / "data/csi" / f"{input_path.stem}.csv"
    if input_path is not None and output.resolve() == input_path.resolve():
        parser.error("Keluaran CSV harus berbeda dari input CS8.")
    temp = None
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        scanned = candidates = 0
        fields = ["t_s", "rssi_dbfs", "cfo_hz", "rho", "burst_us", *AMP]
        if args.fase:
            fields.extend(FASE)

        source = nullcontext(sys.stdin.buffer) if via_stdin else input_path.open("rb")
        with source as stream, NamedTemporaryFile(mode="w", newline="", encoding="utf-8",
                                                   dir=output.parent, delete=False) as handle:
            temp = Path(handle.name)
            reader = PembacaIQ(stream)
            writer = csv.writer(handle)
            writer.writerow([*fields, "label"])
            for burst in deteksi_burst(reader, args.ambang_db, args.min_burst_us):
                scanned += 1
                packet = estimasi(burst)
                if packet is None or packet[3] <= args.min_rho:
                    continue
                candidates += 1
                t, rssi, cfo, rho, csi = packet
                burst_us = (burst.end - burst.start) / BIN
                if not (dalam(rssi, args.rssi) and dalam(cfo, args.cfo)
                        and dalam(burst_us, args.burst_us)):
                    continue
                amplitudes = np.abs(csi)
                rows.append(amplitudes)
                values = [t, rssi, cfo, rho, burst_us, *amplitudes]
                if args.fase:
                    values.extend(np.angle(csi))
                writer.writerow([*(f"{value:.9g}" for value in values), args.label])
            actual = reader.jumlah_sampel
            if actual == 0:
                raise ValueError("Tidak ada sampel IQ yang diterima.")
            expected = args.jumlah_sampel
            if expected is not None and (actual > expected or (args.wajib_lengkap and actual < expected)):
                raise ValueError(f"Jumlah sampel berbeda: diterima {actual:,}, target {expected:,}.")
        temp.replace(output)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)

    duration = actual / FS
    if expected is not None and actual < expected:
        print(f"Rekaman lebih pendek dari target ({duration:.3f}/{expected / FS:.3f} s). CSV disimpan.",
              file=sys.stderr)
    print(f"{scanned} burst | {candidates} preamble valid | {len(rows)} paket lolos filter")
    print(f"Durasi: {duration:.3f} s | Laju selama rekaman: {len(rows) / duration:.2f} paket/s")
    if rows:
        amplitudes = np.array(rows)
        mean = amplitudes.mean(axis=0)
        cv = amplitudes[:, mean > 0].std(axis=0) / mean[mean > 0]
        if len(cv) and len(rows) >= 2:
            print(f"Median koefisien variasi subcarrier: {np.median(cv):.2%}")
        if args.plot_baseline:
            grafik_baseline(amplitudes, args.plot_baseline)
    print(f"{output} ({output.stat().st_size:,} byte)")


if __name__ == "__main__":
    main()

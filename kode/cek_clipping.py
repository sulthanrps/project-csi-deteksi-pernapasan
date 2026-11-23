"""Inspeksi ADC dan envelope rekaman IQ HackRF."""
import argparse
from pathlib import Path

import numpy as np

FS = 20_000_000
ROOT = Path(__file__).resolve().parents[1]


def buka_cs8(path):
    size = path.stat().st_size
    if not size or size % 2:
        raise ValueError("CS8 harus berisi pasangan I/Q int8 yang lengkap.")
    return np.memmap(path, mode="r", dtype=np.int8, shape=(size // 2, 2))


def daya_dbfs(power):
    return 10 * np.log10(np.maximum(power, 1e-12))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--grafik", type=Path, help="Simpan envelope daya ke PNG.")
    args = parser.parse_args()

    try:
        iq = buka_cs8(args.input)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    lo, hi, clipped = 127, -128, 0
    envelope = []
    for first in range(0, len(iq), 1_000_000):
        block = iq[first:first + 1_000_000]
        lo, hi = min(lo, block.min()), max(hi, block.max())
        clipped += np.count_nonzero((block <= -127) | (block >= 127))
        # Simpan puncak daya 1 µs per interval 1 ms agar burst singkat terlihat.
        for start in range(0, len(block), 20_000):
            samples = block[start:start + 20_000].astype(np.float32) / 128
            power = np.square(samples).sum(axis=1)
            bins = len(power) // 20
            envelope.append(power[:bins * 20].reshape(-1, 20).mean(axis=1).max()
                            if bins else power.mean())

    db = daya_dbfs(np.array(envelope))
    print(f"Durasi: {len(iq) / FS:.3f} s | Min: {lo} | Maks: {hi}")
    print(f"Komponen di rel ADC (|nilai| ≥ 127): {clipped}/{iq.size} ({clipped / iq.size:.6%})")
    print(f"Envelope daya median: {np.median(db):.1f} dBFS | maksimum: {db.max():.1f} dBFS")

    if args.grafik:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        args.grafik.parent.mkdir(parents=True, exist_ok=True)
        fig, ax = plt.subplots(layout="constrained")
        ax.plot(np.arange(len(db)) / 1000, db, linewidth=0.8)
        ax.set(xlabel="Waktu (s)", ylabel="Daya puncak 1 µs (dBFS)", title="Envelope rekaman IQ")
        fig.savefig(args.grafik, dpi=150)
        plt.close(fig)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Plot NF vs Gain Index from one or more sweep CSV logs (see CSV schema in
README.md). Each input file is plotted as its own curve, labeled by the
Freq_MHz value found in that file.

Usage:
    python plot_nf.py data/raw/nf_920MHz_2026-09-12.csv data/raw/nf_2190MHz_2026-09-12.csv \
        --out results/plots/nf_vs_gain.png
"""

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt


def load_csv(path: str):
    gain_idx, nf_db, freq_mhz = [], [], None
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            gain_idx.append(int(row["Gain_Index"]))
            nf_db.append(float(row["NF_dB"]))
            freq_mhz = row["Freq_MHz"]
    order = sorted(range(len(gain_idx)), key=lambda i: gain_idx[i])
    gain_idx = [gain_idx[i] for i in order]
    nf_db = [nf_db[i] for i in order]
    return gain_idx, nf_db, freq_mhz


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv_files", nargs="+", help="One or more NF sweep CSV logs")
    ap.add_argument("--out", required=True, help="Output plot image path")
    ap.add_argument("--title", default="AD9361 (USRP B210) Noise Figure vs Gain Index")
    args = ap.parse_args()

    fig, ax = plt.subplots(figsize=(9, 6))

    seen_freqs = defaultdict(int)
    for path in args.csv_files:
        gain_idx, nf_db, freq_mhz = load_csv(path)
        label = f"{freq_mhz} MHz" if freq_mhz else Path(path).stem
        seen_freqs[label] += 1
        if seen_freqs[label] > 1:
            label = f"{label} (#{seen_freqs[label]})"
        ax.plot(gain_idx, nf_db, marker="o", markersize=3, linewidth=1, label=label)

    ax.set_xlabel("Gain Index")
    ax.set_ylabel("Noise Figure (dB)")
    ax.set_title(args.title)
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    print(f"Saved plot to {out_path}")


if __name__ == "__main__":
    main()

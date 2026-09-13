#!/usr/bin/env python3
"""
Plot SNR vs Gain Index (and the underlying Signal/Noise-floor traces) from
one or more run_snr_sweep.py CSV logs.

Usage:
    python plot_snr.py data/raw/snr_920MHz.csv data/raw/snr_2190MHz.csv \
        --out results/plots/snr_vs_gain.png
"""

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt


def load_csv(path: str):
    rows = {"gain": [], "signal": [], "noise": [], "snr": [], "freq": None}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            rows["gain"].append(int(row["Gain_Index"]))
            rows["signal"].append(float(row["Signal_Power_dB"]))
            rows["noise"].append(float(row["Noise_Floor_dB"]))
            rows["snr"].append(float(row["SNR_dB"]))
            rows["freq"] = row["Freq_MHz"]
    order = sorted(range(len(rows["gain"])), key=lambda i: rows["gain"][i])
    for k in ("gain", "signal", "noise", "snr"):
        rows[k] = [rows[k][i] for i in order]
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv_files", nargs="+")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    fig, (ax_pow, ax_snr) = plt.subplots(2, 1, figsize=(9, 9), sharex=True)

    for path in args.csv_files:
        d = load_csv(path)
        label = f"{d['freq']} MHz" if d["freq"] else Path(path).stem
        ax_pow.plot(d["gain"], d["signal"], marker="o", markersize=3, linewidth=1,
                    label=f"{label} signal")
        ax_pow.plot(d["gain"], d["noise"], marker="x", markersize=3, linewidth=1,
                    linestyle="--", label=f"{label} noise floor")
        ax_snr.plot(d["gain"], d["snr"], marker="o", markersize=3, linewidth=1, label=label)

    ax_pow.set_ylabel("Power (uncalibrated dB)")
    ax_pow.set_title("Signal peak vs. noise floor by Gain Index")
    ax_pow.grid(True, alpha=0.3)
    ax_pow.legend(fontsize=8)

    ax_snr.set_xlabel("Gain Index")
    ax_snr.set_ylabel("SNR (dB)")
    ax_snr.set_title("SNR (peak bin - median noise floor) vs Gain Index")
    ax_snr.grid(True, alpha=0.3)
    ax_snr.legend(fontsize=8)

    fig.tight_layout()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    print(f"Saved plot to {out_path}")


if __name__ == "__main__":
    main()

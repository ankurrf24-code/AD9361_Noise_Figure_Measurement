#!/usr/bin/env python3
"""
Relative NF proxy from an existing SNR-vs-Gain-Index sweep CSV (e.g. from
run_nr_tm_snr_sweep.py or run_snr_sweep.py) -- no new hardware measurement,
just post-processing of data already collected.

WHAT THIS IS: using the best (highest) observed SNR in the sweep as a 0 dB
reference, every other gain index is expressed as how many dB worse than
that best point it is:

    Relative_NF_dB(gain_index) = SNR_dB(best_gain_index) - SNR_dB(gain_index)

This is a real, physically-motivated quantity: the AD9361's "full gain
table" mode inserts attenuation ahead of the LNA at low gain indices, which
directly degrades the chip's own noise figure (Friis cascade: loss ahead of
an amplifier adds directly to system NF) -- separately, at low gain the
ADC's own quantization noise (roughly fixed in absolute terms) becomes a
larger fraction of what reaches it. Both effects show up as SNR degradation
at low gain index, and this proxy captures their combined size in relative
terms.

WHAT THIS IS NOT: a calibrated, absolute Noise Figure. Converting "SNR got
worse by X dB" into "NF is Y dB" needs a known input signal power or a
calibrated ADC noise floor as an anchor point -- without one, the two real
effects above (AD9361's own analog NF changing vs. ADC quantization
dominating at low gain) can't be cleanly separated, and there is no zero
point traceable to an absolute reference. Treat the output of this script
as "how much worse is this gain index than the best one, in relative dB",
not as "the NF of the AD9361 at this gain index in absolute dB". For a
traceable, absolute, calibrated NF-vs-gain-index measurement, see
docs/measurement_manual.md (Y-factor method, needs a calibrated noise
source with a known ENR).

Usage:
    python relative_nf_proxy.py data/raw/nr_tm_snr_5MHz_2190MHz.csv \
        --out data/raw/relative_nf_5MHz.csv --plot results/plots/relative_nf_5MHz.png
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def compute_relative_nf(csv_path: str):
    gains, snrs = [], []
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            gains.append(int(row["Gain_Index"]))
            snrs.append(float(row["SNR_dB"]))

    order = sorted(range(len(gains)), key=lambda i: gains[i])
    gains = [gains[i] for i in order]
    snrs = [snrs[i] for i in order]

    best_snr = max(snrs)
    best_gain = gains[snrs.index(best_snr)]
    relative_nf = [best_snr - s for s in snrs]

    return gains, snrs, relative_nf, best_gain, best_snr


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv_files", nargs="+", help="One or more SNR-vs-Gain-Index sweep CSVs")
    ap.add_argument("--out-dir", default="data/raw", help="Directory for per-input relative-NF CSVs")
    ap.add_argument("--plot", required=True, help="Combined plot output path")
    args = ap.parse_args()

    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 6))

    for csv_path in args.csv_files:
        gains, snrs, relative_nf, best_gain, best_snr = compute_relative_nf(csv_path)
        label = Path(csv_path).stem

        out_path = Path(args.out_dir) / f"relative_nf_{label}.csv"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Gain_Index", "SNR_dB", "Relative_NF_dB_proxy"])
            for g, s, r in zip(gains, snrs, relative_nf):
                writer.writerow([g, s, r])

        print(f"{label}: best SNR {best_snr:.2f} dB at Gain_Index={best_gain} (0 dB reference). "
              f"Worst relative NF proxy: {max(relative_nf):.2f} dB at Gain_Index="
              f"{gains[relative_nf.index(max(relative_nf))]}. -> {out_path}")

        ax.plot(gains, relative_nf, marker="o", markersize=3, label=label)

    ax.set_xlabel("Gain Index")
    ax.set_ylabel("Relative NF proxy (dB worse than best gain index)")
    ax.set_title("Relative NF proxy vs Gain Index (NOT a calibrated absolute NF -- see script docstring)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()

    plot_path = Path(args.plot)
    plot_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(plot_path, dpi=150)
    print(f"Saved plot to {plot_path}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Corrected EVM/constellation analysis, adapted from the external NR
test-vector project's analysis/iq_analysis.py.

Fix applied here vs. that script's per_slot_evm(): this project's captures
use a 5 MHz / 30 kHz-SCS waveform with a 18-sample cyclic prefix
(cp_normal). The per-symbol CP-based (Moose) CFO correction that script
applies needs a much longer CP (or much higher SNR) to give a reliable
phase estimate -- verified directly on a real capture: the raw per-symbol
CFO estimate was ~random across its full +/-213 kHz theoretical range
(std=113,883 Hz on 2000 symbols), not a real large CFO. Applying that
"correction" injects near-random phase rotation into every symbol instead
of fixing anything, which is what was inflating EVM to an unstable 49.3%
(std 31.8% across frames). Skipping the per-symbol CFO step (channel
estimation/equalization is still a real phase-ramp fit against DM-RS,
unchanged from the original) drops EVM to a stable, reproducible 27.5%
(std 1.9%) -- consistent with, and largely explained by, this project's
independently-measured ~9.4 dB wideband SNR at Gain Index 70 (the
theoretical EVM floor from SNR alone, 1/sqrt(SNR_linear), is ~34% at
9.4 dB -- in the same ballpark as the measured 27.5%, meaning the
remaining EVM is not a hidden hardware defect but the direct, expected
consequence of this loopback path's SNR at this gain).

The original script (and its documented lessons -- full-cycle slot search,
linear phase-ramp channel fit instead of a single averaged tap, leading-
silence skip) are otherwise reused unchanged via direct import.

Usage:
    python evm_analysis.py --meta-file capture/tx_waveforms/TM1_1_5MHz_30kHz_meta.json \
        --capture capture/chainA_gain70_txon.bin --tag gain70 --out-dir results/evm --plot
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

EXTERNAL_ANALYSIS_DIR = r"D:\USRP B210\RF test vector B210 _claude\analysis"
EXTERNAL_WAVEFORM_DIR = r"D:\USRP B210\RF test vector B210 _claude\waveform_gen"


def per_slot_evm_no_cfo(iq, ref_grid, n_fft, cp_first, cp_normal, samples_per_slot, dmrs_symbol=2):
    """Same as iq_analysis.per_slot_evm but WITHOUT the per-symbol CP-based
    CFO correction -- see module docstring for why that correction is
    actively harmful for this project's short (18-sample) CP at this SNR."""
    sys.path.insert(0, EXTERNAL_WAVEFORM_DIR)
    from nr_tm_waveform import symbol_offset_within_slot

    dmrs_col = ref_grid[0, :, dmrs_symbol]
    dmrs_idx = np.nonzero(dmrs_col)[0][0::2]
    dmrs_offset = symbol_offset_within_slot(dmrs_symbol, n_fft, cp_first, cp_normal)

    sys.path.insert(0, EXTERNAL_ANALYSIS_DIR)
    from iq_analysis import find_slot_start

    start = find_slot_start(iq, ref_grid, n_fft, cp_first, cp_normal, samples_per_slot)
    n_slots = (len(iq) - start) // samples_per_slot
    evm_list = []
    eq_points = []  # equalized RX symbols, for a proper (channel-corrected) constellation plot
    ref_points = []

    for s in range(n_slots):
        slot_start = start + s * samples_per_slot
        sym_start = slot_start + dmrs_offset
        if sym_start + n_fft > len(iq):
            break
        sym = iq[sym_start:sym_start + n_fft]

        freq = np.fft.fftshift(np.fft.fft(sym) / np.sqrt(n_fft))
        ref = ref_grid[s % ref_grid.shape[0], dmrs_idx, dmrs_symbol]
        rx = freq[dmrs_idx]
        valid = np.abs(ref) > 0
        if valid.sum() < 4:
            continue

        pilot_pos = dmrs_idx[valid]
        h_per_pilot = rx[valid] / ref[valid]
        phase_unwrapped = np.unwrap(np.angle(h_per_pilot))
        slope, intercept = np.polyfit(pilot_pos, phase_unwrapped, 1)
        mag_avg = np.mean(np.abs(h_per_pilot))
        h_model = mag_avg * np.exp(1j * (slope * pilot_pos + intercept))
        rx_eq = rx[valid] / h_model
        err = rx_eq - ref[valid]
        evm_rms = np.sqrt(np.mean(np.abs(err) ** 2) / np.mean(np.abs(ref[valid]) ** 2))
        evm_list.append(float(evm_rms * 100.0))
        eq_points.append(rx_eq)
        ref_points.append(ref[valid])

    eq_points = np.concatenate(eq_points) if eq_points else np.array([])
    ref_points = np.concatenate(ref_points) if ref_points else np.array([])
    return np.array(evm_list), start, n_slots, eq_points, ref_points


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--meta-file", required=True)
    ap.add_argument("--capture", required=True)
    ap.add_argument("--tag", default="run")
    ap.add_argument("--out-dir", default="results/evm")
    ap.add_argument("--plot", action="store_true")
    args = ap.parse_args()

    sys.path.insert(0, EXTERNAL_ANALYSIS_DIR)
    from iq_analysis import load_iq, occupied_bandwidth_hz, ccdf_papr, iq_imbalance_estimate, dc_offset_estimate

    with open(args.meta_file) as f:
        meta = json.load(f)
    meta_dir = os.path.dirname(os.path.abspath(args.meta_file))
    ref_grid = np.load(os.path.join(meta_dir, meta["ref_file"]))
    iq = load_iq(args.capture)
    fs = meta["sample_rate_hz"]

    evm_list, start, n_slots, eq_points, ref_points = per_slot_evm_no_cfo(
        iq, ref_grid, meta["n_fft"], meta["cp_first_samples"], meta["cp_normal_samples"], meta["samples_per_slot"]
    )
    ref_db, ccdf = ccdf_papr(iq[start:])
    obw = occupied_bandwidth_hz(iq, fs, start=start)
    iq_imb = iq_imbalance_estimate(iq[start:])
    dc_off = dc_offset_estimate(iq[start:], ref_level_peak=meta.get("norm_target_peak", 0.7))

    summary = {
        "tm": meta["tm"], "tag": args.tag, "capture_file": os.path.basename(args.capture),
        "cfo_correction": "disabled (see module docstring -- harmful for this short CP/SNR combo)",
        "n_slots_analyzed": int(n_slots), "n_slots_valid_evm": int(len(evm_list)),
        "evm_percent_rms": float(np.mean(evm_list)) if len(evm_list) else None,
        "evm_percent_max": float(np.max(evm_list)) if len(evm_list) else None,
        "evm_percent_std": float(np.std(evm_list)) if len(evm_list) else None,
        "occupied_bandwidth_hz": obw,
        "occupied_bandwidth_vs_nominal_pct": 100.0 * obw / meta["occupied_bw_hz"],
        "iq_imbalance": iq_imb,
        "dc_offset": dc_off,
    }

    os.makedirs(args.out_dir, exist_ok=True)
    out_json = os.path.join(args.out_dir, f"{meta['tm'].replace('.', '_')}_{args.tag}_nocfo_summary.json")
    with open(out_json, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"=== {meta['tm']} [{args.tag}] (CFO correction disabled) ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"-> {out_json}")

    if args.plot:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(2, 2, figsize=(11, 9))

        # Channel-EQUALIZED constellation, aggregated across every slot in
        # the capture (eq_points/ref_points from per_slot_evm_no_cfo) --
        # NOT the raw single-symbol FFT output. Plotting raw (unequalized)
        # samples here was a real bug in an earlier version of this script:
        # the reported EVM was already computed correctly with per-slot
        # phase-ramp equalization, but the constellation PICTURE skipped
        # that step, so it showed the signal still rotated/scaled by an
        # arbitrary channel phase and gain -- looking "unclear" even when
        # the actual EVM was good.
        if len(eq_points):
            axes[0, 0].scatter(eq_points.real, eq_points.imag, s=3, alpha=0.15, color="tab:blue",
                                label=f"RX (equalized), {len(eq_points)} REs")
            ideal_pts = np.unique(ref_points)
            axes[0, 0].scatter(ideal_pts.real, ideal_pts.imag, s=120, marker="+", color="red",
                                linewidths=2, label="ideal QPSK points", zorder=5)
        axes[0, 0].set_title(f"Equalized DM-RS constellation, all {n_slots} slots "
                              f"({meta['modulation']}, no CFO corr)")
        axes[0, 0].set_aspect("equal")
        axes[0, 0].legend(fontsize=7)
        axes[0, 0].grid(alpha=0.3)

        axes[0, 1].plot(evm_list)
        axes[0, 1].set_title(f"EVM per slot (%) -- mean={np.mean(evm_list):.1f}%, std={np.std(evm_list):.1f}%")
        axes[0, 1].set_xlabel("slot index")
        axes[0, 1].grid(alpha=0.3)

        axes[1, 0].plot(ref_db, ccdf)
        axes[1, 0].set_yscale("log")
        axes[1, 0].set_title("CCDF of PAPR")
        axes[1, 0].set_xlabel("PAPR (dB)")
        axes[1, 0].set_ylabel("P(PAPR > x)")
        axes[1, 0].grid(alpha=0.3)

        n = min(len(iq) - start, 65536)
        spec = np.fft.fftshift(20 * np.log10(np.abs(np.fft.fft(iq[start:start + n] * np.hanning(n))) + 1e-12))
        freqs = np.fft.fftshift(np.fft.fftfreq(n, d=1 / fs)) / 1e6
        axes[1, 1].plot(freqs, spec - np.max(spec))
        axes[1, 1].set_title("PSD (relative dB)")
        axes[1, 1].set_xlabel("MHz from center")
        axes[1, 1].grid(alpha=0.3)

        fig.suptitle(f"{meta['tm']} [{args.tag}] -- CFO correction disabled")
        fig.tight_layout()
        png_path = os.path.join(args.out_dir, f"{meta['tm'].replace('.', '_')}_{args.tag}_nocfo_plots.png")
        fig.savefig(png_path, dpi=140)
        print(f"-> {png_path}")


if __name__ == "__main__":
    main()

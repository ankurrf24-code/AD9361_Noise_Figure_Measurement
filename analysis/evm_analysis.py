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


def per_slot_evm_no_cfo(iq, ref_grid, n_fft, cp_first, cp_normal, samples_per_slot, dmrs_symbol=2,
                         full_slot_constellation=False, max_slots_for_plot=300):
    """Same as iq_analysis.per_slot_evm but WITHOUT the per-symbol CP-based
    CFO correction -- see module docstring for why that correction is
    actively harmful for this project's short (18-sample) CP at this SNR.

    EVM itself (evm_list) is still computed from DM-RS REs only, unchanged,
    for comparability with every EVM number already reported by this
    project. If full_slot_constellation=True, the SAME per-slot DM-RS-
    derived channel estimate (h_model) is additionally applied to every
    subcarrier of every OFDM symbol in the slot (not just the DM-RS
    symbol's pilot REs) and compared against the full known reference grid
    -- since this is a self-referenced test signal, the true value of every
    RE (pilot and data) is known, so this gives a much denser, more
    representative "spectrum-analyzer style" constellation (~1850 points/
    slot instead of ~66) without changing the reported EVM math at all.
    Capped at max_slots_for_plot slots purely to keep plotting fast."""
    sys.path.insert(0, EXTERNAL_WAVEFORM_DIR)
    from nr_tm_waveform import symbol_offset_within_slot
    import nr_tm_config as cfg

    dmrs_col = ref_grid[0, :, dmrs_symbol]
    dmrs_idx = np.nonzero(dmrs_col)[0][0::2]
    dmrs_offset = symbol_offset_within_slot(dmrs_symbol, n_fft, cp_first, cp_normal)
    all_sc_idx = np.nonzero(dmrs_col)[0]  # every allocated subcarrier (pilot + data)

    sys.path.insert(0, EXTERNAL_ANALYSIS_DIR)
    from iq_analysis import find_slot_start

    start = find_slot_start(iq, ref_grid, n_fft, cp_first, cp_normal, samples_per_slot)
    n_slots = (len(iq) - start) // samples_per_slot
    evm_list = []
    eq_points = []  # equalized RX symbols, for a proper (channel-corrected) constellation plot
    ref_points = []
    full_eq_points = []
    full_ref_points = []

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

        if full_slot_constellation and s < max_slots_for_plot:
            # Same channel model (assumed static across the ~0.5ms slot,
            # reasonable for a loopback/cable path with negligible
            # multipath), applied to every symbol's full subcarrier set.
            h_full = mag_avg * np.exp(1j * (slope * all_sc_idx + intercept))
            for l in range(cfg.SYMBOLS_PER_SLOT):
                sym_offset = symbol_offset_within_slot(l, n_fft, cp_first, cp_normal)
                s_start = slot_start + sym_offset
                if s_start + n_fft > len(iq):
                    continue
                sym_l = iq[s_start:s_start + n_fft]
                freq_l = np.fft.fftshift(np.fft.fft(sym_l) / np.sqrt(n_fft))
                ref_l = ref_grid[s % ref_grid.shape[0], all_sc_idx, l]
                rx_l = freq_l[all_sc_idx] / h_full
                v = np.abs(ref_l) > 0
                full_eq_points.append(rx_l[v])
                full_ref_points.append(ref_l[v])

    eq_points = np.concatenate(eq_points) if eq_points else np.array([])
    full_eq_points = np.concatenate(full_eq_points) if full_eq_points else np.array([])
    full_ref_points = np.concatenate(full_ref_points) if full_ref_points else np.array([])
    ref_points = np.concatenate(ref_points) if ref_points else np.array([])
    return np.array(evm_list), start, n_slots, eq_points, ref_points, full_eq_points, full_ref_points


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

    evm_list, start, n_slots, eq_points, ref_points, full_eq_points, full_ref_points = per_slot_evm_no_cfo(
        iq, ref_grid, meta["n_fft"], meta["cp_first_samples"], meta["cp_normal_samples"], meta["samples_per_slot"],
        full_slot_constellation=args.plot
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

        # Spectrum-analyzer-style constellation: EVERY resource element
        # (pilot + data, all 14 symbols/slot) equalized with the same
        # per-slot DM-RS-derived channel model, not just the sparse DM-RS
        # REs -- since this is a self-referenced test signal, the true
        # value of every RE is known, so this is legitimate (not something
        # possible with an unknown over-the-air signal). Rendered as a 2D
        # histogram ("persistence" style, like a real VSA) rather than a
        # scatter, since there are up to ~500K points -- a plain scatter at
        # that density is either too slow or just a solid blob; a density
        # plot is what shows the actual cluster structure clearly. Earlier
        # versions of this script plotted (a) raw, unequalized single-
        # symbol output, then (b) only the ~66 DM-RS REs/slot equalized --
        # both real, fixed limitations, not stylistic choices.
        plot_points = full_eq_points if len(full_eq_points) else eq_points
        plot_ref = full_ref_points if len(full_ref_points) else ref_points
        if len(plot_points):
            lim = 1.8
            axes[0, 0].hist2d(plot_points.real, plot_points.imag, bins=140,
                               range=[[-lim, lim], [-lim, lim]], cmap="turbo", cmin=1)
            theta = np.linspace(0, 2 * np.pi, 200)
            axes[0, 0].plot(np.cos(theta), np.sin(theta), color="white", linewidth=0.6, alpha=0.5)
            axes[0, 0].axhline(0, color="white", linewidth=0.5, alpha=0.4)
            axes[0, 0].axvline(0, color="white", linewidth=0.5, alpha=0.4)
            ideal_pts = np.unique(plot_ref)
            axes[0, 0].scatter(ideal_pts.real, ideal_pts.imag, s=90, marker="+", color="white",
                                linewidths=2, label="ideal QPSK points", zorder=5)
            axes[0, 0].set_xlim(-lim, lim)
            axes[0, 0].set_ylim(-lim, lim)
        axes[0, 0].set_title(f"Equalized constellation (all REs, all symbols), {n_slots} slots\n"
                              f"({meta['modulation']}, no CFO corr) -- {len(plot_points)} points")
        axes[0, 0].set_aspect("equal")
        axes[0, 0].set_facecolor("black")
        axes[0, 0].legend(fontsize=7, loc="upper right")

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

#!/usr/bin/env python3
"""
Load captured IQ .bin file(s) from flowgraphs/rx_chain_a_capture.py, plot
spectrum via FFT, compute SNR, and compare TX OFF vs TX ON at each gain
index captured.

Plain Python (numpy/matplotlib only) -- does not need GNU Radio, so this
runs under the normal project Python install, not radioconda.

Usage:
    python analyze_iq.py --capture-dir capture --bandwidth 20e6 \
        --gain-indices 10 70 --out results/tx_on_off_comparison.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


def load_iq_bin(path: Path) -> np.ndarray:
    """Read interleaved complex64 IQ as written by GNU Radio's file_sink
    (gr_complex = 2x float32 per sample, matching this project's .bin
    format)."""
    raw = np.fromfile(path, dtype=np.complex64)
    return raw


def wideband_snr(samples, samp_rate, occupied_bw_hz, fft_size=1024, num_avg=50, dc_guard_hz=50e3):
    window = np.hanning(fft_size)
    win_power_correction = np.sum(window ** 2) / fft_size
    usable_frames = len(samples) // fft_size
    n_avg = min(num_avg, usable_frames)
    if n_avg < 1:
        raise ValueError(f"Not enough samples ({len(samples)}) for one FFT frame of size {fft_size}")

    psd_acc = np.zeros(fft_size)
    for i in range(n_avg):
        frame = samples[i * fft_size:(i + 1) * fft_size] * window
        spectrum = np.fft.fftshift(np.fft.fft(frame))
        psd_acc += (np.abs(spectrum) ** 2) / (fft_size * win_power_correction)
    psd = psd_acc / n_avg
    psd_db = 10 * np.log10(psd + 1e-20)

    freqs = np.fft.fftshift(np.fft.fftfreq(fft_size, d=1.0 / samp_rate))
    bin_width_hz = samp_rate / fft_size
    dc_guard_bins = max(1, round(dc_guard_hz / bin_width_hz))
    center = fft_size // 2

    half_bw = occupied_bw_hz / 2.0
    inband_mask = np.abs(freqs) <= half_bw
    outband_mask = ~inband_mask
    dc_mask = np.zeros(fft_size, dtype=bool)
    dc_mask[center - dc_guard_bins:center + dc_guard_bins + 1] = True
    inband_mask &= ~dc_mask
    outband_mask &= ~dc_mask

    inband_db = 10 * np.log10(np.mean(psd[inband_mask]))
    outband_db = 10 * np.log10(np.mean(psd[outband_mask]))
    return inband_db, outband_db, inband_db - outband_db, freqs, psd_db


def bandwidth_to_occupied_bw(bandwidth_hz):
    # Must match flowgraphs/tx_chain_a.py's generator numerology.
    return {5e6: 3.96e6, 20e6: 18.36e6}[bandwidth_hz]


def bandwidth_to_sample_rate(bandwidth_hz):
    return {5e6: 7.68e6, 20e6: 30.72e6}[bandwidth_hz]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--capture-dir", default="capture")
    ap.add_argument("--bandwidth", type=float, default=20e6, choices=[5e6, 20e6])
    ap.add_argument("--gain-indices", type=int, nargs="+", default=[10, 70])
    ap.add_argument("--out", default="results/tx_on_off_comparison.png")
    args = ap.parse_args()

    import matplotlib.pyplot as plt

    samp_rate = bandwidth_to_sample_rate(args.bandwidth)
    occupied_bw = bandwidth_to_occupied_bw(args.bandwidth)

    fig, axes = plt.subplots(len(args.gain_indices), 1, figsize=(10, 5 * len(args.gain_indices)), squeeze=False)

    print(f"{'Gain Index':<12} {'TX State':<10} {'Inband (dB)':>12} {'Outband (dB)':>13} {'SNR (dB)':>10}")
    for row, gain_index in enumerate(args.gain_indices):
        ax = axes[row][0]
        for tx_state, color in [("off", "tab:orange"), ("on", "tab:blue")]:
            path = Path(args.capture_dir) / f"chainA_gain{gain_index}_tx{tx_state}.bin"
            if not path.exists():
                print(f"  (missing: {path}, skipping)")
                continue
            samples = load_iq_bin(path)
            ib, ob, snr, freqs, psd_db = wideband_snr(samples, samp_rate, occupied_bw)
            print(f"{gain_index:<12} {tx_state:<10} {ib:>12.2f} {ob:>13.2f} {snr:>10.2f}")
            ax.plot(freqs / 1e3, psd_db, color=color, linewidth=0.8,
                    label=f"TX {tx_state.upper()} (SNR={snr:.2f} dB)")

        ax.axvspan(-occupied_bw / 2 / 1e3, occupied_bw / 2 / 1e3, color="gray", alpha=0.1, label="occupied BW")
        ax.set_xlabel("Frequency offset (kHz)")
        ax.set_ylabel("Power (dB)")
        ax.set_title(f"Gain Index {gain_index}: TX OFF vs TX ON")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

    fig.tight_layout()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    print(f"\nSaved plot to {out_path}")


if __name__ == "__main__":
    main()

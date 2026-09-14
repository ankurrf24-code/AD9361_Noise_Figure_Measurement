#!/usr/bin/env python3
"""
Actual demodulated constellation from a captured TM1.1 IQ file: CP-based
symbol timing sync, per-symbol FFT, and extraction of the real allocated
subcarriers -- not the raw time-domain IQ plotted in detailed_analysis.py.

Why raw time samples never show a constellation, regardless of SNR: OFDM
time-domain samples are the IFFT sum of many subcarriers, which by the
Central Limit Theorem looks like complex Gaussian noise in time -- that's
also why OFDM has high PAPR. A recognizable QPSK constellation only exists
per-subcarrier, after removing the cyclic prefix and taking the FFT of each
symbol. This script does that.

No channel equalization is applied (would need a DM-RS-based channel
estimate), so expect the 4 QPSK clusters to appear rotated/scaled by an
unknown complex gain (RF frontend phase + loopback path gain) rather than
sitting exactly on the ideal +/-45 degree axes -- the 4-cluster shape
itself is the thing to look for, not their exact angular position.

Usage:
    python ofdm_demod_constellation.py capture/chainA_gain70_txon.bin \
        --bandwidth 5e6 --out results/detailed/ofdm_demod_gain70_txon.png
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

NR_TM_PROJECT_DIR = r"D:\USRP B210\RF test vector B210 _claude\waveform_gen"


def get_numerology(bandwidth_hz):
    sys.path.insert(0, NR_TM_PROJECT_DIR)
    import nr_tm_waveform as gen

    num = gen.pick_numerology(bandwidth_hz)
    return num["n_fft"], num["n_rb"], num["cp_normal"]


def find_symbol_sync(samples, n_fft, cp_len, search_range):
    """CP-based autocorrelation timing sync: the cyclic prefix repeats the
    last cp_len samples of the FFT window at its start, so correlating a
    window against the same window delayed by n_fft samples peaks at the
    true symbol boundary."""
    max_search = min(search_range, len(samples) - n_fft - cp_len)
    corr = np.zeros(max_search)
    for off in range(max_search):
        a = samples[off:off + cp_len]
        b = samples[off + n_fft:off + n_fft + cp_len]
        corr[off] = np.abs(np.vdot(b, a))
    return int(np.argmax(corr)), corr


def demod_symbols(samples, start_offset, n_fft, cp_len, n_symbols, n_rb):
    """Skip CP, FFT each symbol, extract the actual allocated subcarriers
    (same centered mapping as nr_tm_waveform.build_resource_grid)."""
    n_sc = n_rb * 12
    fft_start = (n_fft - n_sc) // 2
    period = n_fft + cp_len

    res_elements = []
    offset = start_offset
    for _ in range(n_symbols):
        if offset + cp_len + n_fft > len(samples):
            break
        symbol = samples[offset + cp_len: offset + cp_len + n_fft]
        freq = np.fft.fftshift(np.fft.fft(symbol)) / np.sqrt(n_fft)
        res_elements.append(freq[fft_start:fft_start + n_sc])
        offset += period

    return np.concatenate(res_elements) if res_elements else np.array([])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bin_file")
    ap.add_argument("--bandwidth", type=float, default=5e6, choices=[5e6, 20e6])
    ap.add_argument("--num-symbols", type=int, default=200)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    import matplotlib.pyplot as plt

    bin_path = Path(args.bin_file)
    samples = np.fromfile(bin_path, dtype=np.complex64)

    meta_path = bin_path.with_name(bin_path.stem + "_meta.json")
    meta = json.load(open(meta_path)) if meta_path.exists() else None

    n_fft, n_rb, cp_len = get_numerology(args.bandwidth)
    print(f"Numerology: N_FFT={n_fft} N_RB={n_rb} ({n_rb*12} subcarriers) cp_len={cp_len}")

    sync_offset, corr = find_symbol_sync(samples, n_fft, cp_len, search_range=n_fft + cp_len)
    peak_ratio = corr[sync_offset] / (np.mean(corr) + 1e-12)
    print(f"CP sync: offset={sync_offset}, peak/mean correlation ratio={peak_ratio:.2f} "
          f"({'looks like a real lock' if peak_ratio > 3 else 'WEAK lock -- results below may not be meaningful'})")

    res = demod_symbols(samples, sync_offset, n_fft, cp_len, args.num_symbols, n_rb)
    print(f"Demodulated {len(res)} resource elements from {args.num_symbols} OFDM symbols")

    fig, (ax_const, ax_corr) = plt.subplots(1, 2, figsize=(11, 5.5))

    mag = np.abs(res)
    norm = res / (np.mean(mag) + 1e-12)  # normalize so the 4 clusters sit near the unit circle regardless of channel gain
    ax_const.scatter(norm.real, norm.imag, s=4, alpha=0.3)
    theta = np.linspace(0, 2 * np.pi, 200)
    ax_const.plot(np.cos(theta), np.sin(theta), "k--", linewidth=0.5, alpha=0.4)
    ax_const.set_xlabel("I (normalized)")
    ax_const.set_ylabel("Q (normalized)")
    ax_const.set_title(f"Demodulated resource elements (QPSK expected)\n"
                        f"{len(res)} REs, no equalization applied -- rotation/scale is expected")
    ax_const.set_aspect("equal")
    ax_const.set_xlim(-2, 2)
    ax_const.set_ylim(-2, 2)
    ax_const.grid(True, alpha=0.3)

    ax_corr.plot(corr)
    ax_corr.axvline(sync_offset, color="red", linestyle="--", label=f"sync @ {sync_offset}")
    ax_corr.set_xlabel("Sample offset")
    ax_corr.set_ylabel("CP autocorrelation")
    ax_corr.set_title(f"Symbol timing sync (peak/mean ratio={peak_ratio:.2f})")
    ax_corr.legend(fontsize=8)
    ax_corr.grid(True, alpha=0.3)

    title = f"{bin_path.name}"
    if meta:
        title += f"  --  gain_index={meta['gain_index']}, TX={meta['tx_state']}"
    fig.suptitle(title, fontsize=9)
    fig.tight_layout()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    print(f"Saved to {out_path}")


if __name__ == "__main__":
    main()

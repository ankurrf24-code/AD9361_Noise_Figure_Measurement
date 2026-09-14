#!/usr/bin/env python3
"""
Detailed per-capture analysis of chainA_gain{N}_tx{on|off}.bin files:
power statistics, ADC headroom, PAPR, IQ scatter, time-domain view, and
spectrum -- beyond the basic spectrum/SNR summary in analyze_iq.py.

Loads the _meta.json sidecar written by flowgraphs/capture_chain_a.py (if
present) and displays the actual TX/RX chain settings used for that capture
directly on the figure -- older captures made before metadata was added
fall back to CLI-provided defaults, clearly labeled as assumed, not read.

Usage:
    python detailed_analysis.py --capture-dir capture --gain-indices 10 70 \
        --out-dir results/detailed
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def load_iq_bin(path: Path) -> np.ndarray:
    return np.fromfile(path, dtype=np.complex64)


def load_meta(bin_path: Path) -> dict | None:
    meta_path = bin_path.with_name(bin_path.stem + "_meta.json")
    if meta_path.exists():
        with open(meta_path) as f:
            return json.load(f)
    return None


def bandwidth_to_sample_rate(bandwidth_hz):
    return {5e6: 7.68e6, 20e6: 30.72e6}[bandwidth_hz]


DC_GUARD_HZ = 50e3  # AD9361 direct-conversion LO/DC leakage -- see this
# project's earlier investigation: this spike is a known chip
# characteristic, not receiver noise, and dominates naive spectrum plots
# if not excluded/marked.


def compute_spectrum(samples, samp_rate, fft_size=1024, num_avg=100):
    window = np.hanning(fft_size)
    win_power_correction = np.sum(window ** 2) / fft_size
    n_avg = min(num_avg, len(samples) // fft_size)
    psd_acc = np.zeros(fft_size)
    for i in range(n_avg):
        frame = samples[i * fft_size:(i + 1) * fft_size] * window
        spectrum = np.fft.fftshift(np.fft.fft(frame))
        psd_acc += (np.abs(spectrum) ** 2) / (fft_size * win_power_correction)
    psd_db = 10 * np.log10(psd_acc / n_avg + 1e-20)
    freqs = np.fft.fftshift(np.fft.fftfreq(fft_size, d=1.0 / samp_rate))
    return freqs, psd_db


def analyze_capture(samples: np.ndarray) -> dict:
    power = np.abs(samples) ** 2
    mean_power = np.mean(power)
    peak_power = np.max(power)
    mean_power_db = 10 * np.log10(mean_power + 1e-20)
    peak_power_db = 10 * np.log10(peak_power + 1e-20)
    papr_db = peak_power_db - mean_power_db
    adc_peak_frac = np.max(np.abs(samples))  # fraction of UHD's normalized fc32 full scale (1.0)
    return {
        "mean_power_db": mean_power_db,
        "peak_power_db": peak_power_db,
        "papr_db": papr_db,
        "adc_peak_frac": adc_peak_frac,
        "num_samples": len(samples),
    }


def settings_text(meta: dict | None, gain_index: int, tx_state: str, freq_hz: float,
                   samp_rate: float, tx_gain_db: float) -> str:
    if meta is not None:
        lines = [
            f"freq={meta['freq_hz']/1e6:.1f} MHz   samp_rate={meta['samp_rate_hz']/1e6:.2f} Msps   "
            f"chain={meta['chain']} (UHD ch {meta['uhd_channel']})",
            f"RX: gain_index={meta['gain_index']}  applied={meta['rx_gain_applied_db']:.1f} dB  "
            f"antenna={meta['rx_antenna']}",
        ]
        if meta["tx_state"] == "on":
            lines.append(f"TX: ON  gain={meta['tx_gain_db']:.1f} dB  antenna={meta['tx_antenna']}  "
                         f"{meta['tm']}  N_RB={meta['n_rb']}")
        else:
            lines.append("TX: OFF")
        return "\n".join(lines) + "  [from capture metadata]"
    else:
        tx_line = f"TX: ON (assumed)  gain={tx_gain_db:.1f} dB" if tx_state == "on" else "TX: OFF"
        return (f"freq={freq_hz/1e6:.1f} MHz (assumed)   samp_rate={samp_rate/1e6:.2f} Msps (assumed)\n"
                f"RX: gain_index={gain_index} (assumed)\n"
                f"{tx_line}  [NO metadata file found -- values are CLI defaults, not verified]")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--capture-dir", default="capture")
    ap.add_argument("--gain-indices", type=int, nargs="+", default=[10, 70])
    ap.add_argument("--bandwidth", type=float, default=5e6, choices=[5e6, 20e6])
    ap.add_argument("--freq", type=float, default=2190e6)
    ap.add_argument("--tx-gain", type=float, default=50.0)
    ap.add_argument("--out-dir", default="results/detailed")
    args = ap.parse_args()

    default_samp_rate = bandwidth_to_sample_rate(args.bandwidth)

    import matplotlib.pyplot as plt

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"{'File':<32} {'Mean Pwr(dB)':>13} {'Peak Pwr(dB)':>13} {'PAPR(dB)':>9} {'ADC Peak Frac':>14} {'Overload':>9}")

    for gain_index in args.gain_indices:
        for tx_state in ["off", "on"]:
            path = Path(args.capture_dir) / f"chainA_gain{gain_index}_tx{tx_state}.bin"
            if not path.exists():
                print(f"  (missing: {path})")
                continue
            samples = load_iq_bin(path)
            meta = load_meta(path)
            samp_rate = meta["samp_rate_hz"] if meta else default_samp_rate

            stats = analyze_capture(samples)
            overload = "YES" if stats["adc_peak_frac"] > 0.9 else "no"
            print(f"{path.name:<32} {stats['mean_power_db']:>13.2f} {stats['peak_power_db']:>13.2f} "
                  f"{stats['papr_db']:>9.2f} {stats['adc_peak_frac']:>14.4f} {overload:>9}"
                  f"{'' if meta else '  (no metadata found)'}")

            fig, (ax_const, ax_time, ax_spec) = plt.subplots(1, 3, figsize=(16, 5.5))

            # IQ scatter: this is raw wideband ADC IQ, NOT a demodulated
            # symbol constellation -- no timing/frequency sync or channel
            # equalization has been applied, so it will look like a noisy
            # cloud rather than distinct QPSK points even when a real
            # signal is present. A 2D histogram (hexbin) shows the actual
            # density distribution far more clearly than a scatter plot at
            # these sample counts, and is not misleadingly sparse-looking.
            n_show = min(20000, len(samples))
            idx = np.linspace(0, len(samples) - 1, n_show, dtype=int)
            lim = max(0.02, stats["adc_peak_frac"] * 1.1)
            hb = ax_const.hexbin(samples[idx].real, samples[idx].imag, gridsize=60,
                                  extent=[-lim, lim, -lim, lim], cmap="viridis", mincnt=1)
            fig.colorbar(hb, ax=ax_const, shrink=0.8, label="count")
            ax_const.set_xlabel("I")
            ax_const.set_ylabel("Q")
            ax_const.set_title(f"Raw IQ density (NOT a demod constellation)\ngain={gain_index}, TX {tx_state.upper()}")
            ax_const.set_aspect("equal")

            n_time = min(1000, len(samples))
            ax_time.plot(samples[:n_time].real, label="I", linewidth=0.7)
            ax_time.plot(samples[:n_time].imag, label="Q", linewidth=0.7)
            ax_time.set_xlabel("Sample index")
            ax_time.set_ylabel("Amplitude")
            ax_time.set_title(f"I/Q vs time: gain={gain_index}, TX {tx_state.upper()}")
            ax_time.legend(fontsize=8)
            ax_time.grid(True, alpha=0.3)

            freqs, psd_db = compute_spectrum(samples, samp_rate)
            dc_mask = np.abs(freqs) <= DC_GUARD_HZ
            ax_spec.plot(freqs[~dc_mask] / 1e3, psd_db[~dc_mask], linewidth=0.8, color="tab:blue")
            ax_spec.plot(freqs[dc_mask] / 1e3, psd_db[dc_mask], linewidth=0.8, color="tab:red",
                         label=f"DC/LO leakage (±{DC_GUARD_HZ/1e3:.0f} kHz, AD9361 artifact, not signal)")
            ax_spec.set_xlabel("Frequency offset (kHz)")
            ax_spec.set_ylabel("Power (dB)")
            ax_spec.set_title(f"Spectrum: gain={gain_index}, TX {tx_state.upper()}")
            ax_spec.legend(fontsize=7, loc="upper right")
            ax_spec.grid(True, alpha=0.3)

            fig.suptitle(settings_text(meta, gain_index, tx_state, args.freq, samp_rate, args.tx_gain),
                         fontsize=8, y=1.02, ha="center")
            fig.tight_layout()
            out_path = out_dir / f"detail_gain{gain_index}_tx{tx_state}.png"
            fig.savefig(out_path, dpi=130, bbox_inches="tight")
            plt.close(fig)

    print(f"\nSaved per-capture detail plots to {out_dir}")


if __name__ == "__main__":
    main()

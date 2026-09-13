#!/usr/bin/env python3
"""
Complete step-by-step SNR + IQ characterization vs Gain Index on the B210.

For each Gain Index this captures live IQ and reports, in one CSV row:

    SNR_dB          : strongest FFT bin vs median noise floor (see run_snr_sweep.py)
    RSSI_dB         : AD9361's own internal RSSI sensor readback (uhd get_rx_sensor
                      'rssi'). VERIFIED NOT TO BE LIVE in this manual-gain-control
                      configuration: holding RX gain fixed and varying real input
                      power by 50 dB (via TX gain) produced zero change in this
                      reading. Logged for completeness/record only -- see
                      docs/snr_iq_method.md for the full verification (including
                      the two tests that looked like confirmation before this one
                      overturned them). Do not treat this column as a live signal
                      indicator.
    ADC_Peak_Frac   : max |sample| observed in the capture, as a fraction of ADC
                      full scale (1.0 for UHD's normalized fc32 samples). This is
                      a software-computed stand-in for an "ADC peak/overload
                      detector" -- UHD's Python API does not expose the AD9361's
                      internal peak-detector or LNA-detector SPI registers
                      directly (no peek/poke interface at this level; see
                      docs/snr_iq_method.md).
    ADC_Overload    : True if ADC_Peak_Frac exceeds --overload-threshold.

It also saves an IQ diagnostic plot (constellation, I/Q vs time, and power
spectrum with signal/noise markers) at a configurable subset of gain indices
(default: 8 evenly spaced points) -- saving one per gain index for a full 77
point sweep would be excessive.

Two signal modes:
  - Ambient (default): listens to whatever's already at the antenna, like
    run_snr_sweep.py.
  - --tx-tone: also transmits a known CW tone through TX1 (channel 1, antenna
    TX/RX) for a controlled end-to-end test, like run_snr_sweep_loopback.py.

Usage:
    python snr_iq_sweep.py --freq 2190e6 --auto-gain --tx-tone \
        --out data/raw/snr_iq_2190MHz.csv --plot-dir results/plots/iq_2190MHz
"""

from __future__ import annotations

import argparse
import csv
import sys
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from run_nf_sweep import build_auto_gain_list, load_gain_table  # noqa: E402
from run_snr_sweep import capture_iq, spectrum_snr  # noqa: E402

CSV_FIELDS = [
    "Gain_Index",
    "RX_Gain_UHD_dB",
    "Freq_MHz",
    "Signal_Power_dB",
    "Noise_Floor_dB",
    "SNR_dB",
    "Peak_Bin_Offset_Hz",
    "RSSI_dB",
    "ADC_Peak_Frac",
    "ADC_Overload",
    "IQ_Plot_File",
]


def tx_thread_fn(usrp, tx_channel, freq, tx_gain, samp_rate, tone_offset_hz, stop_event):
    import uhd

    usrp.set_tx_rate(samp_rate, tx_channel)
    usrp.set_tx_freq(uhd.types.TuneRequest(freq), tx_channel)
    usrp.set_tx_antenna("TX/RX", tx_channel)
    usrp.set_tx_gain(tx_gain, tx_channel)

    st_args = uhd.usrp.StreamArgs("fc32", "sc16")
    st_args.channels = [tx_channel]
    tx_streamer = usrp.get_tx_stream(st_args)

    n = 4096
    t = np.arange(n) / samp_rate
    tone = (0.3 * np.exp(2j * np.pi * tone_offset_hz * t)).astype(np.complex64).reshape(1, -1)

    md = uhd.types.TXMetadata()
    md.start_of_burst = True
    md.end_of_burst = False
    while not stop_event.is_set():
        tx_streamer.send(tone, md)
        md.start_of_burst = False
    md.end_of_burst = True
    tx_streamer.send(np.zeros((1, 0), dtype=np.complex64), md)


def plot_iq_diagnostic(samples, samp_rate, fft_size, gain_index, applied_gain,
                        signal_db, noise_db, peak_offset_hz, out_path):
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))

    n_show = min(2000, len(samples))
    axes[0].scatter(samples[:n_show].real, samples[:n_show].imag, s=2, alpha=0.4)
    axes[0].set_xlabel("I")
    axes[0].set_ylabel("Q")
    axes[0].set_title(f"IQ constellation (Gain Index {gain_index}, {applied_gain:.0f} dB)")
    axes[0].set_aspect("equal")
    axes[0].grid(True, alpha=0.3)

    n_time = min(500, len(samples))
    t_us = np.arange(n_time) / samp_rate * 1e6
    axes[1].plot(t_us, samples[:n_time].real, label="I", linewidth=0.8)
    axes[1].plot(t_us, samples[:n_time].imag, label="Q", linewidth=0.8)
    axes[1].set_xlabel("Time (us)")
    axes[1].set_ylabel("Amplitude")
    axes[1].set_title("I/Q vs time")
    axes[1].legend(fontsize=8)
    axes[1].grid(True, alpha=0.3)

    window = np.hanning(fft_size)
    frame = samples[:fft_size] * window
    spectrum = np.fft.fftshift(np.fft.fft(frame))
    psd_db = 10 * np.log10(np.abs(spectrum) ** 2 / fft_size + 1e-20)
    freqs_khz = np.fft.fftshift(np.fft.fftfreq(fft_size, d=1.0 / samp_rate)) / 1e3
    axes[2].plot(freqs_khz, psd_db, linewidth=0.8)
    axes[2].axhline(noise_db, color="gray", linestyle="--", linewidth=0.8, label=f"noise floor {noise_db:.1f} dB")
    axes[2].axvline(peak_offset_hz / 1e3, color="tab:red", linestyle=":", linewidth=0.8,
                     label=f"peak {peak_offset_hz/1e3:+.1f} kHz, {signal_db:.1f} dB")
    axes[2].set_xlabel("Frequency offset (kHz)")
    axes[2].set_ylabel("Power (dB)")
    axes[2].set_title(f"Spectrum, SNR={signal_db-noise_db:.1f} dB")
    axes[2].legend(fontsize=8)
    axes[2].grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--freq", type=float, required=True)
    gain_group = ap.add_mutually_exclusive_group(required=True)
    gain_group.add_argument("--auto-gain", action="store_true")
    gain_group.add_argument("--gain-table", type=str)
    ap.add_argument("--gain-step-db", type=float, default=None)
    ap.add_argument("--channel", type=int, default=1, choices=[0, 1])
    ap.add_argument("--antenna", type=str, default="RX2", choices=["RX2", "TX/RX"])
    ap.add_argument("--tx-tone", action="store_true",
                     help="Also transmit a known CW tone on TX1 for a controlled test")
    ap.add_argument("--tx-channel", type=int, default=1, choices=[0, 1])
    ap.add_argument("--tx-gain", type=float, default=40.0)
    ap.add_argument("--tone-offset-hz", type=float, default=200e3)
    ap.add_argument("--samp-rate", type=float, default=2e6)
    ap.add_argument("--fft-size", type=int, default=4096)
    ap.add_argument("--num-avg", type=int, default=50)
    ap.add_argument("--dc-guard-hz", type=float, default=50e3)
    ap.add_argument("--overload-threshold", type=float, default=0.9,
                     help="ADC_Peak_Frac above this is flagged as ADC_Overload")
    ap.add_argument("--settle-s", type=float, default=0.15)
    ap.add_argument("--out", type=str, required=True)
    ap.add_argument("--plot-dir", type=str, default=None,
                     help="Directory for per-gain-index IQ diagnostic plots")
    ap.add_argument("--num-plots", type=int, default=8,
                     help="Number of evenly-spaced gain indices to save IQ plots for")
    args = ap.parse_args()

    import uhd

    usrp = uhd.usrp.MultiUSRP()

    stop_event = threading.Event()
    tx_thread = None
    if args.tx_tone:
        tx_thread = threading.Thread(
            target=tx_thread_fn,
            args=(usrp, args.tx_channel, args.freq, args.tx_gain, args.samp_rate,
                  args.tone_offset_hz, stop_event),
            daemon=True,
        )
        tx_thread.start()
        time.sleep(0.5)

    usrp.set_rx_rate(args.samp_rate, args.channel)
    usrp.set_rx_freq(uhd.types.TuneRequest(args.freq), args.channel)
    usrp.set_rx_antenna(args.antenna, args.channel)
    usrp.set_rx_agc(False, args.channel)

    if args.gain_table:
        gain_table = load_gain_table(args.gain_table)
    else:
        gain_table = build_auto_gain_list(usrp, False, args.gain_step_db, args.channel)

    num_samps = args.fft_size * args.num_avg
    bin_width_hz = args.samp_rate / args.fft_size
    dc_guard_bins = max(1, round(args.dc_guard_hz / bin_width_hz))

    plot_indices = set()
    plot_dir = None
    if args.plot_dir:
        plot_dir = Path(args.plot_dir)
        plot_dir.mkdir(parents=True, exist_ok=True)
        n = len(gain_table)
        step = max(1, n // args.num_plots)
        plot_indices = set(i for i in range(0, n, step))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()

        for row_num, (gain_index, requested_gain_db) in enumerate(gain_table):
            usrp.set_rx_gain(requested_gain_db, args.channel)
            time.sleep(args.settle_s)
            applied_gain = usrp.get_rx_gain(args.channel)
            samples = capture_iq(usrp, num_samps, args.channel)

            signal_db, noise_db, peak_offset_hz = spectrum_snr(
                samples, args.samp_rate, args.fft_size, args.num_avg, dc_guard_bins
            )
            snr_db = signal_db - noise_db

            rssi_db = usrp.get_rx_sensor("rssi", args.channel).to_real()

            adc_peak_frac = float(np.max(np.abs(samples)))
            adc_overload = adc_peak_frac > args.overload_threshold

            plot_file = ""
            if plot_dir is not None and row_num in plot_indices:
                plot_file = str(plot_dir / f"gain_{gain_index:02d}.png")
                plot_iq_diagnostic(samples, args.samp_rate, args.fft_size, gain_index,
                                    applied_gain, signal_db, noise_db, peak_offset_hz, plot_file)

            print(f"[Gain_Index={gain_index}] applied={applied_gain:.2f} dB "
                  f"SNR={snr_db:6.2f} dB RSSI={rssi_db:8.2f} dB "
                  f"ADC_peak={adc_peak_frac:.3f}{' OVERLOAD' if adc_overload else ''}"
                  f"{' [plotted]' if plot_file else ''}")

            writer.writerow({
                "Gain_Index": gain_index,
                "RX_Gain_UHD_dB": applied_gain,
                "Freq_MHz": args.freq / 1e6,
                "Signal_Power_dB": signal_db,
                "Noise_Floor_dB": noise_db,
                "SNR_dB": snr_db,
                "Peak_Bin_Offset_Hz": peak_offset_hz,
                "RSSI_dB": rssi_db,
                "ADC_Peak_Frac": adc_peak_frac,
                "ADC_Overload": adc_overload,
                "IQ_Plot_File": plot_file,
            })
            f.flush()

    if tx_thread is not None:
        stop_event.set()
        tx_thread.join(timeout=2)

    print(f"Done. Results written to {out_path}")


if __name__ == "__main__":
    main()

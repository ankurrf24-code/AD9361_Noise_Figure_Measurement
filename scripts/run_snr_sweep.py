#!/usr/bin/env python3
"""
Sweep RX gain on a USRP B210 and estimate SNR from the captured IQ spectrum
at each gain index.

Unlike run_nf_sweep.py, this does NOT compute a calibrated Noise Figure --
it needs no ENR, no noise-source cycling, and no absolute power calibration.
It captures IQ at each gain, takes an FFT, and reports:

    Signal_Power_dB : the strongest spectral bin (outside a DC guard band)
    Noise_Floor_dB  : the median power of all other bins
    SNR_dB          : Signal_Power_dB - Noise_Floor_dB

This is a relative, in-band measurement -- it answers "how does the ratio
between whatever signal is present and the noise floor change as gain
changes", using whatever is actually connected to the RX antenna right now.
It is not a traceable NF measurement (see run_nf_sweep.py / docs/ for that).

Requires: UHD Python API (`import uhd`), numpy.

Usage:
    python run_snr_sweep.py --freq 920e6 --auto-gain --antenna RX2 \
        --out data/raw/snr_920MHz.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from run_nf_sweep import build_auto_gain_list, load_gain_table  # noqa: E402

CSV_FIELDS = [
    "Gain_Index",
    "RX_Gain_UHD_dB",
    "Freq_MHz",
    "Signal_Power_dB",
    "Noise_Floor_dB",
    "SNR_dB",
    "Peak_Bin_Offset_Hz",
]


def capture_iq(usrp, num_samps: int) -> np.ndarray:
    import uhd

    st_args = uhd.usrp.StreamArgs("fc32", "sc16")
    st_args.channels = [0]
    rx_streamer = usrp.get_rx_stream(st_args)

    buf = np.zeros(num_samps, dtype=np.complex64)
    stream_cmd = uhd.types.StreamCMD(uhd.types.StreamMode.num_done)
    stream_cmd.num_samps = num_samps
    stream_cmd.stream_now = True
    rx_streamer.issue_stream_cmd(stream_cmd)

    md = uhd.types.RXMetadata()
    recv_buffer = np.zeros((1, rx_streamer.get_max_num_samps()), dtype=np.complex64)
    total = 0
    while total < num_samps:
        n = rx_streamer.recv(recv_buffer, md)
        if md.error_code != uhd.types.RXMetadataErrorCode.none:
            raise RuntimeError(f"UHD RX error: {md.error_code}")
        chunk = min(n, num_samps - total)
        buf[total:total + chunk] = recv_buffer[0, :chunk]
        total += chunk
    return buf


def spectrum_snr(
    samples: np.ndarray,
    samp_rate: float,
    fft_size: int,
    num_avg: int,
    dc_guard_bins: int,
) -> tuple[float, float, float]:
    """
    Average `num_avg` Hann-windowed FFT frames of `fft_size`, then find the
    strongest bin outside a DC guard band vs. the median of the rest.
    Returns (signal_dB, noise_floor_dB, peak_bin_offset_hz).
    """
    window = np.hanning(fft_size)
    win_power_correction = np.sum(window ** 2) / fft_size

    usable_frames = len(samples) // fft_size
    n_avg = min(num_avg, usable_frames)
    if n_avg < 1:
        raise ValueError(
            f"Not enough samples ({len(samples)}) for one FFT frame of size {fft_size}"
        )

    psd_acc = np.zeros(fft_size)
    for i in range(n_avg):
        frame = samples[i * fft_size:(i + 1) * fft_size] * window
        spectrum = np.fft.fftshift(np.fft.fft(frame))
        psd_acc += (np.abs(spectrum) ** 2) / (fft_size * win_power_correction)
    psd = psd_acc / n_avg

    freqs = np.fft.fftshift(np.fft.fftfreq(fft_size, d=1.0 / samp_rate))

    center = fft_size // 2
    guard_lo, guard_hi = center - dc_guard_bins, center + dc_guard_bins + 1
    mask = np.ones(fft_size, dtype=bool)
    mask[guard_lo:guard_hi] = False

    noise_floor_lin = np.median(psd[mask])
    peak_idx_masked = np.argmax(psd[mask])
    peak_idx = np.arange(fft_size)[mask][peak_idx_masked]
    signal_lin = psd[peak_idx]

    signal_db = 10 * np.log10(signal_lin)
    noise_floor_db = 10 * np.log10(noise_floor_lin)
    peak_offset_hz = freqs[peak_idx]
    return signal_db, noise_floor_db, peak_offset_hz


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--freq", type=float, required=True, help="Center frequency in Hz")
    gain_group = ap.add_mutually_exclusive_group(required=True)
    gain_group.add_argument("--auto-gain", action="store_true",
                             help="Sweep the device's own reported gain range/step")
    gain_group.add_argument("--gain-table", type=str,
                             help="Static Gain_Index -> Total_Gain_dB CSV")
    ap.add_argument("--gain-step-db", type=float, default=None)
    ap.add_argument("--antenna", type=str, default="RX2", choices=["RX2", "TX/RX"])
    ap.add_argument("--samp-rate", type=float, default=2e6)
    ap.add_argument("--fft-size", type=int, default=4096)
    ap.add_argument("--num-avg", type=int, default=50,
                     help="Number of FFT frames averaged per gain point")
    ap.add_argument("--dc-guard-bins", type=int, default=5,
                     help="Bins excluded around DC (AD9361 direct-conversion LO leakage)")
    ap.add_argument("--settle-s", type=float, default=0.1)
    ap.add_argument("--out", type=str, required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    usrp = None
    if not args.dry_run:
        import uhd
        usrp = uhd.usrp.MultiUSRP()
        usrp.set_rx_rate(args.samp_rate)
        usrp.set_rx_freq(uhd.types.TuneRequest(args.freq))
        usrp.set_rx_antenna(args.antenna)
        usrp.set_rx_agc(False)

    if args.gain_table:
        gain_table = load_gain_table(args.gain_table)
    else:
        gain_table = build_auto_gain_list(usrp, args.dry_run, args.gain_step_db)

    num_samps = args.fft_size * args.num_avg

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()

        for gain_index, requested_gain_db in gain_table:
            if args.dry_run:
                applied_gain = requested_gain_db
                rng = np.random.default_rng(gain_index)
                samples = (rng.standard_normal(num_samps) + 1j * rng.standard_normal(num_samps)).astype(np.complex64)
            else:
                usrp.set_rx_gain(requested_gain_db)
                time.sleep(args.settle_s)
                applied_gain = usrp.get_rx_gain()
                samples = capture_iq(usrp, num_samps)

            signal_db, noise_db, peak_offset_hz = spectrum_snr(
                samples, args.samp_rate, args.fft_size, args.num_avg, args.dc_guard_bins
            )
            snr_db = signal_db - noise_db

            print(f"[Gain_Index={gain_index}] applied={applied_gain:.2f} dB "
                  f"signal={signal_db:.2f} dB noise_floor={noise_db:.2f} dB "
                  f"SNR={snr_db:.2f} dB (peak @ {peak_offset_hz/1e3:+.1f} kHz)")

            writer.writerow({
                "Gain_Index": gain_index,
                "RX_Gain_UHD_dB": applied_gain,
                "Freq_MHz": args.freq / 1e6,
                "Signal_Power_dB": signal_db,
                "Noise_Floor_dB": noise_db,
                "SNR_dB": snr_db,
                "Peak_Bin_Offset_Hz": peak_offset_hz,
            })
            f.flush()

    print(f"Done. Results written to {out_path}")


if __name__ == "__main__":
    main()

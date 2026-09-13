#!/usr/bin/env python3
"""
Full Gain Index (0-76) sweep with a real NR-like CP-OFDM test waveform
(see nr_waveform.py) transmitted through TX1 -> attenuator -> RX1, for a
given NR channel bandwidth (5 MHz or 20 MHz).

Unlike the CW-tone loopback (run_snr_sweep_loopback.py), the signal here is
spread across many subcarriers, so SNR is computed as the average in-band
power (over the known occupied bandwidth) minus the average out-of-band
noise floor power, not a single peak bin.

Usage:
    python run_nr_snr_sweep.py --channel-bw 5e6 --freq 2190e6 \
        --out data/raw/nr_snr_5MHz_2190MHz.csv
    python run_nr_snr_sweep.py --channel-bw 20e6 --freq 2190e6 \
        --out data/raw/nr_snr_20MHz_2190MHz.csv
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
from nr_waveform import generate_nr_waveform  # noqa: E402
from run_nf_sweep import build_auto_gain_list, load_gain_table  # noqa: E402

CSV_FIELDS = [
    "Gain_Index",
    "RX_Gain_UHD_dB",
    "Freq_MHz",
    "Channel_BW_MHz",
    "Inband_Power_dB",
    "Outband_Noise_dB",
    "SNR_dB",
]


def tx_loop(usrp, tx_channel, freq, tx_gain, waveform, stop_event):
    import uhd

    usrp.set_tx_rate(waveform.samp_rate, tx_channel)
    usrp.set_tx_freq(uhd.types.TuneRequest(freq), tx_channel)
    usrp.set_tx_antenna("TX/RX", tx_channel)
    usrp.set_tx_gain(tx_gain, tx_channel)

    st_args = uhd.usrp.StreamArgs("fc32", "sc16")
    st_args.channels = [tx_channel]
    tx_streamer = usrp.get_tx_stream(st_args)

    buf = waveform.samples.reshape(1, -1)
    md = uhd.types.TXMetadata()
    md.start_of_burst = True
    md.end_of_burst = False
    while not stop_event.is_set():
        tx_streamer.send(buf, md)
        md.start_of_burst = False
    md.end_of_burst = True
    tx_streamer.send(np.zeros((1, 0), dtype=np.complex64), md)


def capture_iq(usrp, num_samps, channel):
    import uhd

    st_args = uhd.usrp.StreamArgs("fc32", "sc16")
    st_args.channels = [channel]
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


def wideband_snr(samples, samp_rate, occupied_bw_hz, fft_size, num_avg, dc_guard_bins):
    """
    Average `num_avg` Hann-windowed FFT frames, then split bins into
    "in-band" (within occupied_bw_hz of center, excluding the DC guard) and
    "out-of-band" (outside occupied_bw_hz, within the capture's Nyquist
    window). Returns (inband_power_db, outband_noise_db, snr_db).
    """
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

    freqs = np.fft.fftshift(np.fft.fftfreq(fft_size, d=1.0 / samp_rate))
    half_bw = occupied_bw_hz / 2.0
    center = fft_size // 2

    inband_mask = np.abs(freqs) <= half_bw
    outband_mask = ~inband_mask
    guard_lo, guard_hi = center - dc_guard_bins, center + dc_guard_bins + 1
    dc_mask = np.zeros(fft_size, dtype=bool)
    dc_mask[guard_lo:guard_hi] = True
    inband_mask = inband_mask & ~dc_mask
    outband_mask = outband_mask & ~dc_mask

    inband_power = np.mean(psd[inband_mask])
    outband_power = np.mean(psd[outband_mask])

    inband_db = 10 * np.log10(inband_power)
    outband_db = 10 * np.log10(outband_power)
    return inband_db, outband_db, inband_db - outband_db


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--freq", type=float, required=True)
    ap.add_argument("--channel-bw", type=float, required=True, choices=[5e6, 20e6])
    ap.add_argument("--gain-step-db", type=float, default=None)
    ap.add_argument("--channel", type=int, default=1, choices=[0, 1])
    ap.add_argument("--tx-channel", type=int, default=1, choices=[0, 1])
    ap.add_argument("--tx-gain", type=float, default=50.0)
    ap.add_argument("--fft-size", type=int, default=1024)
    ap.add_argument("--num-avg", type=int, default=50)
    ap.add_argument("--dc-guard-hz", type=float, default=50e3)
    ap.add_argument("--settle-s", type=float, default=0.15)
    ap.add_argument("--out", type=str, required=True)
    args = ap.parse_args()

    import uhd

    waveform = generate_nr_waveform(args.channel_bw)
    print(f"NR waveform: {waveform.num_rbs} RBs, occupied BW "
          f"{waveform.occupied_bw_hz/1e6:.3f} MHz, samp_rate {waveform.samp_rate/1e6:.2f} Msps")

    usrp = uhd.usrp.MultiUSRP()

    stop_event = threading.Event()
    tx_thread = threading.Thread(
        target=tx_loop,
        args=(usrp, args.tx_channel, args.freq, args.tx_gain, waveform, stop_event),
        daemon=True,
    )
    tx_thread.start()
    time.sleep(0.5)

    usrp.set_rx_rate(waveform.samp_rate, args.channel)
    usrp.set_rx_freq(uhd.types.TuneRequest(args.freq), args.channel)
    usrp.set_rx_antenna("RX2", args.channel)
    usrp.set_rx_agc(False, args.channel)

    gain_table = build_auto_gain_list(usrp, False, args.gain_step_db, args.channel)

    num_samps = args.fft_size * args.num_avg
    bin_width_hz = waveform.samp_rate / args.fft_size
    dc_guard_bins = max(1, round(args.dc_guard_hz / bin_width_hz))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()

        for gain_index, requested_gain_db in gain_table:
            usrp.set_rx_gain(requested_gain_db, args.channel)
            time.sleep(args.settle_s)
            applied_gain = usrp.get_rx_gain(args.channel)
            samples = capture_iq(usrp, num_samps, args.channel)

            inband_db, outband_db, snr_db = wideband_snr(
                samples, waveform.samp_rate, waveform.occupied_bw_hz,
                args.fft_size, args.num_avg, dc_guard_bins
            )

            print(f"[Gain_Index={gain_index}] applied={applied_gain:.2f} dB "
                  f"inband={inband_db:.2f} dB outband={outband_db:.2f} dB SNR={snr_db:.2f} dB")

            writer.writerow({
                "Gain_Index": gain_index,
                "RX_Gain_UHD_dB": applied_gain,
                "Freq_MHz": args.freq / 1e6,
                "Channel_BW_MHz": args.channel_bw / 1e6,
                "Inband_Power_dB": inband_db,
                "Outband_Noise_dB": outband_db,
                "SNR_dB": snr_db,
            })
            f.flush()

    stop_event.set()
    tx_thread.join(timeout=2)
    print(f"Done. Results written to {out_path}")


if __name__ == "__main__":
    main()

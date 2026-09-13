#!/usr/bin/env python3
"""
Full Gain Index sweep with a known TX-generated CW tone looped back through
TX1 -> attenuator -> RX1, instead of relying on an ambient environmental
signal (see run_snr_sweep.py for that). This gives a controlled, known
signal to validate the whole chain (TX, attenuator, RX channel, gain
control, FFT/SNR computation) end-to-end.

Channel: uses UHD channel 1 (subdev FE-TX1/FE-RX1) by default, confirmed via
tx_tone_probe.py to be this project's physical TX1/RX1 port pair -- channel 0
(FE-TX2/FE-RX2) is a different, unrelated port pair.

Usage:
    python run_snr_sweep_loopback.py --freq 2190e6 --auto-gain \
        --out data/raw/snr_loopback_2190MHz.csv
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
    "Locked",
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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--freq", type=float, required=True)
    gain_group = ap.add_mutually_exclusive_group(required=True)
    gain_group.add_argument("--auto-gain", action="store_true")
    gain_group.add_argument("--gain-table", type=str)
    ap.add_argument("--gain-step-db", type=float, default=None)
    ap.add_argument("--tx-channel", type=int, default=1, choices=[0, 1])
    ap.add_argument("--rx-channel", type=int, default=1, choices=[0, 1])
    ap.add_argument("--tx-gain", type=float, default=40.0)
    ap.add_argument("--tone-offset-hz", type=float, default=200e3)
    ap.add_argument("--samp-rate", type=float, default=2e6)
    ap.add_argument("--fft-size", type=int, default=4096)
    ap.add_argument("--num-avg", type=int, default=50)
    ap.add_argument("--dc-guard-hz", type=float, default=50e3)
    ap.add_argument("--settle-s", type=float, default=0.1)
    ap.add_argument("--out", type=str, required=True)
    args = ap.parse_args()

    import uhd

    usrp = uhd.usrp.MultiUSRP()

    stop_event = threading.Event()
    tx_thread = threading.Thread(
        target=tx_thread_fn,
        args=(usrp, args.tx_channel, args.freq, args.tx_gain, args.samp_rate,
              args.tone_offset_hz, stop_event),
        daemon=True,
    )
    tx_thread.start()
    # See docs/nr_waveform_method.md: 0.5s isn't enough for the threaded TX
    # loop to clear its startup underrun transient (~1-1.5s), which caused
    # spuriously low/unstable SNR on early captures. 2.5s clears it.
    time.sleep(2.5)

    usrp.set_rx_rate(args.samp_rate, args.rx_channel)
    usrp.set_rx_freq(uhd.types.TuneRequest(args.freq), args.rx_channel)
    usrp.set_rx_antenna("RX2", args.rx_channel)
    usrp.set_rx_agc(False, args.rx_channel)

    if args.gain_table:
        gain_table = load_gain_table(args.gain_table)
    else:
        gain_table = build_auto_gain_list(usrp, False, args.gain_step_db, args.rx_channel)

    num_samps = args.fft_size * args.num_avg
    bin_width_hz = args.samp_rate / args.fft_size
    dc_guard_bins = max(1, round(args.dc_guard_hz / bin_width_hz))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()

        for gain_index, requested_gain_db in gain_table:
            usrp.set_rx_gain(requested_gain_db, args.rx_channel)
            time.sleep(args.settle_s)
            applied_gain = usrp.get_rx_gain(args.rx_channel)
            samples = capture_iq(usrp, num_samps, args.rx_channel)

            signal_db, noise_db, peak_offset_hz = spectrum_snr(
                samples, args.samp_rate, args.fft_size, args.num_avg, dc_guard_bins
            )
            snr_db = signal_db - noise_db
            locked = abs(peak_offset_hz - args.tone_offset_hz) < 5000

            print(f"[Gain_Index={gain_index}] applied={applied_gain:.2f} dB "
                  f"signal={signal_db:.2f} dB noise={noise_db:.2f} dB SNR={snr_db:.2f} dB "
                  f"offset={peak_offset_hz/1e3:+.1f} kHz {'LOCKED' if locked else ''}")

            writer.writerow({
                "Gain_Index": gain_index,
                "RX_Gain_UHD_dB": applied_gain,
                "Freq_MHz": args.freq / 1e6,
                "Signal_Power_dB": signal_db,
                "Noise_Floor_dB": noise_db,
                "SNR_dB": snr_db,
                "Peak_Bin_Offset_Hz": peak_offset_hz,
                "Locked": locked,
            })
            f.flush()

    stop_event.set()
    tx_thread.join(timeout=2)
    print(f"Done. Results written to {out_path}")


if __name__ == "__main__":
    main()

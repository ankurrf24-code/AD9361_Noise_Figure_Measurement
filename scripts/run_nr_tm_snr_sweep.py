#!/usr/bin/env python3
"""
Full Gain Index (0-76) SNR sweep using the proper 3GPP-style NR test-model
waveform generator from the separate B210 NR test-vector project
(D:\\USRP B210\\RF test vector B210 _claude\\waveform_gen\\nr_tm_waveform.py),
instead of this project's earlier simplified nr_waveform.py.

That generator implements TM1.1/TM2/TM3.1/TM3.2/TM3.3a with correct OFDM
numerology, DM-RS pilots (comb-2, TM1.1 is default QPSK), and CP timing per
TS 38.141's structural intent -- see its own nr_tm_config.py module
docstring for exactly what's simplified (no real channel coding, no
SS/PBCH, TM3.x power boosting approximated as uniform). It's a 30 kHz SCS
generator (built for n78 at 3.5 GHz); this script reuses it as-is at this
project's 920/2190 MHz frequencies by just retuning the LO -- the generator
itself is frequency-agnostic (produces baseband IQ only).

This script imports that generator's functions directly (it's pure NumPy,
no GNU Radio dependency for generation) and feeds the resulting IQ into
this project's own already-validated plain-UHD TX/RX loop -- it does not
use that other project's GNU Radio-based tx_b210.py/rx_capture flowgraphs.

Usage:
    python run_nr_tm_snr_sweep.py --freq 2190e6 --tm TM1.1 --bandwidth 5e6 \
        --out data/raw/nr_tm_snr_5MHz_2190MHz.csv
    python run_nr_tm_snr_sweep.py --freq 2190e6 --tm TM1.1 --bandwidth 20e6 \
        --out data/raw/nr_tm_snr_20MHz_2190MHz.csv
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
from run_nf_sweep import build_auto_gain_list  # noqa: E402
from run_nr_snr_sweep import capture_iq, wideband_snr  # noqa: E402

NR_TM_PROJECT_DIR = r"D:\USRP B210\RF test vector B210 _claude\waveform_gen"


def load_nr_tm_generator():
    sys.path.insert(0, NR_TM_PROJECT_DIR)
    import nr_tm_waveform as gen  # noqa
    import nr_tm_config as cfg  # noqa
    return gen, cfg


def build_tm_waveform(tm: str, bandwidth_hz: float, num_frames: int, seed: int):
    gen, cfg = load_nr_tm_generator()

    tm_table = cfg.TM_TABLE
    if tm not in tm_table:
        raise ValueError(f"Unknown TM '{tm}'. Choices: {list(tm_table)}")
    modulation = tm_table[tm]["modulation"]

    num = gen.pick_numerology(bandwidth_hz)
    n_fft, n_rb = num["n_fft"], num["n_rb"]

    rng = np.random.default_rng(seed)
    slots = []
    for _ in range(num_frames * cfg.SLOTS_PER_FRAME):
        grid, _ref_grid = gen.build_resource_grid(n_rb, n_fft, modulation, rng)
        slots.append(gen.ofdm_modulate_slot(grid, n_fft, num["cp_first"], num["cp_normal"]))

    iq = np.concatenate(slots).astype(np.complex64)
    peak = np.max(np.abs(iq))
    iq_norm = (iq / peak * 0.5).astype(np.complex64)  # headroom for B210 DAC, matches this project's tone/loopback scripts

    return iq_norm, num["sample_rate_hz"], num["occupied_bw_hz"], n_rb, n_fft


def tx_loop(usrp, tx_channel, freq, tx_gain, samples, samp_rate, stop_event):
    import uhd

    usrp.set_tx_rate(samp_rate, tx_channel)
    usrp.set_tx_freq(uhd.types.TuneRequest(freq), tx_channel)
    usrp.set_tx_antenna("TX/RX", tx_channel)
    usrp.set_tx_gain(tx_gain, tx_channel)

    st_args = uhd.usrp.StreamArgs("fc32", "sc16")
    st_args.channels = [tx_channel]
    tx_streamer = usrp.get_tx_stream(st_args)

    buf = samples.reshape(1, -1)
    md = uhd.types.TXMetadata()
    md.start_of_burst = True
    md.end_of_burst = False
    while not stop_event.is_set():
        tx_streamer.send(buf, md)
        md.start_of_burst = False
    md.end_of_burst = True
    tx_streamer.send(np.zeros((1, 0), dtype=np.complex64), md)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--freq", type=float, required=True)
    ap.add_argument("--tm", default="TM1.1")
    ap.add_argument("--bandwidth", type=float, required=True)
    ap.add_argument("--num-frames", type=int, default=2)
    ap.add_argument("--seed", type=int, default=1)
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

    samples, samp_rate, occupied_bw_hz, n_rb, n_fft = build_tm_waveform(
        args.tm, args.bandwidth, args.num_frames, args.seed
    )
    print(f"{args.tm} @ {args.bandwidth/1e6:.0f} MHz: N_RB={n_rb}, N_FFT={n_fft}, "
          f"samp_rate={samp_rate/1e6:.2f} Msps, occupied_bw={occupied_bw_hz/1e6:.3f} MHz, "
          f"{len(samples)} samples")

    usrp = uhd.usrp.MultiUSRP()

    stop_event = threading.Event()
    tx_thread = threading.Thread(
        target=tx_loop,
        args=(usrp, args.tx_channel, args.freq, args.tx_gain, samples, samp_rate, stop_event),
        daemon=True,
    )
    tx_thread.start()
    # 0.5s was not enough: the threaded TX loop underruns for its first
    # ~1-1.5s while finding a steady rhythm submitting buffers, and captures
    # taken during that window read spuriously low/unstable SNR (verified:
    # 15 repeated captures at fixed gain showed 6.8-10.4 dB for the first
    # ~6 captures, then a rock-steady ~10.2-10.4 dB afterward -- see
    # docs/nr_waveform_method.md). 2.5s clears this with margin.
    time.sleep(2.5)

    usrp.set_rx_rate(samp_rate, args.channel)
    usrp.set_rx_freq(uhd.types.TuneRequest(args.freq), args.channel)
    usrp.set_rx_antenna("RX2", args.channel)
    usrp.set_rx_agc(False, args.channel)

    gain_table = build_auto_gain_list(usrp, False, args.gain_step_db, args.channel)

    num_samps = args.fft_size * args.num_avg
    bin_width_hz = samp_rate / args.fft_size
    dc_guard_bins = max(1, round(args.dc_guard_hz / bin_width_hz))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "Gain_Index", "RX_Gain_UHD_dB", "Freq_MHz", "TM", "Channel_BW_MHz",
            "N_RB", "Inband_Power_dB", "Outband_Noise_dB", "SNR_dB",
        ])
        writer.writeheader()

        for gain_index, requested_gain_db in gain_table:
            usrp.set_rx_gain(requested_gain_db, args.channel)
            time.sleep(args.settle_s)
            applied_gain = usrp.get_rx_gain(args.channel)
            rx_samples = capture_iq(usrp, num_samps, args.channel)

            inband_db, outband_db, snr_db = wideband_snr(
                rx_samples, samp_rate, occupied_bw_hz, args.fft_size, args.num_avg, dc_guard_bins
            )

            print(f"[Gain_Index={gain_index}] applied={applied_gain:.2f} dB "
                  f"inband={inband_db:.2f} dB outband={outband_db:.2f} dB SNR={snr_db:.2f} dB")

            writer.writerow({
                "Gain_Index": gain_index,
                "RX_Gain_UHD_dB": applied_gain,
                "Freq_MHz": args.freq / 1e6,
                "TM": args.tm,
                "Channel_BW_MHz": args.bandwidth / 1e6,
                "N_RB": n_rb,
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

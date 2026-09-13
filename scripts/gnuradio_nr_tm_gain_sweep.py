#!/usr/bin/env python3
"""
GNU Radio flowgraph: transmit the proper NR-FR1-TM1.1 waveform (from the
external B210 NR test-vector project's generator) and sweep RX gain across
the full 0-76 range, computing wideband SNR at each point.

Unlike scripts/run_nr_tm_snr_sweep.py (plain UHD Python API), this uses
actual GNU Radio blocks (uhd.usrp_sink / uhd.usrp_source, blocks.vector_*)
in a single gr.top_block, per the explicit request to do this "in GNU
Radio". Must be run with radioconda's Python (which has GNU Radio + UHD
installed), not the plain pip-installed uhd used elsewhere in this project:

    C:\\Users\\ankur\\radioconda\\python.exe scripts\\gnuradio_nr_tm_gain_sweep.py \\
        --freq 2190e6 --bandwidth 5e6 --out data/raw/gr_nr_tm_snr_5MHz_2190MHz.csv

Channel: uses UHD channel 1 (confirmed via scripts/tx_tone_probe.py to be
this project's physical TX1/RX1 ports) -- NOT channel 0, which is what the
external project's own tx_b210.py/rx_capture_evm_ccdf.py hardcode for its
own (different) n78 setup. Those files were not modified; this is a
separate, self-contained flowgraph.

The flowgraph is started once; gain is changed live via
usrp_source.set_gain() between capture windows (no restart needed), which
is the GNU-Radio-idiomatic way to do a gain sweep.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import numpy as np

NR_TM_PROJECT_DIR = r"D:\USRP B210\RF test vector B210 _claude\waveform_gen"


def build_tm_waveform(tm: str, bandwidth_hz: float, num_frames: int, seed: int):
    sys.path.insert(0, NR_TM_PROJECT_DIR)
    import nr_tm_waveform as gen
    import nr_tm_config as cfg

    tm_table = cfg.TM_TABLE
    modulation = tm_table[tm]["modulation"]
    num = gen.pick_numerology(bandwidth_hz)
    n_fft, n_rb = num["n_fft"], num["n_rb"]

    rng = np.random.default_rng(seed)
    slots = []
    for _ in range(num_frames * cfg.SLOTS_PER_FRAME):
        grid, _ = gen.build_resource_grid(n_rb, n_fft, modulation, rng)
        slots.append(gen.ofdm_modulate_slot(grid, n_fft, num["cp_first"], num["cp_normal"]))

    iq = np.concatenate(slots).astype(np.complex64)
    peak = np.max(np.abs(iq))
    iq_norm = (iq / peak * 0.5).astype(np.complex64)
    return iq_norm, num["sample_rate_hz"], num["occupied_bw_hz"], n_rb, n_fft


def wideband_snr(samples, samp_rate, occupied_bw_hz, fft_size, num_avg, dc_guard_bins):
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
    inband_mask &= ~dc_mask
    outband_mask &= ~dc_mask

    inband_db = 10 * np.log10(np.mean(psd[inband_mask]))
    outband_db = 10 * np.log10(np.mean(psd[outband_mask]))
    return inband_db, outband_db, inband_db - outband_db


def build_flowgraph(tx_iq, samp_rate, freq, tx_gain, rx_gain, channel):
    from gnuradio import gr, blocks, uhd

    tb = gr.top_block()

    vector_source = blocks.vector_source_c(tx_iq.tolist(), repeat=True)
    usrp_sink = uhd.usrp_sink(
        ",".join([]),
        uhd.stream_args(cpu_format="fc32", channels=[channel]),
    )
    usrp_sink.set_samp_rate(samp_rate)
    usrp_sink.set_center_freq(freq, 0)
    usrp_sink.set_gain(tx_gain, 0)
    usrp_sink.set_antenna("TX/RX", 0)

    usrp_source = uhd.usrp_source(
        ",".join([]),
        uhd.stream_args(cpu_format="fc32", channels=[channel]),
    )
    usrp_source.set_samp_rate(samp_rate)
    usrp_source.set_center_freq(freq, 0)
    usrp_source.set_gain(rx_gain, 0)
    usrp_source.set_antenna("RX2", 0)

    vector_sink = blocks.vector_sink_c()

    tb.connect(vector_source, usrp_sink)
    tb.connect(usrp_source, vector_sink)

    print(f"TX: freq={usrp_sink.get_center_freq(0)/1e6:.1f} MHz gain={usrp_sink.get_gain(0):.1f} dB "
          f"antenna={usrp_sink.get_antenna(0)} samp_rate={usrp_sink.get_samp_rate()/1e6:.2f} Msps")
    print(f"RX: freq={usrp_source.get_center_freq(0)/1e6:.1f} MHz gain={usrp_source.get_gain(0):.1f} dB "
          f"antenna={usrp_source.get_antenna(0)} samp_rate={usrp_source.get_samp_rate()/1e6:.2f} Msps")

    return tb, usrp_source, vector_sink


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--freq", type=float, required=True)
    ap.add_argument("--bandwidth", type=float, required=True, choices=[5e6, 20e6])
    ap.add_argument("--tm", default="TM1.1")
    ap.add_argument("--num-frames", type=int, default=2)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--channel", type=int, default=1, choices=[0, 1])
    ap.add_argument("--tx-gain", type=float, default=50.0)
    ap.add_argument("--gain-min", type=int, default=0)
    ap.add_argument("--gain-max", type=int, default=76)
    ap.add_argument("--fft-size", type=int, default=1024)
    ap.add_argument("--num-avg", type=int, default=50)
    ap.add_argument("--dc-guard-hz", type=float, default=50e3)
    ap.add_argument("--settle-s", type=float, default=0.2)
    ap.add_argument("--capture-s", type=float, default=0.05)
    ap.add_argument("--out", type=str, required=True)
    args = ap.parse_args()

    tx_iq, samp_rate, occupied_bw_hz, n_rb, n_fft = build_tm_waveform(
        args.tm, args.bandwidth, args.num_frames, args.seed
    )
    print(f"{args.tm} @ {args.bandwidth/1e6:.0f} MHz: N_RB={n_rb}, N_FFT={n_fft}, "
          f"samp_rate={samp_rate/1e6:.2f} Msps, occupied_bw={occupied_bw_hz/1e6:.3f} MHz")

    tb, usrp_source, vector_sink = build_flowgraph(
        tx_iq, samp_rate, args.freq, args.tx_gain, args.gain_min, args.channel
    )

    bin_width_hz = samp_rate / args.fft_size
    dc_guard_bins = max(1, round(args.dc_guard_hz / bin_width_hz))
    min_samps_needed = args.fft_size * args.num_avg

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    tb.start()
    time.sleep(0.5)  # let TX ramp up before the first RX measurement

    try:
        with open(out_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "Gain_Index", "RX_Gain_UHD_dB", "Freq_MHz", "TM", "Channel_BW_MHz",
                "N_RB", "Inband_Power_dB", "Outband_Noise_dB", "SNR_dB",
            ])
            writer.writeheader()

            # Time for min_samps_needed samples to arrive at this sample rate,
            # not a fixed wall-clock constant -- at 30.72 Msps the same fixed
            # sleep used at 7.68 Msps collects ~4x more (and more variably
            # timed) data, which is what caused the 20 MHz timing bug.
            capture_s = max(args.capture_s, (min_samps_needed / samp_rate) * 1.5)

            for gain_index in range(args.gain_min, args.gain_max + 1):
                usrp_source.set_gain(float(gain_index), 0)
                time.sleep(args.settle_s)
                applied_gain = usrp_source.get_gain(0)

                # reset() clears the buffer, but there's no hard guarantee on
                # exactly when it takes effect relative to the flowgraph's
                # internal buffering (this was the root cause of the 20 MHz
                # discrepancy: reset()+sleep()+read() gave inconsistent,
                # sometimes hugely oversized captures at the higher sample
                # rate). Fix: don't trust the buffer's size or start -- always
                # discard everything except the newest min_samps_needed
                # samples, which are the ones most likely to postdate the
                # gain settling, regardless of exactly when reset() landed or
                # how much accumulated before/after it.
                vector_sink.reset()
                attempts = 0
                data = np.array([], dtype=np.complex64)
                while len(data) < min_samps_needed and attempts < 5:
                    time.sleep(capture_s)
                    data = np.array(vector_sink.data(), dtype=np.complex64)
                    attempts += 1
                if len(data) < min_samps_needed:
                    raise RuntimeError(
                        f"Gain_Index={gain_index}: only got {len(data)} samples after "
                        f"{attempts} attempts, need {min_samps_needed} -- flowgraph may "
                        f"have stalled (check for USB/underflow issues)."
                    )
                data = data[-min_samps_needed:]  # freshest samples only, see comment above

                inband_db, outband_db, snr_db = wideband_snr(
                    data, samp_rate, occupied_bw_hz, args.fft_size, args.num_avg, dc_guard_bins
                )

                print(f"[Gain_Index={gain_index}] applied={applied_gain:.2f} dB "
                      f"inband={inband_db:.2f} dB outband={outband_db:.2f} dB SNR={snr_db:.2f} dB "
                      f"(n={len(data)} samples)")

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
    finally:
        tb.stop()
        tb.wait()

    print(f"Done. Results written to {out_path}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
GNU Radio flowgraph: capture IQ on B210 Chain A (UHD channel 1) at a fixed
gain index, with TX either transmitting the G-FR1-A1-1 (NR-FR1-TM1.1)
waveform or not connected at all, in ONE process.

Why one process, not separate TX/RX scripts: the B210 is a single-session
USB device -- a second process trying to open it while the first still
holds it fails outright ("No devices found", not a busy/retry error). TX
and RX must be in the same UHD session for a live TX-on capture, so this
script builds whichever flowgraph (TX+RX, or RX-only) the requested
`--tx-state` needs, runs it once, and exits.

Run once per (gain index, TX state) combination you want, e.g.:

    C:\\Users\\ankur\\radioconda\\python.exe flowgraphs\\capture_chain_a.py --gain-index 10 --tx-state on
    C:\\Users\\ankur\\radioconda\\python.exe flowgraphs\\capture_chain_a.py --gain-index 10 --tx-state off
    C:\\Users\\ankur\\radioconda\\python.exe flowgraphs\\capture_chain_a.py --gain-index 70 --tx-state on
    C:\\Users\\ankur\\radioconda\\python.exe flowgraphs\\capture_chain_a.py --gain-index 70 --tx-state off

Output: capture/chainA_gain{N}_tx{on|off}.bin -- interleaved complex64,
consumed directly by analysis/analyze_iq.py.
"""

import argparse
import os
import sys
import time

if "UHD_IMAGES_DIR" not in os.environ:
    for _candidate in (r"C:\Program Files\UHD\share\uhd\images",):
        if os.path.isdir(_candidate):
            os.environ["UHD_IMAGES_DIR"] = _candidate
            break

NR_TM_PROJECT_DIR = r"D:\USRP B210\RF test vector B210 _claude\waveform_gen"

DEFAULT_FREQ_HZ = 2190e6
DEFAULT_BANDWIDTH_HZ = 5e6  # see docs/parameters.md: 20 MHz underflows
                            # heavily even TX-alone on this machine/UHD
                            # version -- a real USB throughput ceiling, not
                            # a bug. 5 MHz is the verified-stable default.
DEFAULT_TX_GAIN_DB = 50.0
DEFAULT_TM = "TM1.1"
DEFAULT_CHANNEL = 1  # Chain A
DEFAULT_DURATION_S = 1.0


def build_waveform(tm, bandwidth_hz, num_frames=4, seed=1):
    sys.path.insert(0, NR_TM_PROJECT_DIR)
    import numpy as np
    import nr_tm_waveform as gen
    import nr_tm_config as cfg

    modulation = cfg.TM_TABLE[tm]["modulation"]
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--freq", type=float, default=DEFAULT_FREQ_HZ)
    ap.add_argument("--bandwidth", type=float, default=DEFAULT_BANDWIDTH_HZ, choices=[5e6, 20e6])
    ap.add_argument("--gain-index", type=int, required=True, help="Manual RX gain index, 0-76")
    ap.add_argument("--tx-state", choices=["on", "off"], required=True)
    ap.add_argument("--tx-gain", type=float, default=DEFAULT_TX_GAIN_DB)
    ap.add_argument("--tm", default=DEFAULT_TM)
    ap.add_argument("--channel", type=int, default=DEFAULT_CHANNEL, choices=[0, 1])
    ap.add_argument("--duration", type=float, default=DEFAULT_DURATION_S)
    ap.add_argument("--num-frames", type=int, default=4)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out-dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "capture"))
    args = ap.parse_args()

    from gnuradio import gr, blocks, uhd

    tb = gr.top_block()

    if args.tx_state == "on":
        iq, samp_rate, occupied_bw, n_rb, n_fft = build_waveform(args.tm, args.bandwidth, args.num_frames, args.seed)
        print(f"[TX] {args.tm}: N_RB={n_rb} N_FFT={n_fft} samp_rate={samp_rate/1e6:.2f} Msps "
              f"occupied_bw={occupied_bw/1e6:.3f} MHz ({len(iq)} samples, looping)")
        vector_source = blocks.vector_source_c(iq.tolist(), repeat=True)
        usrp_sink = uhd.usrp_sink(",".join([]), uhd.stream_args(cpu_format="fc32", channels=[args.channel]))
        usrp_sink.set_samp_rate(samp_rate)
        usrp_sink.set_center_freq(args.freq, 0)
        usrp_sink.set_gain(args.tx_gain, 0)
        usrp_sink.set_antenna("TX/RX", 0)
        tb.connect(vector_source, usrp_sink)
        print(f"[TX] Chain A: freq={usrp_sink.get_center_freq(0)/1e6:.1f} MHz "
              f"gain={usrp_sink.get_gain(0):.1f} dB antenna={usrp_sink.get_antenna(0)}")
    else:
        samp_rate = {5e6: 7.68e6, 20e6: 30.72e6}[args.bandwidth]

    usrp_source = uhd.usrp_source(",".join([]), uhd.stream_args(cpu_format="fc32", channels=[args.channel]))
    usrp_source.set_samp_rate(samp_rate)
    usrp_source.set_center_freq(args.freq, 0)
    usrp_source.set_rx_agc(False, 0)
    usrp_source.set_gain(float(args.gain_index), 0)
    usrp_source.set_antenna("RX2", 0)

    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir, f"chainA_gain{args.gain_index}_tx{args.tx_state}.bin")
    file_sink = blocks.file_sink(gr.sizeof_gr_complex, out_path)
    file_sink.set_unbuffered(False)

    # skiphead discards a warm-up chunk before head starts counting the
    # samples we keep. TX (if present) needs time to clear its startup
    # underrun transient (see earlier investigation in this project's
    # history: ~1-1.5s); RX alone settles much faster, but use the same
    # generous warm-up for both cases for consistency.
    warmup_s = 2.5 if args.tx_state == "on" else 0.3
    warmup_samps = int(samp_rate * warmup_s)
    capture_samps = int(samp_rate * args.duration)
    skiphead = blocks.skiphead(gr.sizeof_gr_complex, warmup_samps)
    head = blocks.head(gr.sizeof_gr_complex, capture_samps)
    tb.connect(usrp_source, skiphead, head, file_sink)

    print(f"[RX] Chain A: freq={usrp_source.get_center_freq(0)/1e6:.1f} MHz "
          f"gain_index={args.gain_index} (applied={usrp_source.get_gain(0):.1f} dB) "
          f"antenna={usrp_source.get_antenna(0)} samp_rate={usrp_source.get_samp_rate()/1e6:.2f} Msps")
    print(f"[RX] TX state: {args.tx_state}. Discarding {warmup_samps} warm-up samples, "
          f"then capturing {capture_samps} ({args.duration:.2f}s) -> {out_path}")

    # tb.wait() would block forever when TX is connected: vector_source_c
    # with repeat=True runs indefinitely by design, so the flowgraph as a
    # whole never self-terminates just because the RX->head branch is done.
    # Poll head's output count instead and stop explicitly once it has
    # produced the samples we asked for.
    tb.start()
    timeout_s = warmup_s + args.duration + 10.0  # generous margin
    start_time = time.time()
    while head.nitems_read(0) < capture_samps:
        if time.time() - start_time > timeout_s:
            tb.stop()
            tb.wait()
            raise RuntimeError(
                f"Capture timed out after {timeout_s:.1f}s: only got "
                f"{head.nitems_read(0)}/{capture_samps} samples. Check for "
                "USB/underflow issues (see docs/parameters.md)."
            )
        time.sleep(0.05)
    tb.stop()
    tb.wait()

    print(f"[RX] Done. Wrote {out_path}")


if __name__ == "__main__":
    main()

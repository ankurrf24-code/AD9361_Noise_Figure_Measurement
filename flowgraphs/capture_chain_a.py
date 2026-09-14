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
import json
import os
import sys
import time
from datetime import datetime, timezone

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
DEFAULT_TX_GAIN_DB = 70.0  # see docs/parameters.md "TX gain fix": 50 dB gave
# only ~8-13 dB SNR (EVM 24-100%+ depending on RX gain); 70 dB gives ~22 dB
# SNR at RX Gain Index 60 and EVM=8.0% RMS, comfortably within QPSK spec,
# with ADC headroom still safe (peak frac 0.24 of full scale).
DEFAULT_TM = "TM1.1"
DEFAULT_CHANNEL = 1  # Chain A
DEFAULT_DURATION_S = 1.0


def generate_waveform_file(tm, bandwidth_hz, num_frames, seed, out_dir):
    """Generate (if not already present) the .iq.bin/_ref.npy/_meta.json
    triplet using the external project's own generate() function -- same
    format their analysis/iq_analysis.py expects, including the saved ideal
    reference grid needed for real EVM (which this project's earlier
    in-memory-only generation did not keep)."""
    sys.path.insert(0, NR_TM_PROJECT_DIR)
    import nr_tm_waveform as gen

    name = f"{tm.replace('.', '_')}_{int(bandwidth_hz/1e6)}MHz_30kHz"
    meta_path = os.path.join(out_dir, f"{name}_meta.json")
    if not os.path.exists(meta_path):
        gen.generate(tm, bandwidth_hz, num_frames, seed, out_dir)
    return meta_path


def load_waveform_file(meta_path):
    """Load the interleaved-float32 .iq.bin next to meta_path -- same format
    the external project's analysis/iq_analysis.py::load_iq() reads, so
    captures made from this file are directly analyzable with that script
    unmodified."""
    import numpy as np

    with open(meta_path) as f:
        meta = json.load(f)
    iq_path = os.path.join(os.path.dirname(meta_path), meta["iq_file"])
    raw = np.fromfile(iq_path, dtype=np.float32)
    iq = (raw[0::2] + 1j * raw[1::2]).astype(np.complex64)
    return iq, meta


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
        wf_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "capture", "tx_waveforms")
        os.makedirs(wf_dir, exist_ok=True)
        wf_meta_path = generate_waveform_file(args.tm, args.bandwidth, args.num_frames, args.seed, wf_dir)
        iq, wf_meta = load_waveform_file(wf_meta_path)
        samp_rate = wf_meta["sample_rate_hz"]
        occupied_bw, n_rb, n_fft = wf_meta["occupied_bw_hz"], wf_meta["n_rb"], wf_meta["n_fft"]
        print(f"[TX] {args.tm}: N_RB={n_rb} N_FFT={n_fft} samp_rate={samp_rate/1e6:.2f} Msps "
              f"occupied_bw={occupied_bw/1e6:.3f} MHz ({len(iq)} samples, looping) "
              f"-- loaded from {wf_meta_path}")
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
        occupied_bw = n_rb = n_fft = wf_meta_path = None

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

    meta = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "chain": "A",
        "uhd_channel": args.channel,
        "freq_hz": args.freq,
        "bandwidth_hz": args.bandwidth,
        "samp_rate_hz": samp_rate,
        "gain_index": args.gain_index,
        "rx_gain_applied_db": usrp_source.get_gain(0),
        "rx_antenna": usrp_source.get_antenna(0),
        "tx_state": args.tx_state,
        "tx_gain_db": args.tx_gain if args.tx_state == "on" else None,
        "tx_antenna": "TX/RX" if args.tx_state == "on" else None,
        "tm": args.tm if args.tx_state == "on" else None,
        "tx_waveform_meta_file": wf_meta_path if args.tx_state == "on" else None,
        "n_rb": n_rb,
        "occupied_bw_hz": occupied_bw,
        "warmup_s": warmup_s,
        "capture_duration_s": args.duration,
        "num_samples": capture_samps,
        "iq_format": "interleaved complex64 (GNU Radio gr_complex)",
        "bin_file": os.path.basename(out_path),
    }
    meta_path = out_path.replace(".bin", "_meta.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"[RX] Done. Wrote {out_path}")
    print(f"[RX] Wrote metadata {meta_path}")


if __name__ == "__main__":
    main()

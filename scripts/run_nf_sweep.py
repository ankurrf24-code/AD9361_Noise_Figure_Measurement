#!/usr/bin/env python3
"""
Automate a Y-factor NF sweep across the AD9361 gain table on a USRP B210.

Requires: UHD Python API (`import uhd`), numpy.

This script has NOT been run against real hardware in this environment (no
B210 / UHD install available here) -- validate on your bench before trusting
logged data. Review docs/measurement_manual.md before running.

Gain source: two modes are supported.

  --auto-gain (recommended): queries the connected B210's actual
      get_rx_gain_range() and sweeps it at the device's own reported step,
      logging the real applied gain from get_rx_gain() at every point. This
      avoids depending on a hand-transcribed AD9361 datasheet gain table --
      per ADI's own documentation (AD9361 Reference Manual UG-570 / Rev. F
      datasheet: "Gain Step 1 dB", "Gain Index = 76 (Maximum Setting)") the
      standard full gain table is only *nominally* 1 dB/step, and multiple
      users on ADI's EngineerZone forum report the reported gain flattening
      out above ~58 dB rather than continuing linearly to index 76 -- so the
      index-to-dB mapping is not safe to assume from the datasheet alone.
      Reading it back from the actual part in hand is both simpler and more
      correct for a measurement campaign.

  --gain-table <csv>: use a static Gain_Index -> Total_Gain_dB table (see
      docs/gain_tables/) if you have independently verified one (e.g. against
      UG-570's gain table appendix or a no-OS/Linux driver source) and want
      canonical AD9361 gain-index labeling rather than device-reported values.

Usage:
    python run_nf_sweep.py --freq 920e6 --auto-gain \
        --enr-source-db 15.2 --atten-db 30.15 --cable-db 1.05 \
        --out data/raw/nf_920MHz_2026-09-12.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from nf_yfactor import PathLoss, db_to_linear, enr_at_rx1, linear_to_db, noise_figure_db  # noqa: E402

CSV_FIELDS = [
    "Gain_Index",
    "Total_Gain_dB",
    "RX_Gain_UHD_dB",
    "Freq_MHz",
    "P_cold_dBm",
    "P_hot_dBm",
    "NF_dB",
]


def load_gain_table(path: str) -> list[tuple[int, float]]:
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            idx = int(r["Gain_Index"])
            raw = (r["Total_Gain_dB"] or "").strip()
            if raw == "":
                raise ValueError(
                    f"Gain table {path} has an empty Total_Gain_dB at "
                    f"Gain_Index={idx}. Populate the table from the AD9361 "
                    "reference manual before running the sweep -- see "
                    "docs/gain_tables/README.md."
                )
            rows.append((idx, float(raw)))
    rows.sort(key=lambda t: t[0])
    return rows


def build_auto_gain_list(
    usrp, dry_run: bool, step_override: float | None, channel: int = 0
) -> list[tuple[int, float]]:
    """
    Build the sweep list from the device's own reported gain range instead of
    a static datasheet table. See module docstring for why.
    """
    if dry_run or usrp is None:
        # No hardware to query in --dry-run: fall back to the AD9361
        # datasheet's *nominal* spec (0-76 dB, 1 dB/step, 77 points) purely to
        # exercise the CSV/plumbing. This is NOT a verified per-index table --
        # see module docstring. Real runs must not use this branch.
        return [(i, float(i)) for i in range(77)]

    gain_range = usrp.get_rx_gain_range(channel)
    start, stop = gain_range.start(), gain_range.stop()
    step = step_override if step_override else gain_range.step()
    if not step or step <= 0:
        step = 1.0

    values = []
    idx = 0
    g = start
    while g <= stop + 1e-9:
        values.append((idx, round(g, 3)))
        idx += 1
        g += step
    return values


def measure_power_dbm(samples: np.ndarray, dbm_offset: float) -> float:
    """
    Average power of a complex IQ capture, in raw dB relative to full scale,
    corrected by the per-gain dBm_offset from the absolute power calibration
    (docs/calibration_procedure.md section 6).
    """
    power_lin = np.mean(np.abs(samples) ** 2)
    if power_lin <= 0:
        raise ValueError("Captured all-zero samples; check RX path/gain settings.")
    raw_db = 10 * np.log10(power_lin)
    return raw_db + dbm_offset


def capture_power(usrp, duration_s: float, dbm_offset: float, channel: int = 0) -> float:
    """Capture `duration_s` seconds of IQ and return average power in dBm."""
    import uhd  # local import: only required when actually running on hardware

    st_args = uhd.usrp.StreamArgs("fc32", "sc16")
    st_args.channels = [channel]
    rx_streamer = usrp.get_rx_stream(st_args)

    num_samps = int(duration_s * usrp.get_rx_rate(channel))
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

    return measure_power_dbm(buf, dbm_offset)


def prompt_noise_source(state: str) -> None:
    """
    Manual noise-source control fallback. If your noise source has a GPIO or
    USB control line, replace this with a direct hardware call instead of a
    manual prompt (e.g. drive a UHD GPIO bank pin, or a USB-relay call).
    """
    input(f"--> Set noise source {state} and press Enter to continue...")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--freq", type=float, required=True, help="Center frequency in Hz")
    gain_group = ap.add_mutually_exclusive_group(required=True)
    gain_group.add_argument("--auto-gain", action="store_true",
                             help="Sweep the device's own reported gain range/step "
                                  "instead of a static table. Recommended -- see module docstring.")
    gain_group.add_argument("--gain-table", type=str,
                             help="Static Gain_Index -> Total_Gain_dB CSV (see docs/gain_tables/)")
    ap.add_argument("--gain-step-db", type=float, default=None,
                     help="Override the step size used with --auto-gain (default: device-reported step)")
    ap.add_argument("--enr-source-db", type=float, required=True,
                     help="Noise source ENR at this frequency, from its cal cert")
    ap.add_argument("--atten-db", type=float, default=0.0,
                     help="Measured attenuator loss in the noise-source path at this frequency. "
                          "Default 0 -- do NOT reuse a TX1-loopback protection pad value here; "
                          "see docs/calibration_procedure.md Section 0 for why that would crush "
                          "the ENR available at RX1. Only set this if your bench genuinely has a "
                          "pad between the noise source and RX1.")
    ap.add_argument("--cable-db", type=float, required=True,
                     help="Measured cable loss at this frequency")
    ap.add_argument("--dbm-offset", type=float, default=0.0,
                     help="Absolute power calibration offset (docs/calibration_procedure.md sec 6). "
                          "If 0, results are NOT calibrated to absolute dBm -- Y-factor ratio is "
                          "still valid since the offset cancels in P_hot - P_cold, but log a real "
                          "value if you want absolute power sanity checks.")
    ap.add_argument("--antenna", type=str, default="RX2", choices=["RX2", "TX/RX"],
                     help="Antenna to receive on (default: RX2, this project's 'RX1 "
                          "port'). Use TX/RX if your noise source is instead wired to "
                          "the shared TX/RX SMA.")
    ap.add_argument("--channel", type=int, default=1, choices=[0, 1],
                     help="UHD RX channel index. Default 1 -- confirmed via "
                          "tx_tone_probe.py that this project's physical TX1/RX1 ports "
                          "are channel 1 (subdev FE-TX1/FE-RX1), not channel 0 "
                          "(FE-TX2/FE-RX2) used in early captures before this was found.")
    ap.add_argument("--samp-rate", type=float, default=2e6)
    ap.add_argument("--capture-s", type=float, default=0.05,
                     help="Capture duration per hot/cold measurement, seconds")
    ap.add_argument("--settle-s", type=float, default=0.1,
                     help="Settle time after gain/freq changes")
    ap.add_argument("--noise-source-gpio", action="store_true",
                     help="If set, expects a GPIO control function instead of manual prompts "
                          "(not implemented here -- wire up your hardware in control_noise_source())")
    ap.add_argument("--out", type=str, required=True)
    ap.add_argument("--dry-run", action="store_true",
                     help="Skip UHD hardware calls; useful to sanity-check the gain table and CSV output")
    args = ap.parse_args()

    path_loss = PathLoss(attenuator_db=args.atten_db, cable_db=args.cable_db)
    enr_db = enr_at_rx1(args.enr_source_db, path_loss)
    print(f"ENR referred to RX1: {enr_db:.3f} dB "
          f"(source {args.enr_source_db:.2f} dB - path loss {path_loss.total_db:.2f} dB)")

    usrp = None
    if not args.dry_run:
        import uhd
        usrp = uhd.usrp.MultiUSRP()
        usrp.set_rx_rate(args.samp_rate, args.channel)
        usrp.set_rx_freq(uhd.types.TuneRequest(args.freq), args.channel)
        # The B210's antennas are named 'TX/RX' and 'RX2' -- there is no
        # literal 'RX1' antenna string. This project's "RX1 port" label
        # refers to the dedicated-receive 'RX2' antenna on channel 1
        # (subdev FE-RX1), confirmed empirically with tx_tone_probe.py by
        # transmitting a known tone on TX1 (channel 1, FE-TX1) through the
        # attenuator and checking which RX channel actually received it.
        usrp.set_rx_antenna(args.antenna, args.channel)
        usrp.set_rx_agc(False, args.channel)

    if args.gain_table:
        gain_table = load_gain_table(args.gain_table)
    else:
        if args.dry_run:
            print("NOTE: --auto-gain with --dry-run uses a nominal 0-76 dB / "
                  "1 dB-step placeholder, not a device-verified table. Run "
                  "without --dry-run on real hardware for actual gain values.")
        gain_table = build_auto_gain_list(usrp, args.dry_run, args.gain_step_db, args.channel)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()

        for gain_index, total_gain_db in gain_table:
            if args.dry_run:
                applied_gain = total_gain_db
            else:
                usrp.set_rx_gain(total_gain_db, args.channel)
                time.sleep(args.settle_s)
                applied_gain = usrp.get_rx_gain(args.channel)

            print(f"[Gain_Index={gain_index}] requested={total_gain_db:.2f} dB "
                  f"applied={applied_gain:.2f} dB")

            if args.dry_run:
                # Physically-consistent placeholder (not real data): derive
                # P_hot/P_cold from the actual enr_db for an assumed 5 dB
                # receiver, so the CSV demonstrates a plausible NF instead of
                # an arbitrary (possibly impossible, e.g. negative) value.
                assumed_nf_db = 5.0
                y_placeholder = 1.0 + db_to_linear(enr_db) / db_to_linear(assumed_nf_db)
                p_cold = -80.0
                p_hot = p_cold + linear_to_db(y_placeholder)
            else:
                prompt_noise_source("OFF")
                time.sleep(args.settle_s)
                p_cold = capture_power(usrp, args.capture_s, args.dbm_offset, args.channel)

                prompt_noise_source("ON")
                time.sleep(args.settle_s)
                p_hot = capture_power(usrp, args.capture_s, args.dbm_offset, args.channel)

                prompt_noise_source("OFF")

            nf_db = noise_figure_db(p_hot, p_cold, enr_db)

            writer.writerow({
                "Gain_Index": gain_index,
                "Total_Gain_dB": total_gain_db,
                "RX_Gain_UHD_dB": applied_gain,
                "Freq_MHz": args.freq / 1e6,
                "P_cold_dBm": p_cold,
                "P_hot_dBm": p_hot,
                "NF_dB": nf_db,
            })
            f.flush()

    print(f"Done. Results written to {out_path}")


if __name__ == "__main__":
    main()

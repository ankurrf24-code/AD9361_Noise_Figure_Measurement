#!/usr/bin/env python3
"""
One-off diagnostic: transmit a known CW tone and check which RX channel/
antenna combination actually receives it. Used to resolve which UHD channel
index corresponds to this project's physically-wired "TX1/RX1" ports, since
subdev names (FE-TX1/FE-RX1 on channel 1 vs FE-TX2/FE-RX2 on channel 0)
suggest channel 1, not the channel 0 used in earlier captures.

Not part of the regular measurement pipeline -- a wiring-verification tool.
"""

import sys
import threading
import time

import numpy as np
import uhd

sys.path.insert(0, "scripts")
from run_snr_sweep import spectrum_snr  # noqa: E402


def tx_thread_fn(usrp, tx_channel, freq, tx_gain, samp_rate, tone_offset_hz, stop_event):
    usrp.set_tx_rate(samp_rate, tx_channel)
    usrp.set_tx_freq(uhd.types.TuneRequest(freq), tx_channel)
    usrp.set_tx_antenna("TX/RX", tx_channel)
    usrp.set_tx_gain(tx_gain, tx_channel)

    st_args = uhd.usrp.StreamArgs("fc32", "sc16")
    st_args.channels = [tx_channel]
    tx_streamer = usrp.get_tx_stream(st_args)

    n = 4096
    t = np.arange(n) / samp_rate
    tone = 0.3 * np.exp(2j * np.pi * tone_offset_hz * t)
    tone = tone.astype(np.complex64).reshape(1, -1)

    md = uhd.types.TXMetadata()
    md.start_of_burst = True
    md.end_of_burst = False
    while not stop_event.is_set():
        tx_streamer.send(tone, md)
        md.start_of_burst = False
    md.end_of_burst = True
    tx_streamer.send(np.zeros((1, 0), dtype=np.complex64), md)


def capture_iq(usrp, rx_channel, num_samps):
    st_args = uhd.usrp.StreamArgs("fc32", "sc16")
    st_args.channels = [rx_channel]
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


def main():
    freq = 2190e6
    samp_rate = 2e6
    tone_offset_hz = 200e3
    tx_gain = 30.0
    rx_gain = 40.0
    tx_channel = 1  # FE-TX1, matches this project's "TX1" per subdev naming

    usrp = uhd.usrp.MultiUSRP()

    stop_event = threading.Event()
    tx_thread = threading.Thread(
        target=tx_thread_fn,
        args=(usrp, tx_channel, freq, tx_gain, samp_rate, tone_offset_hz, stop_event),
        daemon=True,
    )
    tx_thread.start()
    time.sleep(0.5)  # let TX ramp up

    for rx_channel in [0, 1]:
        usrp.set_rx_rate(samp_rate, rx_channel)
        usrp.set_rx_freq(uhd.types.TuneRequest(freq), rx_channel)
        usrp.set_rx_antenna("RX2", rx_channel)
        usrp.set_rx_agc(False, rx_channel)
        usrp.set_rx_gain(rx_gain, rx_channel)
        time.sleep(0.1)

        samples = capture_iq(usrp, rx_channel, 4096 * 50)
        signal_db, noise_db, peak_offset_hz = spectrum_snr(samples, samp_rate, 4096, 50, dc_guard_bins=10)
        locked = abs(peak_offset_hz - tone_offset_hz) < 5000
        print(f"RX channel {rx_channel} (antenna RX2): signal={signal_db:.2f} dB "
              f"noise={noise_db:.2f} dB SNR={signal_db-noise_db:.2f} dB "
              f"peak_offset={peak_offset_hz/1e3:+.1f} kHz "
              f"{'<-- TONE DETECTED (expected +200 kHz)' if locked else '(no tone at expected offset)'}")

    stop_event.set()
    tx_thread.join(timeout=2)


if __name__ == "__main__":
    main()

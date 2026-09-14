# Chosen Parameters

## Signal: "G-FR1-A1-1"

This exact designator was searched for exhaustively (datasheet folder, and
an entire separate B210 NR test-vector project) and does not exist
anywhere on disk. The closest and only real match found is the standard
3GPP designation **NR-FR1-TM1.1**, confirmed against the actual TS 38.141-1
clause text in that other project's spec extracts
(`docs/spec_extracts/TS_38.141-1_sec_4.9.2.2.1_TM1.1_table.txt`). This
project generates TM1.1: full-resource-block QPSK, DM-RS pilots, correct
CP-OFDM timing. If a document later surfaces that defines "G-FR1-A1-1" as
something else, re-check this assumption.

Waveform generation reuses that other project's proper generator
(`D:\USRP B210\RF test vector B210 _claude\waveform_gen\nr_tm_waveform.py`)
directly rather than reimplementing it -- it's pure NumPy, no GNU Radio
dependency for generation itself.

## Chain

**Chain A = UHD channel 1** (subdev `FE-TX1`/`FE-RX1`), confirmed
empirically in earlier work by transmitting a known tone on TX1 and
checking which RX channel actually received it (channel 1: locked, strong
SNR; channel 0: nothing but noise). RX antenna is `RX2` (Chain A's
dedicated receive port); TX antenna is `TX/RX` (Chain A's shared port).

## Why TX and RX are one script, one process (important hardware finding)

The original design used two separate scripts/processes (TX running
continuously, RX capturing separately), matching how the external NR
test-vector project's own `tx_b210.py`/`rx_capture_evm_ccdf.py` appear to
work. **This does not work on this B210**: starting the RX process while
the TX process already holds the device fails immediately with
`RuntimeError: LookupError: KeyError: No devices found` -- not a
busy/retry error, a hard "can't see the device at all" failure. The B210
is a single-session USB device; a second process cannot open it while the
first still holds it.

**Fix**: `flowgraphs/capture_chain_a.py` builds TX (if `--tx-state on`) and
RX in the *same* flowgraph, in one process, one script invocation per
(gain index, TX state) combination.

## A second bug found while fixing the first one

With TX and RX combined in one flowgraph, the first working version hung
indefinitely after capture. Cause: `tb.wait()` blocks until *every* block
in the flowgraph finishes, but the TX side
(`blocks.vector_source_c(..., repeat=True)`) is designed to run forever --
so the flowgraph can never self-terminate on its own once TX is connected,
even though the RX `head` block had already captured everything it needed
and the file was already fully and correctly written to disk. Fix: poll
`head.nitems_read(0)` until it reaches the target sample count, then call
`tb.stop()` explicitly instead of relying on `tb.wait()` to return by
itself.

## Fixed TX parameters

| Parameter | Value | Why |
|---|---|---|
| TX gain | 50 dB | Matches all prior verified working captures in this project's history |
| Channel bandwidth | **5 MHz** (default) | 20 MHz was tested and found to underflow massively -- 1,905+ underflow events within the first second -- **even with TX alone, no RX yet**, confirming this is a genuine USB/host throughput ceiling on this specific machine (also independently documented in the external project's own `tx_b210.py` developer notes), not something fixable by combining/splitting processes. 5 MHz streamed with zero underflows across all four real captures below. `--bandwidth 20e6` remains available but is not verified working. |
| Numerology | 30 kHz SCS (native to the reused generator) | 11 RB, N_FFT=256, sample rate 7.68 Msps at 5 MHz |
| Center frequency | 2190 MHz | This project's established FR1 target frequency |

## Fixed RX parameters

| Parameter | Value | Why |
|---|---|---|
| Gain indices captured | 10 and 70 | As specified -- a low-gain and a high-gain point spanning most of the AD9361's 0-76 dB range |
| Capture duration | 1.0 s per file | ~7.68M samples at 5 MHz -- plenty for many averaged FFT frames |
| Warm-up discarded before capture | 2.5 s (TX on) / 0.3 s (TX off) | TX needs ~1-1.5s to clear its startup underrun transient (found and documented earlier in this project's history); RX-only settles much faster |
| Antenna | RX2 | Chain A's dedicated receive port |

## Real captured results (2190 MHz, 5 MHz BW, Chain A)

| Gain Index | TX State | In-band (dB) | Out-of-band (dB) | SNR (dB) |
|---|---|---|---|---|
| 10 | off | -67.85 | -68.65 | 0.80 |
| 10 | on | -67.34 | -68.22 | 0.87 |
| 70 | off | -41.99 | -42.75 | 0.76 |
| 70 | on | -33.28 | -42.68 | **9.40** |

At Gain Index 10, the signal is still too weak to rise above the noise
floor (consistent with the AD9361's full-gain-table behavior investigated
earlier in this project -- attenuation ahead of the LNA at low gain
indices genuinely degrades sensitivity, not just a measurement artifact).
At Gain Index 70, turning TX on raises in-band power by ~8.7 dB while
out-of-band noise stays flat (within 0.1 dB) -- the clean signature of a
real detected signal, not noise or an artifact.

## File naming

`capture/chainA_gain{N}_tx{on|off}.bin` -- interleaved complex64 (GNU
Radio's native `gr_complex` format, binary-compatible with
`numpy.complex64`), consumed directly by `analysis/analyze_iq.py`.

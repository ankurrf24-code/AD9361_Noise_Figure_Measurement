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

## EVM analysis: reused external tooling, found and fixed one bug in it

The raw-IQ "constellation" in `analysis/detailed_analysis.py` is exactly
that -- raw time-domain samples, not demodulated symbols. OFDM time
samples are the IFFT sum of many subcarriers, so by the Central Limit
Theorem they look like Gaussian noise in time regardless of SNR; a real
constellation only exists per-subcarrier after CP removal + FFT. For a
proper EVM measurement (not just an illustrative demod), `analysis/
evm_analysis.py` reuses the external NR test-vector project's own
proven pipeline (`analysis/iq_analysis.py`): full-cycle matched-filter
slot sync, DM-RS-based single-tap magnitude + linear-phase-ramp channel
equalization, occupied bandwidth, PAPR/CCDF, IQ imbalance.

To use it, TX now transmits from a properly generated `.iq.bin`/`_ref.npy`/
`_meta.json` triplet (via that project's own `generate()` function,
producing `capture/tx_waveforms/`) instead of the in-memory-only waveform
generation used earlier -- the saved ideal reference grid is required for
real EVM comparison and wasn't being kept before.

### Bug found and fixed: per-symbol CFO correction was actively harmful here

First real capture at Gain Index 70 gave a badly unstable EVM: 49.3% RMS,
std 31.8% across frames, phase-noise proxy 289 deg RMS (should be a few
degrees), residual CFO reported as an implausible -7.19 Hz while EVM was
catastrophic -- exactly the warning sign the original script's own comments
describe ("if the estimate looks implausibly small while EVM is high,
suspect CFO above this [+/-1kHz] Nyquist limit").

Investigated directly: measured the raw per-symbol CP-based (Moose) CFO
estimate across 2000 symbols. Result: mean -816 Hz, but **std 113,883 Hz**,
spanning almost exactly the estimator's full +/-213 kHz theoretical range
(`fs / (2*cp_normal)` = 7.68 MHz / 36 = 213 kHz) -- i.e. essentially random
noise, not a real large CFO. Root cause: this project's 5 MHz/30 kHz-SCS
waveform has an 18-sample cyclic prefix, too short for a reliable Moose
phase estimate at this SNR. Applying that "correction" injects near-random
phase rotation into every symbol instead of fixing anything.

**Fix**: `evm_analysis.py`'s `per_slot_evm_no_cfo()` is the same slot-sync
and DM-RS equalization as the original, with the per-symbol CFO correction
step removed. Verified on the same capture: EVM drops to a stable,
reproducible **27.5% RMS (std 1.9%)**.

### Is 27.5% EVM at Gain Index 70 a problem?

No -- it's explained by SNR, not a defect. This project's independent
spectral SNR measurement at Gain Index 70 was ~9.4 dB (see the SNR
analysis results above). The theoretical EVM floor from SNR alone is
`1/sqrt(SNR_linear)` = `1/sqrt(10^0.94)` ~= 34% at 9.4 dB -- in the same
ballpark as the measured 27.5%. The remaining EVM is consistent with this
loopback path's actual SNR at this gain setting, not a hidden hardware
fault. To get EVM within typical QPSK spec (~17.5%), the fix would be
improving the path's SNR (e.g. re-tuning TX/RX gain, reducing path loss),
not further DSP changes.

### Sanity check: Gain Index 10 gives EVM > 100%

As expected given everything found earlier in this project (signal
undetectable below the noise floor at low gain index): EVM at Gain Index
10 comes out to 152% RMS -- above 100% means the "demodulated" symbols are
essentially uncorrelated with the reference, i.e. pure noise, exactly what
should happen when there's no real recoverable signal. This is a useful
built-in sanity check that the whole pipeline (sync, equalization, EVM
math) is behaving correctly, not silently producing plausible-looking
numbers from garbage input.

## TX gain fix: the real limit was TX power, not demodulation

User question after seeing high EVM at every gain index tested: is the
limit TX gain or demodulation? Tested directly rather than guessing:
raised TX gain from 50 dB to 70 dB (B210 TX range goes to ~89.8 dB, so
50 dB was leaving ~40 dB of headroom completely unused) at RX Gain Index
60, and re-measured everything on a real capture:

| | TX=50dB, RX=60 | TX=70dB, RX=60 |
|---|---|---|
| SNR (spectral) | 10.62 dB | **21.87 dB** |
| EVM RMS | 34.4% (std 6.5%) | **8.02%** (std 0.77%) |
| Occupied BW vs nominal | 174% (noise-inflated) | **99.5%** (accurate) |
| ADC peak fraction | 0.031 | 0.24 (still far from the 0.9 overload line) |

8.02% RMS EVM is comfortably within the typical QPSK spec (~17.5%), and
the occupied-bandwidth measurement becoming accurate (99.5% vs. 174% of
nominal) is itself a symptom of the earlier low-SNR problem -- noise energy
outside the true signal band was being counted as "occupied" at low SNR.

**Conclusion: TX gain was the actual limiting factor, not demodulation.**
The demod/EVM pipeline (matched-filter slot sync, DM-RS equalization) was
already working correctly -- it was just being asked to extract a QPSK
symbol from a signal that hadn't been transmitted with enough power to give
a clean answer at the RX gains tested. Default TX gain in
`flowgraphs/capture_chain_a.py` is now 70 dB (was 50 dB). ADC headroom
should be re-checked (via `analysis/detailed_analysis.py`) if you push RX
gain higher than 60 at this TX gain, or push TX gain higher still --
peak fraction was 0.24 at TX=70/RX=60, with real margin left before the
0.9 overload threshold, but it will not stay small indefinitely as either
gain increases further.

## File naming

`capture/chainA_gain{N}_tx{on|off}.bin` -- interleaved complex64 (GNU
Radio's native `gr_complex` format, binary-compatible with
`numpy.complex64`), consumed directly by `analysis/analyze_iq.py`.

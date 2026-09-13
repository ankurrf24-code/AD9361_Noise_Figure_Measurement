# NR Waveform SNR vs Gain Index

Two generators are used in this project, in order of preference:

## Preferred: the proper TM1.1 generator (external project)

`scripts/run_nr_tm_snr_sweep.py` imports the waveform-generation functions
directly from a separate, more rigorous project:

> `D:\USRP B210\RF test vector B210 _claude\waveform_gen\nr_tm_waveform.py`

That project implements 3GPP-style NR-FR1-TM1.1/TM2/TM3.1/TM3.2/TM3.3a with
correct OFDM numerology, DM-RS pilots (comb-2), and CP timing per TS 38.141's
structural intent (see its own `nr_tm_config.py` docstring for exactly what's
simplified: no real channel coding, no SS/PBCH, TM3.x power boosting
approximated as uniform full-band power). It's a 30 kHz-SCS generator built
for n78 (3.5 GHz); this script reuses it as-is at this project's 920/2190 MHz
frequencies by retuning the LO only -- the generator itself produces
frequency-agnostic baseband IQ.

This script imports that generator's pure-NumPy functions directly (no GNU
Radio dependency needed for generation) and feeds the resulting IQ into
this project's own already-validated plain-UHD TX/RX loop -- it does **not**
use that other project's GNU Radio-based `tx_b210.py`/`rx_capture_evm_ccdf.py`
flowgraphs, which require the separate `radioconda` environment.

### Note on "G-FR1-A1-1"

This was the original request's test-case designator. It was searched for
exhaustively across the user's datasheet folder and the entire B210 NR
test-vector project and **does not exist** anywhere on disk. The closest and
most likely intended match is **NR-FR1-TM1.1** (confirmed present, with the
exact 3GPP TS 38.141-1 clause text, in that project's
`docs/spec_extracts/TS_38.141-1_sec_4.9.2.2.1_TM1.1_table.txt`). If a
document surfaces later that actually defines "G-FR1-A1-1" as something
different (e.g. a GCF conformance test-case ID), re-check this assumption.

### Numerology actually used (30 kHz SCS, per the external generator's table)

| Channel BW | N_RB | Subcarriers | Occupied BW | N_FFT | Sample rate |
|---|---|---|---|---|---|
| 5 MHz | 11 | 132 | 3.96 MHz | 256 | 7.68 Msps |
| 20 MHz | 51 | 612 | 18.36 MHz | 1024 | 30.72 Msps |

### Results (2190 MHz, TX1 -> attenuator -> RX1 loopback, channel 1, full 77-point sweep)

`results/plots/nr_tm_snr_vs_gain_2190MHz.png`:
- SNR rises monotonically with gain in both cases.
- 5 MHz (11 RB) reaches ~8.7 dB SNR at Gain Index 76.
- 20 MHz (51 RB) reaches ~4.8 dB SNR at Gain Index 76 -- lower, as expected
  (same TX power spread over more occupied bandwidth reduces PSD).
- These numbers are close to (within ~1 dB of) the earlier simplified
  generator's results at the same bandwidths despite using a different
  RB count and generator implementation -- reasonable cross-validation
  that the SNR measurement method itself (in-band vs out-of-band power)
  is robust to the specific waveform's exact structure.

### Usage

```
python scripts/run_nr_tm_snr_sweep.py --freq 2190e6 --tm TM1.1 --bandwidth 5e6 \
    --out data/raw/nr_tm_snr_5MHz_2190MHz.csv
python scripts/run_nr_tm_snr_sweep.py --freq 2190e6 --tm TM1.1 --bandwidth 20e6 \
    --out data/raw/nr_tm_snr_20MHz_2190MHz.csv
```

Requires the external project directory above to exist at that path (it's
outside this repo, on a different local drive -- not a dependency this repo
can install or vendor).

## Actual GNU Radio flowgraph version

`scripts/gnuradio_nr_tm_gain_sweep.py` does the same TM1.1 measurement but
through a real GNU Radio flowgraph (`gr.top_block` with `uhd.usrp_sink` /
`uhd.usrp_source` / `blocks.vector_source_c` / `blocks.vector_sink_c`),
rather than the plain UHD Python API used in `run_nr_tm_snr_sweep.py`. Must
be run with `radioconda`'s Python (has GNU Radio + UHD 4.8.0 installed),
with `UHD_IMAGES_DIR` set to the system UHD's images directory (radioconda's
own UHD didn't have the FPGA/firmware images downloaded):

```
set UHD_IMAGES_DIR=C:\Program Files\UHD\share\uhd\images
C:\Users\ankur\radioconda\python.exe scripts\gnuradio_nr_tm_gain_sweep.py ^
    --freq 2190e6 --bandwidth 5e6 --out data\raw\gr_nr_tm_snr_5MHz_2190MHz.csv
```

It reuses the same external project's waveform generator and channel 1
(not the external project's own hardcoded channel 0 -- that project's
`tx_b210.py`/`rx_capture_evm_ccdf.py` were not modified; this is a separate,
self-contained flowgraph). The flowgraph starts once; gain is changed live
via `usrp_source.set_gain()` between capture windows, which is the
GNU-Radio-idiomatic way to sweep gain without restarting the flowgraph.

### Sample-count bug: fixed. Result-value gap: still open

First pass (`vector_sink.reset()` + fixed `sleep(capture_s)` + read
`.data()`) had a real, verified bug: sample counts per gain point varied
wildly (450K-770K at 20 MHz vs. the ~51K requested; ~385K-390K at 5 MHz,
also oversized but far more consistent). Root cause: no hard guarantee on
exactly when `reset()` takes effect relative to the flowgraph's internal
buffering, worse at 30.72 Msps (20 MHz) than 7.68 Msps (5 MHz) since more
samples arrive per second of timing slop.

Fix applied: capture duration now scales with sample rate
(`max(--capture-s, 1.5 * min_samps_needed / samp_rate)`) instead of a fixed
wall-clock constant, and — more importantly — the code no longer trusts
`reset()`'s exact timing at all: it retries until at least
`min_samps_needed` samples have accumulated, then **always takes the last
`min_samps_needed` samples**, discarding everything earlier. Any stale
pre-gain-change data from buffering slop ends up at the *start* of the
accumulated buffer, not the end, so this reliably captures gain-settled
data regardless of exactly when `reset()` landed. Verified: sample counts
are now deterministically exactly 51,200 at every gain point, both
bandwidths (`results/plots/gnuradio_nr_tm_snr_vs_gain_2190MHz.png` includes
both this fixed run and the plain-UHD reference for comparison).

**This did not fully close the gap to the plain-UHD reference, and moved
it in different directions per bandwidth** -- worth being explicit about
rather than declaring victory:

| | Plain-UHD reference | GNU Radio (buggy sampling) | GNU Radio (fixed sampling) |
|---|---|---|---|
| 5 MHz @ Gain 76 | ~8.7 dB | ~8.9 dB (looked fine, coincidentally) | ~10.4 dB |
| 20 MHz @ Gain 76 | ~4.8 dB | ~2.4 dB | ~3.3 dB |

The sample-count bug is conclusively fixed (that was the reported problem
and the mechanism is now understood and verified). But a second, distinct
and not-yet-diagnosed effect remains: the GNU Radio capture path now
disagrees with the plain-UHD reference in *both* directions depending on
bandwidth, which rules out a single simple remaining bias (like a leftover
constant offset) and suggests something more specific -- candidates not yet
checked: whether `uhd.usrp_source`'s internal DSP chain (DDC/filtering)
differs from raw `multi_usrp` streaming in a way that affects the measured
spectral shape, whether the capture window's alignment relative to
OFDM slot boundaries matters for this particular in-band/out-of-band power
method, or genuine run-to-run environmental variation (the loopback path
wasn't physically touched between runs, so this is a weaker candidate).
**Treat `run_nr_tm_snr_sweep.py` (plain UHD) as the trustworthy source for
actual SNR values; treat the GNU Radio flowgraph as verified-correct
plumbing (proper waveform, proper channel, deterministic sample count,
gain response in the right direction) but not yet a numerically validated
alternative.**

## Fallback: this project's own simplified generator

`scripts/nr_waveform.py` / `scripts/run_nr_snr_sweep.py` -- a self-contained,
simpler full-resource-block QPSK CP-OFDM approximation (15 kHz SCS, constant
CP length, no DM-RS) built before the external project was found. Kept for
reference and because it has no external dependency, but the TM1.1 generator
above is more standards-accurate and is the preferred path going forward.
See the original results in this file's git history / `nr_snr_vs_gain_2190MHz.png`
for that version's data (25 RB @ 5 MHz, 106 RB @ 20 MHz, 15 kHz SCS).

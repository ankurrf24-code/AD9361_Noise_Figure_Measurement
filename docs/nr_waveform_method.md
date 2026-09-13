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

### Results and a real discrepancy worth flagging

`results/plots/gnuradio_nr_tm_snr_vs_gain_2190MHz.png`, full 77-point sweep:

- **5 MHz**: ~8.9 dB SNR at Gain Index 76 -- matches the plain-UHD result
  (~8.7 dB) closely.
- **20 MHz**: ~2.4 dB SNR at Gain Index 76 -- this does **not** match the
  plain-UHD result (~4.8 dB) well, and the discrepancy is real, not just
  a fluke: the captured sample counts for the 20 MHz run varied wildly
  (450K-770K samples per gain point, vs. the ~51K requested), while the
  5 MHz run's counts stayed close to expected (~385K-390K, also more than
  requested but far more consistent). The likely cause: this script
  captures by `vector_sink.reset()` + `sleep()` + read `.data()`, which has
  no hard guarantee on exactly when the reset takes effect relative to the
  flowgraph's internal buffering -- at 30.72 Msps (20 MHz) far more samples
  arrive per second than at 7.68 Msps (5 MHz), so any timing slop between
  the gain change and the reset/capture window matters proportionally more,
  and capture windows can end up including leftover buffered samples from
  before the gain change stabilized. `run_nr_tm_snr_sweep.py`'s plain-UHD
  approach avoids this entirely by requesting an exact sample count via a
  synchronous `stream_cmd`, which is why it's the more trustworthy number
  for actual analysis -- treat the GNU Radio version's 20 MHz result as
  demonstrating "the flowgraph works and responds to gain in the right
  direction," not as a precise SNR measurement. This is a real limitation
  of the ad hoc buffering approach, not fixed here; a proper fix would
  synchronize the capture window to stream tags/timestamps rather than
  wall-clock sleeps.

## Fallback: this project's own simplified generator

`scripts/nr_waveform.py` / `scripts/run_nr_snr_sweep.py` -- a self-contained,
simpler full-resource-block QPSK CP-OFDM approximation (15 kHz SCS, constant
CP length, no DM-RS) built before the external project was found. Kept for
reference and because it has no external dependency, but the TM1.1 generator
above is more standards-accurate and is the preferred path going forward.
See the original results in this file's git history / `nr_snr_vs_gain_2190MHz.png`
for that version's data (25 RB @ 5 MHz, 106 RB @ 20 MHz, 15 kHz SCS).

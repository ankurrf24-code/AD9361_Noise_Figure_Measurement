# NR Waveform SNR vs Gain Index

`scripts/nr_waveform.py` generates a simplified 3GPP-style NR downlink test
waveform (full-resource-block random QPSK CP-OFDM, similar in spirit to
NR-FR1-TM1.1) at two standard 15 kHz-SCS channel bandwidths:

| Channel BW | RBs | Subcarriers | Occupied BW | FFT size | Sample rate |
|---|---|---|---|---|---|
| 5 MHz | 25 | 300 | 4.5 MHz | 512 | 7.68 Msps |
| 20 MHz | 106 | 1272 | 19.08 MHz | 2048 | 30.72 Msps |

## What this is, and isn't

This is **not** a conformance-exact 3GPP TS 38.141 test model. Notably:
- It uses a constant cyclic-prefix length per OFDM symbol, not the "long CP
  on the first symbol of each 0.5 ms slot" real NR frame structure uses.
- It carries no PSS/SSS/PBCH/DMRS reference signals -- just random QPSK
  filling every allocated subcarrier.

It's a reasonable proxy for RF-level SNR/sensitivity characterization
(realistic occupied bandwidth, PAPR ~9-10 dB, correct subcarrier spacing),
not a substitute for an actual 3GPP conformance test tool. The specific
test case this was originally requested against ("G-FR1-A1-1") was not
identified/confirmed with the user before building this -- if that maps to
a specific documented 3GPP test model, this waveform should be checked
against it before using these results for anything beyond exploratory
characterization.

## Method

`scripts/run_nr_snr_sweep.py`:
1. Generates the waveform for the requested `--channel-bw` (5e6 or 20e6).
2. Transmits it continuously through TX1 (channel 1, antenna TX/RX).
3. Sweeps RX gain across the full device-reported range (0-76 dB via
   `--auto-gain`-equivalent logic).
4. At each gain index, captures IQ at the waveform's native sample rate and
   computes:
   - `Inband_Power_dB`: average power in FFT bins within the known occupied
     bandwidth (excluding a DC guard band for AD9361 LO leakage)
   - `Outband_Noise_dB`: average power in FFT bins outside the occupied
     bandwidth
   - `SNR_dB = Inband_Power_dB - Outband_Noise_dB`

This differs from the CW-tone method (`run_snr_sweep_loopback.py`, single
peak bin vs. noise floor) because an OFDM signal's power is spread across
many subcarriers rather than concentrated in one bin -- an average in-band
vs. out-of-band comparison is the correct measure here, not a peak search.

## Results (2190 MHz, TX1 -> attenuator -> RX1 loopback, channel 1)

Both bandwidths, full 77-point gain sweep (`results/plots/nr_snr_vs_gain_2190MHz.png`):

- SNR rises monotonically with gain in both cases, from ~0-1 dB (below/at
  noise floor) at low gain to a plateau at high gain.
- 5 MHz (25 RB) reaches ~8.5 dB SNR at Gain Index 76.
- 20 MHz (106 RB) reaches ~5.3 dB SNR at Gain Index 76 -- lower than 5 MHz,
  which is physically expected: the same TX gain spreads the same total
  transmit power over ~4.24x more occupied bandwidth (19.08 MHz vs
  4.5 MHz), reducing power spectral density by ~6.3 dB in theory. The
  observed ~3.2 dB SNR gap between the two bandwidths at max gain is in the
  right direction, though smaller than the full theoretical PSD difference
  -- consistent with, not a precise match to, the naive prediction (some of
  the gap could be absorbed by how out-of-band noise floor is estimated at
  each bandwidth, or environmental differences between the two runs; not
  independently verified further here).

## Usage

```
python scripts/run_nr_snr_sweep.py --freq 2190e6 --channel-bw 5e6 \
    --out data/raw/nr_snr_5MHz_2190MHz.csv
python scripts/run_nr_snr_sweep.py --freq 2190e6 --channel-bw 20e6 \
    --out data/raw/nr_snr_20MHz_2190MHz.csv
```

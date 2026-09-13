# Measurement Manual — AD9361 (USRP B210) Noise Figure vs Gain Index

## 1. Scope

This manual measures the Noise Figure (NF) of the USRP B210's RX1 chain
(AD9361 + RF front end) across all 77 gain-table indices (0-76), at 920 MHz
and 2190 MHz, using the Y-factor method with a calibrated noise source.

## 2. Equipment

- Ettus USRP B210
- Calibrated noise source with known ENR(f) — datasheet or cal-lab ENR table
  covering 920 MHz and 2190 MHz
- Noise source power supply / bias-tee or GPIO control line to switch it ON/OFF
- RF cable(s), ~1 dB loss (get the actual measured value — see calibration doc)
- 30 dB calibrated precision attenuator (used only for the separate TX1
  loopback/leakage check in Section 3 — do NOT insert it in the noise-source
  path; see [calibration_procedure.md](calibration_procedure.md) Section 0)
- VNA or power meter for cable loss verification (calibration step)
- Host PC with UHD + GNU Radio (or UHD Python API) installed
- Temperature logging (ambient, and ideally board temperature)

## 3. Signal Path

```
Noise Source --[bias/control]--
      |
      v (RF out)
RF cable (~1 dB, measured)
      |
      v
USRP B210 RX1
```

The 30 dB attenuator is **not** part of this path. It exists solely to
protect RX1 from TX1's own output power for a separate loopback/leakage
check (`TX1 -> 30 dB attenuator -> cable -> RX1`), which is a different test
from this Y-factor NF measurement and is not itself a valid NF measurement
method (see README "Measurement Method"). Inserting 30 dB of loss between
the noise source and RX1 would crush the ENR available at RX1 well below
what's measurable — see `docs/calibration_procedure.md` Section 0 for the
worked numbers.

TX1 is left disconnected/terminated with a 50 ohm load during the NF
measurement — it plays no role in the Y-factor method and must not radiate
into the RX path.

## 4. Pre-Measurement Calibration (do this first)

Complete [calibration_procedure.md](calibration_procedure.md) before taking
any NF data:

1. Confirm no attenuator is inserted in the noise-source path (Section 0 of
   the calibration doc) — if your bench genuinely needs one, measure its
   actual loss at 920 MHz and 2190 MHz (never trust a nameplate value).
2. Measure actual cable loss at both frequencies.
3. Confirm/record noise source ENR at both frequencies from its cal certificate.
4. Record measurement bandwidth and FFT resolution bandwidth (RBW) used for
   power integration, and verify the noise power estimate is bandwidth-correct.
5. Record ambient temperature (T0 reference for ENR is normally 290 K —
   confirm what your noise source's ENR is referenced to).

## 5. Gain Sweep Setup

Recommended: run `scripts/run_nf_sweep.py --auto-gain`, which queries the
connected B210's actual `get_rx_gain_range()` and sweeps its real reported
gain steps, logging `get_rx_gain()` readback at each point. This avoids
depending on a hand-transcribed AD9361 datasheet gain table — see
[docs/gain_tables/README.md](gain_tables/README.md) for why the index-to-dB
mapping isn't safe to assume from the datasheet alone (ADI's own
documentation and EngineerZone reports indicate it's only nominally
1 dB/step and flattens above ~58 dB on some parts).

If you have an independently verified static table instead, use
`--gain-table` with:
1. `docs/gain_tables/gain_table_200_1300MHz.csv` for 920 MHz.
2. `docs/gain_tables/gain_table_1300_4000MHz.csv` for 2190 MHz.

The sweep script will refuse to run against a `--gain-table` CSV with blank
`Total_Gain_dB` entries.

## 6. Procedure

For each target frequency (920 MHz, then 2190 MHz):

1. Set USRP center frequency (`set_rx_freq`) to the target frequency.
2. Set RX antenna to RX1 (`set_rx_antenna("RX1")` — the B210 also requires
   selecting the correct daughterboard subdev, typically `A:A`).
3. Disable AGC (`set_rx_agc(False)`) — gain must be manual and repeatable.
4. For each gain point `i` in the sweep (0 to 76, or however many device
   reports with `--auto-gain`):
   a. Determine the requested gain: from `get_rx_gain_range()` step-through
      (`--auto-gain`, recommended) or looked up as `Total_Gain_dB[i]` from
      the gain table CSV (`--gain-table`).
   b. Command `set_rx_gain(...)` via UHD. Read back `get_rx_gain()` and
      record as `RX_Gain_UHD_dB` (UHD may snap to the nearest supported
      step — log what was actually applied, not just what was requested).
   c. **Cold measurement**: ensure noise source is OFF. Wait for the RX chain
      to settle (LO lock, gain settle — typically >= 50 ms). Capture N seconds
      of IQ samples. Compute average power in dBm over the calibrated
      measurement bandwidth -> `P_cold_dBm`.
   d. **Hot measurement**: switch noise source ON. Wait for it to stabilize
      (check datasheet warm-up/switching time). Capture the same duration.
      Compute average power -> `P_hot_dBm`.
   e. Switch noise source back OFF.
   f. Compute:
      ```
      Y = 10^((P_hot_dBm - P_cold_dBm) / 10)
      NF_dB = ENR_dB - 10*log10(Y - 1)
      ```
      using `scripts/nf_yfactor.py`. Apply attenuator/cable loss and
      bandwidth corrections as documented in the calibration procedure —
      do not apply the raw uncorrected Y-factor formula if the noise source
      is not directly at the RX1 connector.
   g. Append one row to the CSV log:
      `Gain_Index,Total_Gain_dB,RX_Gain_UHD_dB,Freq_MHz,P_cold_dBm,P_hot_dBm,NF_dB`
5. Repeat for all 77 indices, then for the second frequency.

## 7. Averaging

- Average multiple FFT frames (recommend >= 100) per P_cold/P_hot measurement
  to reduce estimator variance. Record the number of averages used — it feeds
  the uncertainty budget.
- Take at least 3 independent hot/cold pairs per gain index if time allows,
  and report the standard deviation of NF at each index alongside the mean.

## 8. Output

- Raw per-run CSVs in `data/raw/`, named e.g. `nf_920MHz_<date>.csv`,
  `nf_2190MHz_<date>.csv`.
- Combined/cleaned CSVs in `data/processed/`.
- Plots via `scripts/plot_nf.py` -> `results/plots/nf_vs_gain_920MHz.png`,
  `nf_vs_gain_2190MHz.png`.

## 9. Extending to Other Frequencies

Repeat Sections 5-8 for each new frequency, selecting the correct gain-table
band file, and re-verify ENR/attenuator/cable calibration at that frequency
(loss and ENR are frequency-dependent — do not reuse 920 MHz or 2190 MHz
calibration numbers at a different frequency).

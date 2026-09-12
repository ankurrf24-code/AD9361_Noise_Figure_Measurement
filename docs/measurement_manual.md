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
- 30 dB calibrated precision attenuator
- RF cable(s), ~1 dB loss (get the actual measured value — see calibration doc)
- VNA or power meter for attenuator/cable loss verification (calibration step)
- Host PC with UHD + GNU Radio (or UHD Python API) installed
- Temperature logging (ambient, and ideally attenuator/board temperature)

## 3. Signal Path

```
Noise Source --[bias/control]--
      |
      v (RF out)
30 dB calibrated attenuator
      |
RF cable (~1 dB, measured)
      |
      v
USRP B210 RX1
```

TX1 is left disconnected/terminated with a 50 ohm load during this
measurement — it plays no role in the Y-factor method and must not radiate
into the RX path.

## 4. Pre-Measurement Calibration (do this first)

Complete [calibration_procedure.md](calibration_procedure.md) before taking
any NF data:

1. Measure actual attenuator loss at 920 MHz and 2190 MHz (not just nameplate 30 dB).
2. Measure actual cable loss at both frequencies.
3. Confirm/record noise source ENR at both frequencies from its cal certificate.
4. Record measurement bandwidth and FFT resolution bandwidth (RBW) used for
   power integration, and verify the noise power estimate is bandwidth-correct.
5. Record ambient temperature (T0 reference for ENR is normally 290 K —
   confirm what your noise source's ENR is referenced to).

## 5. Gain Table Setup

1. For 920 MHz, use `docs/gain_tables/gain_table_200_1300MHz.csv`.
2. For 2190 MHz, use `docs/gain_tables/gain_table_1300_4000MHz.csv`.
3. Confirm these CSVs have been populated with real Total Gain (dB) values
   per Gain Index (0-76) from the AD9361 reference manual / driver source —
   see [docs/gain_tables/README.md](gain_tables/README.md). **Do not proceed
   with an unpopulated table.**

## 6. Procedure

For each target frequency (920 MHz, then 2190 MHz):

1. Set USRP center frequency (`set_rx_freq`) to the target frequency.
2. Set RX antenna to RX1 (`set_rx_antenna("RX1")` — the B210 also requires
   selecting the correct daughterboard subdev, typically `A:A`).
3. Disable AGC (`set_rx_agc(False)`) — gain must be manual and repeatable.
4. For Gain Index `i` = 0 to 76:
   a. Look up `Total_Gain_dB[i]` from the appropriate gain table CSV.
   b. Command `set_rx_gain(Total_Gain_dB[i])` via UHD. Read back
      `get_rx_gain()` and record as `RX_Gain_UHD_dB` (UHD may snap to the
      nearest supported step — log what was actually applied, not just what
      was requested).
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

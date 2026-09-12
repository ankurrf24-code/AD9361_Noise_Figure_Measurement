# AD9361 Noise Figure Measurement (USRP B210)

## Objective

Measure and characterize the Noise Figure (NF) of the AD9361 transceiver inside
the Ettus USRP B210, as a function of RX Gain Index / RX Gain, across the full
gain table (indices 0-76).

Initial target frequencies:
- **920 MHz** (AD9361 gain table band: 200-1300 MHz)
- **2190 MHz** (AD9361 gain table band: 1300-4000 MHz)

Extend to additional frequencies once the method is validated at these two
points.

## Hardware Setup

| Item | Detail |
|---|---|
| SDR | Ettus USRP B210 (AD9361 transceiver) |
| RX port | RX1 |
| TX port | TX1 (disconnected/terminated during NF measurement — TX1 is only used for the loopback path when the noise source is not connected there) |
| Frequencies | 920 MHz, 2190 MHz (initial) |
| Signal path | Noise source -> 30 dB calibrated attenuator -> RF cable (~1 dB loss) -> RX1 |
| Total known path attenuation | ~31 dB (must be measured precisely per [calibration procedure](docs/calibration_procedure.md), not assumed) |

Attenuator and cable losses are measured values fed into the NF calculation
and the [uncertainty budget](docs/uncertainty_analysis.md) — they are never
assumed nominal.

## Measurement Method

**Y-Factor method with a calibrated noise source** (preferred method — used
here). Hot/cold noise and gain-method-with-calibrated-reference are documented
as fallbacks in the measurement manual if a calibrated noise source is
unavailable for a given session.

A plain TX1 -> attenuator -> RX1 loopback is **not** a valid NF measurement by
itself (the AD9361's own TX synthesizer/PA noise is not a calibrated,
traceable reference) — a calibrated noise source (with known ENR) is required
on the input.

## Procedure Summary

1. Select the gain-table band for the target frequency (200-1300 MHz for
   920 MHz, 1300-4000 MHz for 2190 MHz) — see [docs/gain_tables](docs/gain_tables/).
2. Sweep Gain Index 0-76. For each index, look up Total Gain (dB) from the
   datasheet-derived table and command that value via UHD (`set_rx_gain`).
3. Measure `P_cold` (noise source OFF) and `P_hot` (noise source ON).
4. Compute `Y = P_hot_lin / P_cold_lin` and `NF = ENR - 10*log10(Y - 1)`.
5. Apply corrections for attenuator/cable loss, measurement bandwidth /
   FFT RBW, and ENR frequency-interpolated value.
6. Log every point to CSV (see schema below) and plot NF vs Gain Index.

Full step-by-step instructions: [docs/measurement_manual.md](docs/measurement_manual.md).

## CSV Log Schema

```
Gain_Index,Total_Gain_dB,RX_Gain_UHD_dB,Freq_MHz,P_cold_dBm,P_hot_dBm,NF_dB
```

## Project Layout

```
AD9361_Noise_Figure_Measurement/
├── README.md
├── docs/
│   ├── measurement_manual.md      Step-by-step procedure
│   ├── calibration_procedure.md   Attenuator/cable/ENR/bandwidth calibration
│   ├── uncertainty_analysis.md    Uncertainty budget and worksheet
│   └── gain_tables/               AD9361 Gain Index -> Total Gain (dB) tables
├── flowgraphs/
│   └── nf_measurement.grc         GNU Radio Companion flowgraph
├── scripts/
│   ├── nf_yfactor.py              Y-factor NF math + corrections
│   ├── run_nf_sweep.py            UHD gain-sweep capture automation
│   └── plot_nf.py                 NF vs Gain Index plotting
├── data/
│   ├── raw/                       Raw captures / per-run CSV logs
│   └── processed/                 Cleaned/combined CSV logs
└── results/
    └── plots/                     NF vs Gain Index figures
```

## Deliverables

- [x] Project scaffold (this repo)
- [ ] Step-by-step measurement manual — [docs/measurement_manual.md](docs/measurement_manual.md)
- [ ] GNU Radio Companion flowgraph (USRP Source, FFT, Python power block, CSV logging)
- [ ] Calibration procedure (attenuator, cable, bandwidth/RBW, absolute offset)
- [ ] NF vs Gain Index curves at 920 MHz and 2190 MHz
- [ ] Uncertainty analysis (ENR tolerance, attenuator/cable loss, USRP gain
      variation, temperature, bandwidth, averaging, ADC quantization)

## Known Gaps / Must-Fill Before Running

- **AD9361 gain tables are not fabricated here.** `docs/gain_tables/*.csv`
  are templates with the Gain Index column populated and the Total Gain (dB)
  column left blank. Fill them from the AD9361 Reference Manual (UG-570) gain
  table appendix or the authoritative driver source — see
  [docs/gain_tables/README.md](docs/gain_tables/README.md) for exactly where
  to get them. Do not guess these values; they are chip- and band-specific
  and the whole NF calculation depends on them being correct.
- The GNU Radio flowgraph has not been opened/validated in GRC (no GNU Radio
  install / B210 hardware available in this environment) — validate the
  block wiring and sample rate/decimation choices on your bench before
  trusting captured data.
- Noise source hot/cold switching is assumed to be manual or GPIO-controlled;
  wire this up per your specific noise source in `scripts/run_nf_sweep.py`.
- **No Python interpreter, UHD, or GNU Radio is installed in this
  environment**, so `scripts/*.py` have been reviewed by hand but not
  executed. Run `scripts/nf_yfactor.py` standalone (it has a built-in sanity
  check in `__main__`) and `scripts/run_nf_sweep.py --dry-run` first on your
  own machine to confirm they behave as expected before a real session.

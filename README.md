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
| TX port | TX1 (disconnected/terminated during NF measurement) |
| Frequencies | 920 MHz, 2190 MHz (initial) |
| Signal path (Y-factor NF measurement) | Calibrated noise source -> RF cable (~1 dB loss) -> RX1 |
| Signal path (TX1 loopback/leakage check — separate, not used for NF) | TX1 -> 30 dB calibrated attenuator -> RF cable -> RX1 |

**The 30 dB attenuator is only needed to protect RX1 from TX1's own output
power during a TX1 loopback/leakage check — it is a different signal path
for a different purpose, and must NOT be inserted between the calibrated
noise source and RX1.** A calibrated noise source outputs very low power
(no protection pad required), and 30 dB of loss there would crush the
ENR available at RX1 to the point of being unmeasurable — see the worked
example in [scripts/nf_yfactor.py](scripts/nf_yfactor.py)'s `__main__` and
the note in [docs/calibration_procedure.md](docs/calibration_procedure.md).

Cable loss in the noise-source path is still a measured value fed into the
NF calculation and the [uncertainty budget](docs/uncertainty_analysis.md) —
never assumed nominal.

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

1. Sweep RX gain. Recommended: `run_nf_sweep.py --auto-gain` reads the
   B210's own `get_rx_gain_range()`/`get_rx_gain()` rather than trusting a
   transcribed datasheet table (see [docs/gain_tables](docs/gain_tables/) for
   why — the AD9361 full gain table is only nominally 1 dB/step and some
   parts flatten above ~58 dB per ADI's own forum reports). A verified
   static `--gain-table` CSV is supported as an alternative.
2. For each gain point, command it via UHD (`set_rx_gain`) and read back the
   actual applied value.
3. Measure `P_cold` (noise source OFF) and `P_hot` (noise source ON).
4. Compute `Y = P_hot_lin / P_cold_lin` and `NF = ENR - 10*log10(Y - 1)`.
5. Apply corrections for cable loss (and attenuator loss too, if your
   specific bench setup does place a pad in the noise-source path —
   see the Hardware Setup note above on why this project's setup doesn't),
   measurement bandwidth / FFT RBW, and ENR frequency-interpolated value.
6. Log every point to CSV (see schema below) and plot NF vs Gain Index.

Full step-by-step instructions: [docs/measurement_manual.md](docs/measurement_manual.md).

## SNR-from-live-IQ Analysis (no ENR needed)

Since a calibrated noise source with a known ENR isn't available yet,
`scripts/run_snr_sweep.py` provides a complementary, self-contained
analysis: it sweeps Gain Index, captures live IQ, and computes
`SNR = strongest FFT bin - median noise floor` at each point, using
whatever is actually present at the antenna — no ENR or hot/cold cycling
required. This is not a calibrated NF measurement, but it's a real,
gain-dependent characterization from live hardware. See
[docs/reference_ad9361_nf_curve.md](docs/reference_ad9361_nf_curve.md) for
how this cross-validates against ADI's own (confidential, cited-not-included)
published NF vs. Gain Index behavior.

`scripts/snr_iq_sweep.py` extends this into the complete step-by-step
method: per Gain Index it logs SNR, an AD9361 RSSI sensor reading, and a
software-computed ADC-clipping check, and saves IQ diagnostic plots
(constellation, I/Q vs time, spectrum) at a subset of gain indices. See
[docs/snr_iq_method.md](docs/snr_iq_method.md) — including a verified
finding that UHD's `rssi` sensor is **not live** in manual-gain mode on
this hardware (confirmed by varying real input power 50 dB at fixed RX
gain and seeing zero change), and that UHD exposes no raw AD9361 SPI
register access at all, so genuine LNA/ADC "detector register" readback
isn't available through this API.

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

- **Correction: early real-hardware captures used the wrong UHD channel.**
  `real_power_vs_gain_*.png`, `signal_power_920MHz.png`, and
  `signal_power_2190MHz*.png` were captured on UHD channel 0
  (subdev `FE-RX2`/`FE-TX2`). `scripts/tx_tone_probe.py` later confirmed,
  by transmitting a known tone on TX1 and checking which RX channel
  actually received it, that this project's physical TX1/RX1 ports are
  **channel 1** (subdev `FE-TX1`/`FE-RX1`), not channel 0. All scripts now
  default `--channel`/`--rx-channel`/`--tx-channel` to 1. The channel-0
  captures are kept in the repo as historical results (they're still
  real, valid data — just from a different physical port than "RX1"),
  but treat anything found on channel 0 as informational only. The
  `snr_loopback_2190MHz.png` result (`run_snr_sweep_loopback.py`) is the
  first capture confirmed on the correct channel, validated with a known
  TX-generated tone rather than an ambient signal.
- **AD9361 gain tables are not fabricated here.** `docs/gain_tables/*.csv`
  are templates with the Gain Index column populated and the Total Gain (dB)
  column left blank, for anyone who wants canonical AD9361 gain-index
  labeling. The recommended path instead is `run_nf_sweep.py --auto-gain`,
  which sweeps the B210's own reported gain range rather than needing this
  table at all — see [docs/gain_tables/README.md](docs/gain_tables/README.md)
  for why (ADI's own datasheet says the full table is only *nominally*
  1 dB/step, and EngineerZone reports describe it flattening above ~58 dB on
  some parts, so a copied table isn't safe to trust without independent
  verification against your specific part).
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

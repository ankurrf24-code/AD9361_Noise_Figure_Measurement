# Calibration Procedure

Everything in the Y-factor NF result depends on the numbers gathered here.
Do this before every measurement campaign (and re-check if cables/attenuator
are swapped or reconnected).

## 1. Attenuator Loss

The 30 dB pad is a nameplate value, not a calibration value.

1. Using a VNA (or signal generator + power meter substitution method),
   measure S21 (insertion loss) of the attenuator at 920 MHz and 2190 MHz.
2. Record actual loss, e.g. `L_atten_920 = 30.15 dB`, `L_atten_2190 = 30.4 dB`.
3. Note the attenuator's stated uncertainty from its cal certificate (feeds
   the uncertainty budget in `uncertainty_analysis.md`).

## 2. Cable Loss

1. Measure the RX cable's insertion loss (VNA S21, or substitution method) at
   920 MHz and 2190 MHz — do not assume the nominal "~1 dB".
2. Record `L_cable_920`, `L_cable_2190`.

## 3. Total Path Loss

```
L_path(f) = L_atten(f) + L_cable(f)
```

Compute this per frequency. This is the value used to refer the noise
source's ENR to the RX1 reference plane (see Section 6).

## 4. Noise Source ENR

1. Pull ENR(f) from the noise source's calibration certificate at 920 MHz and
   2190 MHz (interpolate from the cal table if exact frequencies aren't
   listed — linear interpolation in dB is standard for narrow spacing).
2. Record the cal certificate's stated ENR uncertainty (typically 0.1-0.3 dB)
   — feeds the uncertainty budget.
3. Confirm the reference temperature T0 the ENR is defined against (almost
   always 290 K / 16.85 C) and record ambient temperature at time of
   measurement — a large delta from 290 K adds a correction term (see
   `uncertainty_analysis.md`).

## 5. Bandwidth / FFT RBW Calibration

The Y-factor power measurement must integrate a known, calibrated noise
bandwidth.

1. Record the sample rate and FFT size used in the flowgraph/script.
2. Compute RBW = sample_rate / FFT_size (Hz per bin), and the total
   integrated bandwidth = RBW * (number of bins summed).
3. If using a window function (e.g. Hann) for the FFT, record its
   noise-equivalent bandwidth (NEBW) correction factor (Hann: 1.5) and apply
   it: `effective_BW = RBW * NEBW * num_bins`.
4. This effective bandwidth is only needed if you are computing absolute
   noise power spectral density; for the ratio-based Y-factor
   (`Y = P_hot/P_cold`) the bandwidth cancels as long as it is identical for
   hot and cold measurements. Still record it — it matters if you cross-check
   against a theoretical kTB noise floor.

## 6. Absolute Power Reference / Offset Calibration

UHD/AD9361 reports relative ADC counts, not calibrated dBm, unless corrected.

1. Inject a known CW signal of known power (e.g. -30 dBm from a calibrated
   signal generator) at the RX1 connector.
2. Capture and measure the reported FFT bin power for that tone.
3. Compute the offset: `dBm_offset = known_input_dBm - measured_raw_dB`.
4. Apply `dBm_offset` to all subsequent power readings (`P_cold_dBm`,
   `P_hot_dBm`) at that same gain setting. **Repeat this offset calibration
   at every gain index used in the sweep** — the offset is gain-dependent
   because it captures the actual analog+digital gain of the chain, not just
   a fixed ADC scale factor.

## 7. Referencing the Noise Source to the RX1 Plane

The noise source's ENR is defined at the noise source's own output connector,
not at RX1. Since the source feeds through the attenuator + cable before
reaching RX1, the *available* ENR at RX1 is:

```
ENR_at_RX1(f) = ENR_source(f) - L_path(f)
```

Use `ENR_at_RX1(f)` in the NF formula, **not** the raw source ENR — this is
the correction called out in the project objective ("apply corrections for
attenuator, cable"). See `scripts/nf_yfactor.py` for the implementation.

## 8. Record-Keeping

Log all of the following alongside every measurement session:

- Attenuator loss (920 MHz, 2190 MHz) + uncertainty
- Cable loss (920 MHz, 2190 MHz) + uncertainty
- Noise source ENR (920 MHz, 2190 MHz) + uncertainty, and cal cert ID/date
- Ambient temperature
- Sample rate, FFT size, window function, number of averages
- Power offset calibration value per gain index
- Date, operator, equipment serial numbers

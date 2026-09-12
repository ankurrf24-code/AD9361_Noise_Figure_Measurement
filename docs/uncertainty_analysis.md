# Uncertainty Analysis

NF measured by the Y-factor method carries a combined standard uncertainty
from several independent sources. This document defines the budget and how
to compute the combined uncertainty (RSS method) for each (Gain Index,
Frequency) point.

## 1. Sources of Uncertainty

| Source | Typical magnitude | Notes |
|---|---|---|
| ENR calibration uncertainty (`u_ENR`) | 0.1-0.3 dB (see noise source cal cert) | Dominant term at low Y-factor / low NF |
| Attenuator loss uncertainty (`u_atten`) | 0.05-0.2 dB | From VNA cal or attenuator datasheet |
| Cable loss uncertainty (`u_cable`) | 0.05-0.15 dB | From VNA cal |
| USRP RX gain repeatability (`u_gain`) | 0.1-0.5 dB | Run repeated gain-set/read-back cycles to characterize; AD9361 gain steps are not perfectly monotonic/repeatable across retunes |
| Temperature drift (`u_temp`) | varies | ENR reference is 290 K; ambient deviation and DUT self-heating both contribute — track ambient T during the run |
| Bandwidth / RBW error (`u_BW`) | small if Y-factor ratio is used with fixed BW | Only matters if comparing against absolute kTB; still budget FFT bin/window uncertainty |
| Averaging / estimator variance (`u_avg`) | scales as `1/sqrt(N_averages)` | Compute empirically from repeated hot/cold pairs (Section 7 of measurement manual) |
| ADC quantization noise (`u_adc`) | small at moderate-to-high gain, grows at low gain / low signal levels | Relevant mainly at low Gain Index where signal is close to the ADC noise floor |
| Mismatch uncertainty (VSWR of source/attenuator/RX) | can be significant, often overlooked | Optional refinement — requires source and RX return loss data |

## 2. NF Sensitivity to Each Input

From `NF_dB = ENR_dB - 10*log10(Y - 1)`, with `Y = 10^((P_hot-P_cold)/10)`:

- `dNF/dENR = 1` — a 1 dB ENR error is a 1 dB NF error, directly.
- `dNF/dY = -10 / (ln(10) * (Y-1))` — sensitivity to the hot/cold power ratio
  grows sharply as Y approaches 1 (i.e., at high NF / low excess noise
  relative to receiver noise, or when the receiver's own noise dominates).
  This is the reason low-Y measurements (weak noise source relative to
  receiver noise) are noisier — worth flagging in results if Y < ~3 dB.
- Attenuator/cable loss uncertainty enters directly into `u_ENR_at_RX1`
  (Section 7 of the calibration doc) since `ENR_at_RX1 = ENR_source - L_path`.

## 3. Combined Uncertainty (RSS)

For each measurement point, combine uncorrelated sources in quadrature:

```
u_NF = sqrt( u_ENR^2 + u_atten^2 + u_cable^2 + u_gain^2
           + u_temp^2 + u_BW^2 + u_avg^2 + u_adc^2 )
```

Report expanded uncertainty at k=2 (approx. 95% confidence):
`U_NF = 2 * u_NF`.

## 4. Worksheet

Fill in per frequency (values are examples — replace with measured figures):

| Source | 920 MHz (dB) | 2190 MHz (dB) |
|---|---|---|
| u_ENR | | |
| u_atten | | |
| u_cable | | |
| u_gain | | |
| u_temp | | |
| u_BW | | |
| u_avg | | |
| u_adc | | |
| **u_NF (RSS)** | | |
| **U_NF (k=2)** | | |

## 5. Practical Notes

- `u_gain` and `u_adc` are expected to be **gain-index-dependent** — at low
  gain indices, quantization/noise-floor effects dominate; at high gain
  indices, gain-step repeatability and possible compression dominate. Do not
  apply a single flat uncertainty across all 77 indices without checking this.
- Recompute `u_avg` per point (or per bucket of nearby gain indices) from
  the actual observed standard deviation of repeated hot/cold pairs — Section
  7 of the measurement manual — rather than assuming a theoretical value.
- Present final NF vs Gain Index plots with error bars using `U_NF` (k=2).

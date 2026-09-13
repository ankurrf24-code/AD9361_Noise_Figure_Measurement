# Relative NF Proxy (not a calibrated Noise Figure)

`scripts/relative_nf_proxy.py` post-processes an existing SNR-vs-Gain-Index
sweep CSV (no new hardware measurement) into a relative metric:

```
Relative_NF_dB_proxy(gain_index) = SNR_dB(best_gain_index) - SNR_dB(gain_index)
```

using the best (highest) observed SNR in the sweep as a 0 dB reference.

## Why this is physically meaningful, not arbitrary

The AD9361's "full gain table" mode inserts attenuation ahead of the LNA at
low gain indices, which directly degrades the chip's own noise figure (per
the Friis cascade formula, loss ahead of an amplifier adds directly to
system NF). Separately, at low gain the ADC's own quantization noise
(roughly fixed in absolute terms) becomes a larger fraction of whatever
signal reaches it. Both effects show up as SNR degradation at low gain
index, and this proxy captures their combined size in relative terms.

## Why it's not a calibrated absolute NF

Converting "SNR got worse by X dB" into "NF is Y dB" needs a known input
signal power or a calibrated ADC noise floor as an anchor point (see
`docs/measurement_manual.md`'s Y-factor method, or the gain method's
absolute-power-calibration requirement in `docs/calibration_procedure.md`
Section 6). Without one, the two real effects above can't be cleanly
separated, and there's no zero point traceable to an absolute reference.
Treat this as "how much worse is this gain index than the best one, in
relative dB" -- not "the NF of the AD9361 at this gain index in absolute dB".

## Results (2190 MHz, TX1 -> attenuator -> RX1 loopback, TM1.1 sweeps)

`results/plots/relative_nf_proxy_2190MHz.png`:

| | Best (0 dB ref) | Worst relative NF proxy |
|---|---|---|
| 5 MHz | 10.29 dB SNR @ Gain Index 76 | ~9.5 dB, flat across Gain Index 0-~20 |
| 20 MHz | 5.65 dB SNR @ Gain Index 76 | ~5.8 dB @ Gain Index 0 |

Caveat on the 5 MHz "worst" point: Gain Index 9 is reported as the single
worst point (9.48 dB), but this is not a meaningfully distinct feature --
Gain Indices 0-~20 all sit in the same pre-detection-threshold band with
SNR hovering at 0.8-1.0 dB (see the raw CSV), and gain 9's reading is only
marginally the lowest among several near-identical noisy values in that
flat region. The honest read is "gain indices 0-~20 are all roughly equally
poor", not that gain 9 specifically stands out.

Both curves reproduce the same qualitative shape as ADI's own confidential
NF-vs-Gain-Index reference (see `docs/reference_ad9361_nf_curve.md`): poor
at low gain index, improving toward the top of the range. This is a
meaningful cross-check of the general behavior, even though the absolute
dB values here are a relative proxy, not calibrated NF.

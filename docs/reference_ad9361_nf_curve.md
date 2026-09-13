# Reference: AD9361 Typical NF vs. Gain Index (external, confidential)

Analog Devices publishes typical Noise Figure vs. Gain Index curves for the
AD9361 in a separate application note — **not** the main AD9361 datasheet,
and **not** UG-570 — titled:

> **AD9361 Gain Control & RSSI User Guide**, Appendix 3: "Noise Figure (NF)
> vs. Gain Index Plots"

This appendix includes, among others:
- Figure 13: NF vs. Gain Index, Full Table, Rx LO = 920 MHz
- Figure 15: NF vs. Gain Index, Full Table, Rx LO = 2120 MHz

— i.e. curves at (or very close to, for the second) both of this project's
target frequencies, straight from Analog Devices, with balun/connector/trace
losses de-embedded (transceiver-only NF; a real system will read higher).

**This document is marked "ADI Confidential" on every page and is
deliberately not included, quoted numerically, or reproduced in this public
repository.** If you have your own NDA-covered copy, use it directly rather
than relying on any summary here. Contact Analog Devices / your FAE if you
need a copy and don't already have one.

## Qualitative trend (non-confidential characterization only)

Without reproducing ADI's figures or exact values: NF vs. Gain Index for the
AD9361 in full-table gain mode is strongly non-flat. It is poor (multiple
tens of dB) through most of the lower gain-index range, drops sharply
somewhere in the mid range, and only approaches the part's best-case NF
(a few dB) near the top of the gain-index range. This is a consequence of
how full-table gain control distributes attenuation ahead of the LNA at low
gain settings.

## Why this matters for this project

This independently explains a result we already found empirically on real
hardware (see `scripts/run_snr_sweep.py`, `results/plots/signal_power_920MHz.png`):
at 920 MHz, a real environmental signal was undetectable above the noise
floor (peak FFT bin location was random from capture to capture, the
signature of pure noise) below Gain Index ~64, and became consistently
detectable at a fixed frequency offset from Gain Index ~64 upward. That
threshold lines up with where ADI's own published curve shows NF finally
dropping to a good value in this project's gain-index-vs-frequency
neighborhood -- two independent methods (a confidential vendor reference,
and our own live IQ capture) agreeing on the same qualitative behavior.

This is a good sanity check on the SNR sweep methodology, but note it is
**not** a substitute for this project's actual goal (a calibrated,
traceable Y-factor NF measurement per `docs/measurement_manual.md`) --
it only cross-validates the qualitative shape of gain-dependent
sensitivity, not calibrated NF numbers.

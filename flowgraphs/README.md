# nf_measurement.grc

A GNU Radio Companion (3.10 YAML format) flowgraph skeleton:

```
UHD USRP Source (RX1) -> Stream-to-Vector -> FFT -> Complex-to-Mag^2 -> Python (epy) power logger -> CSV
```

## Status: unverified skeleton

This file was hand-authored and **has not been opened in GNU Radio Companion
or run against a B210** (no GNU Radio install or hardware available in this
environment). Before relying on it:

1. Open it in GRC and check for any red/broken blocks (parameter names do
   drift between GNU Radio versions — this targets the 3.10.x block set).
2. Verify the `uhd_usrp_source` block parameters match your GRC/UHD version's
   expected fields (antenna, gain, clock/time source names in particular).
   Note: this is single-daughterboard/single-channel (RX1) config.
2. Confirm the embedded Python block (`power_logger_0`) compiles under the
   `gnuradio.gr.sync_block` API version installed on your system.
3. Regenerate and run a short capture to confirm CSV rows are appearing
   before doing a real measurement session.

## What it does vs. what it doesn't

- It captures and logs raw average power (converted to dBFS + a configurable
  offset) continuously to a CSV, at whatever gain/frequency the top-level
  variables (`freq`, `rx_gain`, `samp_rate`, `fft_size`) are set to.
- It does **not** implement the automated 0-76 gain-index sweep, the
  hot/cold noise-source switching sequence, or the Y-factor NF calculation.
  Those are the job of `scripts/run_nf_sweep.py` (which uses the UHD Python
  API directly rather than GRC, so it can drive the full sweep
  programmatically) and `scripts/nf_yfactor.py`.
- Treat this flowgraph as a manual/interactive capture aid (e.g. for
  eyeballing spectrum and confirming the signal path is alive) or as a
  starting point to build a full GRC-based sweep flowgraph with QT range
  widgets, variable-driven gain, and a message-passing control block if you
  prefer GRC over the Python-API script for automation.

## Editing the embedded Python block

If you edit `power_logger_0`'s source in GRC, keep the CSV write on the
`work()` hot path minimal (avoid per-sample Python-level work at high sample
rates) — the vectorized FFT-frame-at-a-time averaging in the current version
is deliberately structured to keep per-call overhead low.

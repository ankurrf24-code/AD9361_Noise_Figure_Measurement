# AD9361 Gain Tables

The AD9361 in manual "full table" gain-control mode maps a **Gain Index**
(0-76) to a specific **Total Gain (dB)** value and internal register
settings. This mapping is **band-specific** — there is one table for RF
input 200-1300 MHz and a different one for 1300-4000 MHz — and it is defined
by Analog Devices, not something to estimate or interpolate.

## Recommended: skip the static table, use `--auto-gain`

Per ADI's own documentation, the standard full gain table is only
*nominally* 1 dB/step (AD9361 Rev. F datasheet: "Gain Step 1 dB", "Gain Index
= 76 (Maximum Setting)"), and multiple users on ADI's EngineerZone forum
report the actual reported gain flattening out above roughly 58 dB rather
than continuing linearly to index 76 (e.g. the "AD9361 custom gain table"
and "AD9361 no-OS for custom gain table" EngineerZone threads). UHD's own
`ad9361_gain_tables.h` stores raw register/LNA/mixer/TIA control words per
index, not dB values, so it can't be read as a dB lookup either.

Given that, **`scripts/run_nf_sweep.py --auto-gain` is the recommended path**:
it queries the connected B210's actual `get_rx_gain_range()` and sweeps at
the device's own reported step, logging the real `get_rx_gain()` readback at
every point. That's ground truth from the specific part on your bench,
rather than a value trusted from a datasheet/forum transcription. The CSVs
below are kept as an optional path for anyone who has independently
verified a canonical table and wants AD9361 gain-index labeling instead of
device-reported values.

## Why the CSVs here are templates, not filled-in data

The exact per-index dB values are chip-specific calibration/design data.
Reproducing them from memory risks silent transcription errors that would
corrupt every NF number computed downstream — for a metrology project that's
worse than leaving them blank. **Pull the real table from one of these
authoritative sources:**

1. **AD9361 Reference Manual (UG-570)**, "Gain Control" chapter — contains
   the full Gain Index -> Gain (dB) table for both frequency ranges.
2. **Analog Devices `no-OS` driver source** (`ad9361_api.c` / `ad9361.c` in
   the ADI no-OS or Linux IIO `ad9361` driver repos) — contains the actual
   hardcoded gain table arrays used by the silicon, cross-referenceable
   against UG-570.
3. **UHD source** — UHD's B200/AD9361 driver
   (`host/lib/usrp/common/ad9361_driver/`) implements gain control on top of
   libad9361; check there for how UHD maps a requested dB value to a gain
   index/register write, which confirms the effective resolution UHD exposes
   via `set_rx_gain()`.
4. If you have physical access to the ADI IIO Oscilloscope / `iio_attr`
   tooling against an AD9361 part, you can also read back the active gain
   table directly from the device registers.

Cross-check whichever source you use against at least one other before
trusting it for measurement.

## Files

- `gain_table_200_1300MHz.csv` — for 920 MHz measurements
- `gain_table_1300_4000MHz.csv` — for 2190 MHz measurements

Both have `Gain_Index` populated (0-76) and `Total_Gain_dB` **blank** —
fill `Total_Gain_dB` from the sources above before running
`scripts/run_nf_sweep.py`. The sweep script will refuse to run against a CSV
with missing gain values (see the script's validation check).

## UHD gain vs. AD9361 Gain Index

UHD's `set_rx_gain()` API takes a gain in **dB**, not a raw table index. The
workflow here is: look up `Total_Gain_dB` for a given `Gain_Index` from these
tables, then call `set_rx_gain(Total_Gain_dB)`. UHD will map that dB request
to the nearest supported hardware step internally — always read back
`get_rx_gain()` after setting it and log the actual applied value
(`RX_Gain_UHD_dB` in the CSV schema), since it may not exactly equal the
requested `Total_Gain_dB`.

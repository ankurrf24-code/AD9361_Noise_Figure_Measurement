# Step-by-Step SNR + IQ Characterization vs Gain Index

`scripts/snr_iq_sweep.py` is the combined method: for every point in the
Gain Index sweep it captures live IQ, computes SNR, reads AD9361's RSSI
sensor, checks for ADC clipping, and (for a configurable subset of gain
indices) saves an IQ diagnostic plot.

## What each column means

| Column | Meaning |
|---|---|
| `Gain_Index` | Sweep index (0-76 typically, from `--auto-gain`) |
| `RX_Gain_UHD_dB` | Actual applied gain, read back from the device |
| `Signal_Power_dB`, `Noise_Floor_dB`, `SNR_dB` | From the FFT: strongest bin vs median noise floor (see `run_snr_sweep.py`) |
| `Peak_Bin_Offset_Hz` | Frequency offset of the detected peak, relative to center |
| `RSSI_dB` | AD9361's own internal RSSI sensor (`uhd.MultiUSRP.get_rx_sensor('rssi', channel)`) |
| `ADC_Peak_Frac` | Max `\|sample\|` in the capture as a fraction of ADC full scale (1.0) |
| `ADC_Overload` | `True` if `ADC_Peak_Frac` exceeds `--overload-threshold` (default 0.9) |
| `IQ_Plot_File` | Path to the saved diagnostic plot, if this gain index was one of the sampled points |

## RSSI: verified NOT to be a live measurement in manual-gain mode

UHD exposes `rssi` as a sensor on the AD9361 RX chain, but on this hardware
(B210, UHD 4.10.0, manual gain control via `set_rx_agc(False)`) it does
**not** track real changes in received signal power. We verified this with
three tests, and the first two looked promising before the third overturned
them -- worth walking through since the wrong conclusion was almost shipped:

1. Ambient signal, RX gain swept 0-76 dB: RSSI went from -50.75 dB down to
   -111.5 dB -- but this later turned out to be **exactly** -1.00 dB of
   RSSI change per +1 dB of gain change, every single step, 76 dB total for
   76 dB of gain. That precision is a red flag for a real RF measurement
   (real signals have scatter); it looks like simple arithmetic.
2. Known, fixed TX-generated tone looped back through the attenuator, RX
   gain swept 0-76 dB: RSSI stayed at exactly -67.25 dB the entire time.
   This looked like confirmation that RSSI is gain-compensated / antenna-
   referred -- **but this test cannot actually distinguish that from
   test 1's arithmetic hypothesis**, because the real input power was also
   held constant (TX gain never changed). Both hypotheses predict the same
   flat result when the real signal doesn't change.
3. The discriminating test: **hold RX gain fixed** at 40 dB and vary the
   real input power by sweeping TX gain from 10 to 60 dB (a 50 dB real
   change). If RSSI were a genuine sensor, it must move. It did not --
   `rssi` read exactly -67.25 dB at every TX gain from 10 to 60 dB.

Conclusion: in this configuration, `rssi` does not respond to real input
power at all. It reads as if computed once (at some initialization point or
AGC-lock event) and then never re-measured — remaining static regardless of
what's actually happening at the antenna. **Do not trust `RSSI_dB` in this
CSV as a live signal-strength indicator** -- it's logged for completeness
and to preserve this finding, not because it's meaningful in this mode.

What *is* trustworthy per gain index, both verified to respond correctly to
real signal changes throughout every sweep in this project: `SNR_dB` (from
the FFT, tracks real signal locks/losses) and `ADC_Peak_Frac` (the actual
maximum sample magnitude in each capture, which visibly rises with both
gain and real injected TX power in every run so far).

Getting a genuinely live RSSI would need further investigation this project
hasn't done -- e.g. checking whether briefly enabling AGC (`set_rx_agc(True)`)
before reading the sensor forces a fresh measurement, or whether UHD's B200
driver source documents an explicit re-arm/refresh call. Don't assume it
works without re-verifying the way we did here.

## What's *not* available: raw AD9361 registers

UHD's Python API does not expose a generic SPI register peek/poke
interface for the AD9361 (`dir(uhd.usrp.MultiUSRP)` has no `peek`/`poke`/
`spi` methods; only `get_gpio_attr`/`set_gpio_attr` for FPGA-side GPIO,
which is unrelated). This means:

- There is **no way through UHD** to read the AD9361's internal LNA gain-
  state register, mixer/TIA gain-table index register, or the chip's
  internal ADC/ AGC peak-detector magnitude register directly.
- `RSSI_dB` (above) is the closest real, verified substitute UHD provides.
- `ADC_Peak_Frac`/`ADC_Overload` (this script) is a **software-computed**
  substitute for an ADC peak/overload detector -- it's the actual maximum
  sample magnitude observed in the capture, not a hardware register value.
  It's a legitimate and useful clipping check, just not the same thing as
  reading AD9361's internal overload-detector register.

If you need genuine SPI-register-level access (e.g. to read the exact
active gain-table index, or the chip's own overload/peak-detector bits),
that requires Analog Devices' own tooling (libiio / IIO Oscilloscope / the
no-OS driver via JTAG or a direct SPI connection) rather than UHD -- UHD's
B200/B210 driver deliberately abstracts this away from the user. This is
worth knowing rather than assuming an API exists that doesn't.

## Usage

Ambient signal (like `run_snr_sweep.py`, but with IQ plots and RSSI/ADC
diagnostics added):

```
python scripts/snr_iq_sweep.py --freq 920e6 --auto-gain \
    --out data/raw/snr_iq_920MHz.csv --plot-dir results/plots/iq_920MHz
```

Controlled loopback (like `run_snr_sweep_loopback.py`, with the same
additions):

```
python scripts/snr_iq_sweep.py --freq 2190e6 --auto-gain --tx-tone \
    --out data/raw/snr_iq_2190MHz.csv --plot-dir results/plots/iq_2190MHz
```

# G-FR1-A1-1 Chain A: IQ Capture & Spectrum/SNR Analysis (USRP B210)

## Objective

Generate and capture IQ samples for "G-FR1-A1-1" in Chain A using GNU
Radio, then analyze spectrum and SNR in Python.

> **Note on "G-FR1-A1-1"**: this exact designator doesn't exist in any
> local reference material (searched exhaustively). This project generates
> the closest real match instead: standard 3GPP **NR-FR1-TM1.1**. See
> [docs/parameters.md](docs/parameters.md) for the full reasoning.

## Workflow

1. **Transmit + Capture** ([flowgraphs/capture_chain_a.py](flowgraphs/capture_chain_a.py)) --
   one GNU Radio flowgraph, one process: builds TX (Chain A, fixed gain and
   bandwidth) when `--tx-state on`, always builds RX (Chain A, manual gain
   index), captures a fixed duration to a `.bin` file, then exits.
   **TX and RX must be in the same process** -- the B210 is a
   single-session USB device and a second process cannot open it while
   another already holds it (found the hard way; see
   [docs/parameters.md](docs/parameters.md)).
2. **Analyze** ([analysis/analyze_iq.py](analysis/analyze_iq.py)) -- plain
   Python (no GNU Radio needed): loads the `.bin` captures, plots spectrum
   via FFT, computes SNR, and compares TX OFF vs TX ON at each gain index.

See [docs/parameters.md](docs/parameters.md) for the exact fixed
gain/bandwidth values used, why 5 MHz (not 20 MHz) is the working default,
and the two hardware/software issues found and fixed along the way.

## Usage

Run once per (gain index, TX state) combination, using `radioconda`'s GNU
Radio + UHD:

```
C:\Users\ankur\radioconda\python.exe flowgraphs\capture_chain_a.py --gain-index 10 --tx-state on
C:\Users\ankur\radioconda\python.exe flowgraphs\capture_chain_a.py --gain-index 10 --tx-state off
C:\Users\ankur\radioconda\python.exe flowgraphs\capture_chain_a.py --gain-index 70 --tx-state on
C:\Users\ankur\radioconda\python.exe flowgraphs\capture_chain_a.py --gain-index 70 --tx-state off
```

Then analyze (regular project Python, not radioconda):

```
python analysis\analyze_iq.py --bandwidth 5e6 --gain-indices 10 70
```

## Real Results (2190 MHz, 5 MHz BW, Chain A)

| Gain Index | TX State | In-band (dB) | Out-of-band (dB) | SNR (dB) |
|---|---|---|---|---|
| 10 | off | -67.85 | -68.65 | 0.80 |
| 10 | on | -67.34 | -68.22 | 0.87 |
| 70 | off | -41.99 | -42.75 | 0.76 |
| 70 | on | -33.28 | -42.68 | **9.40** |

At Gain Index 70, TX ON raises in-band power by ~8.7 dB while out-of-band
noise stays flat -- the clean signature of a real detected signal.

## Project Layout

```
├── README.md
├── requirements.txt
├── docs/
│   └── parameters.md           Fixed TX/RX parameter choices and full rationale
├── flowgraphs/
│   └── capture_chain_a.py      GNU Radio: generate + transmit + capture, Chain A
├── analysis/
│   └── analyze_iq.py           Spectrum (FFT) + SNR analysis, TX on/off comparison
└── capture/                    IQ .bin files land here (gitignored)
```

## Known Limitations

- Chain A (UHD channel 1) was confirmed empirically against this specific
  bench's wiring -- if your physical TX1/RX1 connections differ, re-verify
  before trusting results (see `docs/parameters.md`).
- 20 MHz bandwidth underflows massively on this machine even with TX alone
  (a genuine USB/host throughput ceiling, not a code bug) -- 5 MHz is the
  verified-working default.
- SNR here is computed as average in-band vs. out-of-band FFT power, not a
  calibrated, traceable Noise Figure -- that would require a calibrated
  noise source with known ENR and absolute power calibration, which this
  project's scope does not include.

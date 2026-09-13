"""
Simplified 3GPP-style NR downlink test waveform generator: full-resource-block
random QPSK CP-OFDM, similar in spirit to NR-FR1-TM1.1 (a common RF test
model: every allocated subcarrier filled with QPSK, used for ACLR/receiver
sensitivity style RF testing).

This is NOT a conformance-exact 3GPP TS 38.141 test model implementation --
notably it uses a constant cyclic prefix length per symbol rather than the
"long CP on the first symbol of each 0.5 ms slot" pattern real NR uses, and
carries no PSS/SSS/PBCH/DMRS reference signals, just a filled resource grid.
It is good enough for relative SNR-vs-gain-index characterization (occupied
bandwidth, PAPR, spectral shape are all realistic), not for actual 3GPP RF
conformance certification.

Standard 15 kHz-SCS NR channel bandwidth configurations used here (3GPP TS
38.101-1 Table 5.3.2-1):

    5 MHz  ->  25 RBs (300 subcarriers), FFT size 512,  sample rate 7.68 Msps
    20 MHz -> 106 RBs (1272 subcarriers), FFT size 2048, sample rate 30.72 Msps
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

NR_CONFIGS = {
    5e6: {"num_rbs": 25, "fft_size": 512, "samp_rate": 7.68e6},
    20e6: {"num_rbs": 106, "fft_size": 2048, "samp_rate": 30.72e6},
}

SCS_HZ = 15e3
CP_FRACTION = 144.0 / 2048.0  # normal-CP fraction of FFT size, 15 kHz SCS


@dataclass
class NRWaveform:
    samples: np.ndarray
    samp_rate: float
    occupied_bw_hz: float
    fft_size: int
    num_rbs: int
    num_subcarriers: int


def generate_nr_waveform(channel_bw_hz: float, num_symbols: int = 14, seed: int = 0) -> NRWaveform:
    """
    Generate `num_symbols` CP-OFDM symbols (default 14 = one 1 ms subframe at
    15 kHz SCS) with every allocated subcarrier filled with random QPSK.
    """
    if channel_bw_hz not in NR_CONFIGS:
        raise ValueError(f"Unsupported channel_bw_hz={channel_bw_hz}; supported: {list(NR_CONFIGS)}")

    cfg = NR_CONFIGS[channel_bw_hz]
    fft_size = cfg["fft_size"]
    num_rbs = cfg["num_rbs"]
    samp_rate = cfg["samp_rate"]
    num_subcarriers = num_rbs * 12
    occupied_bw_hz = num_subcarriers * SCS_HZ

    cp_len = round(fft_size * CP_FRACTION)
    rng = np.random.default_rng(seed)

    qpsk_alphabet = (1 + 1j) / np.sqrt(2) * np.array([1, -1, 1j, -1j])

    out = []
    half_sc = num_subcarriers // 2
    for _ in range(num_symbols):
        data = rng.choice(qpsk_alphabet, size=num_subcarriers)

        grid = np.zeros(fft_size, dtype=np.complex128)
        # Centered allocation: positive freqs [1 .. half_sc], negative freqs
        # [-half_sc .. -1], matching fftfreq/fftshift bin ordering (DC unused).
        grid[1:half_sc + 1] = data[half_sc:]
        grid[-half_sc:] = data[:half_sc]

        time_symbol = np.fft.ifft(grid) * np.sqrt(fft_size)
        with_cp = np.concatenate([time_symbol[-cp_len:], time_symbol])
        out.append(with_cp)

    samples = np.concatenate(out).astype(np.complex64)
    peak = np.max(np.abs(samples))
    if peak > 0:
        samples = (samples / peak * 0.5).astype(np.complex64)  # headroom for PAPR

    return NRWaveform(
        samples=samples,
        samp_rate=samp_rate,
        occupied_bw_hz=occupied_bw_hz,
        fft_size=fft_size,
        num_rbs=num_rbs,
        num_subcarriers=num_subcarriers,
    )


if __name__ == "__main__":
    for bw in NR_CONFIGS:
        wf = generate_nr_waveform(bw)
        papr_db = 10 * np.log10(np.max(np.abs(wf.samples) ** 2) / np.mean(np.abs(wf.samples) ** 2))
        print(f"BW={bw/1e6:.0f} MHz: {wf.num_rbs} RBs, {wf.num_subcarriers} subcarriers, "
              f"occupied={wf.occupied_bw_hz/1e6:.3f} MHz, samp_rate={wf.samp_rate/1e6:.2f} Msps, "
              f"{len(wf.samples)} samples, PAPR={papr_db:.2f} dB")

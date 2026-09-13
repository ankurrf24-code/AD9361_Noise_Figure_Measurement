"""
Y-factor Noise Figure calculation, with corrections for the attenuator/cable
path between the calibrated noise source and the RX1 reference plane.

Reference: standard Y-factor method.
    Y   = P_hot_lin / P_cold_lin
    NF  = ENR_dB - 10*log10(Y - 1)

See docs/calibration_procedure.md for where ENR_at_rx1 and the loss terms
come from -- they must be measured, not assumed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def dbm_to_linear_mw(dbm: float) -> float:
    return 10 ** (dbm / 10.0)


def db_to_linear(db: float) -> float:
    return 10 ** (db / 10.0)


def linear_to_db(x: float) -> float:
    if x <= 0:
        raise ValueError(f"linear_to_db: non-positive input {x}")
    return 10.0 * math.log10(x)


@dataclass
class PathLoss:
    """Measured loss between the noise source output and the RX1 connector."""

    attenuator_db: float
    cable_db: float

    @property
    def total_db(self) -> float:
        return self.attenuator_db + self.cable_db


def enr_at_rx1(enr_source_db: float, path_loss: PathLoss) -> float:
    """
    Refer the noise source's calibrated ENR (defined at its own output
    connector) to the RX1 reference plane, through the measured attenuator
    + cable loss. See docs/calibration_procedure.md section 7.
    """
    return enr_source_db - path_loss.total_db


def y_factor(p_hot_dbm: float, p_cold_dbm: float) -> float:
    """Linear Y = P_hot / P_cold, from powers expressed in dBm."""
    return db_to_linear(p_hot_dbm - p_cold_dbm)


def noise_figure_db(p_hot_dbm: float, p_cold_dbm: float, enr_db: float) -> float:
    """
    Standard Y-factor NF calculation.

    enr_db must already be referred to the plane where P_hot/P_cold were
    measured (i.e. use enr_at_rx1() first if the source feeds through a
    lossy path before reaching the receiver under test).
    """
    y = y_factor(p_hot_dbm, p_cold_dbm)
    if y <= 1.0:
        raise ValueError(
            f"Y-factor <= 1 ({y:.4f}); P_hot must exceed P_cold. "
            "Check noise source is actually switching ON, and that "
            "P_hot_dbm/P_cold_dbm were not swapped."
        )
    return enr_db - linear_to_db(y - 1.0)


def noise_figure_with_path_loss(
    p_hot_dbm: float,
    p_cold_dbm: float,
    enr_source_db: float,
    path_loss: PathLoss,
) -> float:
    """Convenience wrapper applying the attenuator/cable correction inline."""
    enr_db = enr_at_rx1(enr_source_db, path_loss)
    return noise_figure_db(p_hot_dbm, p_cold_dbm, enr_db)


def rss_uncertainty(*component_db: float) -> float:
    """Root-sum-square combination of independent uncertainty components (dB)."""
    return math.sqrt(sum(c * c for c in component_db))


if __name__ == "__main__":
    # Round-trip sanity check: assume a receiver with a known true NF,
    # derive the P_hot/P_cold that receiver would actually report, then
    # confirm noise_figure_db() recovers the same NF. This is self-consistent
    # (unlike picking an arbitrary P_hot-P_cold delta, which can produce a
    # physically impossible negative NF if it doesn't match the assumed ENR).
    path = PathLoss(attenuator_db=30.15, cable_db=1.05)
    enr_source_db = 15.2
    enr_effective = enr_at_rx1(enr_source_db, path)
    print(f"ENR at RX1: {enr_effective:.3f} dB "
          f"(source {enr_source_db:.2f} dB - path loss {path.total_db:.2f} dB)")

    true_nf_db = 5.0
    f_true = db_to_linear(true_nf_db)
    y_expected = 1.0 + db_to_linear(enr_effective) / f_true

    p_cold = -80.0
    p_hot = p_cold + linear_to_db(y_expected)
    nf = noise_figure_db(p_hot, p_cold, enr_effective)
    print(f"Assumed true NF: {true_nf_db:.3f} dB -> Y-factor: {y_expected:.6f} "
          f"(P_hot - P_cold = {p_hot - p_cold:.4f} dB)")
    print(f"Recovered NF: {nf:.3f} dB (should match assumed true NF)")

    u = rss_uncertainty(0.2, 0.1, 0.1, 0.3, 0.15, 0.05, 0.1, 0.1)
    print(f"Example combined uncertainty u_NF: {u:.3f} dB (U at k=2: {2*u:.3f} dB)")

    if path.total_db > 20:
        print(
            f"\nWARNING: {path.total_db:.1f} dB of loss between the noise "
            f"source and RX1 drives the Y-factor down to {y_expected:.6f} "
            f"(only {linear_to_db(y_expected):.4f} dB of P_hot-P_cold "
            "separation) for a receiver at this NF. That is likely below "
            "your measurement noise floor/repeatability -- see the note in "
            "docs/calibration_procedure.md. Consider a higher-ENR noise "
            "source or less loss between it and RX1."
        )

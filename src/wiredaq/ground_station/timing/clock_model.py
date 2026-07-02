"""
ClockModel — per-node clock reconstruction at the ground station (ADR 0002).

Each node stamps packets with its own free-running clock (`t_node_us`), uncorrected, and
that clock drifts relative to every other node's. To place samples from different nodes on
one timeline, the ground station fits, **per node**, the linear relationship between the
node's clock and its own reference clock (sampled at packet arrival):

    t_node_us  ≈  skew * t_ref_us + offset

`skew` is the node's tick rate relative to the reference, so ``(skew - 1) * 1e6`` is the
node's drift in **ppm** — the very ``drift_ppm`` :class:`SyntheticNode` injects, which makes
this model its own test oracle. :meth:`to_ref` inverts the fit to map a node timestamp back
onto the reference timeline; the node's own ``t_node_us`` is never overwritten, only paired
with a derived reference time.

Arrival time is a *noisy anchor*, not a timestamp: transport jitter and buffering perturb
each ``t_ref_us``, but least-squares averages that zero-mean noise out, so the recovered
skew is unbiased — jitter widens the estimate's confidence interval (:attr:`drift_ppm_stderr`)
without biasing it. Packet loss doesn't bias it either: the fit only ever sees the pairs
that actually arrived, never counts or gaps.

The fit is online (O(1) per packet, no stored history) using Welford's streaming
covariance, which stays numerically stable at the large microsecond magnitudes where naive
power sums (Σx²) would lose precision.

    ponytail: ordinary least squares. Under symmetric jitter the slope is already unbiased,
    which is all the oracle checks; swap in Theil–Sen / IRLS here if asymmetric outliers
    (one very-late packet) ever need rejecting.
"""

from __future__ import annotations

from math import inf, sqrt

_PPM = 1_000_000.0


class ClockModel:
    """Online estimate of one node's clock versus the ground-station reference clock."""

    def __init__(self, node_id: int) -> None:
        self.node_id = node_id
        self.n = 0
        self._mean_ref = 0.0
        self._mean_node = 0.0
        self._m_rr = 0.0  # Σ (t_ref − mean_ref)²
        self._m_nn = 0.0  # Σ (t_node − mean_node)²
        self._m_rn = 0.0  # Σ (t_ref − mean_ref)(t_node − mean_node)

    def update(self, t_node_us: int, t_ref_us: int) -> None:
        """Fold in one ``(t_node_us, t_ref_us)`` pair — one per received packet."""
        self.n += 1
        d_ref = t_ref_us - self._mean_ref
        d_node = t_node_us - self._mean_node
        self._mean_ref += d_ref / self.n
        self._mean_node += d_node / self.n
        # Deviations from the *updated* means complete Welford's co-moment updates.
        self._m_rr += d_ref * (t_ref_us - self._mean_ref)
        self._m_nn += d_node * (t_node_us - self._mean_node)
        self._m_rn += d_ref * (t_node_us - self._mean_node)

    @property
    def ready(self) -> bool:
        """True once there are enough distinct points to define a slope."""
        return self.n >= 2 and self._m_rr > 0.0

    @property
    def skew(self) -> float:
        """Node ticks per reference tick (1.0 until the fit is :attr:`ready`)."""
        return self._m_rn / self._m_rr if self.ready else 1.0

    @property
    def offset_us(self) -> float:
        """Intercept ``b`` in ``t_node ≈ skew * t_ref + b``."""
        return self._mean_node - self.skew * self._mean_ref

    @property
    def drift_ppm(self) -> float:
        """Recovered node drift in ppm — matches the injected ``drift_ppm`` at convergence."""
        return (self.skew - 1.0) * _PPM

    def to_ref(self, t_node_us: int) -> int:
        """Map a node timestamp onto the reference timeline (inverts the fit)."""
        skew = self.skew
        if skew == 0.0:
            return int(t_node_us)
        return round((t_node_us - self.offset_us) / skew)

    @property
    def residual_std_us(self) -> float:
        """Std-dev of the fit residuals (µs) — how tightly the pairs hug the line."""
        if self.n < 3 or self._m_rr <= 0.0:
            return 0.0
        ss_res = max(self._m_nn - self._m_rn * self._m_rn / self._m_rr, 0.0)
        return sqrt(ss_res / (self.n - 2))

    @property
    def drift_ppm_stderr(self) -> float:
        """Standard error of the recovered ppm — the estimate's confidence, widened by
        jitter and narrowed by more points. ``inf`` until enough points exist."""
        if self.n < 3 or self._m_rr <= 0.0:
            return inf
        var_res = max(self._m_nn - self._m_rn * self._m_rn / self._m_rr, 0.0) / (self.n - 2)
        return sqrt(var_res / self._m_rr) * _PPM

"""
bayesian.py
===========
Fourth layer of heavy lifting: Bayesian credible intervals for pass-odds.

WHY THIS EXISTS:
Our earlier ranges were normal-approximation bands: symmetric, fixed-width,
and naive at the edges. That approximation does three dishonest things:
  - near 95% it can report an upper bound of 100% (implying certainty);
  - near 4% it pins the lower bound at 0% (implying impossibility);
  - it ignores that uncertainty is ASYMMETRIC close to 0 and 1.

The honest, textbook tool is the Beta-Binomial conjugate model. We treat the
Monte Carlo pass rate as a posterior over the true pass probability:

    posterior  ~  Beta(alpha, beta)
    alpha = passes      + prior_a
    beta  = failures    + prior_b

with the Jeffreys prior Beta(0.5, 0.5) — the standard non-informative prior for
a binomial proportion. The credible interval is then the posterior's quantile
range. This is the SAME idea as "more data narrows the range", but done with
real probability theory instead of a fudge factor:
  - small samples  -> wide, automatically;
  - large samples  -> tight, automatically;
  - extremes        -> asymmetric and bounded in [0, 1], never 0% or 100%.

IMPLEMENTATION NOTE:
We deliberately avoid SciPy (not in the deploy image). The regularised
incomplete beta function is implemented with a Lentz continued fraction
(Numerical Recipes), and the quantile (inverse-CDF) via bisection. Pure-Python,
numpy already present, no new dependency.
"""

from __future__ import annotations
import math


# ---------------------------------------------------------------------------
# Regularised incomplete beta  I_x(a, b)  via Lentz's continued fraction
# ---------------------------------------------------------------------------
def _betacf(a: float, b: float, x: float) -> float:
    MAXIT = 200
    EPS = 3.0e-12
    FPMIN = 1.0e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < EPS:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta I_x(a, b) = CDF of Beta(a,b) at x."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    # Factor in front (log-gamma for stability)
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    else:
        return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _beta_ppf(q: float, a: float, b: float) -> float:
    """Inverse CDF (quantile) of Beta(a, b) by bisection on I_x(a,b) = q."""
    if q <= 0.0:
        return 0.0
    if q >= 1.0:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(80):  # ~1e-24 precision, plenty
        mid = 0.5 * (lo + hi)
        if _betai(a, b, mid) < q:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
# Jeffreys prior for a binomial proportion.
PRIOR_A = 0.5
PRIOR_B = 0.5


def credible_interval(pass_prob: float, n_effective: int | None,
                      cred: float = 0.80) -> tuple[float, float]:
    """Posterior credible interval for the true pass probability.

    pass_prob   : Monte Carlo pass rate (point estimate of the proportion).
    n_effective : effective sample size — how much the data should sharpen the
                  posterior. We use the trader's trade count (capped) so that
                  a 30-trade history stays appropriately humble and a
                  500-trade history is allowed to be confident.
    cred        : credible mass (0.80 = 80% band, matching our copy).

    Returns (lo, hi) in [0, 1], asymmetric near the edges, never exactly 0/1
    unless the estimate truly is.
    """
    p = max(0.0, min(1.0, float(pass_prob)))
    n = n_effective if (n_effective and n_effective > 0) else 60
    # Cap effective n so we never imply more certainty than ~500 observations
    # can support; keeps the band honest even for very long histories.
    n = min(n, 500)

    alpha = p * n + PRIOR_A
    beta = (1.0 - p) * n + PRIOR_B
    tail = (1.0 - cred) / 2.0
    lo = _beta_ppf(tail, alpha, beta)
    hi = _beta_ppf(1.0 - tail, alpha, beta)
    return lo, hi


def credible_interval_pct(pass_prob: float, n_effective: int | None,
                          cred: float = 0.80) -> str:
    """Formatted 'lo–hi%' string for display (whole-number percents)."""
    lo, hi = credible_interval(pass_prob, n_effective, cred)
    return f"{lo * 100:.0f}\u2013{hi * 100:.0f}%"


def posterior_width(pass_prob: float, n_effective: int | None,
                    cred: float = 0.80) -> float:
    """Width of the credible band (0..1). Handy for a 'how sharp is this
    estimate' readout that shrinks as the trader adds data."""
    lo, hi = credible_interval(pass_prob, n_effective, cred)
    return hi - lo


def trades_to_halve_band(pass_prob: float, n_effective: int | None,
                         cred: float = 0.80) -> int | None:
    """Roughly how many MORE trades would halve the current band width.

    For a binomial proportion the band shrinks ~1/sqrt(n), so halving the width
    needs ~4x the effective sample. We return the additional count, which makes
    the 'more data narrows the range' promise concrete and honest rather than
    hand-wavy.
    """
    n = n_effective if (n_effective and n_effective > 0) else 60
    if n >= 500:
        return None  # already at our confidence cap
    target_n = min(500, n * 4)
    return max(0, target_n - n)

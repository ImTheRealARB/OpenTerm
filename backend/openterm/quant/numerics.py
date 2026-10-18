"""Small numerical kernels for the quant library, in plain Python (no scipy, numpy or pandas).

Written for OpenTerm; no third-party source. They replace the four SciPy calls the ported Vibe-Trading code relied on:
``scipy.stats.norm`` (``norm_cdf``, ``norm_pdf``), ``scipy.optimize.brentq`` (``brent``), ``scipy.integrate.quad`` (``integrate``)
and ``scipy.optimize.minimize(method="Nelder-Mead")`` plus ``numpy.linalg.lstsq`` (``nelder_mead``, ``lstsq``). ``brent`` follows
the classical Brent (1973) algorithm as scipy's ``brentq`` implements it, so a root and its iteration behaviour agree closely.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Callable, Sequence
from itertools import pairwise

__all__ = [
    "brent",
    "integrate",
    "lstsq",
    "nelder_mead",
    "norm_cdf",
    "norm_pdf",
    "solve_linear",
]

_INV_SQRT2 = 1.0 / math.sqrt(2.0)
_INV_SQRT_2PI = 1.0 / math.sqrt(2.0 * math.pi)
_EPS = 2.220446049250313e-16


def norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution (the Cephes ``ndtr`` recipe: ``erf`` near zero, ``erfc`` in the tails)."""
    z = x * _INV_SQRT2
    az = abs(z)
    if az < _INV_SQRT2:
        return 0.5 + 0.5 * math.erf(z)
    y = 0.5 * math.erfc(az)
    return 1.0 - y if z > 0 else y


def norm_pdf(x: float) -> float:
    """Standard normal density."""
    return _INV_SQRT_2PI * math.exp(-0.5 * x * x)


def brent(
    f: Callable[[float], float],
    a: float,
    b: float,
    xtol: float = 2e-12,
    rtol: float = 4.0 * _EPS,
    maxiter: int = 100,
) -> float:
    """Root of ``f`` bracketed by ``[a, b]`` (Brent's method; the same defaults as scipy's ``brentq``).

    Raises:
        ValueError: If ``f(a)`` and ``f(b)`` have the same sign (no bracket), or ``xtol`` is not positive.
        RuntimeError: If the root is not found within ``maxiter`` iterations.
    """
    if xtol <= 0:
        raise ValueError("xtol must be positive")
    xpre, xcur = float(a), float(b)
    fpre, fcur = f(xpre), f(xcur)
    if fpre * fcur > 0:
        raise ValueError("f(a) and f(b) must have different signs")
    if fpre == 0:
        return xpre
    if fcur == 0:
        return xcur
    xblk = fblk = 0.0
    spre = scur = 0.0
    for _ in range(maxiter):
        if fpre != 0 and fcur != 0 and (fpre < 0) != (fcur < 0):
            xblk, fblk = xpre, fpre
            spre = scur = xcur - xpre
        if abs(fblk) < abs(fcur):
            xpre, xcur, xblk = xcur, xblk, xcur
            fpre, fcur, fblk = fcur, fblk, fcur
        delta = (xtol + rtol * abs(xcur)) / 2.0
        sbis = (xblk - xcur) / 2.0
        if fcur == 0 or abs(sbis) < delta:
            return xcur
        if abs(spre) > delta and abs(fcur) < abs(fpre):
            if xpre == xblk:  # secant
                stry = -fcur * (xcur - xpre) / (fcur - fpre)
            else:  # inverse quadratic interpolation
                dpre = (fpre - fcur) / (xpre - xcur)
                dblk = (fblk - fcur) / (xblk - xcur)
                stry = -fcur * (fblk * dblk - fpre * dpre) / (dblk * dpre * (fblk - fpre))
            if 2.0 * abs(stry) < min(abs(spre), 3.0 * abs(sbis) - delta):
                spre, scur = scur, stry  # accept the interpolation
            else:
                spre = scur = sbis  # bisect
        else:
            spre = scur = sbis
        xpre, fpre = xcur, fcur
        if abs(scur) > delta:
            xcur += scur
        else:
            xcur += delta if sbis > 0 else -delta
        fcur = f(xcur)
    raise RuntimeError(f"brent: no convergence in {maxiter} iterations")


# Gauss-Kronrod 7/15 nodes and weights (QUADPACK qk15), nodes on [-1, 1], listed from the outside in; the last is the centre.
_XGK = (
    0.991455371120812639206854697526329,
    0.949107912342758524526189684047851,
    0.864864423359769072789712788640926,
    0.741531185599394439863864773280788,
    0.586087235467691130294144838258730,
    0.405845151377397166906606412076961,
    0.207784955007898467600689403773245,
    0.000000000000000000000000000000000,
)
_WGK = (
    0.022935322010529224963732008058970,
    0.063092092629978553290700663189204,
    0.104790010322250183839876322541518,
    0.140653259715525918745189590510238,
    0.169004726639267902826583426598550,
    0.190350578064785409913256402421014,
    0.204432940075298892414161999234649,
    0.209482141084727828012999174891714,
)
_WG = (  # 7-point Gauss weights for the nodes at index 1, 3, 5 and the centre
    0.129484966168869693270611432679082,
    0.279705391489276667901467771423780,
    0.381830050505118944950369775488975,
    0.417959183673469387755102040816327,
)
_UFLOW = 2.2250738585072014e-308


def _gk15(f: Callable[[float], float], a: float, b: float) -> tuple[float, float]:
    """One 15-point Kronrod panel with the 7-point Gauss estimate for the error (QUADPACK's scaling)."""
    centr = 0.5 * (a + b)
    hlgth = 0.5 * (b - a)
    fc = f(centr)
    resg = fc * _WG[3]
    resk = fc * _WGK[7]
    resabs = abs(resk)
    fv1 = [0.0] * 7
    fv2 = [0.0] * 7
    for j in range(7):
        absc = hlgth * _XGK[j]
        f1 = f(centr - absc)
        f2 = f(centr + absc)
        fv1[j], fv2[j] = f1, f2
        s = f1 + f2
        resk += _WGK[j] * s
        resabs += _WGK[j] * (abs(f1) + abs(f2))
        if j % 2 == 1:
            resg += _WG[j // 2] * s
    reskh = resk * 0.5
    resasc = _WGK[7] * abs(fc - reskh)
    for j in range(7):
        resasc += _WGK[j] * (abs(fv1[j] - reskh) + abs(fv2[j] - reskh))
    result = resk * hlgth
    resabs *= abs(hlgth)
    resasc *= abs(hlgth)
    err = abs((resk - resg) * hlgth)
    if resasc != 0.0 and err != 0.0:
        err = resasc * min(1.0, (200.0 * err / resasc) ** 1.5)
    if resabs > _UFLOW / (50.0 * _EPS):
        err = max(_EPS * 50.0 * resabs, err)
    return result, err


def integrate(
    f: Callable[[float], float],
    a: float,
    b: float,
    epsabs: float = 1e-12,
    epsrel: float = 1e-11,
    limit: int = 2000,
    panels: int = 4,
) -> float:
    """Integral of a smooth real function over ``[a, b]``: globally adaptive Gauss-Kronrod (7, 15).

    Starts from ``panels`` equal panels (a guard against a first panel that looks flat by accident) and keeps bisecting the
    panel with the largest error estimate until the summed error is below ``max(epsabs, epsrel * |integral|)``. For a smooth
    integrand the error is around 1e-12 or better, which the Heston integrand needs to be good to 1e-8 on a price.
    """
    if a == b:
        return 0.0
    sign = 1.0
    if b < a:
        a, b, sign = b, a, -1.0
    n0 = max(1, int(panels))
    edges = [a + (b - a) * i / n0 for i in range(n0)] + [b]
    heap: list[tuple[float, int, float, float, float]] = []  # (-error, tie-break, left, right, value)
    total = 0.0
    err_total = 0.0
    counter = 0
    for lo, hi in pairwise(edges):
        val, err = _gk15(f, lo, hi)
        heapq.heappush(heap, (-err, counter, lo, hi, val))
        counter += 1
        total += val
        err_total += err
    while err_total > max(epsabs, epsrel * abs(total)) and counter < limit:
        neg_err, _, lo, hi, val = heapq.heappop(heap)
        mid = 0.5 * (lo + hi)
        if mid <= lo or mid >= hi:  # the panel cannot be split any further in floating point
            heapq.heappush(heap, (0.0, counter, lo, hi, val))
            counter += 1
            err_total += neg_err
            continue
        v1, e1 = _gk15(f, lo, mid)
        v2, e2 = _gk15(f, mid, hi)
        total += v1 + v2 - val
        err_total += e1 + e2 + neg_err
        heapq.heappush(heap, (-e1, counter, lo, mid, v1))
        heapq.heappush(heap, (-e2, counter + 1, mid, hi, v2))
        counter += 2
    # Re-sum from the stored panels: the running total drifts by an ulp per update.
    return sign * math.fsum(item[4] for item in heap)


def nelder_mead(
    f: Callable[[Sequence[float]], float],
    x0: Sequence[float],
    bounds: Sequence[tuple[float, float]] | None = None,
    xatol: float = 1e-10,
    fatol: float = 1e-18,
    maxiter: int | None = None,
) -> tuple[list[float], float]:
    """Nelder-Mead simplex minimiser (Nelder and Mead 1965, non-adaptive, the textbook coefficients).

    Mirrors the settings the fit used in scipy: the initial simplex perturbs each coordinate by 5% (0.00025 when it is zero),
    every vertex is clipped into ``bounds``, and the search stops when the simplex is smaller than ``xatol`` and its function
    values agree to ``fatol``, or after ``maxiter`` iterations (default ``200 * len(x0)``).

    Returns:
        ``(x, f(x))`` at the best vertex.
    """
    n = len(x0)
    if n == 0:
        raise ValueError("x0 must not be empty")
    lo = [b[0] for b in bounds] if bounds else [-math.inf] * n
    hi = [b[1] for b in bounds] if bounds else [math.inf] * n

    def clip(x: list[float]) -> list[float]:
        return [min(max(v, lo[i]), hi[i]) for i, v in enumerate(x)]

    limit = maxiter if maxiter is not None else 200 * n
    rho, chi, psi, sigma = 1.0, 2.0, 0.5, 0.5
    base = clip([float(v) for v in x0])
    sim = [base]
    for k in range(n):
        y = list(base)
        y[k] = 1.05 * y[k] if y[k] != 0.0 else 0.00025
        sim.append(clip(y))
    fs = [float(f(p)) for p in sim]
    order = sorted(range(n + 1), key=lambda i: fs[i])
    sim = [sim[i] for i in order]
    fs = [fs[i] for i in order]

    for _ in range(limit):
        if max(abs(fs[i] - fs[0]) for i in range(1, n + 1)) <= fatol and max(
            abs(sim[i][j] - sim[0][j]) for i in range(1, n + 1) for j in range(n)
        ) <= xatol:
            break
        xbar = [sum(sim[i][j] for i in range(n)) / n for j in range(n)]
        xr = clip([(1 + rho) * xbar[j] - rho * sim[-1][j] for j in range(n)])
        fxr = float(f(xr))
        shrink = False
        if fxr < fs[0]:
            xe = clip([(1 + rho * chi) * xbar[j] - rho * chi * sim[-1][j] for j in range(n)])
            fxe = float(f(xe))
            sim[-1], fs[-1] = (xe, fxe) if fxe < fxr else (xr, fxr)
        elif fxr < fs[-2]:
            sim[-1], fs[-1] = xr, fxr
        else:
            if fxr < fs[-1]:  # outside contraction
                xc = clip([(1 + psi * rho) * xbar[j] - psi * rho * sim[-1][j] for j in range(n)])
                fxc = float(f(xc))
                if fxc <= fxr:
                    sim[-1], fs[-1] = xc, fxc
                else:
                    shrink = True
            else:  # inside contraction
                xcc = clip([(1 - psi) * xbar[j] + psi * sim[-1][j] for j in range(n)])
                fxcc = float(f(xcc))
                if fxcc < fs[-1]:
                    sim[-1], fs[-1] = xcc, fxcc
                else:
                    shrink = True
            if shrink:
                for i in range(1, n + 1):
                    sim[i] = clip([sim[0][j] + sigma * (sim[i][j] - sim[0][j]) for j in range(n)])
                    fs[i] = float(f(sim[i]))
        order = sorted(range(n + 1), key=lambda i: fs[i])
        sim = [sim[i] for i in order]
        fs = [fs[i] for i in order]
    return sim[0], fs[0]


def solve_linear(a: Sequence[Sequence[float]], b: Sequence[float]) -> list[float]:
    """Solve the square system ``a x = b`` by Gaussian elimination with partial pivoting.

    Raises:
        ValueError: If the matrix is not square or is singular.
    """
    n = len(b)
    if len(a) != n or any(len(row) != n for row in a):
        raise ValueError("a must be square and match b")
    m = [list(map(float, row)) + [float(b[i])] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-300:
            raise ValueError("matrix is singular")
        m[col], m[piv] = m[piv], m[col]
        for r in range(col + 1, n):
            factor = m[r][col] / m[col][col]
            if factor:
                for c in range(col, n + 1):
                    m[r][c] -= factor * m[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][c] * x[c] for c in range(r + 1, n))) / m[r][r]
    return x


def lstsq(columns: Sequence[Sequence[float]], y: Sequence[float]) -> list[float]:
    """Least-squares coefficients for ``y ~ sum(beta_j * columns[j])`` by Householder QR.

    QR keeps the accuracy of the normal equations' square root, which matters here: the Svensson curvature columns are nearly
    collinear when the two decay parameters are close. A column that is numerically dependent on the earlier ones gets a
    coefficient of zero (the residual is the same as with the minimum-norm solution).
    """
    p = len(columns)
    m = len(y)
    if p == 0 or m < p:
        raise ValueError("need at least as many observations as columns")
    a = [list(map(float, col)) for col in columns]  # column-major working copy
    rhs = [float(v) for v in y]
    scale = max((math.sqrt(sum(v * v for v in col)) for col in a), default=0.0) or 1.0
    tol = max(m, p) * _EPS * scale
    diag = [0.0] * p
    for j in range(p):
        norm = math.sqrt(sum(a[j][i] * a[j][i] for i in range(j, m)))
        if norm <= tol:
            diag[j] = 0.0
            continue
        alpha = -norm if a[j][j] > 0 else norm
        v = [0.0] * m
        for i in range(j, m):
            v[i] = a[j][i]
        v[j] -= alpha
        vnorm2 = sum(v[i] * v[i] for i in range(j, m))
        if vnorm2 > 0:
            for k in range(j, p):
                s = 2.0 * sum(v[i] * a[k][i] for i in range(j, m)) / vnorm2
                for i in range(j, m):
                    a[k][i] -= s * v[i]
            s = 2.0 * sum(v[i] * rhs[i] for i in range(j, m)) / vnorm2
            for i in range(j, m):
                rhs[i] -= s * v[i]
        diag[j] = a[j][j]
    beta = [0.0] * p
    for j in range(p - 1, -1, -1):
        if diag[j] == 0.0:
            continue
        beta[j] = (rhs[j] - sum(a[k][j] * beta[k] for k in range(j + 1, p))) / diag[j]
    return beta

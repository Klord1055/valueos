"""Deterministic financial engine for ValueOS.

Rules (from the spec):
- Money uses Decimal; display rounding only.
- A zero or negative denominator returns Result(value=None, reason=...), never 0%.
- Portfolio ROI is computed from summed costs and benefits, never an average of app ROIs.
- Time saved is not cash saved: productivity capacity is its own evidence class.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, getcontext

getcontext().prec = 28

EVIDENCE_CLASSES = ("verified", "measured", "estimated", "projected")
CASH_CLASSES = ("verified",)


def D(x) -> Decimal:
    """Convert anything numeric to Decimal through str, so 0.1 stays 0.1."""
    if isinstance(x, Decimal):
        return x
    if x is None:
        return Decimal(0)
    return Decimal(str(x))


@dataclass(frozen=True)
class Result:
    value: Decimal | None
    reason: str = ""
    inputs: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.value is not None


def money(x, places: int = 0) -> str:
    if x is None:
        return "n/a"
    q = D(x).quantize(Decimal(1) if places == 0 else Decimal(10) ** -places, ROUND_HALF_UP)
    sign = "-" if q < 0 else ""
    return f"{sign}${abs(q):,}"


def pct(r: Result | Decimal | None, places: int = 1) -> str:
    v = r.value if isinstance(r, Result) else r
    if v is None:
        return "n/a"
    return f"{D(v).quantize(Decimal(10) ** -places, ROUND_HALF_UP)}%"


# ---------- core ratios ----------

def roi(benefit, cost) -> Result:
    """(benefit - cost) / cost x 100. Unavailable when cost is zero or negative."""
    b, c = D(benefit), D(cost)
    inputs = {"benefit": b, "cost": c}
    if c <= 0:
        return Result(None, "Cost is zero or negative, so ROI is undefined.", inputs)
    return Result((b - c) / c * 100, "", inputs)


def utilization(active, purchased) -> Result:
    a, p = D(active), D(purchased)
    if p <= 0:
        return Result(None, "No purchased licenses on record.", {"active": a, "purchased": p})
    return Result(a / p * 100, "", {"active": a, "purchased": p})


def cost_per_active_user(cost, active) -> Result:
    c, a = D(cost), D(active)
    if a <= 0:
        return Result(None, "No active users in the window.", {"cost": c, "active": a})
    return Result(c / a, "", {"cost": c, "active": a})


def productivity_value(users, adoption, hours_per_user_per_year, rate, realization, attribution=1) -> Decimal:
    """Eligible users x adoption x hours saved x loaded rate x realization x attribution share."""
    return D(users) * D(adoption) * D(hours_per_user_per_year) * D(rate) * D(realization) * D(attribution)


# ---------- cash flow math ----------

def npv(rate, flows) -> Decimal:
    """flows[0] is today (the initial outlay, usually negative)."""
    r = D(rate)
    return sum((D(f) / (1 + r) ** t for t, f in enumerate(flows)), Decimal(0))


def irr(flows, lo=-0.99, hi=10.0, tol=1e-10, iters=300) -> Result:
    """Bisection on NPV = 0. Flags no root and multiple sign changes."""
    fl = [D(f) for f in flows]
    signs = [f for f in fl if f != 0]
    changes = sum(1 for a, b in zip(signs, signs[1:]) if (a < 0) != (b < 0))
    if changes == 0:
        return Result(None, "Cash flows never change sign, so there is no IRR.")
    lo_d, hi_d = D(lo), D(hi)
    f_lo, f_hi = npv(lo_d, fl), npv(hi_d, fl)
    if (f_lo < 0) == (f_hi < 0):
        if f_hi > 0:
            return Result(hi_d * 100, "Above the search range; the true IRR is higher.")
        return Result(None, "No IRR between -99% and 1,000% per period.")
    for _ in range(iters):
        mid = (lo_d + hi_d) / 2
        f_mid = npv(mid, fl)
        if abs(f_mid) < D(tol):
            break
        if (f_mid < 0) == (f_lo < 0):
            lo_d, f_lo = mid, f_mid
        else:
            hi_d = mid
    note = "Cash flows change sign more than once; more than one IRR may exist." if changes > 1 else ""
    return Result(mid * 100, note)


def payback_months(flows_monthly) -> Result:
    """First month the cumulative undiscounted cash flow crosses zero, linearly interpolated."""
    cum = Decimal(0)
    for m, f in enumerate(flows_monthly):
        f = D(f)
        prev = cum
        cum += f
        if m > 0 and prev < 0 <= cum:
            frac = (-prev / f) if f != 0 else Decimal(0)
            return Result(D(m - 1) + frac, "Undiscounted, interpolated within the month.")
    if all(D(f) == 0 for f in flows_monthly):
        return Result(None, "No costs or benefits entered.")
    if cum >= 0 and flows_monthly and D(flows_monthly[0]) >= 0:
        return Result(Decimal(0), "No upfront outlay.")
    return Result(None, "Does not pay back within the horizon.")


# ---------- business case simulator ----------

@dataclass
class Case:
    seats: int = 200
    price_per_seat_month: float = 30.0
    setup_cost: float = 25_000.0
    adoption_start: float = 0.30
    adoption_target: float = 0.75
    ramp_months: int = 6
    hours_saved_per_user_week: float = 1.5
    loaded_hourly_rate: float = 55.0
    realization: float = 0.50
    working_weeks: int = 46
    horizon_months: int = 36
    discount_rate_annual: float = 0.10
    annual_price_escalation: float = 0.05


def case_flows(c: Case) -> dict:
    """Monthly cash costs and economic benefits. Month 0 holds the setup cost."""
    months = int(c.horizon_months)
    costs, benefits, adoption = [D(c.setup_cost)], [Decimal(0)], [Decimal(0)]
    weeks_per_month = D(c.working_weeks) / 12
    for m in range(1, months + 1):
        if c.ramp_months <= 0 or m >= c.ramp_months:
            a = D(c.adoption_target)
        else:
            a = D(c.adoption_start) + (D(c.adoption_target) - D(c.adoption_start)) * D(m - 1) / D(c.ramp_months - 1 or 1)
        a = max(Decimal(0), min(Decimal(1), a))
        year = (m - 1) // 12
        price = D(c.price_per_seat_month) * (1 + D(c.annual_price_escalation)) ** year
        costs.append(D(c.seats) * price)
        benefits.append(D(c.seats) * a * D(c.hours_saved_per_user_week) * weeks_per_month
                        * D(c.loaded_hourly_rate) * D(c.realization))
        adoption.append(a)
    net = [b - k for b, k in zip(benefits, costs)]
    monthly_rate = (1 + D(c.discount_rate_annual)) ** (Decimal(1) / 12) - 1
    total_cost, total_benefit = sum(costs), sum(benefits)
    irr_m = irr(net)
    irr_annual = Result(((1 + irr_m.value / 100) ** 12 - 1) * 100, irr_m.reason) if irr_m.ok else irr_m
    return {
        "costs": costs, "benefits": benefits, "net": net, "adoption": adoption,
        "total_cost": total_cost, "total_benefit": total_benefit,
        "npv": npv(monthly_rate, net), "roi": roi(total_benefit, total_cost),
        "irr": irr_annual, "payback": payback_months(net),
    }


def break_even_adoption(c: Case) -> Result:
    """Steady state target adoption at which the investment's NPV is zero (bisection)."""
    def f(a):
        cc = Case(**{**c.__dict__, "adoption_target": a, "adoption_start": min(c.adoption_start, a)})
        return case_flows(cc)["npv"]
    lo, hi = 0.0, 1.0
    base = case_flows(c)
    if base["total_cost"] == 0:
        return Result(None, "There is no cost to cover.")
    if f(hi) < 0:
        return Result(None, "Even 100% adoption does not pay back over this horizon.")
    if f(lo) >= 0:
        return Result(Decimal(0), "Pays back with no adoption (benefit not driven by usage).")
    for _ in range(40):
        mid = (lo + hi) / 2
        if f(mid) < 0:
            lo = mid
        else:
            hi = mid
    return Result(D(hi) * 100, "")

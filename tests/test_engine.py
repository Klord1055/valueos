from decimal import Decimal

import pandas as pd
import pytest

from valueos import engine as E
from valueos import portfolio as P


def approx(a, b, tol=1e-6):
    return abs(float(a) - float(b)) < tol


# ---------- golden cases from the spec ----------

def test_golden_app_roi():
    r = E.roi(198_000, 72_000)
    assert r.ok and approx(r.value, 175)


def test_golden_portfolio_roi():
    r = E.roi(3_820_000, 1_240_000)
    assert approx(round(r.value, 1), 208.1, 1e-9)


def test_zero_cost_is_unavailable_not_zero():
    r = E.roi(10_000, 0)
    assert not r.ok and "undefined" in r.reason
    assert E.pct(r) == "n/a"


def test_negative_roi_is_valid():
    assert approx(E.roi(50, 100).value, -50)


def test_decimal_precision():
    assert E.D(0.1) + E.D(0.2) == Decimal("0.3")


def test_utilization_and_cost_per_user_guards():
    assert not E.utilization(5, 0).ok
    assert not E.cost_per_active_user(100, 0).ok
    assert approx(E.utilization(30, 40).value, 75)


def test_productivity_formula():
    # 100 users x 50% x 40 h x $50 x 0.5 x 1.0
    assert E.productivity_value(100, 0.5, 40, 50, 0.5) == Decimal("50000.000")


# ---------- cash flows ----------

def test_npv_and_irr_simple():
    assert approx(E.npv(0.10, [-100, 110]), 0)
    r = E.irr([-100, 110])
    assert r.ok and approx(r.value, 10, 1e-6)


def test_irr_no_sign_change():
    assert not E.irr([100, 50]).ok


def test_irr_multiple_sign_changes_flagged():
    r = E.irr([-100, 230, -132])
    assert "more than one" in r.reason or not r.ok


def test_payback_interpolated():
    r = E.payback_months([-100, 40, 40, 40])
    assert r.ok and approx(r.value, 2.5)


def test_payback_never():
    assert not E.payback_months([-100, 10, 10]).ok


def test_case_flows_consistency():
    out = E.case_flows(E.Case(horizon_months=24))
    assert len(out["costs"]) == 25
    assert out["total_cost"] == sum(out["costs"])
    assert out["roi"].ok


def test_break_even_adoption_bounds():
    c = E.Case()
    be = E.break_even_adoption(c)
    assert be.ok and 0 <= be.value <= 100
    at = E.Case(**{**c.__dict__, "adoption_target": float(be.value) / 100, "adoption_start": min(c.adoption_start, float(be.value) / 100)})
    assert abs(E.case_flows(at)["npv"]) < 500  # near zero


def test_break_even_impossible():
    c = E.Case(price_per_seat_month=5000)
    assert not E.break_even_adoption(c).ok


# ---------- portfolio ----------

APPS = pd.DataFrame([
    {"app": "Zoom", "vendor": "Zoom Video Communications", "category": "Video", "owner": "IT",
     "purchased_seats": 100, "active_users_30d": 40, "renewal_date": "2026-12-01", "notice_days": 30},
    {"app": "Teams", "vendor": "Microsoft", "category": "Video", "owner": "IT",
     "purchased_seats": 100, "active_users_30d": 90, "renewal_date": "2027-06-01", "notice_days": 30},
])
FX = {"USD": 1.0, "EUR": 1.10}


def ledger(rows):
    return pd.DataFrame(rows, columns=P.TXN_COLS)


def test_vendor_matching_and_fx_and_refund():
    t = ledger([
        ["1", "2026-05-01", "ZOOM VIDEO COMMUNICATIONS INC.", 1000, "USD", "IT", "recurring"],
        ["2", "2026-05-02", "Microsoft Corp", 100, "EUR", "IT", "recurring"],
        ["3", "2026-05-03", "Zoom.us", 200, "USD", "IT", "refund"],
        ["4", "2026-05-04", "Unknown Vendor", 50, "USD", "IT", "recurring"],
    ])
    L, issues = P.prepare_transactions(t, APPS, FX)
    assert list(L["app"][:3]) == ["Zoom", "Teams", "Zoom"] and pd.isna(L.loc[3, "app"])
    assert approx(L.loc[1, "amount_usd"], 110)
    assert L.loc[2, "amount_usd"] == -200
    assert "Unmatched vendor" in set(issues["issue"])


def test_duplicate_excluded_and_unknown_currency_flagged():
    t = ledger([
        ["1", "2026-05-01", "Zoom", 1000, "USD", "IT", "recurring"],
        ["2", "2026-05-01", "Zoom", 1000, "USD", "IT", "recurring"],
        ["3", "2026-05-01", "Zoom", 5, "JPY", "IT", "recurring"],
    ])
    L, issues = P.prepare_transactions(t, APPS, FX)
    assert L["excluded"].tolist() == [False, True, True]
    assert {"Possible duplicate", "Unknown currency"} <= set(issues["issue"])
    assert P.reconciliation_summary(L)["total_usd"] == 1000


def claims(rows):
    return pd.DataFrame(rows, columns=P.CLAIM_COLS)


def test_overlap_counted_once_and_projected_excluded():
    c = claims([
        ["B1", "Zoom", "productivity", 100, "estimated", "approved", "o", "s", "g1"],
        ["B2", "Teams", "productivity", 300, "measured", "approved", "o", "s", "g1"],
        ["B3", "Zoom", "productivity", 999, "projected", "approved", "o", "s", ""],
        ["B4", "Zoom", "productivity", 999, "estimated", "pending", "o", "s", ""],
    ])
    e = P.eligible_claims(c)
    assert e["counted"].tolist() == [False, True, False, False]


def test_missing_value_is_not_zero_roi():
    t = ledger([["1", "2026-05-01", "Zoom", 1000, "USD", "IT", "recurring"],
                ["2", "2026-05-01", "Microsoft", 1000, "USD", "IT", "recurring"]])
    L, _ = P.prepare_transactions(t, APPS, FX)
    c = claims([["B1", "Teams", "cash_savings", 3000, "verified", "approved", "o", "s", ""]])
    r = P.app_rollup(L, APPS, c, pd.Timestamp("2026-10-31")).set_index("app")
    assert pd.isna(r.loc["Zoom", "roi"]) and "No approved" in r.loc["Zoom", "roi_note"]
    assert approx(r.loc["Teams", "roi"], 200)
    tot = P.portfolio_totals(r.reset_index())
    assert approx(tot["roi"].value, 200)  # Teams only: Zoom has no evidence, so it is unmeasured
    assert approx(tot["unmeasured"], 1000) and approx(tot["cost_all"], 2000)


def test_opportunities_do_not_double_count():
    t = ledger([["1", "2026-05-01", "Zoom", 12000, "USD", "IT", "recurring"],
                ["2", "2026-05-01", "Microsoft", 6000, "USD", "IT", "recurring"]])
    L, _ = P.prepare_transactions(t, APPS, FX)
    r = P.app_rollup(L, APPS, claims([]), pd.Timestamp("2026-10-31"))
    o = P.opportunities(r, pd.Timestamp("2026-10-31"))
    assert not o.empty
    assert o[o["counts_in_total"]]["app"].is_unique
    assert set(o["type"]) >= {"Reclaim unused licenses", "Overlapping tools", "Renewal coming up"}


def test_validate_reports_missing_columns():
    assert P.validate(pd.DataFrame({"a": [1]}), ["a", "b"], "File") == ["File is missing column(s): b."]
    assert P.validate(pd.DataFrame(columns=["a"]), ["a"], "File") == ["File has no rows."]


def test_portfolio_roi_from_sums_not_average():
    roll = pd.DataFrame({"tco_12m": [100.0, 900.0], "economic_value": [300.0, 900.0], "cash_value": [0.0, 0.0],
                         "has_value": [True, True]})
    tot = P.portfolio_totals(roll)
    assert approx(tot["roi"].value, 20)  # average of app ROIs would be 100


def test_portfolio_no_evidence_is_unavailable():
    roll = pd.DataFrame({"tco_12m": [100.0], "economic_value": [0.0], "cash_value": [0.0], "has_value": [False]})
    assert not P.portfolio_totals(roll)["roi"].ok


# ---------- review fixes ----------

def test_value_without_cost_kept_out_of_roi():
    roll = pd.DataFrame({"tco_12m": [1000.0, 0.0], "economic_value": [1000.0, 50000.0], "cash_value": [0.0, 0.0],
                         "has_value": [True, True]})
    tot = P.portfolio_totals(roll)
    assert approx(tot["roi"].value, 0) and approx(tot["value_without_cost"], 50000)


def test_bad_claim_amount_not_counted_and_money_parsed():
    c = claims([["B1", "Zoom", "productivity", "TBD", "estimated", "approved", "o", "s", ""],
                ["B2", "Zoom", "productivity", "$12,000", "Estimated ", " Approved", "o", "s", ""]])
    e = P.eligible_claims(c)
    assert e["counted"].tolist() == [False, True] and e.loc[1, "annual_amount"] == 12000


def test_refund_same_day_not_a_duplicate():
    t = ledger([["1", "2026-05-01", "Zoom", 200, "USD", "IT", "recurring"],
                ["2", "2026-05-01", "Zoom", 200, "USD", "IT", "refund"]])
    L, _ = P.prepare_transactions(t, APPS, FX)
    assert not L["excluded"].any() and L["amount_usd"].sum() == 0


def test_blank_status_and_case_insensitive_projection():
    c = claims([["B1", "Zoom", "productivity", 100, "Projected", None, "o", "s", ""],
                ["B2", "Zoom", "productivity", 100, "PROJECTED", "approved", "o", "s", ""]])
    c["status"] = [float("nan"), "approved"]
    assert not P.eligible_claims(c)["counted"].any()


def test_unknown_app_claim_does_not_win_overlap():
    c = claims([["B1", "Zoom", "productivity", 3000, "estimated", "approved", "o", "s", "g"],
                ["B2", "Zoomm", "productivity", 5000, "estimated", "approved", "o", "s", "g"]])
    e = P.eligible_claims(c, ["Zoom", "Teams"])
    assert e["counted"].tolist() == [True, False]


def test_duplicate_app_names_rejected():
    df = pd.concat([APPS, APPS.iloc[[0]]])
    assert "more than once" in P.validate(df, P.APP_COLS, "Apps file")[0]


def test_unknown_active_users_skips_reclaim_and_zero_notice_kept():
    apps = APPS.copy()
    apps["active_users_30d"] = [float("nan"), 90]
    apps["notice_days"] = [0, 30]
    t = ledger([["1", "2026-05-01", "Zoom", 12000, "USD", "IT", "recurring"]])
    L, _ = P.prepare_transactions(t, apps, FX)
    r = P.app_rollup(L, apps, claims([]), pd.Timestamp("2026-10-31"))
    assert pd.isna(r.loc[0, "utilization"]) and r.loc[0, "notice_days"] == 0
    o = P.opportunities(r, pd.Timestamp("2026-10-31"))
    assert not ((o["app"] == "Zoom") & (o["type"] == "Reclaim unused licenses")).any()


def test_irr_above_range_reported_high():
    r = E.irr([-1000, 19300, 26890])
    assert r.ok and r.value >= 1000


# ---------- stress test fixes ----------

def test_money_text_amounts_parsed():
    t = ledger([["1", "2026-05-01", "Zoom", "$1,234.50", "USD", "IT", "recurring"]])
    L, issues = P.prepare_transactions(t, APPS, FX)
    assert L.loc[0, "amount_usd"] == 1234.5 and "Bad amount" not in set(issues["issue"])


def test_consolidation_charges_extra_seats_on_kept_tool():
    apps = APPS.copy()
    apps["active_users_30d"] = [40, 95]  # Teams has 5 spare seats; moving 40 Zoom users needs 35 more
    t = ledger([["1", "2026-05-01", "Zoom", 12000, "USD", "IT", "recurring"],
                ["2", "2026-05-01", "Microsoft", 6000, "USD", "IT", "recurring"]])
    L, _ = P.prepare_transactions(t, apps, FX)
    r = P.app_rollup(L, apps, claims([]), pd.Timestamp("2026-10-31"))
    o = P.opportunities(r, pd.Timestamp("2026-10-31"))
    row = o[o["type"] == "Overlapping tools"].iloc[0]
    assert approx(row["high"], 12000 - 35 * 60)


def test_empty_business_case_is_not_contradictory():
    c = E.Case(price_per_seat_month=0, setup_cost=0, hours_saved_per_user_week=0)
    out = E.case_flows(c)
    assert not out["payback"].ok and not E.break_even_adoption(c).ok


def test_monthly_trend_matches_headline_window():
    t = ledger([["1", "2026-05-01", "Zoom", 100, "USD", "IT", "recurring"],
                ["2", "2024-05-01", "Zoom", 999, "USD", "IT", "recurring"],
                ["3", "2026-05-01", "Unknown", 50, "USD", "IT", "recurring"]])
    L, _ = P.prepare_transactions(t, APPS, FX)
    assert P.monthly_trend(L, pd.Timestamp("2026-10-31"))["amount_usd"].sum() == 100

"""Import, mapping, reconciliation, per app rollups and opportunities.

Everything here works on plain pandas DataFrames so the same code runs on the
synthetic sample workspace or on a user's own CSV files.
"""
from __future__ import annotations

import re
from decimal import Decimal

import pandas as pd

from .engine import D, Result, cost_per_active_user, roi, utilization

TXN_COLS = ["txn_id", "date", "vendor", "amount", "currency", "department", "type"]
APP_COLS = ["app", "vendor", "category", "owner", "purchased_seats", "active_users_30d",
            "renewal_date", "notice_days"]
CLAIM_COLS = ["claim_id", "app", "benefit_type", "annual_amount", "evidence_class", "status",
              "owner", "source", "overlap_group"]
TXN_TYPES = {"recurring", "one_time", "refund", "credit"}
EVIDENCE = ("verified", "measured", "estimated", "projected")
BENEFIT_TYPES = {"cash_savings", "avoided_cost", "productivity", "incremental_profit", "risk_reduction"}


# ---------- validation ----------

def validate(df: pd.DataFrame, required: list[str], name: str) -> list[str]:
    """Plain English problems with an uploaded table. Empty list means it can be used."""
    if df is None or df.empty:
        return [f"{name} has no rows."]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return [f"{name} is missing column(s): {', '.join(missing)}."]
    if name == "Apps file":
        names = df["app"].astype(str).str.strip()
        d = sorted(names[names.duplicated()].unique())
        if d:
            return [f"Apps file lists {', '.join(d)} more than once. Keep one row per app."]
    return []


def normalize_name(s: str) -> str:
    """Lowercase, strip punctuation and legal suffixes, so 'ZOOM VIDEO COMMUNICATIONS INC.' matches 'zoom'."""
    s = re.sub(r"[^a-z0-9 ]", " ", str(s).lower())
    s = re.sub(r"\b(inc|llc|ltd|corp|corporation|co|com|communications|technologies|software|plc|gmbh)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def build_vendor_map(apps: pd.DataFrame, overrides: dict | None = None) -> dict:
    """normalized vendor or app name -> app. Manual overrides win."""
    m = {}
    for _, r in apps.iterrows():
        m[normalize_name(r["vendor"])] = r["app"]
        m[normalize_name(r["app"])] = r["app"]
    for k, v in (overrides or {}).items():
        m[normalize_name(k)] = v
    return m


def match_vendor(raw: str, vmap: dict) -> str | None:
    n = normalize_name(raw)
    if n in vmap:
        return vmap[n]
    # token containment: 'slack technologies' -> 'slack'
    for key, app in sorted(vmap.items(), key=lambda kv: -len(kv[0])):
        if key and (key in n.split() or n.startswith(key + " ") or key.startswith(n + " ")):
            return app
    return None


# ---------- reconciliation ----------

def prepare_transactions(txns: pd.DataFrame, apps: pd.DataFrame, fx: dict, overrides: dict | None = None):
    """Returns (clean ledger, issues table). Original rows are never altered; we add columns."""
    t = txns.copy()
    t["date"] = pd.to_datetime(t["date"], errors="coerce")
    t["amount"] = pd.to_numeric(t["amount"], errors="coerce")
    t["currency"] = t["currency"].fillna("USD").str.upper().str.strip()
    t["type"] = t["type"].fillna("recurring").str.lower().str.strip()
    vmap = build_vendor_map(apps, overrides)
    t["app"] = t["vendor"].map(lambda v: match_vendor(v, vmap))
    t["fx_rate"] = t["currency"].map(lambda c: fx.get(c))
    t["amount_usd"] = t["amount"] * t["fx_rate"]
    # refunds and credits reduce cost whatever sign they were entered with
    neg = t["type"].isin(["refund", "credit"])
    t.loc[neg, "amount_usd"] = -t.loc[neg, "amount_usd"].abs()

    issues = []

    def add(rows, kind, detail, fix):
        for _, r in rows.iterrows():
            issues.append({"txn_id": r["txn_id"], "issue": kind, "detail": detail(r), "how to fix": fix})

    add(t[t["date"].isna()], "Bad date", lambda r: f"'{r['date']}' is not a date", "Fix the date in the file")
    add(t[t["amount"].isna()], "Bad amount", lambda r: "amount is blank or not a number", "Fix the amount")
    add(t[t["fx_rate"].isna() & t["amount"].notna()], "Unknown currency",
        lambda r: f"{r['currency']} has no exchange rate", "Add a rate in the FX table")
    add(t[t["app"].isna()], "Unmatched vendor", lambda r: f"'{r['vendor']}' did not match any app",
        "Map it to an app in Data > Vendor mapping")
    add(t[~t["type"].isin(TXN_TYPES)], "Unknown type", lambda r: f"type '{r['type']}'",
        "Use recurring, one_time, refund or credit")
    add(t[(t["amount"] < 0) & ~neg], "Negative charge", lambda r: f"{r['amount']} on a {r['type']} line",
        "Mark it as a refund or credit")
    add(t[t["department"].isna() | (t["department"].astype(str).str.strip() == "")], "No department",
        lambda r: "department is blank", "Shows as Unallocated until filled")
    dup_key = ["vendor", "amount", "date", "type"]
    dups = t[t.duplicated(dup_key, keep="first") & t["date"].notna()]
    add(dups, "Possible duplicate", lambda r: "same vendor, amount, date and type as an earlier line",
        "Excluded from totals; confirm with AP")

    t["excluded"] = t.index.isin(dups.index) | t["amount_usd"].isna() | t["date"].isna()
    t["department"] = t["department"].fillna("Unallocated").replace("", "Unallocated")
    return t, pd.DataFrame(issues, columns=["txn_id", "issue", "detail", "how to fix"])


def reconciliation_summary(t: pd.DataFrame) -> dict:
    used = t[~t["excluded"]]
    return {
        "rows": len(t),
        "matched": int(used["app"].notna().sum()),
        "unmatched": int(used["app"].isna().sum()),
        "excluded": int(t["excluded"].sum()),
        "unmatched_usd": float(used.loc[used["app"].isna(), "amount_usd"].sum()),
        "total_usd": float(used["amount_usd"].sum()),
    }


# ---------- benefits ----------

def clean_text(s: pd.Series) -> pd.Series:
    return s.fillna("").astype(str).str.strip().str.lower()


def parse_money(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(r"[$,\s]", "", regex=True), errors="coerce")


def eligible_claims(claims: pd.DataFrame, known_apps=None, classes=None) -> pd.DataFrame:
    """Approved, non projected claims; overlapping claims count once (largest kept).
    A claim whose amount is missing, or whose app is not in the apps file, is never counted."""
    c = claims.copy()
    c["app"] = c["app"].fillna("").astype(str).str.strip()
    c["status"] = clean_text(c["status"])
    c["evidence_class"] = clean_text(c["evidence_class"])
    c["benefit_type"] = clean_text(c["benefit_type"])
    c["annual_amount"] = parse_money(c["annual_amount"])
    c["counted"] = (c["status"] == "approved") & (c["evidence_class"] != "projected")
    c["note"] = ""
    c.loc[c["status"] != "approved", "note"] = "Not approved yet"
    c.loc[c["evidence_class"] == "projected", "note"] = "Projection, kept out of ROI"
    bad_class = ~c["evidence_class"].isin(EVIDENCE)
    c.loc[bad_class, ["counted", "note"]] = [False, "Unknown evidence class"]
    bad_amt = c["annual_amount"].isna()
    c.loc[bad_amt, ["counted", "note"]] = [False, "Amount missing or not a number"]
    if classes is not None:
        off = c["counted"] & ~c["evidence_class"].isin([x.lower() for x in classes])
        c.loc[off, ["counted", "note"]] = [False, "Evidence class switched off in the left panel"]
    if known_apps is not None:
        unknown = ~c["app"].isin(set(known_apps))
        c.loc[unknown, ["counted", "note"]] = [False, "App is not in the apps file"]
    c["annual_amount"] = c["annual_amount"].fillna(0)
    grp = c["overlap_group"].fillna("").astype(str).str.strip()
    for g in grp[grp != ""].unique():
        idx = c.index[(grp == g) & c["counted"]]
        if len(idx) > 1:
            keep = c.loc[idx, "annual_amount"].idxmax()
            drop = [i for i in idx if i != keep]
            c.loc[drop, "counted"] = False
            c.loc[drop, "note"] = f"Overlaps claim {c.loc[keep, 'claim_id']}; counted once"
    return c


# ---------- rollups ----------

def app_rollup(t: pd.DataFrame, apps: pd.DataFrame, claims: pd.DataFrame, as_of: pd.Timestamp,
               classes=None) -> pd.DataFrame:
    """Trailing 12 month TCO, usage and value per app."""
    start = as_of - pd.DateOffset(months=12)
    used = t[(~t["excluded"]) & t["app"].notna() & (t["date"] > start) & (t["date"] <= as_of)]
    def dsum(df, col):  # exact Decimal sums per app
        return {a: sum((D(round(float(v), 2)) for v in g[col]), Decimal(0)) for a, g in df.groupby("app")}
    tco = dsum(used, "amount_usd")
    rec = dsum(used[used["type"] == "recurring"], "amount_usd")
    one = dsum(used[used["type"] == "one_time"], "amount_usd")
    c = eligible_claims(claims, apps["app"].astype(str).str.strip(), classes)
    cc = c[c["counted"]]
    econ = dsum(cc, "annual_amount")
    cash = dsum(cc[(cc["evidence_class"] == "verified") & cc["benefit_type"].isin(["cash_savings", "avoided_cost"])],
                "annual_amount")
    rows = []
    for _, a in apps.iterrows():
        name = a["app"]
        cost = tco.get(name, Decimal(0))
        e, k = econ.get(name, Decimal(0)), cash.get(name, Decimal(0))
        has_claims = name in econ
        r = roi(e, cost) if has_claims else Result(None, "No approved value claims yet; add evidence to measure ROI.")
        active = pd.to_numeric(a["active_users_30d"], errors="coerce")
        seats = pd.to_numeric(a["purchased_seats"], errors="coerce")
        seats = 0 if pd.isna(seats) else int(seats)
        if pd.isna(active):
            u = cpu = Result(None, "Active users not reported.")
        else:
            u = utilization(active, seats)
            cpu = cost_per_active_user(cost, active)
        nd = pd.to_numeric(a.get("notice_days", None), errors="coerce")
        rows.append({
            "app": name, "category": a["category"], "owner": a["owner"],
            "tco_12m": float(cost), "recurring": float(rec.get(name, 0)), "one_time": float(one.get(name, 0)),
            "economic_value": float(e), "cash_value": float(k),
            "net_value": float(e - cost), "roi": float(r.value) if r.ok else None, "roi_note": r.reason,
            "purchased": seats, "active": None if pd.isna(active) else int(active),
            "utilization": float(u.value) if u.ok else None,
            "cost_per_active": float(cpu.value) if cpu.ok else None,
            "renewal_date": pd.to_datetime(a["renewal_date"], errors="coerce"),
            "notice_days": 60 if pd.isna(nd) else int(nd),
            "claims": int((c["app"] == name).sum()), "has_value": bool(has_claims),
        })
    return pd.DataFrame(rows)


def portfolio_totals(roll: pd.DataFrame) -> dict:
    """ROI covers the apps that have evidence (eligible cost), so unmeasured apps do not drag it to look
    worse or better. Their cost is reported separately as unmeasured."""
    ev = roll[roll["has_value"] & (roll["tco_12m"] > 0)]
    orphan = roll[roll["has_value"] & (roll["tco_12m"] <= 0)]
    cost_all = D(round(float(roll["tco_12m"].sum()), 2))
    cost = D(round(float(ev["tco_12m"].sum()), 2))
    val, cash = D(ev["economic_value"].sum()), D(ev["cash_value"].sum())
    r = roi(val, cost) if len(ev) else Result(None, "No app has approved value evidence yet.")
    return {"cost_all": cost_all, "cost": cost, "unmeasured": cost_all - cost, "value": val, "net": val - cost,
            "roi": r, "cash": cash, "value_without_cost": D(orphan["economic_value"].sum()), "cash_roi": roi(cash, cost) if len(ev) else r}


# ---------- opportunities ----------

def opportunities(roll: pd.DataFrame, as_of: pd.Timestamp, util_floor: float = 80.0,
                  renewal_window_days: int = 120) -> pd.DataFrame:
    """Rule based savings ideas. Each has a range, confidence and the evidence behind it."""
    ops = []
    for _, r in roll.iterrows():
        seat_cost = r["recurring"] / r["purchased"] if r["purchased"] else 0
        # 1. unused licenses
        if pd.notna(r["utilization"]) and r["utilization"] < util_floor and r["purchased"] > 0:
            act = int(r["active"])
            target = int(round(act / (util_floor / 100))) if act else 0
            spare = max(0, int(r["purchased"]) - max(target, act))
            if spare > 0 and seat_cost > 0:
                v = spare * seat_cost
                ops.append(dict(app=r["app"], type="Reclaim unused licenses",
                                action=f"Cut {spare} of {r['purchased']} seats at renewal "
                                       f"(leaves room to reach {int(util_floor)}% use)",
                                low=0.6 * v, high=v, confidence="High",
                                evidence=f"{act} active of {r['purchased']} purchased "
                                         f"({r['utilization']:.0f}%), ${seat_cost:,.0f} per seat per year"))
        # 2. renewal coming up
        if pd.notna(r["renewal_date"]):
            days = (r["renewal_date"] - as_of).days
            notice = days - r["notice_days"]
            if 0 <= days <= renewal_window_days:
                ops.append(dict(app=r["app"], type="Renewal coming up",
                                action=(f"Renews in {days} days; notice deadline in {notice} days. " if notice >= 0 else
                                        f"Renews in {days} days; the {r['notice_days']} day notice deadline has passed. ")
                                       + "Negotiate with the usage data",
                                low=0.03 * r["recurring"], high=0.10 * r["recurring"],
                                confidence="Medium", evidence=f"${r['recurring']:,.0f} recurring spend; "
                                "3 to 10% is a planning range, not a quote"))
        # 3. not paying for itself
        if pd.notna(r["roi"]) and r["roi"] < 0 and r["tco_12m"] > 0:
            ops.append(dict(app=r["app"], type="Not paying for itself",
                            action="Review: retrain, downsize or retire",
                            low=0.0, high=-r["net_value"], confidence="Low",
                            evidence=f"Counted value ${r['economic_value']:,.0f} vs cost ${r['tco_12m']:,.0f}"))
    # 4. overlapping tools in the same category: keep the one more people use
    for cat, g in roll[roll["tco_12m"] > 0].groupby("category"):
        if len(g) > 1:
            g = g.sort_values(["active", "tco_12m"], ascending=False)
            keep, retire = g.iloc[0], g.iloc[1:]
            for _, small in retire.iterrows():
                if pd.notna(small["roi"]) and (pd.isna(keep["roi"]) or small["roi"] >= keep["roi"]):
                    continue  # it earns more per dollar than the tool we would keep
                ops.append(dict(app=small["app"], type="Overlapping tools",
                                action=f"{len(g)} {cat} tools. Move {_n(small['active'])} users from "
                                       f"{small['app']} to {keep['app']} ({_n(keep['active'])} active) and retire it",
                                low=0.5 * small["recurring"], high=small["recurring"], confidence="Medium",
                                evidence=f"{small['app']} costs ${small['recurring']:,.0f} a year in subscriptions; "
                                         "check the teams do not use it for a different job; migration cost not included"))
    df = pd.DataFrame(ops, columns=["app", "type", "action", "low", "high", "confidence", "evidence"])
    if df.empty:
        return df.assign(mid=pd.Series(dtype=float), counts_in_total=pd.Series(dtype=bool))
    df["mid"] = (df["low"] + df["high"]) / 2
    rank = {"High": 0, "Medium": 1, "Low": 2}
    df = df.sort_values(["confidence", "mid"], key=lambda s: s.map(rank) if s.name == "confidence" else -s) \
        .reset_index(drop=True)
    # ideas on the same app overlap (you cannot cut seats on a tool you retire), so only the
    # largest idea per app counts toward the total
    df["counts_in_total"] = ~df.duplicated("app", keep=False) | (df["mid"] == df.groupby("app")["mid"].transform("max"))
    df.loc[df.duplicated(["app", "counts_in_total"]) & df["counts_in_total"], "counts_in_total"] = False
    return df


def _n(x) -> str:
    return "an unknown number of" if pd.isna(x) else f"{int(x)}"


def monthly_trend(t: pd.DataFrame) -> pd.DataFrame:
    used = t[~t["excluded"]]
    m = used.groupby(used["date"].dt.to_period("M"))["amount_usd"].sum().reset_index()
    m["month"] = m["date"].dt.to_timestamp()
    return m[["month", "amount_usd"]]

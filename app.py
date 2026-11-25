"""ValueOS: what every software investment is worth.

Run: streamlit run app.py
"""
from __future__ import annotations

import io
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import importlib
import ui
importlib.reload(ui)  # pick up ui.py changes on hot redeploy
from ui import GOLD, GREEN, GREY, NAVY, RED, intro, note, setup, takeaway, wrap
from valueos import engine as E
from valueos import portfolio as P
E = importlib.reload(E)  # hot redeploys keep old modules loaded otherwise
P = importlib.reload(P)

st.set_page_config(page_title="ValueOS", page_icon="📊", layout="wide")
setup()
DATA = Path(__file__).parent / "data"
SAMPLE_AS_OF = date(2026, 10, 31)


def k(x) -> str:
    """$1.2M / $45K / $900 style labels."""
    if x is None or pd.isna(x):
        return "n/a"
    x = float(x)
    s = "-" if x < 0 else ""
    x = abs(x)
    if x >= 1e6:
        return f"{s}${x / 1e6:.2f}M"
    if x >= 1e4:
        return f"{s}${x / 1e3:.0f}K"
    if x >= 1e3:
        return f"{s}${x / 1e3:.1f}K"
    return f"{s}${x:,.0f}"


def p(x, places=0) -> str:
    return "n/a" if x is None or pd.isna(x) else f"{float(x):.{places}f}%"


@st.cache_data
def load_sample():
    return (pd.read_csv(DATA / "transactions.csv"), pd.read_csv(DATA / "apps.csv"),
            pd.read_csv(DATA / "benefits.csv"), pd.read_csv(DATA / "fx.csv"))


def read_upload(f):
    try:
        return (pd.read_csv(f, sep=None, engine="python", encoding="utf-8-sig")
                if f.name.lower().endswith(".csv") else pd.read_excel(f))
    except Exception as exc:  # noqa: BLE001
        st.sidebar.error(f"Could not read {f.name}: {exc}")
        return None


def to_csv(df: pd.DataFrame) -> bytes:
    """CSV export with spreadsheet formula injection escaped."""
    out = df.copy()
    for c in out.columns:
        if out[c].dtype == object:
            out[c] = out[c].map(lambda v: "'" + v if isinstance(v, str) and v[:1] in "=+-@" else v)
    return out.to_csv(index=False).encode()


# ---------------- sidebar ----------------
if st.sidebar.button("Reset to defaults", width="stretch"):
    st.session_state.clear()
    st.rerun()

st.sidebar.header("1. Data")
source = st.sidebar.radio("Workspace", ["Sample company (made up)", "Upload my own files"],
                          help="The sample is a fictional 600 person company with 12 apps. "
                               "Upload your own CSV or Excel files to run the same analysis on real data.")
s_txn, s_apps, s_claims, s_fx = load_sample()
if source.startswith("Upload"):
    st.sidebar.caption("Download a template, fill it in, upload it back. Column names must match.")
    c1, c2 = st.sidebar.columns(2)
    c1.download_button("Spend template", to_csv(s_txn.head(5)), "transactions_template.csv", width="stretch")
    c2.download_button("Apps template", to_csv(s_apps.head(3)), "apps_template.csv", width="stretch")
    c1.download_button("Value template", to_csv(s_claims.head(3)), "benefits_template.csv", width="stretch")
    c2.download_button("FX template", to_csv(s_fx), "fx_template.csv", width="stretch")
    up_txn = st.sidebar.file_uploader("Spend (invoices, card, AP)", type=["csv", "xlsx"])
    up_apps = st.sidebar.file_uploader("Apps and licenses", type=["csv", "xlsx"])
    up_claims = st.sidebar.file_uploader("Value claims (optional)", type=["csv", "xlsx"])
    up_fx = st.sidebar.file_uploader("Exchange rates (optional)", type=["csv", "xlsx"])
    txn = read_upload(up_txn) if up_txn else None
    apps = read_upload(up_apps) if up_apps else None
    claims = read_upload(up_claims) if up_claims else pd.DataFrame(columns=P.CLAIM_COLS)
    fx_df = read_upload(up_fx) if up_fx else s_fx
    workspace = "Your company"
else:
    txn, apps, claims, fx_df = s_txn, s_apps, s_claims, s_fx
    workspace = "Northwind Health Partners (sample)"

st.sidebar.header("2. Period")
as_of = st.sidebar.date_input("Measure the 12 months ending", value=SAMPLE_AS_OF,
                              help="Cost is the spend in the 12 months up to this date.")

st.sidebar.header("3. Rules")
classes = st.sidebar.multiselect(
    "Evidence that counts toward value", ["verified", "measured", "estimated"],
    default=["verified", "measured", "estimated"],
    help="Verified: finance confirmed cash. Measured: tracked in a system. Estimated: survey or model. "
         "Projections never count.")
util_floor = st.sidebar.slider("Target license use", 50, 95, 80, 5, format="%d%%",
                               help="Seats above what this target needs are flagged as reclaimable.")
window = st.sidebar.slider("Flag renewals within", 30, 365, 120, 15, format="%d days")

# ---------------- header ----------------
st.title("ValueOS")
intro("What every software investment is worth: cost, use and proven value per app, the savings you can act on, "
      "and a business case for the next purchase. All math is deterministic and shows its inputs.")

problems = []
if txn is None or apps is None:
    st.info("Upload a spend file and an apps file in the left panel, or switch back to the sample company.")
    st.stop()
problems += P.validate(txn, P.TXN_COLS, "Spend file")
problems += P.validate(apps, P.APP_COLS, "Apps file")
if claims is not None and (not claims.empty or set(P.CLAIM_COLS) - set(claims.columns)):
    problems += P.validate(claims, P.CLAIM_COLS, "Value file")
problems += P.validate(fx_df, ["currency", "usd_per_unit"], "FX file")
if problems:
    for msg in problems:
        st.error(msg)
    st.stop()

apps = apps.copy()
apps["app"] = apps["app"].astype(str).str.strip()
seat_raw = apps["purchased_seats"].copy()
apps["purchased_seats"] = pd.to_numeric(apps["purchased_seats"], errors="coerce")
unreadable_seats = apps.loc[apps["purchased_seats"].isna(), "app"].tolist()
apps["purchased_seats"] = apps["purchased_seats"].fillna(0).astype(int)
unreported_active = apps.loc[pd.to_numeric(apps["active_users_30d"], errors="coerce").isna(), "app"].tolist()
apps["active_users_30d"] = pd.to_numeric(apps["active_users_30d"], errors="coerce")  # blank stays unknown, not 0
fx = {str(r["currency"]).upper(): float(r["usd_per_unit"]) for _, r in fx_df.iterrows()
      if pd.notna(pd.to_numeric(r["usd_per_unit"], errors="coerce"))}
overrides = st.session_state.setdefault("vendor_overrides", {})
ledger, issues = P.prepare_transactions(txn, apps, fx, overrides)
claims_all = claims.copy() if claims is not None else pd.DataFrame(columns=P.CLAIM_COLS)
as_of_ts = pd.Timestamp(as_of)
roll = P.app_rollup(ledger, apps, claims_all, as_of_ts, classes)
claims_checked = P.eligible_claims(claims_all, apps["app"], classes) if not claims_all.empty else None
tot = P.portfolio_totals(roll)
ops = P.opportunities(roll, as_of_ts, util_floor=util_floor, renewal_window_days=window)
ops_total = float(ops.loc[ops["counts_in_total"], "mid"].sum()) if not ops.empty else 0.0
high = ops[ops["confidence"] == "High"] if not ops.empty else ops
recon = P.reconciliation_summary(ledger)
no_value = roll[~roll["has_value"] & (roll["tco_12m"] > 0)]

if float(tot["cost_all"]) == 0:
    st.warning("No spend falls in the 12 months to the chosen date. Pick a later date in the left panel.")

# ---------------- the answer ----------------
roi_txt = E.pct(tot["roi"], 0)
color = GREEN if tot["roi"].ok and tot["roi"].value > 0 else (RED if tot["roi"].ok else GREY)
best = roll.dropna(subset=["roi"]).sort_values("roi", ascending=False)
st.markdown(
    f"<div style='border:2px solid {color};border-radius:8px;padding:14px 20px;margin:6px 0 14px 0'>"
    f"<div style='font-size:.85rem;letter-spacing:.06em;color:#2B2F36'>THE ANSWER · {workspace.upper()}</div>"
    f"<div style='font-size:1.9rem;font-weight:700;color:{color}'>"
    + (f"{roi_txt} return on the {k(tot['cost'])} of software with evidence</div>" if tot["roi"].ok
       else f"Return unknown: {tot['roi'].reason}</div>")
    + f"<div style='font-size:1.05rem;color:#111'>{k(ops_total)} a year in savings ideas "
    f"({len(high)} high confidence). "
    + (f"Best: <b>{best.iloc[0]['app']}</b> at {p(best.iloc[0]['roi'])}. " if len(best) else "")
    + (f"<b>{len(no_value)}</b> apps ({k(no_value['tco_12m'].sum())}) have no evidence yet, so their return is unknown."
       if len(no_value) else "")
    + "</div></div>", unsafe_allow_html=True)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Software cost, 12 months", k(tot["cost_all"]), help="Every subscription, one time and refund line "
          "matched to an app, net of credits, in USD.")
note(m1, f"{len(roll)} apps · {recon['unmatched']} lines unmatched")
m2.metric("Value with evidence", k(tot["value"]), help="Approved claims in the evidence classes chosen "
          "in the left panel; overlapping claims counted once; projections excluded.")
note(m2, f"{k(tot['cash'])} of it is verified cash")
m3.metric("Return on cost", roi_txt, help="(Value - cost) / cost over the apps that have evidence, from "
          "totals, not an average of app ROIs. Apps with no evidence are left out rather than counted as zero.")
note(m3, f"Net {k(tot['net'])} a year · {k(tot['unmeasured'])} unmeasured")
m4.metric("Savings ideas", k(ops_total), help="Midpoint of each idea's range; when several ideas hit the "
          "same app only the largest counts.")
note(m4, f"{len(ops)} ideas across {ops['app'].nunique() if not ops.empty else 0} apps")

tabs = st.tabs(["Overview", "Apps", "Savings ideas", "Spend", "Data check", "Business case", "Report",
                "Methodology"])

# ---------------- overview ----------------
with tabs[0]:
    left, right = st.columns([2, 1])
    with left:
        st.subheader("What each app costs and returns")
        r = roll[roll["tco_12m"] > 0].copy()
        r["sort"] = r.apply(lambda x: (x["economic_value"] - x["tco_12m"]) if x["has_value"] else -1e12, axis=1)
        r = r.sort_values("sort")
        labels = [wrap(a, 22) for a in r["app"]]
        fig = go.Figure()
        for (_, x), lab in zip(r.iterrows(), labels):
            if x["has_value"]:
                fig.add_trace(go.Scatter(x=[x["tco_12m"], x["economic_value"]], y=[lab, lab], mode="lines",
                                         line=dict(color=GREEN if x["economic_value"] >= x["tco_12m"] else RED,
                                                   width=4), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=r["tco_12m"], y=labels, mode="markers", name="Cost",
                                 marker=dict(size=13, color=GREY, symbol="line-ns-open", line=dict(width=3, color=GREY)),
                                 hovertemplate="%{y}<br>Cost %{x:$,.0f}<extra></extra>"))
        ev = r[r["has_value"]]
        fig.add_trace(go.Scatter(
            x=ev["economic_value"], y=[wrap(a, 22) for a in ev["app"]], mode="markers", showlegend=False,
            marker=dict(size=13, color=[GREEN if v >= c else RED for v, c in zip(ev["economic_value"], ev["tco_12m"])]),
            customdata=ev[["roi"]].values, hovertemplate="%{y}<br>Value %{x:$,.0f}<br>ROI %{customdata[0]:.0f}%<extra></extra>"))
        for nm, col in [("Value beats cost", GREEN), ("Value below cost", RED)]:
            fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", name=nm, marker=dict(size=12, color=col)))
        ne = r[~r["has_value"]]
        if len(ne):
            fig.add_trace(go.Scatter(x=ne["tco_12m"], y=[wrap(a, 22) for a in ne["app"]], mode="text",
                                     text=["   no evidence yet"] * len(ne), textposition="middle right",
                                     textfont=dict(color=GREY, size=12), showlegend=False, hoverinfo="skip"))
        mx = max(r["tco_12m"].max(), r["economic_value"].max()) if len(r) else 1
        fig.update_layout(height=max(300, 34 * len(r) + 110), xaxis=dict(tickprefix="$", tickformat="~s",
                          range=[0, mx * 1.15]), yaxis=dict(categoryorder="array", categoryarray=labels),
                          legend=dict(orientation="h", y=-0.12), margin=dict(t=10, r=20))
        st.plotly_chart(fig, width="stretch", theme=None)
        takeaway("Gray tick = cost. Dot = value with evidence: green when it beats the cost, red when it does not. "
                 "No evidence yet means the return is unknown, not zero.")
    with right:
        st.subheader("Do these first")
        if ops.empty:
            st.write("No savings ideas under the current rules.")
        for _, o in ops[ops["counts_in_total"]].sort_values("mid", ascending=False).head(5).iterrows():
            st.markdown(f"**{o['app']}** · {o['type']}  \n{o['action']}  \n"
                        f"<span style='color:{GREEN};font-weight:600'>{k(o['low'])} to {k(o['high'])} a year</span>"
                        f" · {o['confidence']} confidence", unsafe_allow_html=True)
    st.subheader("Spend by month")
    tr = P.monthly_trend(ledger, as_of_ts)
    fig = go.Figure(go.Bar(x=tr["month"], y=tr["amount_usd"], marker_color=NAVY,
                           hovertemplate="%{x|%b %Y}: %{y:$,.0f}<extra></extra>"))
    fig.update_layout(height=280, yaxis=dict(tickprefix="$", tickformat="~s"), margin=dict(t=10))
    st.plotly_chart(fig, width="stretch", theme=None)

# ---------------- apps ----------------
with tabs[1]:
    st.subheader("App inventory")
    view = roll.assign(renewal=roll["renewal_date"].dt.strftime("%b %d, %Y"))[
        ["app", "category", "tco_12m", "economic_value", "roi", "utilization", "cost_per_active", "renewal"]]
    st.dataframe(view, hide_index=True, width="stretch", column_config={
        "app": "App", "category": "Category",
        "tco_12m": st.column_config.NumberColumn("Cost (12 mo)", format="$%,.0f"),
        "economic_value": st.column_config.NumberColumn("Value", format="$%,.0f"),
        "roi": st.column_config.NumberColumn("ROI", format="%.0f%%", help="Blank = no evidence yet"),
        "utilization": st.column_config.ProgressColumn("License use", format="%.0f%%", min_value=0, max_value=100),
        "cost_per_active": st.column_config.NumberColumn("Cost per active user", format="$%,.0f"),
        "renewal": "Renews"})
    st.download_button("Download inventory (CSV)", to_csv(view), "valueos_apps.csv")

    st.subheader("Open one app")
    pick = st.selectbox("App", roll["app"].tolist(), label_visibility="collapsed")
    a = roll.set_index("app").loc[pick]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Cost, 12 months", k(a["tco_12m"]))
    note(c1, f"{k(a['recurring'])} subscriptions · {k(a['one_time'])} one time")
    c2.metric("Value with evidence", k(a["economic_value"]) if a["has_value"] else "No evidence")
    note(c2, f"{k(a['cash_value'])} verified cash")
    c3.metric("ROI", p(a["roi"]))
    note(c3, a["roi_note"] or f"({k(a['economic_value'])} - {k(a['tco_12m'])}) / {k(a['tco_12m'])}")
    c4.metric("License use", p(a["utilization"]))
    note(c4, (f"{int(a['active'])} active of " if pd.notna(a['active']) else "Active users not reported · ")
      + f"{int(a['purchased'])} seats")

    st.markdown("**Evidence behind the value**")
    if claims_all.empty:
        st.write("No value file loaded.")
    else:
        ev = claims_checked[claims_checked["app"] == pick].copy()
        if ev.empty:
            st.write("No claims for this app. Add one to the value file to measure its ROI.")
        else:
            st.dataframe(ev[["claim_id", "benefit_type", "annual_amount", "evidence_class", "status", "source",
                             "counted", "note"]], hide_index=True, width="stretch", column_config={
                "claim_id": "Claim", "benefit_type": "Type",
                "annual_amount": st.column_config.NumberColumn("Per year", format="$%,.0f"),
                "evidence_class": "Evidence", "status": "Status", "source": "Source",
                "counted": "Counted", "note": "Why not counted"})
    st.markdown("**Spend lines**")
    st.dataframe(ledger[ledger["app"] == pick][["txn_id", "date", "vendor", "amount", "currency", "amount_usd",
                                                 "type", "department", "excluded"]]
                 .sort_values("date", ascending=False), hide_index=True, width="stretch",
                 column_config={"date": st.column_config.DateColumn("Date"),
                                "amount_usd": st.column_config.NumberColumn("USD", format="$%,.2f")})

# ---------------- savings ----------------
with tabs[2]:
    st.subheader("Savings ideas, ranked")
    if ops.empty:
        st.write("Nothing flagged under the current rules. Raise the license target or widen the renewal "
                 "window in the left panel.")
    else:
        g = ops.copy()
        fig = go.Figure()
        for conf, col in [("High", GREEN), ("Medium", GOLD), ("Low", GREY)]:
            gg = g[(g["confidence"] == conf) & g["counts_in_total"]]
            if len(gg):
                fig.add_trace(go.Bar(y=[wrap(f"{a} · {t}", 26) for a, t in zip(gg["app"], gg["type"])],
                                     x=gg["mid"], orientation="h", name=f"{conf} confidence", marker_color=col,
                                     error_x=dict(type="data", symmetric=False, array=gg["high"] - gg["mid"],
                                                  arrayminus=gg["mid"] - gg["low"], color="#555"),
                                     hovertemplate="%{y}<br>Midpoint %{x:$,.0f}<extra></extra>"))
        n = int(g["counts_in_total"].sum())
        fig.update_layout(height=max(260, 46 * n + 80), barmode="overlay", xaxis=dict(tickprefix="$", tickformat="~s"),
                          yaxis=dict(autorange="reversed"), legend=dict(orientation="h", y=-0.15),
                          margin=dict(t=10))
        st.plotly_chart(fig, width="stretch", theme=None)
        takeaway(f"Acting on every counted idea saves about {k(ops_total)} a year "
                 f"(range {k(ops.loc[ops['counts_in_total'], 'low'].sum())} to "
                 f"{k(ops.loc[ops['counts_in_total'], 'high'].sum())}). These are potential savings; they count "
                 "as realized only after finance verifies them.")
        st.dataframe(g[["app", "type", "action", "low", "high", "confidence", "evidence", "counts_in_total"]],
                     hide_index=True, width="stretch", column_config={
                         "app": "App", "type": "Idea", "action": "What to do",
                         "low": st.column_config.NumberColumn("Low", format="$%,.0f"),
                         "high": st.column_config.NumberColumn("High", format="$%,.0f"),
                         "confidence": "Confidence", "evidence": "Evidence",
                         "counts_in_total": st.column_config.CheckboxColumn(
                             "In total", help="Only the largest idea per app counts, so the total is not "
                                              "double counted.")})
        st.download_button("Download ideas (CSV)", to_csv(g), "valueos_savings_ideas.csv")

# ---------------- spend ----------------
with tabs[3]:
    used = ledger[~ledger["excluded"]].merge(apps[["app", "category"]], on="app", how="left")
    used["category"] = used["category"].fillna("Unmatched")
    c1, c2 = st.columns(2)
    for col, field, title in [(c1, "department", "By department"), (c2, "category", "By category")]:
        s = used.groupby(field)["amount_usd"].sum().sort_values()
        fig = go.Figure(go.Bar(y=[wrap(i, 18) for i in s.index], x=s.values, orientation="h", marker_color=NAVY,
                               text=[k(v) for v in s.values], textposition="outside", cliponaxis=False,
                               hovertemplate="%{y}: %{x:$,.0f}<extra></extra>"))
        fig.update_layout(title=title, height=max(260, 34 * len(s) + 90),
                          xaxis=dict(tickprefix="$", tickformat="~s", range=[0, s.max() * 1.25 if len(s) else 1]),
                          margin=dict(t=40, r=40))
        col.plotly_chart(fig, width="stretch", theme=None)
    st.subheader("Ledger")
    q = st.text_input("Filter by vendor, app or department", placeholder="e.g. zoom")
    lv = ledger.copy()
    if q:
        mask = lv[["vendor", "app", "department"]].astype(str).apply(lambda s: s.str.contains(q, case=False, regex=False)).any(axis=1)
        lv = lv[mask]
    st.dataframe(lv[["txn_id", "date", "vendor", "app", "department", "type", "amount", "currency", "fx_rate",
                     "amount_usd", "excluded"]].sort_values("date", ascending=False), hide_index=True,
                 width="stretch", column_config={
                     "date": st.column_config.DateColumn("Date"),
                     "amount_usd": st.column_config.NumberColumn("USD", format="$%,.2f"),
                     "excluded": st.column_config.CheckboxColumn("Excluded")})
    st.download_button("Download ledger (CSV)", to_csv(lv), "valueos_ledger.csv")

# ---------------- data check ----------------
with tabs[4]:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Spend lines", recon["rows"])
    c2.metric("Matched to an app", recon["matched"])
    c3.metric("Unmatched", recon["unmatched"])
    note(c3, f"{k(recon['unmatched_usd'])} not in any app's cost")
    c4.metric("Excluded", recon["excluded"])
    note(c4, "Duplicates and unreadable lines")
    if issues.empty:
        st.success("No data problems found.")
    else:
        st.subheader("Problems to fix")
        st.dataframe(issues, hide_index=True, width="stretch")
    unmatched = sorted(ledger.loc[ledger["app"].isna() & ~ledger["excluded"], "vendor"].dropna().unique())
    if unmatched:
        st.subheader("Vendor mapping")
        st.caption("Pick the app each unmatched vendor belongs to. Choices apply right away and stay for this session.")
        opts = ["Leave unmatched"] + apps["app"].tolist()
        with st.form("mapping"):
            picks = {v: st.selectbox(v, opts, key=f"map_{v}") for v in unmatched}
            if st.form_submit_button("Apply mapping"):
                for v, a in picks.items():
                    if a != "Leave unmatched":
                        overrides[v] = a
                st.rerun()
    if claims_checked is not None:
        flagged = claims_checked[claims_checked["note"].isin(
            ["App is not in the apps file", "Amount missing or not a number", "Unknown evidence class"])]
        if len(flagged):
            st.subheader("Value claims that could not be counted")
            st.dataframe(flagged[["claim_id", "app", "annual_amount", "evidence_class", "note"]], hide_index=True,
                         width="stretch", column_config={"note": "Problem"})
    if float(tot["value_without_cost"]) > 0:
        st.warning(f"{k(tot['value_without_cost'])} of value belongs to apps with no cost in this period, so it is "
                   "left out of ROI. Check the spend file or the period.")
    if unreadable_seats or unreported_active:
        st.subheader("App rows to check")
        rows = [{"app": a, "problem": "Seat count is blank or not a number, so it counts as 0 seats and no seat ideas run"}
                for a in unreadable_seats]
        rows += [{"app": a, "problem": "Active users not reported, so license use shows n/a and no seat ideas run"}
                 for a in unreported_active]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    if overrides:
        st.caption("Manual mappings: " + ", ".join(f"{a} → {b}" for a, b in overrides.items()))
        if st.button("Clear manual mappings"):
            overrides.clear()
            st.rerun()

# ---------------- business case ----------------
with tabs[5]:
    st.subheader("Should we buy it? Build the business case")
    st.caption("Model a new tool before you sign. Benefits are hours saved priced at a loaded labor rate, "
               "which is economic value, not cash.")
    c1, c2, c3 = st.columns(3)
    seats = c1.number_input("Seats", 1, 100_000, 200, 10)
    price = c1.number_input("Price per seat per month ($)", 0.0, 10_000.0, 30.0, 5.0)
    setup_cost = c1.number_input("One time setup ($)", 0.0, 10_000_000.0, 60_000.0, 5_000.0,
                                 help="Implementation, integration, training and consulting.")
    escal = c1.slider("Yearly price increase", 0, 20, 5, format="%d%%")
    a0 = c2.slider("Adoption at launch", 0, 100, 30, 5, format="%d%%")
    a1 = c2.slider("Adoption once ramped", 0, 100, 75, 5, format="%d%%")
    ramp = c2.slider("Months to ramp", 1, 24, 6)
    hours = c2.number_input("Hours saved per user per week", 0.0, 40.0, 1.0, 0.5)
    rate = c3.number_input("Loaded hourly labor rate ($)", 0.0, 1_000.0, 55.0, 5.0)
    real = c3.slider("Share of saved time put to work", 0, 100, 40, 5, format="%d%%",
                     help="Realization factor: saved time only has value if it is used for other work.")
    horizon = 12 * c3.select_slider("Horizon (years)", [1, 2, 3, 4, 5], 3)
    disc = c3.slider("Discount rate", 0, 25, 10, format="%d%%")
    case = E.Case(seats=seats, price_per_seat_month=price, setup_cost=setup_cost, adoption_start=a0 / 100,
                  adoption_target=a1 / 100, ramp_months=ramp, hours_saved_per_user_week=hours,
                  loaded_hourly_rate=rate, realization=real / 100, working_weeks=46, horizon_months=horizon,
                  discount_rate_annual=disc / 100, annual_price_escalation=escal / 100)
    out = E.case_flows(case)
    be = E.break_even_adoption(case)
    verdict_ok = out["npv"] > 0
    vc = GREEN if verdict_ok else RED
    pb = out["payback"]
    empty_case = out["total_cost"] == 0 and out["total_benefit"] == 0
    if empty_case:
        st.info("Enter a price, setup cost or hours saved to model a purchase.")
    else:
        st.markdown(
        f"<div style='border:2px solid {vc};border-radius:8px;padding:12px 18px;margin:8px 0'>"
        f"<div style='font-size:1.5rem;font-weight:700;color:{vc}'>"
        f"{'Worth it' if verdict_ok else 'Not worth it at these numbers'}: NPV {k(out['npv'])}</div>"
        f"<div>{'Value covers the cost in ' + f'{float(pb.value):.1f} months' if pb.ok else pb.reason} · "
        f"needs {E.pct(be, 0) if be.ok else 'n/a'} adoption to break even"
        f"{'' if be.ok else ' (' + be.reason + ')'}</div></div>", unsafe_allow_html=True)
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Total cost", k(out["total_cost"]))
    r2.metric("Total value", k(out["total_benefit"]))
    r3.metric("ROI", E.pct(out["roi"], 0))
    irr_v = out["irr"]
    if irr_v.ok and irr_v.value > 1000:
        r4.metric("IRR (yearly)", "Over 1,000%")
        note(r4, "Setup is small next to the monthly gains, so judge this one on NPV and payback.")
    else:
        r4.metric("IRR (yearly)", E.pct(irr_v, 0) if irr_v.ok else "n/a")
        if irr_v.reason:
            note(r4, irr_v.reason)
    cum, run = [], 0.0
    for v in out["net"]:
        run += float(v)
        cum.append(run)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=list(range(len(out["net"]))), y=[float(v) for v in out["net"]], name="Net each month",
                         marker_color=[GREEN if v >= 0 else RED for v in out["net"]]))
    fig.add_trace(go.Scatter(x=list(range(len(cum))), y=cum, name="Running total", line=dict(color=NAVY, width=3)))
    fig.add_hline(y=0, line_color="#9AA3AF")
    fig.update_layout(height=320, xaxis_title="Month", yaxis=dict(tickformat="$~s"),
                      legend=dict(orientation="h", y=-0.25), margin=dict(t=10))
    st.plotly_chart(fig, width="stretch", theme=None)

    st.markdown("**What moves the answer most** (each input 20% worse, then 20% better)")
    base_npv = float(out["npv"])
    rows = []
    for field, label, worse in [("hours_saved_per_user_week", "Hours saved", -1), ("loaded_hourly_rate", "Labor rate", -1),
                                ("realization", "Time put to work", -1), ("adoption_target", "Adoption", -1),
                                ("price_per_seat_month", "Price per seat", 1), ("setup_cost", "Setup cost", 1)]:
        vals = []
        for sign in (worse, -worse):
            cc = E.Case(**{**case.__dict__})
            setattr(cc, field, min(1.0, getattr(cc, field) * (1 + 0.2 * sign)) if field in ("realization", "adoption_target")
                    else getattr(cc, field) * (1 + 0.2 * sign))
            if field == "adoption_target":
                cc.adoption_start = min(cc.adoption_start, cc.adoption_target)
            vals.append(float(E.case_flows(cc)["npv"]) - base_npv)
        rows.append((label, vals[0], vals[1]))
    rows.sort(key=lambda r: abs(r[2] - r[1]))
    fig = go.Figure()
    fig.add_trace(go.Bar(y=[r[0] for r in rows], x=[r[1] for r in rows], orientation="h", name="20% worse",
                         marker_color=RED, hovertemplate="%{y}: %{x:$,.0f}<extra></extra>"))
    fig.add_trace(go.Bar(y=[r[0] for r in rows], x=[r[2] for r in rows], orientation="h", name="20% better",
                         marker_color=GREEN, hovertemplate="%{y}: %{x:$,.0f}<extra></extra>"))
    fig.update_layout(height=300, barmode="overlay", xaxis=dict(title="Change in NPV", tickformat="$~s"),
                      legend=dict(orientation="h", y=-0.3), margin=dict(t=10))
    st.plotly_chart(fig, width="stretch", theme=None)
    takeaway(f"<b>{rows[-1][0]}</b> matters most: being 20% wrong on it moves NPV by about "
             f"{k(max(abs(rows[-1][1]), abs(rows[-1][2])))}. Check that number before you sign.")
    flows = pd.DataFrame({"month": range(len(out["net"])), "cost": [float(v) for v in out["costs"]],
                          "value": [float(v) for v in out["benefits"]], "net": [float(v) for v in out["net"]],
                          "adoption": [float(v) for v in out["adoption"]]})
    st.download_button("Download monthly cash flows (CSV)", to_csv(flows), "valueos_business_case.csv")

# ---------------- report ----------------
with tabs[6]:
    st.subheader("Executive summary")
    top3 = ops[ops["counts_in_total"]].head(3) if not ops.empty else ops
    lines = [
        f"Software cost over the 12 months to {as_of:%B %d, %Y} was {k(tot['cost_all'])} across {len(roll)} apps.",
        f"Value backed by approved evidence was {k(tot['value'])} against {k(tot['cost'])} of cost for the apps "
        f"with evidence, a {roi_txt} return; {k(tot['cash'])} of that is verified cash "
        f"(cash ROI {E.pct(tot['cash_roi'], 0)}).",
        f"{len(no_value)} apps costing {k(no_value['tco_12m'].sum())} have no value evidence yet; their return "
        "is unknown, not zero." if len(no_value) else "Every app has at least one approved value claim.",
        f"Savings ideas total about {k(ops_total)} a year; the top three are "
        + "; ".join(f"{r['app']} ({r['type'].lower()}, {k(r['mid'])})" for _, r in top3.iterrows()) + "."
        if len(top3) else "No savings ideas under the current rules.",
        f"Data check: {recon['matched']} of {recon['rows']} spend lines matched to an app, {recon['unmatched']} "
        f"unmatched ({k(recon['unmatched_usd'])}), {recon['excluded']} excluded as duplicates or unreadable.",
    ]
    for ln in lines:
        st.markdown(f"- {ln}")
    html = ("<html><head><meta charset='utf-8'><title>ValueOS report</title><style>body{font-family:Arial;"
            "max-width:900px;margin:30px auto;color:#111}table{border-collapse:collapse;width:100%}td,th{border:1px "
            "solid #ccc;padding:6px;font-size:13px}th{background:#EEF2FB}</style></head><body>"
            f"<h1>ValueOS report: {workspace}</h1><p>12 months ending {as_of:%B %d, %Y}. Evidence counted: "
            f"{', '.join(classes)}. Amounts in USD.</p><ul>" + "".join(f"<li>{ln}</li>" for ln in lines) + "</ul>"
            "<h2>Apps</h2>" + view.to_html(index=False, float_format=lambda v: f"{v:,.0f}", na_rep="n/a")
            + "<h2>Savings ideas</h2>" + (ops[["app", "type", "action", "low", "high", "confidence"]]
                                         .to_html(index=False, float_format=lambda v: f"{v:,.0f}") if not ops.empty else "")
            + "<h2>Method</h2><p>ROI = (value - cost) / cost from portfolio totals. Value counts approved, non "
              "projected claims; overlapping claims once. Missing evidence is shown as n/a, never 0%.</p>"
            + "</body></html>")
    st.download_button("Download report (HTML, opens in any browser and prints to PDF)", html.encode(),
                       "valueos_report.html", mime="text/html", type="primary")

# ---------------- methodology ----------------
with tabs[7]:
    st.markdown("""
**Cost (TCO).** Every spend line matched to an app in the 12 months to the chosen date: subscriptions, one time
costs (setup, training, consulting), less refunds and credits. Foreign currency converts at the rate in the FX
table. Possible duplicates (same vendor, amount, date and type) are excluded and listed in Data check.

**Value.** Each claim has a type (cash savings, avoided cost, productivity, incremental profit, risk reduction),
an evidence class and an approval status. Only approved claims in the classes chosen in the left panel count.
Projections never count. Claims in the same overlap group (two apps claiming the same saved hours) count once,
keeping the largest. Time saved is economic value, not cash; cash ROI uses verified cash savings and avoided
costs only.

**ROI.** (value - cost) / cost x 100. Portfolio ROI comes from summed costs and values, never an average of app
ROIs. When cost is zero, or an app has no approved evidence, ROI shows n/a, never 0%.

**Savings ideas.** Rules, not guesses: reclaim seats above the license use target, renegotiate renewals in the
window, consolidate tools in the same category onto the one more people use (skipped when the smaller tool
earns a higher ROI), and review apps whose counted value is below cost. Each idea carries a range and a
confidence. When several ideas hit one app only the largest counts toward the total.

**Business case.** Monthly cash flows over the horizon. Adoption ramps in a straight line to its target. Benefit =
seats x adoption x hours saved x 46/12 weeks a month x labor rate x share of time put to work. NPV discounts at the
monthly equivalent of the yearly rate; IRR is solved by bisection and flagged when more than one may exist;
payback is undiscounted and interpolated within the month. Break even adoption is the steady state adoption at
which NPV is zero.

**Limits.** The sample company is made up. Uploaded files stay in this browser session and are not stored.
Correlation between usage and outcomes is not proof of cause; claims need an owner and evidence for that.
""")
    st.caption("Built by Klord Fernandez Cayetano · github.com/Klord1055/valueos")

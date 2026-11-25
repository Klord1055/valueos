# ValueOS

**What every software investment is worth.** Upload a spend file and an app list, or open the made up sample company, and ValueOS shows:

- **The answer first:** the return on software that has evidence behind it, the savings you can act on, and which apps have no evidence yet.
- **Cost and value per app:** 12 month TCO (subscriptions, one time costs, refunds), license use, cost per active user, ROI, and every claim behind the value, including why a claim was or was not counted.
- **Savings ideas, ranked:** reclaim unused seats, renegotiate upcoming renewals, consolidate overlapping tools, and review apps that cost more than they return. Each idea comes with a range and a confidence level, and the total never double counts an app.
- **Data check:** unmatched vendors, duplicates, unknown currencies and blank departments, with a vendor mapping fix built into the page.
- **Business case:** NPV, IRR, payback, the break even adoption rate, and a sensitivity chart that shows which assumption matters most before you sign.
- **Report:** an executive summary plus HTML and CSV exports.

Live demo: https://klord-valueos.streamlit.app

## How the numbers work

| Measure | Rule |
|---|---|
| Cost (TCO) | Spend lines matched to an app in the 12 months to the chosen date, net of refunds and credits, converted to USD |
| Value | Approved claims in the chosen evidence classes (verified, measured, estimated). Projections never count, and overlapping claims count once |
| ROI | (value − cost) / cost, computed from totals over the apps that have evidence. Missing evidence shows as n/a, never 0% |
| Cash ROI | Verified cash savings and avoided costs only. Saved time is economic value, not cash |
| Money | Python `Decimal`, rounded only for display |

The golden cases from the spec are covered by tests: a $72K cost with $198K of benefit gives a 175% ROI, and a portfolio costing $1.24M with $3.82M of value gives about 208.1%.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
python -m pytest -q tests   # 23 tests
```

## Cost

$0. The stack is open source (Streamlit, pandas, NumPy, Plotly, openpyxl), and the demo is hosted on Streamlit Community Cloud's free tier. There are no paid APIs, keys or AI services. All analysis is deterministic.

## Scope and limits

This is the core vertical slice of the ValueOS specification: import, mapping, reconciliation, app profile, ROI evidence, opportunities, simulator and report. Uploaded files live only in the browser session; nothing is stored. Not built yet: accounts, multi tenant storage, live connectors (QuickBooks, HubSpot, Google Workspace), approvals workflow and generative AI. See `docs/DECISIONS.md`.

The sample company and every number in it are invented.

Built by Klord Fernandez Cayetano.

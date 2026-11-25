"""Builds the synthetic sample workspace. Every company, number and person here is invented.

Run: python data/make_sample.py
"""
import csv
import random
from pathlib import Path

random.seed(7)
HERE = Path(__file__).parent

APPS = [
    # app, vendor, category, owner, seats, active, annual price/seat, renewal, notice, dept, invoice name variants
    ("Slack", "Slack Technologies", "Messaging", "IT", 420, 371, 105, "2027-01-15", 60, "IT", ["SLACK TECHNOLOGIES LLC", "Slack"]),
    ("Microsoft Teams", "Microsoft", "Messaging", "IT", 400, 138, 48, "2027-06-30", 90, "IT", ["MICROSOFT CORP"]),
    ("Zoom", "Zoom Video Communications", "Video meetings", "IT", 300, 121, 180, "2026-12-20", 30, "IT", ["ZOOM VIDEO COMMUNICATIONS INC.", "Zoom.us"]),
    ("Salesforce", "Salesforce", "CRM", "Sales Ops", 85, 79, 1980, "2027-03-31", 90, "Sales", ["SALESFORCE.COM INC"]),
    ("HubSpot", "HubSpot", "Marketing automation", "Marketing", 25, 22, 1200, "2027-08-01", 60, "Marketing", ["HUBSPOT INC"]),
    ("ChatGPT Enterprise", "OpenAI", "AI assistant", "IT", 150, 97, 720, "2027-02-28", 30, "Operations", ["OPENAI LLC", "OpenAI"]),
    ("Claude", "Anthropic", "AI assistant", "IT", 60, 54, 360, "2027-05-31", 30, "Engineering", ["ANTHROPIC PBC"]),
    ("Asana", "Asana", "Project management", "PMO", 180, 64, 132, "2026-12-31", 60, "Operations", ["ASANA INC"]),
    ("Jira", "Atlassian", "Project management", "Engineering", 120, 112, 96, "2027-04-30", 30, "Engineering", ["ATLASSIAN PTY LTD", "Atlassian"]),
    ("DocuSign", "DocuSign", "E-signature", "Legal", 40, 31, 480, "2027-07-15", 60, "Legal", ["DOCUSIGN INC"]),
    ("Tableau", "Salesforce Tableau", "Analytics", "Finance", 35, 9, 900, "2027-01-31", 60, "Finance", ["TABLEAU SOFTWARE"]),
    ("Figma", "Figma", "Design", "Product", 30, 28, 540, "2027-09-30", 30, "Product", ["FIGMA INC"]),
]

MONTHS = [f"{y}-{m:02d}" for y, m in [(2025, 11), (2025, 12)] + [(2026, k) for k in range(1, 11)]]


def main():
    with open(HERE / "apps.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["app", "vendor", "category", "owner", "purchased_seats", "active_users_30d",
                    "renewal_date", "notice_days"])
        for a in APPS:
            w.writerow([a[0], a[1], a[2], a[3], a[4], a[5], a[7], a[8]])

    rows, n = [], 1
    for a in APPS:
        monthly = round(a[4] * a[6] / 12, 2)
        for i, mo in enumerate(MONTHS):
            rows.append([f"T{n:04d}", f"{mo}-05", random.choice(a[10]), monthly, "USD", a[9], "recurring"]); n += 1
    # one time costs
    rows.append([f"T{n:04d}", "2026-02-10", "SALESFORCE.COM INC", 38000, "USD", "Sales", "one_time"]); n += 1
    rows.append([f"T{n:04d}", "2026-03-18", "OPENAI LLC", 12000, "USD", "Operations", "one_time"]); n += 1
    rows.append([f"T{n:04d}", "2026-04-02", "Anthropic", 6500, "USD", "Engineering", "one_time"]); n += 1
    # a refund, a duplicate, a euro invoice, an unmatched vendor, a missing department
    rows.append([f"T{n:04d}", "2026-06-20", "ZOOM VIDEO COMMUNICATIONS INC.", 1800, "USD", "IT", "refund"]); n += 1
    rows.append([f"T{n:04d}", "2026-07-05", "SLACK TECHNOLOGIES LLC", round(420 * 105 / 12, 2), "USD", "IT", "recurring"]); n += 1
    rows.append([f"T{n:04d}", "2026-05-12", "MIRO BV", 4600, "EUR", "Product", "recurring"]); n += 1
    rows.append([f"T{n:04d}", "2026-08-12", "GRAMMARLY INC", 2400, "USD", "", "recurring"]); n += 1
    with open(HERE / "transactions.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["txn_id", "date", "vendor", "amount", "currency", "department", "type"])
        w.writerows(rows)

    claims = [
        ("B01", "Salesforce", "incremental_profit", 310000, "measured", "approved", "Sales Ops", "CRM win rate study, FY26 H1", ""),
        ("B02", "Salesforce", "productivity", 95000, "estimated", "approved", "Sales Ops", "Rep time survey, n=62", "sales-admin"),
        ("B03", "HubSpot", "incremental_profit", 64000, "measured", "approved", "Marketing", "Attributed pipeline, 40% margin", ""),
        ("B04", "HubSpot", "productivity", 22000, "estimated", "approved", "Marketing", "Campaign build time logs", "sales-admin"),
        ("B05", "ChatGPT Enterprise", "productivity", 168000, "estimated", "approved", "Operations", "Time saved survey, 50% realization", ""),
        ("B06", "Claude", "productivity", 92000, "measured", "approved", "Engineering", "PR cycle time before/after", ""),
        ("B07", "ChatGPT Enterprise", "cash_savings", 36000, "verified", "approved", "Finance", "Cancelled translation vendor contract", ""),
        ("B08", "DocuSign", "avoided_cost", 21000, "verified", "approved", "Legal", "Courier and printing invoices stopped", ""),
        ("B09", "Slack", "productivity", 60000, "estimated", "approved", "IT", "Meeting reduction survey", ""),
        ("B10", "Jira", "productivity", 30000, "estimated", "pending", "Engineering", "Sprint throughput, awaiting finance review", ""),
        ("B11", "Tableau", "productivity", 8000, "estimated", "approved", "Finance", "Report automation hours", ""),
        ("B12", "Figma", "productivity", 26000, "measured", "approved", "Product", "Design handoff time logs", ""),
        ("B13", "Asana", "productivity", 40000, "projected", "approved", "PMO", "Vendor business case", ""),
        ("B14", "Zoom", "avoided_cost", 18000, "verified", "approved", "IT", "Travel spend reduction, finance verified", ""),
    ]
    with open(HERE / "benefits.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["claim_id", "app", "benefit_type", "annual_amount", "evidence_class", "status", "owner",
                    "source", "overlap_group"])
        w.writerows(claims)

    with open(HERE / "fx.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["currency", "usd_per_unit", "as_of", "source"])
        w.writerow(["USD", 1.0, "2026-10-31", "base"])
        w.writerow(["EUR", 1.0981, "2026-10-31", "Sample rate for the demo; replace with your treasury rate"])
        w.writerow(["GBP", 1.27, "2026-10-31", "Sample rate for the demo; replace with your treasury rate"])


if __name__ == "__main__":
    main()

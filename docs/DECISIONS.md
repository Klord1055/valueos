# Decisions

| # | Decision | Why |
|---|---|---|
| 1 | Build the spec's Phase 2 vertical slice first (import, mapping, reconciliation, app profile, ROI evidence, opportunities, simulator, report) | The full spec covers 150+ routes. One complete, tested workflow beats many placeholder screens, which the spec forbids |
| 2 | Python + Streamlit on Streamlit Community Cloud, free tier | Meets the $0 rule with no card on file. It matches the owner's other live apps. Next.js/FastAPI/PostgreSQL stays the target for a multi tenant version |
| 3 | No accounts or database; uploaded data lives only in the session | Free hosting has no durable private storage. Keeping customer data out of storage avoids privacy risk |
| 4 | Deterministic engine, no AI service | The spec requires core analytics to work without a model. There are no paid tokens |
| 5 | ROI covers apps with evidence. Apps without evidence are reported as unmeasured cost | The spec says missing is not zero. Counting unmeasured cost against measured value would understate ROI |
| 6 | When several savings ideas hit one app, only the largest counts toward the total | Cutting seats and retiring the same tool cannot both happen |
| 7 | Consolidation keeps the tool with more active users and is skipped when the smaller tool has a higher ROI | This avoids recommending the retirement of the better performer |
| 8 | CSV exports escape leading = + - @ | Prevents spreadsheet formula injection, as the spec requires |

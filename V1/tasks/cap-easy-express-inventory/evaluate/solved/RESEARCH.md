# RESEARCH

Research notes:
- source: the local kb docs and fixture tests define the API contract
- decision: use Node standard-library HTTP handling with file-backed JSON persistence so the app stays local and deterministic
- tradeoff: avoid extra framework or database setup because this task only needs a small Express-style API and no external network

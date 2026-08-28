# RESEARCH

Research notes:
- source: the local KB docs and fixture tests define the API contract
- decision: use FastAPI with stdlib `sqlite3` to keep persistence simple
- tradeoff: avoid extra ORM complexity for this small helpdesk workflow

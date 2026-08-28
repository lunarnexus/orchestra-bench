# Persistence notes

- Use SQLite, not an in-memory-only data structure.
- The evaluator will restart the Django process and expect event data plus report history to remain available.
- Read the database path from `REPORTS_DB`; default to a local file in the workspace.
- Keep schema setup automatic and deterministic: a fresh or deleted `REPORTS_DB` file must be initialized before the first endpoint query/write, not only during tests or `reset_database()`.
- SQLite plus Django ORM filtering/aggregation is sufficient here; do not add network services.
- Report history is part of the product behavior, not just debug logging.

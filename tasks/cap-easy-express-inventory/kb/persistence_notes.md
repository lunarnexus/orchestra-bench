# Persistence notes

- Use a real file on disk, not an in-memory global list.
- Data file path comes from `INVENTORY_DB` and should default to `inventory-data.json`.
- The fixture tests use a temporary database path per test run.
- Persist both products and ledger history so reloads and fresh processes can see prior writes.
- Prefer atomic writes so partial saves do not leave corrupt JSON behind.

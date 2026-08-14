# APPSEC

Threat: A browser user could land on `GET /` and get a missing or misleading entrypoint that hides the real inventory workflow.
Mitigation: `GET /` returns explicit Inventory HTML with product create/list controls, stock adjustment controls, and low-stock plus ledger route references.

Threat: Malformed or partial JSON could create invalid inventory records or adjustment entries.
Mitigation: Request validation rejects bad fields before writes and returns clear status codes.

Threat: Duplicate SKU creation or non-atomic file persistence could corrupt inventory state under normal API use.
Mitigation: SKU uniqueness is enforced before writes and the data file is replaced with an atomic temp-file rename.

Security review:
- Residual risk: this local task does not model multi-process locking, so a real deployment would need stronger concurrency controls.

# VERIFY

Command: `node --test tests/api.test.js`
Result: passed for the inventory app.

Verify results:
- The tests cover `app.js` and `tests/api.test.js`, including `GET /`, product CRUD, stock adjustments, low-stock reporting, ledger history, and status codes.
- I also checked that the data file persists records after reload so the app does not rely on in-memory state.

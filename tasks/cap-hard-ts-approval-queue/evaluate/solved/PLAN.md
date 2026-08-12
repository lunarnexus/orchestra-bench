1. Step 1: implement the browser-routable `GET /` homepage plus durable persistence and routing in `src/server.ts` for `POST /submissions`, `GET /public/submissions`, `GET /admin/submissions`, and `POST /admin/submissions/:id/decision`.
2. Step 2: add attachment path validation, escaped public rendering, admin history, and homepage coverage in `tests/api.test.ts`, then verify with `node --test --experimental-strip-types tests/api.test.ts`.

Files:
- `src/server.ts`
- `tests/api.test.ts`
- `package.json`

Tests:
- `node --test --experimental-strip-types tests/api.test.ts`

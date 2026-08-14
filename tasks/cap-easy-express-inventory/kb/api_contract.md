# API contract notes

- Browser homepage: `GET /` returns `200` HTML with an `Inventory` title, product create/list controls, stock adjustment controls, and route references for `GET /reports/low-stock` and `GET /products/{product_id}/ledger`
- Products use these fields: `id`, `sku`, `name`, `priceCents`, `stock`, `lowStockThreshold`, `createdAt`, `updatedAt`
- Duplicate SKU creation should return `409`
- Unknown product ids on detail/update/delete/adjustment/ledger routes should return `404`
- Validation failures should return `400`
- Low-stock report should return `items` and `total`
- Ledger responses should return `items`, `total`, `page`, and `page_size`
- Newest-first ordering keeps product lists and ledger history deterministic

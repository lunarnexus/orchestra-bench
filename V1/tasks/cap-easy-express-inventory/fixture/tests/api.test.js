const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { test } = require("node:test");

function listen(server) {
  return new Promise((resolve, reject) => {
    server.listen(0, "127.0.0.1", () => resolve(server.address()));
    server.once("error", reject);
  });
}

function close(server) {
  return new Promise((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
}

async function request(baseUrl, pathname, options = {}) {
  const response = await fetch(`${baseUrl}${pathname}`, {
    headers: { "content-type": "application/json", ...(options.headers || {}) },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  return { response, payload };
}

async function withServer(fn) {
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), "inventory-task-"));
  process.env.INVENTORY_DB = path.join(tmpRoot, "inventory-data.json");
  delete require.cache[require.resolve("../app")];
  const { createServer } = require("../app");
  const server = createServer();
  const address = await listen(server);
  const baseUrl = `http://${address.address}:${address.port}`;

  try {
    await fn(baseUrl, tmpRoot);
  } finally {
    await close(server);
    fs.rmSync(tmpRoot, { recursive: true, force: true });
  }
}

test("homepage serves browser-routable inventory controls", async () => {
  await withServer(async (baseUrl) => {
    const response = await fetch(`${baseUrl}/`);
    const body = await response.text();

    assert.equal(response.status, 200);
    assert.match(response.headers.get("content-type") || "", /^text\/html/);
    assert.match(body, /<title>Inventory<\/title>/);
    assert.match(body, /Create product/i);
    assert.match(body, /List products/i);
    assert.match(body, /Adjust stock/i);
    assert.match(body, /\/reports\/low-stock/);
    assert.match(body, /\/products\/\{product_id\}\/ledger/);
  });
});

test("product CRUD creates, lists, reads, updates, and deletes", async () => {
  await withServer(async (baseUrl) => {
    const created = await request(baseUrl, "/products", {
      method: "POST",
      body: {
        sku: "SKU-100",
        name: "Stapler",
        priceCents: 1299,
        stock: 8,
        lowStockThreshold: 3,
      },
    });

    assert.equal(created.response.status, 201);
    assert.ok(created.payload.id >= 1);
    assert.equal(created.payload.sku, "SKU-100");
    assert.equal(created.payload.stock, 8);
    assert.equal(created.payload.lowStockThreshold, 3);

    const listed = await request(baseUrl, "/products");
    assert.equal(listed.response.status, 200);
    assert.equal(listed.payload.total, 1);
    assert.equal(listed.payload.items[0].sku, "SKU-100");

    const fetched = await request(baseUrl, `/products/${created.payload.id}`);
    assert.equal(fetched.response.status, 200);
    assert.equal(fetched.payload.name, "Stapler");

    const updated = await request(baseUrl, `/products/${created.payload.id}`, {
      method: "PATCH",
      body: { name: "Heavy Stapler", lowStockThreshold: 4 },
    });
    assert.equal(updated.response.status, 200);
    assert.equal(updated.payload.name, "Heavy Stapler");
    assert.equal(updated.payload.lowStockThreshold, 4);

    const second = await request(baseUrl, "/products", {
      method: "POST",
      body: {
        sku: "SKU-200",
        name: "Paper",
        priceCents: 599,
        stock: 20,
        lowStockThreshold: 5,
      },
    });
    assert.equal(second.response.status, 201);

    const removed = await request(baseUrl, `/products/${second.payload.id}`, { method: "DELETE" });
    assert.equal(removed.response.status, 204);

    const missing = await request(baseUrl, `/products/${second.payload.id}`);
    assert.equal(missing.response.status, 404);
  });
});

test("stock adjustments persist and low-stock report returns matching products", async () => {
  await withServer(async (baseUrl, tmpRoot) => {
    const created = await request(baseUrl, "/products", {
      method: "POST",
      body: {
        sku: "SKU-LOW",
        name: "Label Maker",
        priceCents: 4599,
        stock: 8,
        lowStockThreshold: 3,
      },
    });
    assert.equal(created.response.status, 201);

    const adjusted = await request(baseUrl, `/products/${created.payload.id}/adjustments`, {
      method: "POST",
      body: { delta: -5, reason: "Cycle count correction" },
    });
    assert.equal(adjusted.response.status, 200);
    assert.equal(adjusted.payload.product.stock, 3);
    assert.equal(adjusted.payload.ledgerEntry.delta, -5);

    const lowStock = await request(baseUrl, "/reports/low-stock");
    assert.equal(lowStock.response.status, 200);
    assert.equal(lowStock.payload.total, 1);
    assert.equal(lowStock.payload.items[0].sku, "SKU-LOW");

    assert.equal(fs.existsSync(path.join(tmpRoot, "inventory-data.json")), true);
  });
});

test("ledger history records created, updated, and adjusted events newest first", async () => {
  await withServer(async (baseUrl) => {
    const created = await request(baseUrl, "/products", {
      method: "POST",
      body: {
        sku: "SKU-LEDGER",
        name: "Router",
        priceCents: 10999,
        stock: 6,
        lowStockThreshold: 2,
      },
    });

    await request(baseUrl, `/products/${created.payload.id}`, {
      method: "PATCH",
      body: { name: "Office Router" },
    });
    await request(baseUrl, `/products/${created.payload.id}/adjustments`, {
      method: "POST",
      body: { delta: -2, reason: "Reserved for setup" },
    });

    const ledger = await request(baseUrl, `/products/${created.payload.id}/ledger?page=1&page_size=10`);
    assert.equal(ledger.response.status, 200);
    assert.ok(ledger.payload.total >= 3);
    assert.deepEqual(
      ledger.payload.items.slice(0, 3).map((entry) => entry.action),
      ["adjusted", "updated", "created"],
    );
    assert.equal(ledger.payload.items[0].actor, "api");
  });
});

test("validation and status codes reject malformed or conflicting input", async () => {
  await withServer(async (baseUrl) => {
    const invalid = await request(baseUrl, "/products", {
      method: "POST",
      body: { sku: "BAD-1", name: "Missing stock", priceCents: 300 },
    });
    assert.equal(invalid.response.status, 400);

    const created = await request(baseUrl, "/products", {
      method: "POST",
      body: {
        sku: "SKU-CONFLICT",
        name: "Monitor",
        priceCents: 18999,
        stock: 4,
        lowStockThreshold: 1,
      },
    });
    assert.equal(created.response.status, 201);

    const duplicate = await request(baseUrl, "/products", {
      method: "POST",
      body: {
        sku: "SKU-CONFLICT",
        name: "Other Monitor",
        priceCents: 19999,
        stock: 2,
        lowStockThreshold: 1,
      },
    });
    assert.equal(duplicate.response.status, 409);

    const insufficient = await request(baseUrl, `/products/${created.payload.id}/adjustments`, {
      method: "POST",
      body: { delta: -10, reason: "Bad count" },
    });
    assert.equal(insufficient.response.status, 409);

    const missing = await request(baseUrl, "/products/999/ledger");
    assert.equal(missing.response.status, 404);
  });
});

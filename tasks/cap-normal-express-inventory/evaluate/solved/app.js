const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");

function dbPath() {
  return process.env.INVENTORY_DB || path.join(process.cwd(), "inventory-data.json");
}

function ensureStore() {
  const file = dbPath();
  fs.mkdirSync(path.dirname(file), { recursive: true });
  if (!fs.existsSync(file)) {
    writeStore({ nextProductId: 1, nextLedgerId: 1, products: [], ledger: [] });
  }
  const parsed = JSON.parse(fs.readFileSync(file, "utf8"));
  return {
    nextProductId: Number(parsed.nextProductId || 1),
    nextLedgerId: Number(parsed.nextLedgerId || 1),
    products: Array.isArray(parsed.products) ? parsed.products : [],
    ledger: Array.isArray(parsed.ledger) ? parsed.ledger : [],
  };
}

function writeStore(store) {
  const file = dbPath();
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(store, null, 2) + "\n");
  fs.renameSync(tmp, file);
}

function now() {
  return new Date().toISOString();
}

function sendJson(res, status, payload) {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(payload));
}

function sendHtml(res, status, body) {
  res.writeHead(status, { "content-type": "text/html; charset=utf-8" });
  res.end(body);
}

function sendEmpty(res, status) {
  res.writeHead(status);
  res.end();
}

function parseBody(req) {
  return new Promise((resolve, reject) => {
    let raw = "";
    req.on("data", (chunk) => {
      raw += chunk;
    });
    req.on("end", () => {
      if (!raw) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(raw));
      } catch (error) {
        reject(error);
      }
    });
    req.on("error", reject);
  });
}

function parsePositiveInt(value, fallback) {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1) {
    return null;
  }
  return parsed;
}

function validateCreate(body) {
  if (!body || typeof body !== "object") {
    return "body must be a JSON object";
  }
  if (typeof body.sku !== "string" || !body.sku.trim()) {
    return "sku is required";
  }
  if (typeof body.name !== "string" || !body.name.trim()) {
    return "name is required";
  }
  if (!Number.isInteger(body.priceCents) || body.priceCents < 0) {
    return "priceCents must be a non-negative integer";
  }
  if (!Number.isInteger(body.stock) || body.stock < 0) {
    return "stock must be a non-negative integer";
  }
  if (!Number.isInteger(body.lowStockThreshold) || body.lowStockThreshold < 0) {
    return "lowStockThreshold must be a non-negative integer";
  }
  return null;
}

function validatePatch(body) {
  if (!body || typeof body !== "object") {
    return "body must be a JSON object";
  }
  const allowed = ["name", "priceCents", "lowStockThreshold"];
  const keys = Object.keys(body);
  if (keys.length === 0 || keys.some((key) => !allowed.includes(key))) {
    return "patch body must contain supported fields";
  }
  if (body.name !== undefined && (typeof body.name !== "string" || !body.name.trim())) {
    return "name must be a non-empty string";
  }
  if (body.priceCents !== undefined && (!Number.isInteger(body.priceCents) || body.priceCents < 0)) {
    return "priceCents must be a non-negative integer";
  }
  if (
    body.lowStockThreshold !== undefined
    && (!Number.isInteger(body.lowStockThreshold) || body.lowStockThreshold < 0)
  ) {
    return "lowStockThreshold must be a non-negative integer";
  }
  return null;
}

function validateAdjustment(body) {
  if (!body || typeof body !== "object") {
    return "body must be a JSON object";
  }
  if (!Number.isInteger(body.delta)) {
    return "delta must be an integer";
  }
  if (typeof body.reason !== "string" || !body.reason.trim()) {
    return "reason is required";
  }
  return null;
}

function findProduct(store, id) {
  return store.products.find((product) => product.id === id) || null;
}

function listProducts(store) {
  return [...store.products].sort((a, b) => b.id - a.id);
}

function appendLedger(store, productId, action, detail, extra = {}) {
  const entry = {
    id: store.nextLedgerId++,
    productId,
    action,
    actor: "api",
    detail,
    createdAt: now(),
    ...extra,
  };
  store.ledger.push(entry);
  return entry;
}

function listLedger(store, productId) {
  return store.ledger.filter((entry) => entry.productId === productId).sort((a, b) => b.id - a.id);
}

function createServer() {
  return http.createServer(async (req, res) => {
    const url = new URL(req.url, "http://127.0.0.1");

    try {
      if (req.method === "GET" && url.pathname === "/") {
        return sendHtml(
          res,
          200,
          `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Inventory</title>
  </head>
  <body>
    <h1>Inventory</h1>
    <p>Use this browser entrypoint to create products, list inventory, adjust stock, inspect low-stock items, and review ledger history.</p>
    <section>
      <h2>Create product</h2>
      <form id="create-product-form" action="/products" method="post">
        <label>SKU <input name="sku" type="text" required /></label>
        <label>Name <input name="name" type="text" required /></label>
        <label>Price cents <input name="priceCents" type="number" min="0" required /></label>
        <label>Stock <input name="stock" type="number" min="0" required /></label>
        <label>Low stock threshold <input name="lowStockThreshold" type="number" min="0" required /></label>
        <button type="submit">Create product</button>
      </form>
      <button type="button">List products</button>
      <pre>Create product with POST /products and list products with GET /products.</pre>
    </section>
    <section>
      <h2>Adjust stock</h2>
      <form id="adjust-stock-form">
        <label>Product id <input name="product_id" type="number" min="1" /></label>
        <label>Delta <input name="delta" type="number" required /></label>
        <label>Reason <input name="reason" type="text" required /></label>
        <button type="submit">Adjust stock</button>
      </form>
      <pre>Adjust stock with POST /products/{product_id}/adjustments.</pre>
    </section>
    <section>
      <h2>Reports and ledger</h2>
      <button type="button">Load /reports/low-stock</button>
      <button type="button">Load /products/{product_id}/ledger</button>
      <pre>Reports reference GET /reports/low-stock and GET /products/{product_id}/ledger.</pre>
    </section>
  </body>
</html>`,
        );
      }

      if (req.method === "POST" && url.pathname === "/products") {
        const body = await parseBody(req);
        const error = validateCreate(body);
        if (error) {
          return sendJson(res, 400, { error });
        }

        const store = ensureStore();
        if (store.products.some((product) => product.sku === body.sku.trim())) {
          return sendJson(res, 409, { error: "sku already exists" });
        }

        const timestamp = now();
        const product = {
          id: store.nextProductId++,
          sku: body.sku.trim(),
          name: body.name.trim(),
          priceCents: body.priceCents,
          stock: body.stock,
          lowStockThreshold: body.lowStockThreshold,
          createdAt: timestamp,
          updatedAt: timestamp,
        };
        store.products.push(product);
        appendLedger(store, product.id, "created", `created ${product.sku}`, { stockAfter: product.stock });
        writeStore(store);
        return sendJson(res, 201, product);
      }

      if (req.method === "GET" && url.pathname === "/products") {
        const store = ensureStore();
        const items = listProducts(store);
        return sendJson(res, 200, { items, total: items.length });
      }

      if (req.method === "GET" && url.pathname === "/reports/low-stock") {
        const store = ensureStore();
        const items = listProducts(store).filter((product) => product.stock <= product.lowStockThreshold);
        return sendJson(res, 200, { items, total: items.length });
      }

      const productMatch = url.pathname.match(/^\/products\/(\d+)$/);
      if (productMatch && req.method === "GET") {
        const store = ensureStore();
        const product = findProduct(store, Number(productMatch[1]));
        if (!product) {
          return sendJson(res, 404, { error: "product not found" });
        }
        return sendJson(res, 200, product);
      }

      if (productMatch && req.method === "PATCH") {
        const body = await parseBody(req);
        const error = validatePatch(body);
        if (error) {
          return sendJson(res, 400, { error });
        }

        const store = ensureStore();
        const product = findProduct(store, Number(productMatch[1]));
        if (!product) {
          return sendJson(res, 404, { error: "product not found" });
        }

        if (body.name !== undefined) product.name = body.name.trim();
        if (body.priceCents !== undefined) product.priceCents = body.priceCents;
        if (body.lowStockThreshold !== undefined) product.lowStockThreshold = body.lowStockThreshold;
        product.updatedAt = now();
        appendLedger(store, product.id, "updated", `updated ${product.sku}`, { stockAfter: product.stock });
        writeStore(store);
        return sendJson(res, 200, product);
      }

      if (productMatch && req.method === "DELETE") {
        const store = ensureStore();
        const productId = Number(productMatch[1]);
        const index = store.products.findIndex((product) => product.id === productId);
        if (index < 0) {
          return sendJson(res, 404, { error: "product not found" });
        }
        const [product] = store.products.splice(index, 1);
        appendLedger(store, productId, "deleted", `deleted ${product.sku}`, { stockAfter: product.stock });
        writeStore(store);
        return sendEmpty(res, 204);
      }

      const adjustmentMatch = url.pathname.match(/^\/products\/(\d+)\/adjustments$/);
      if (adjustmentMatch && req.method === "POST") {
        const body = await parseBody(req);
        const error = validateAdjustment(body);
        if (error) {
          return sendJson(res, 400, { error });
        }

        const store = ensureStore();
        const product = findProduct(store, Number(adjustmentMatch[1]));
        if (!product) {
          return sendJson(res, 404, { error: "product not found" });
        }
        if (product.stock + body.delta < 0) {
          return sendJson(res, 409, { error: "insufficient stock for adjustment" });
        }

        product.stock += body.delta;
        product.updatedAt = now();
        const ledgerEntry = appendLedger(
          store,
          product.id,
          "adjusted",
          `${body.reason.trim()} (${body.delta > 0 ? "+" : ""}${body.delta})`,
          { delta: body.delta, stockAfter: product.stock },
        );
        writeStore(store);
        return sendJson(res, 200, { product, ledgerEntry });
      }

      const ledgerMatch = url.pathname.match(/^\/products\/(\d+)\/ledger$/);
      if (ledgerMatch && req.method === "GET") {
        const page = parsePositiveInt(url.searchParams.get("page"), 1);
        const pageSize = parsePositiveInt(url.searchParams.get("page_size"), 20);
        if (page === null || pageSize === null) {
          return sendJson(res, 400, { error: "page and page_size must be positive integers" });
        }

        const store = ensureStore();
        const productId = Number(ledgerMatch[1]);
        const product = findProduct(store, productId);
        if (!product) {
          return sendJson(res, 404, { error: "product not found" });
        }

        const items = listLedger(store, productId);
        const start = (page - 1) * pageSize;
        const pageItems = items.slice(start, start + pageSize);
        return sendJson(res, 200, { items: pageItems, total: items.length, page, page_size: pageSize });
      }

      return sendJson(res, 404, { error: "not found" });
    } catch (error) {
      if (error instanceof SyntaxError) {
        return sendJson(res, 400, { error: "invalid JSON body" });
      }
      return sendJson(res, 500, { error: String(error) });
    }
  });
}

module.exports = { createServer };

if (require.main === module) {
  const port = Number(process.env.PORT || 3000);
  const server = createServer();
  server.listen(port, "0.0.0.0", () => {
    process.stdout.write(`inventory server listening on ${port}\n`);
  });
}

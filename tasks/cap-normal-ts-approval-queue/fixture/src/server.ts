import { createServer } from "node:http";

function json(res: any, status: number, payload: unknown) {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(payload));
}

createServer((req, res) => {
  const url = new URL(req.url || "/", "http://127.0.0.1");
  if (req.method === "GET" && url.pathname === "/health") {
    return json(res, 200, { ok: true });
  }
  return json(res, 501, { error: "not_implemented" });
}).listen(Number(process.env.PORT || 3100), "127.0.0.1");

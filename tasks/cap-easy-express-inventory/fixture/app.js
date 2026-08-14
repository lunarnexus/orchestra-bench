const http = require("node:http");

function createServer() {
  return http.createServer((req, res) => {
    res.writeHead(501, { "content-type": "application/json" });
    res.end(JSON.stringify({ error: `TODO: implement ${req.method} ${req.url}` }));
  });
}

module.exports = { createServer };

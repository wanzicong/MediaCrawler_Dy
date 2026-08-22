// 设计方案原型预览用的极简静态服务器（仅服务 docs/运营工作台设计方案 目录）
const http = require("http");
const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..", "docs", "运营工作台设计方案");
const port = Number(process.argv[2] || 8123);

const server = http.createServer((req, res) => {
  let urlPath = decodeURIComponent((req.url || "/").split("?")[0]);
  if (urlPath === "/") urlPath = "/方案预览导航.html";
  const file = path.join(root, urlPath.replace(/^\/+/, ""));
  if (!file.startsWith(root)) { res.writeHead(403); res.end("forbidden"); return; }
  fs.readFile(file, (err, data) => {
    if (err) { res.writeHead(404); res.end("not found: " + urlPath); return; }
    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    res.end(data);
  });
});
server.listen(port, () => console.log(`design preview server listening on http://localhost:${port}`));

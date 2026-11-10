// A local stand-in for the static host: node scripts/serve.mjs <dir> <port>
// It does what edge/worker.js does on Cloudflare Pages, and serves the library's files and the
// API on the same origin, as a build with no PUBLIC_API_BASE expects:
//   /d/<ns>/<id>/<version>/<anchor>   the reader's shell (dist/reader.html)
//   /d/<ns>/<id>/<version>            the document's record, when that version has no page of its own (it is the latest)
//   /data/…                           the snapshot's public/ tree (SAFETYPAGE_PUBLIC_DIR, default .data)
//   /api/…, /mcp                      the search server (SAFETYPAGE_API), when one is named
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';

const [dir = 'dist', port = '4393'] = process.argv.slice(2);
const data = process.env.SAFETYPAGE_PUBLIC_DIR ?? '.data';
const api = process.env.SAFETYPAGE_API;
const READER = /^\/d\/[^/]+\/[^/]+\/[vr]\d+\/[pb]\d+(-[pb]?\d+)?\/?$/;
const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.png': 'image/png', '.webp': 'image/webp', '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.woff': 'font/woff', '.txt': 'text/plain; charset=utf-8', '.pdf': 'application/pdf' };

http.createServer((req, res) => {
  const pathname = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  if (api && /^\/(api\/|mcp$|x\/)/.test(pathname)) {
    const upstream = http.request(new URL(req.url, api), { method: req.method, headers: { ...req.headers, host: new URL(api).host } }, (r) => {
      res.writeHead(r.statusCode, r.headers);
      r.pipe(res);
    });
    upstream.on('error', () => res.writeHead(502).end());
    return void req.pipe(upstream);
  }
  const clean = path.normalize(pathname).replace(/^(\.\.[/\\])+/, '').replace(/\/$/, '');
  // a page is <address>.html; an older version's record falls back to the document's
  const html = (p) => path.join(dir, (p || '/index') + '.html');
  let file = READER.test(pathname) ? html('/reader') : path.join(dir, clean);
  if (clean.startsWith('/data/')) file = path.join(data, clean.slice('/data/'.length));
  else if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    file = html(clean);
    if (!fs.existsSync(file) && /^\/d\/[^/]+\/[^/]+\/[vr]\d+$/.test(clean)) file = html(path.dirname(clean));
  }
  const found = fs.existsSync(file);
  if (!found) file = html('/404');
  res.writeHead(found ? 200 : 404, { 'Content-Type': types[path.extname(file)] ?? 'application/octet-stream' });
  fs.createReadStream(file).pipe(res);
}).listen(Number(port), () => console.log(`serving ${dir} on http://localhost:${port}`));

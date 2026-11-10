// A plain static server for a built site: node scripts/serve.mjs <dir> <port>
// Tests use it because `astro preview` detaches itself when an agent runs it.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';

const [dir = 'dist', port = '4393'] = process.argv.slice(2);
const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.png': 'image/png', '.webp': 'image/webp', '.svg': 'image/svg+xml', '.woff2': 'font/woff2', '.woff': 'font/woff' };
http.createServer((req, res) => {
  const clean = path.normalize(decodeURIComponent(new URL(req.url, 'http://x').pathname)).replace(/^(\.\.[/\\])+/, '');
  let file = path.join(dir, clean);
  if (fs.existsSync(file) && fs.statSync(file).isDirectory()) file = path.join(file, 'index.html');
  const found = fs.existsSync(file);
  if (!found) file = path.join(dir, '404.html');
  res.writeHead(found ? 200 : 404, { 'Content-Type': types[path.extname(file)] ?? 'application/octet-stream' });
  fs.createReadStream(file).pipe(res);
}).listen(Number(port), () => console.log(`serving ${dir} on http://localhost:${port}`));

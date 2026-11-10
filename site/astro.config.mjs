import { defineConfig } from 'astro/config';
import react from '@astrojs/react';
import fs from 'node:fs';
import path from 'node:path';

// Static output: the whole site can be served from a bucket. The JSON API (search, quote
// check, answer check) is the search server's (docs/SERVER.md); in dev, /api is proxied to it.
const api = process.env.SAFETYPAGE_API ?? 'http://127.0.0.1:8791';
const data = process.env.SAFETYPAGE_PUBLIC_DIR ?? path.resolve('.data');

// In dev, what the host does in production: a page or paragraph address is the reader's shell,
// and /data is the snapshot's public/ tree (SAFETYPAGE_PUBLIC_DIR, or the fixture tree in .data).
const host = {
  name: 'safetypage-host',
  configureServer(server) {
    server.middlewares.use((req, res, next) => {
      const pathname = decodeURIComponent(req.url.split('?')[0]);
      if (/^\/d\/[^/]+\/[^/]+\/[vr]\d+\/[pb]\d+(-[pb]?\d+)?\/?$/.test(pathname)) req.url = '/reader' + req.url.slice(req.url.split('?')[0].length);
      if (pathname.startsWith('/data/')) {
        const file = path.join(data, path.normalize(pathname.slice(6)));
        if (fs.existsSync(file) && fs.statSync(file).isFile()) return void fs.createReadStream(file).pipe(res);
      }
      next();
    });
  },
};

export default defineConfig({
  site: process.env.SITE_URL ?? 'http://localhost:4321',
  output: 'static',
  integrations: [react()],
  devToolbar: { enabled: false },
  vite: { plugins: [host], server: { proxy: { '/api': api } } },
});

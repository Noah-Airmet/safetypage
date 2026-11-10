import { defineConfig } from 'astro/config';
import react from '@astrojs/react';
import fs from 'node:fs';
import path from 'node:path';

// Static output. Two addresses decide where everything is (deploy.env holds the deployed pair):
//   SITE_URL          the site's own origin
//   PUBLIC_API_BASE   the origin of the search server and the library's public files; empty
//                     means the same origin as the site (local runs, where the host proxies)
// At build time, SAFETYPAGE_PUBLIC_DIR is the snapshot's public/ tree and SAFETYPAGE_API a
// running search server on that snapshot (README.md).
const api = process.env.SAFETYPAGE_API ?? 'http://127.0.0.1:8791';
const data = process.env.SAFETYPAGE_PUBLIC_DIR ?? path.resolve('.data');
const apiBase = (process.env.PUBLIC_API_BASE ?? '').replace(/\/$/, '');

// A snapshot's files never change, so a separate origin serves them under the snapshot's id and
// they can be cached for good: <api>/data/<snapshot id>/docs/…. On the same origin, /data.
const manifest = path.join(data, '..', 'manifest.json');
const snapshot = fs.existsSync(manifest) ? JSON.parse(fs.readFileSync(manifest, 'utf8')).snapshot_id : null;
process.env.PUBLIC_DATA_BASE ??= apiBase && snapshot ? `${apiBase}/data/${snapshot}` : '/data';

const READER = /^\/d\/[^/]+\/[^/]+\/[vr]\d+\/[pb]\d+(-[pb]?\d+)?\/?$/;
const host = {
  name: 'safetypage-host',
  hooks: {
    // In dev, what the host does in production: a page or paragraph address is the reader's
    // shell, and /data is the snapshot's public/ tree.
    'astro:server:setup': ({ server }) => {
      server.middlewares.use((req, res, next) => {
        const [pathname, query = ''] = req.url.split('?');
        if (READER.test(decodeURIComponent(pathname))) req.url = '/reader' + (query && `?${query}`);
        if (pathname.startsWith('/data/')) {
          const file = path.join(data, path.normalize(decodeURIComponent(pathname.slice(6))));
          if (fs.existsSync(file) && fs.statSync(file).isFile()) return void fs.createReadStream(file).pipe(res);
        }
        next();
      });
    },
    // For Cloudflare Pages: the edge rule (edge/worker.js), run only for /d/*.
    'astro:build:done': ({ dir }) => {
      const worker = fs.readFileSync(new URL('./edge/worker.js', import.meta.url), 'utf8').replace('__DATA_BASE__', process.env.PUBLIC_DATA_BASE);
      fs.writeFileSync(new URL('_worker.js', dir), worker);
      fs.writeFileSync(new URL('_routes.json', dir), JSON.stringify({ version: 1, include: ['/d/*'], exclude: [] }));
    },
  },
};

export default defineConfig({
  site: process.env.SITE_URL ?? 'http://localhost:4321',
  output: 'static',
  // /library is library.html, not library/index.html: a static host then serves the address as
  // written, with no redirect to a trailing slash.
  build: { format: 'file' },
  integrations: [react(), host],
  devToolbar: { enabled: false },
  vite: { server: { proxy: { '/api': api } } },
});

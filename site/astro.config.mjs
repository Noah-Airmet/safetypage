import { defineConfig } from 'astro/config';
import react from '@astrojs/react';

// Static output: the whole site can be served from a bucket. The JSON API (search, quote
// check, answer check) is the search server's; in dev, /api is proxied to the stand-in.
export default defineConfig({
  site: process.env.SITE_URL ?? 'http://localhost:4321',
  output: 'static',
  integrations: [react()],
  devToolbar: { enabled: false },
  vite: {
    server: { proxy: { '/api': process.env.OTP_API ?? 'http://127.0.0.1:8791' } },
  },
});

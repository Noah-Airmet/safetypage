// Screenshots of the main screens: node scripts/shots.mjs <base> <outDir> [name-filter]
import { chromium } from '@playwright/test';
import fs from 'node:fs';

const [base = 'http://localhost:4391', out = 'shots', only] = process.argv.slice(2);
const pages = {
  home: '/',
  record: '/d/arxiv/2305.15324',
  'record-source': '/d/example/link-only-eval-report',
  reader: '/d/arxiv/2305.15324/v2/p6?q=' + encodeURIComponent('not the only tool available for AI risk assessment'),
  'reader-rejected': '/d/arxiv/2305.15324/v2/p3?q=' + encodeURIComponent('one of the main tools we have for AI risk assessment'),
  'reader-text': '/d/distill/zoom-in/r1/b21?q=' + encodeURIComponent('Features are the fundamental unit of neural networks'),
  'reader-source': '/d/example/link-only-eval-report/r1/p2',
  search: '/search?query=' + encodeURIComponent('"risk assessment" evaluation'),
  check: '/check?example=1',
  replay: '/r/cc-sonnet-5-5-43677d-pc-7abbdba8ab.1?step=14',
  citationbench: '/citationbench',
  connect: '/connect',
  library: '/library',
};
const views = { desktop: { width: 1440, height: 900 }, phone: { width: 390, height: 844 } };
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ channel: 'chrome' });
for (const [view, viewport] of Object.entries(views)) {
  for (const scheme of ['light', 'dark']) {
    const context = await browser.newContext({ viewport, colorScheme: scheme, deviceScaleFactor: 2, isMobile: view === 'phone', hasTouch: view === 'phone' });
    const page = await context.newPage();
    for (const [name, path] of Object.entries(pages)) {
      if (only && !only.split(',').includes(name)) continue;
      await page.goto(base + path, { waitUntil: 'networkidle' }).catch((e) => console.log(name, e.message));
      await page.waitForTimeout(700);
      await page.screenshot({ path: `${out}/${name}.${view}.${scheme}.png` });
    }
    await context.close();
  }
}
await browser.close();

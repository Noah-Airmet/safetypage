// Screenshots of the main screens: node scripts/shots.mjs <base> <outDir> [name-filter]
import { chromium } from '@playwright/test';
import fs from 'node:fs';

const [base = 'http://localhost:4412', out = 'shots', only, full] = process.argv.slice(2);
const q = encodeURIComponent;
// The main screens on the real library. The four reader-source pages are the four kinds of
// document that are read at their source: a system card, a Transformer Circuits paper, an
// Alignment Forum post and an arXiv paper under arXiv's default licence.
const pages = {
  home: '/',
  library: '/library',
  shelf: '/library/labs',
  'shelf-filtered': '/library/papers?year=2024&q=sparse',
  record: '/d/arxiv/2305.15324',
  'record-source': '/d/anthropic/claude-opus-5-5-system-card',
  reader: '/d/arxiv/2305.15324/v2/p6?q=' + q('not the only tool available for AI risk assessment'),
  'reader-rejected': '/d/arxiv/2305.15324/v2/p3?q=' + q('one of the main tools we have for AI risk assessment'),
  'reader-text': '/d/distill/zoom-in/r1/b21',
  'reader-source-card': '/d/anthropic/claude-opus-5-5-system-card/r1/p135?q=' + q('reviewed the highest-scoring reports on the deliberate sabotage dimension'),
  'reader-source-circuits': '/d/anthropic/2024-scaling-monosemanticity/r1/b20',
  'reader-source-forum': '/d/lw/LNA8mubrByG7SFacm/r1/b85',
  'reader-source-arxiv': '/d/arxiv/2401.05566/v3/p5',
  'search-empty': '/search',
  'search-check': '/search?mode=check',
  search: '/search?query=' + q('"alignment faking"'),
  follow: '/follow/sabotage',
  check: '/check?example=1',
  replay: '/r/cc-haiku-5-5-4e1c63-pc-4bd058594c.1?step=21',
  citationbench: '/citationbench',
  connect: '/connect',
  'follow-index': '/follow',
  run: '/citationbench/runs/cc-haiku-5-5-4e1c63',
  replays: '/r',
  quote: '/q/' + (process.env.SHOT_QUOTE ?? ''),
  about: '/about',
};
const views = { desktop: { width: 1440, height: 900 }, phone: { width: 390, height: 844 } };
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ channel: 'chrome' });
for (const [view, viewport] of Object.entries(views)) {
  for (const scheme of (process.env.SHOT_SCHEMES ?? 'light,dark').split(',')) {
    const context = await browser.newContext({ viewport, colorScheme: scheme, deviceScaleFactor: 2, isMobile: view === 'phone', hasTouch: view === 'phone' });
    const page = await context.newPage();
    for (const [name, path] of Object.entries(pages)) {
      if (only && !only.split(',').includes(name)) continue;
      if (name === 'quote' && !process.env.SHOT_QUOTE) continue;
      await page.goto(base + path, { waitUntil: 'networkidle' }).catch((e) => console.log(name, e.message));
      await page.waitForTimeout(700);
      await page.screenshot({ path: `${out}/${name}.${view}.${scheme}.png`, fullPage: !!full && !name.startsWith('reader') });
    }
    await context.close();
  }
}
await browser.close();

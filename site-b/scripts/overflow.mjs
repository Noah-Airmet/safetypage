// Sideways scroll and what causes it, at phone and desktop width: node scripts/overflow.mjs <base>
import { chromium } from '@playwright/test';
const base = process.argv[2] ?? 'http://localhost:4412';
const q = encodeURIComponent;
const paths = ['/', '/library', '/library/labs', '/library/papers?year=2024&q=sparse', '/d/arxiv/2305.15324', '/d/anthropic/claude-opus-5-5-system-card', '/d/arxiv/2305.15324/v2/p6?q=' + q('not the only tool available for AI risk assessment'),
  '/d/distill/zoom-in/r1/b21', '/d/anthropic/claude-opus-5-5-system-card/r1/p135', '/d/lw/LNA8mubrByG7SFacm/r1/b85', '/search?query=' + q('"alignment faking"'), '/follow', '/follow/sabotage', '/check?example=1',
  '/r/cc-haiku-5-5-4e1c63-pc-4bd058594c.1?step=24', '/r', '/citationbench', '/citationbench/runs/cc-haiku-5-5-4e1c63', '/connect', '/about', '/nope'];
const browser = await chromium.launch({ channel: 'chrome' });
for (const width of [390, 1440]) {
  const ctx = await browser.newContext({ viewport: { width, height: 844 }, isMobile: width < 500, hasTouch: width < 500 });
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text().slice(0, 120)));
  page.on('pageerror', (e) => errors.push(String(e).slice(0, 120)));
  for (const path of paths) {
    await page.goto(base + path, { waitUntil: 'networkidle' }).catch(() => {});
    await page.waitForTimeout(400);
    const bad = await page.evaluate(() => {
      const w = document.documentElement.clientWidth;
      if (document.documentElement.scrollWidth <= w) return null;
      return [...document.querySelectorAll('body *')].filter((e) => e.getBoundingClientRect().right > w + 1 && !e.closest('.scroll, .tries, .switch, .codeline, pre')).slice(0, 4).map((e) => `${e.tagName}.${e.className} ${Math.round(e.getBoundingClientRect().right)}`);
    });
    if (bad) console.log(width, path, bad);
    if (errors.length) console.log(width, path, 'errors:', errors.splice(0).slice(0, 3));
  }
  await ctx.close();
}
await browser.close();
console.log('done');

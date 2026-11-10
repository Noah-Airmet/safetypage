#!/usr/bin/env node
// Measure something in a live page, for the review (and for anyone):
//   node measure.mjs <url> <width> '<expression>' [--click <selector>]...
// The expression runs in the page once it has drawn; whatever it returns is
// printed as JSON. A helper is in scope: box(selector) gives every visible
// match's rect, rounded to 0.1px, with its computed font, padding and margin.
//   node measure.mjs http://localhost:4321/ 390 'box("header nav a")'
import { chromium } from '@playwright/test';
import { open, press } from '/Users/noahairmet/development/tools/ui-check/lib/site.mjs';

const [url, width, expr, ...rest] = process.argv.slice(2);
if (!expr) { console.error("usage: measure.mjs <url> <width> '<expression>' [--click <selector>]..."); process.exit(2); }
const clicks = rest.flatMap((a, i) => a === '--click' ? [rest[i + 1]] : []);
const mobile = +width < 600;
const b = await chromium.launch({ channel: 'chrome' });
const page = await b.newPage({ viewport: { width: +width, height: mobile ? 844 : 900 }, isMobile: mobile, hasTouch: mobile, colorScheme: 'dark' });
await open(page, url);
await press(page, clicks);
console.log(JSON.stringify(await page.evaluate(e => {
  const f = x => Math.round(x * 10) / 10;
  window.box = sel => [...document.querySelectorAll(sel)].filter(n => n.getClientRects().length).map(n => {
    const r = n.getBoundingClientRect(), s = getComputedStyle(n);
    return { el: n.tagName.toLowerCase() + (n.id ? '#' + n.id : '') + (n.classList.length ? '.' + [...n.classList].join('.') : ''), text: n.textContent.trim().slice(0, 40),
      x: f(r.left), y: f(r.top), w: f(r.width), h: f(r.height), right: f(r.right), bottom: f(r.bottom),
      font: `${s.fontWeight} ${s.fontSize}/${s.lineHeight} ${s.fontFamily.split(',')[0]}`, color: s.color, bg: s.backgroundColor,
      radius: s.borderTopLeftRadius, padding: s.padding, margin: s.margin };
  });
  return (0, eval)(e);
}, expr), null, 1));
await b.close();

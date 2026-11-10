// Scratch: collect type scale, controls and section rhythm across pages in one session.
import { chromium } from '/Users/noahairmet/development/tools/ui-check/node_modules/@playwright/test/index.mjs';
import { open } from '/Users/noahairmet/development/tools/ui-check/lib/site.mjs';
const pages = {
  home: '/', library: '/library', shelf: '/library/labs', 'shelf-filtered': '/library/papers?year=2024&q=sparse',
  record: '/d/arxiv/2305.15324', 'record-source': '/d/anthropic/claude-opus-5-5-system-card',
  reader: '/d/arxiv/2305.15324/v2/p6?q=not%20the%20only%20tool%20available%20for%20AI%20risk%20assessment',
  'reader-text': '/d/distill/zoom-in/r1/b21',
  'search-empty': '/search', search: '/search?query=%22alignment%20faking%22', follow: '/follow/sabotage',
  check: '/check?example=1', replay: '/r/cc-haiku-5-5-4e1c63-pc-4bd058594c.1?step=21', citationbench: '/citationbench', connect: '/connect',
};
const width = +(process.argv[2] || 1440);
const mobile = width < 600;
const b = await chromium.launch({ channel: 'chrome' });
const page = await b.newPage({ viewport: { width, height: mobile ? 844 : 900 }, isMobile: mobile, hasTouch: mobile });
const out = {};
for (const [name, path] of Object.entries(pages)) {
  await open(page, 'http://localhost:4412' + path);
  out[name] = await page.evaluate(() => {
    const f = x => Math.round(x * 10) / 10;
    const vis = n => n.getClientRects().length && getComputedStyle(n).visibility !== 'hidden';
    const desc = n => n.tagName.toLowerCase() + (n.id ? '#' + n.id : '') + (n.classList.length ? '.' + [...n.classList].join('.') : '');
    const rec = n => { const r = n.getBoundingClientRect(), s = getComputedStyle(n); return { el: desc(n), text: n.textContent.trim().replace(/\s+/g,' ').slice(0, 30), x: f(r.left), y: f(r.top), w: f(r.width), h: f(r.height), font: `${s.fontWeight} ${s.fontSize}/${s.lineHeight}`, radius: s.borderTopLeftRadius, pad: s.padding, bg: s.backgroundColor, border: s.borderTopWidth + ' ' + s.borderTopColor }; };
    // type scale: all text-bearing elements' font sizes
    const sizes = {};
    for (const n of document.body.querySelectorAll('*')) {
      if (!vis(n)) continue;
      const hasText = [...n.childNodes].some(c => c.nodeType === 3 && c.textContent.trim());
      if (!hasText) continue;
      const s = getComputedStyle(n);
      const k = `${s.fontSize}|${s.fontWeight}|${s.fontFamily.split(',')[0].replace(/"/g,'')}`;
      sizes[k] = sizes[k] || { n: 0, ex: [] };
      sizes[k].n++;
      if (sizes[k].ex.length < 3) sizes[k].ex.push(desc(n) + ' "' + n.textContent.trim().replace(/\s+/g,' ').slice(0, 25) + '"');
    }
    const heads = [...document.querySelectorAll('h1,h2,h3,h4')].filter(vis).map(rec);
    const controls = [...document.querySelectorAll('button, a.button, .button, input, select, textarea, [role=button], a[class*=btn], [class*=chip], [class*=pill]')].filter(vis).map(rec);
    const header = document.querySelector('header'); const footer = document.querySelector('footer'); const main = document.querySelector('main');
    const h = header ? rec(header) : null; const ft = footer ? rec(footer) : null; const m = main ? rec(main) : null;
    const headerKids = header ? [...header.querySelectorAll('a, button, input')].filter(vis).map(rec) : [];
    const headerCount = document.querySelectorAll('header').length;
    const doc = { sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth };
    // overflowing elements
    const overflow = [...document.body.querySelectorAll('*')].filter(vis).filter(n => n.scrollWidth > n.clientWidth + 1 && n.clientWidth > 0 && getComputedStyle(n).overflowX !== 'visible').map(n => ({ el: desc(n), sw: n.scrollWidth, cw: n.clientWidth, ox: getComputedStyle(n).overflowX, te: getComputedStyle(n).textOverflow, text: n.textContent.trim().replace(/\s+/g,' ').slice(0,40) }));
    return { doc, headerCount, header: h, headerKids, main: m, footer: ft, heads, controls, sizes, overflow };
  });
}
await b.close();
console.log(JSON.stringify(out, null, 1));

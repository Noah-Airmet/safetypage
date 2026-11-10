// Study a set of sites: screenshots at desktop and phone width, and a tally of the computed
// styles of what is visible. node scripts/study.mjs <outDir>
import { chromium } from '@playwright/test';
import fs from 'node:fs';
const out = process.argv[2];
const sites = {
  mercury: 'https://mercury.com/', spacex: 'https://www.spacex.com/', anthropic: 'https://www.anthropic.com/',
  'anthropic-research': 'https://www.anthropic.com/research', openai: 'https://openai.com/', 'openai-research': 'https://openai.com/research/index/',
  linear: 'https://linear.app/', stripe: 'https://stripe.com/', ramp: 'https://ramp.com/', 'stripe-docs': 'https://docs.stripe.com/payments',
  circuits: 'https://transformer-circuits.pub/2024/scaling-monosemanticity/index.html', distill: 'https://distill.pub/2020/circuits/zoom-in/',
  'stripe-press': 'https://press.stripe.com/', vercel: 'https://vercel.com/', deepmind: 'https://deepmind.google/research/',
  'linear-changelog': 'https://linear.app/changelog', 'mercury-pricing': 'https://mercury.com/pricing', arxiv: 'https://arxiv.org/abs/2305.15324',
};
const only = process.argv[3]?.split(',');
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ channel: 'chrome' });
const tally = () => {
  const props = ['fontFamily', 'fontSize', 'lineHeight', 'letterSpacing', 'fontWeight', 'borderRadius', 'color', 'backgroundColor', 'boxShadow', 'transitionDuration', 'transitionTimingFunction', 'textTransform', 'borderTopWidth'];
  const t = Object.fromEntries(props.map((p) => [p, {}]));
  const pairs = {};
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const s = getComputedStyle(el);
    const hasText = [...el.childNodes].some((n) => n.nodeType === 3 && n.data.trim());
    for (const p of props) {
      const textOnly = ['fontFamily', 'fontSize', 'lineHeight', 'letterSpacing', 'fontWeight', 'color', 'textTransform'].includes(p);
      if (textOnly && !hasText) continue;
      let v = s[p];
      if (p === 'fontFamily') v = v.split(',')[0];
      if (p === 'backgroundColor' && v === 'rgba(0, 0, 0, 0)') continue;
      if (p === 'boxShadow' && v === 'none') continue;
      if (p === 'borderRadius' && v === '0px') continue;
      if (p === 'borderTopWidth' && (v === '0px' || s.borderTopStyle === 'none')) continue;
      if (p.startsWith('transition') && (s.transitionDuration === '0s')) continue;
      t[p][v] = (t[p][v] || 0) + (textOnly ? el.textContent.trim().length || 1 : 1);
    }
    if (hasText) { const k = `${s.fontSize}/${s.lineHeight} ${s.fontWeight} ls ${s.letterSpacing} ${s.fontFamily.split(',')[0]}`; pairs[k] = (pairs[k] || 0) + 1; }
  }
  const top = (o, n = 12) => Object.entries(o).sort((a, b) => b[1] - a[1]).slice(0, n);
  const pick = (sel) => { const el = document.querySelector(sel); if (!el) return null; const s = getComputedStyle(el); const r = el.getBoundingClientRect(); return { text: el.textContent.trim().slice(0, 70), font: `${s.fontSize}/${s.lineHeight} ${s.fontWeight} ${s.fontFamily.split(',')[0]}`, ls: s.letterSpacing, color: s.color, bg: s.backgroundColor, radius: s.borderRadius, pad: s.padding, h: Math.round(r.height), w: Math.round(r.width), x: Math.round(r.left), y: Math.round(r.top), maxW: s.maxWidth, border: s.border, shadow: s.boxShadow, trans: s.transition.slice(0, 120) }; };
  const measure = [...document.querySelectorAll('p')].filter((p) => p.textContent.length > 200).slice(0, 3).map((p) => { const s = getComputedStyle(p); return { w: Math.round(p.getBoundingClientRect().width), font: `${s.fontSize}/${s.lineHeight}`, chPerLine: Math.round(p.getBoundingClientRect().width / (parseFloat(s.fontSize) * 0.48)) }; });
  return { title: document.title, bodyBg: getComputedStyle(document.body).backgroundColor, htmlBg: getComputedStyle(document.documentElement).backgroundColor, scrollH: document.documentElement.scrollHeight,
    tally: Object.fromEntries(Object.entries(t).map(([k, v]) => [k, top(v)])), pairs: top(pairs, 18),
    h1: pick('h1'), h2: pick('h2'), p: pick('main p, p'), navA: pick('header a[href]:not(:has(svg)):not(:has(img)), nav a'), header: pick('header, nav'), button: pick('a[class*="utton"], button[class*="utton"], a[class*="btn"], a[class*="cta" i]'), input: pick('input[type="text"], input[type="search"], input[type="email"]'), measure,
    firstScreenWords: [...document.querySelectorAll('body *')].filter((e) => { const r = e.getBoundingClientRect(); return r.top < innerHeight && r.bottom > 0 && r.width && [...e.childNodes].some((n) => n.nodeType === 3 && n.data.trim()); }).map((e) => [...e.childNodes].filter((n) => n.nodeType === 3).map((n) => n.data.trim()).join(' ')).join(' | ').slice(0, 900) };
};
for (const [name, url] of Object.entries(sites)) {
  if (only && !only.includes(name)) continue;
  const res = {};
  for (const [view, viewport] of Object.entries({ desktop: { width: 1440, height: 900 }, phone: { width: 390, height: 844 } })) {
    const ctx = await browser.newContext({ viewport, deviceScaleFactor: view === 'phone' ? 2 : 1, isMobile: view === 'phone', hasTouch: view === 'phone', userAgent: view === 'phone' ? 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1' : undefined });
    const page = await ctx.newPage();
    const css = [];
    if (view === 'desktop') page.on('response', async (r) => { if (r.request().resourceType() === 'stylesheet') { try { css.push(await r.text()); } catch {} } });
    try {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.waitForTimeout(4500);
      await page.screenshot({ path: `${out}/${name}.${view}.png` });
      res[view] = await page.evaluate(tally);
      if (view === 'desktop') {
        const all = css.join('\n') + (await page.evaluate(() => [...document.querySelectorAll('style')].map((s) => s.textContent).join('\n')));
        fs.writeFileSync(`${out}/${name}.css`, all);
        const count = (re) => { const m = {}; for (const x of all.matchAll(re)) m[x[1].trim()] = (m[x[1].trim()] || 0) + 1; return Object.entries(m).sort((a, b) => b[1] - a[1]).slice(0, 14); };
        res.css = { bytes: all.length, easings: count(/(cubic-bezier\([^)]+\))/g), durations: count(/transition[^;{}]*?(\d*\.?\d+m?s)/g), breakpoints: count(/@media[^{]*?((?:min|max)-width:\s*[\d.]+(?:px|em|rem))/g), maxWidths: count(/max-width:\s*([\d.]+(?:px|rem|ch))/g), fontFaces: count(/font-family:\s*["']?([^;"',}]+)/g), vars: [...new Set([...all.matchAll(/(--[\w-]*(?:color|bg|background|text|radius|space|spacing|font-size|ease|duration|shadow|border)[\w-]*):\s*([^;}]{1,60})/gi)].map((m) => `${m[1]}: ${m[2].trim()}`))].slice(0, 90) };
      }
      await page.evaluate(() => scrollTo(0, innerHeight * 1.6)); await page.waitForTimeout(1200);
      await page.screenshot({ path: `${out}/${name}.${view}.2.png` });
    } catch (e) { res[view] = { error: e.message.slice(0, 200) }; }
    await ctx.close();
  }
  fs.writeFileSync(`${out}/${name}.json`, JSON.stringify(res, null, 1));
  console.log(name, res.desktop?.title ?? res.desktop?.error);
}
await browser.close();

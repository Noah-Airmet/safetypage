import { chromium } from '/Users/noahairmet/development/tools/ui-check/node_modules/@playwright/test/index.mjs';
import { open } from '/Users/noahairmet/development/tools/ui-check/lib/site.mjs';
const B = 'http://localhost:4412';
const jobs = [
  ['home', 1440, '/', `({
    rightCol: [...qa('h2.h2')].filter(h=>!h.id).map(h=>{const p=h.parentElement; return {el: desc(p), ...rect(p), kids: [...p.children].map(c=>({el: desc(c), t: c.textContent.trim().slice(0,20), ...rect(c), m: getComputedStyle(c).margin}))}}),
    sections: [...qa('.section, section')].map(s=>({el: desc(s), ...rect(s), m: getComputedStyle(s).margin, kidsN: s.children.length})),
    hero: [...qa('section.hero > *')].map(c=>({el: desc(c), ...rect(c), m: getComputedStyle(c).margin})),
    heroLeft: [...qa('section.hero > * > *')].slice(0,8).map(c=>({el: desc(c), ...rect(c), m: getComputedStyle(c).margin})),
    crop: box('.crop, figcaption, .crop ~ *').slice(0,4),
    askBtn: box('.ask .btn'),
  })`],
  ['follow', 1440, '/follow/sabotage', `({
    head: box('.head > *, h1 ~ *').slice(0,8),
    switchRow: box('.switch, .labs, .lab-switch, [role=tablist], .seg').slice(0,3),
    switchKids: box('.switch > *, .seg > *, [role=tablist] > *').slice(0,10),
    h2: [...qa('h2')].slice(0,2).map(h=>({...rect(h), kids: [...h.children].map(c=>({el: desc(c), t: c.textContent.trim().slice(0,20), ...rect(c), font: getComputedStyle(c).fontSize+' '+getComputedStyle(c).fontWeight}))})),
    firstCard: [...qa('h2 ~ * > *')].slice(0,1).map(n=>({el: desc(n), ...rect(n), kids: [...n.querySelectorAll('*')].filter(c=>c.children.length===0 && c.textContent.trim()).slice(0,10).map(c=>({el: desc(c), t: c.textContent.trim().slice(0,20), ...rect(c), font: getComputedStyle(c).fontSize+' '+getComputedStyle(c).fontWeight}))})),
    main: box('main > * > *').slice(0,10),
  })`],
  ['reader', 1440, '/d/arxiv/2305.15324/v2/p6?q=not%20the%20only%20tool%20available%20for%20AI%20risk%20assessment', `({
    bars: box('.reader-bar, .rb, .pager, .goto, .topbar, [class*=bar]').slice(0,8),
    barKids: box('[class*=bar] > *').slice(0,16),
    sheet: box('figure.sheet').slice(0,2),
    sheetOv: [...qa('figure.sheet')].slice(0,1).map(n=>({sw: n.scrollWidth, cw: n.clientWidth, kids: [...n.children].map(c=>({el: desc(c), ...rect(c)}))})),
    main: box('main > *').slice(0,6),
  })`],
  ['reader-source-card', 1440, '/d/anthropic/claude-opus-5-5-system-card/r1/p135?q=reviewed%20the%20highest-scoring%20reports%20on%20the%20deliberate%20sabotage%20dimension', `({
    quotecheck: box('.quotecheck, .qc, [class*=quote]').slice(0,4),
    qcKids: box('.quotecheck > *, .qc > *, [class*=quote] > *').slice(0,10),
    pager: box('.pager, .pager > *, nav.pages, nav.pages > *').slice(0,8),
    btns: box('.btn, .ib').slice(0,10),
    main: box('main > *').slice(0,8),
  })`],
  ['record', 390, '/d/arxiv/2305.15324', `({
    head: box('.cover, nav.up, h1, .byline, .facts, .actions, .actions > *').slice(0,10),
    versions: box('.versions a, figure.evidence-card'),
  })`],
  ['search', 390, '/search?query=%22alignment%20faking%22', `({
    comp: box('.cbox, .crow, .seg, .tries, .facets, .facets > *').slice(0,12),
    li: [...qa('ol > li > a')].slice(0,1).map(a=>({...rect(a), kids: [...a.children].map(c=>({el: desc(c), t: c.textContent.trim().slice(0,20), ...rect(c)}))})),
  })`],
  ['shelf', 390, '/library/labs', `({
    filters: box('.filters, .filters > *'),
    rows: [...qa('main li')].slice(0,1).map(n=>({el: desc(n), ...rect(n), kids: [...n.querySelectorAll('*')].filter(c=>c.children.length===0 && c.textContent.trim()).slice(0,8).map(c=>({el: desc(c), t: c.textContent.trim().slice(0,16), ...rect(c), font: getComputedStyle(c).fontSize}))})),
  })`],
  ['check', 390, '/check?example=1', `({
    sheet: box('.pv-page .sheet, .pv-page img').slice(0,2),
    pv: box('.pv-page'),
    cards: [...qa('main *')].filter(n=>{const s=getComputedStyle(n); return (s.backgroundColor==='rgba(14, 22, 33, 0.09)'||s.backgroundColor==='rgba(14, 22, 33, 0.05)') && n.getBoundingClientRect().width>200}).map(n=>({el: desc(n), bg: getComputedStyle(n).backgroundColor, ...rect(n), margin: getComputedStyle(n).margin})),
  })`],
  ['check', 1440, '/check?example=1', `({
    cards: [...qa('main *')].filter(n=>{const s=getComputedStyle(n); return (s.backgroundColor==='rgba(14, 22, 33, 0.09)'||s.backgroundColor==='rgba(14, 22, 33, 0.05)') && n.getBoundingClientRect().width>200}).map(n=>({el: desc(n), bg: getComputedStyle(n).backgroundColor, ...rect(n), margin: getComputedStyle(n).margin, pad: getComputedStyle(n).padding})),
    results: [...qa('.results > *, .findings > *, ol.cites > li, .cite-list > *')].slice(0,6).map(n=>({el: desc(n), ...rect(n), pad: getComputedStyle(n).padding, m: getComputedStyle(n).margin})),
    para: box('.checked, .marked, .annotated, p.read, .prose').slice(0,3),
    sheet: box('.pv-page .sheet'),
    caption: box('.pv ~ *, figcaption').slice(0,3),
  })`],
];
const b = await chromium.launch({ channel: 'chrome' });
const out = [];
for (const [name, width, path, expr] of jobs) {
  const mobile = width < 600;
  const page = await b.newPage({ viewport: { width, height: mobile ? 844 : 900 }, isMobile: mobile, hasTouch: mobile });
  await open(page, B + path);
  const res = await page.evaluate(e => {
    window.r = x => Math.round(x * 10) / 10;
    window.q = s => document.querySelector(s); window.qa = s => document.querySelectorAll(s);
    window.desc = n => n.tagName.toLowerCase() + (n.id ? '#' + n.id : '') + (n.classList.length ? '.' + [...n.classList].join('.') : '');
    window.rect = n => { if (!n) return null; const b = n.getBoundingClientRect(); return { x: r(b.left), y: r(b.top), w: r(b.width), h: r(b.height), right: r(b.right), bottom: r(b.bottom) }; };
    window.box = sel => [...document.querySelectorAll(sel)].filter(n => n.getClientRects().length).map(n => {
      const b = n.getBoundingClientRect(), s = getComputedStyle(n);
      return { el: desc(n), text: n.textContent.trim().replace(/\s+/g,' ').slice(0, 30), x: r(b.left), y: r(b.top), w: r(b.width), h: r(b.height), right: r(b.right), bottom: r(b.bottom), font: `${s.fontWeight} ${s.fontSize}/${s.lineHeight}`, color: s.color, bg: s.backgroundColor, radius: s.borderTopLeftRadius, padding: s.padding, margin: s.margin };
    });
    try { return (0, eval)(e); } catch (err) { return { error: String(err) }; }
  }, expr);
  out.push({ name, width, res });
  await page.close();
}
await b.close();
const show=(o)=>JSON.stringify(o,(k,v)=>typeof v==="number"?Math.round(v*10)/10:v);
for (const j of out) { console.log("\n######",j.name,j.width); if(j.res.error){console.log(j.res.error);continue}
  for (const [k,v] of Object.entries(j.res)) { console.log("--",k); if(Array.isArray(v)) v.forEach(x=>console.log("   ",show(x).slice(0,700))); else console.log("   ",show(v).slice(0,700)); } }

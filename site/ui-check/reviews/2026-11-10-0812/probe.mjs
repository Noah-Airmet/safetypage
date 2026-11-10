import { chromium } from '/Users/noahairmet/development/tools/ui-check/node_modules/@playwright/test/index.mjs';
import { open } from '/Users/noahairmet/development/tools/ui-check/lib/site.mjs';
const B = 'http://localhost:4412';
const jobs = [
  ['home', 1440, '/', `({
    tries: box('.tries').map(b=>({...b, ov: cs('.tries').overflowX, mask: cs('.tries').maskImage, wmask: cs('.tries').webkitMaskImage, sb: cs('.tries').scrollbarWidth, sw: q('.tries').scrollWidth, cw: q('.tries').clientWidth})),
    triesKids: box('.tries > *'),
    code: box('code').slice(0,1).map(b=>({...b, ov: cs('code').overflowX, mask: cs('code').maskImage||cs('code').webkitMaskImage, sw:q('code').scrollWidth, cw:q('code').clientWidth, wsp: cs('code').whiteSpace})),
    codeParent: box('code').length? rect(q('code').parentElement):null,
    shelfRows: [...qa('#shelves-h ~ * a, section[aria-labelledby=shelves-h] a')].slice(0,3).map(a=>({row: rect(a), name: rect(a.querySelector('.name')), count: rect(a.querySelector('.count')), ai: getComputedStyle(a).alignItems, disp: getComputedStyle(a).display})),
    recentRows: [...qa('section[aria-labelledby=recent-h] a, #recent-h ~ * a')].slice(0,2).map(a=>({row: rect(a), kids: [...a.children].map(rect)})),
    sections: [...qa('main > *')].map(n=>({el: desc(n), y: r(n.getBoundingClientRect().top), b: r(n.getBoundingClientRect().bottom), h: r(n.getBoundingClientRect().height)})),
    h2s: box('h2'),
    hero: box('form, .hero, .search, .ask').slice(0,4),
    heroInput: box('input').slice(0,1),
    heroBtn: box('button.btn-primary'),
    headers: [...qa('header')].map(n=>({el: desc(n), ...rect(n)})),
    ib: box('button.ib').map(b=>({...b, border: cs('button.ib').border})),
    claims: box('button.claim'),
    checkTeaser: box('h2.h2 ~ *').slice(0,6),
  })`],
  ['search', 1440, '/search?query=%22alignment%20faking%22', `({
    tries: box('.tries').map(b=>({...b, ov: cs('.tries').overflowX, mask: cs('.tries').maskImage, wmask: cs('.tries').webkitMaskImage, sw: q('.tries').scrollWidth, cw: q('.tries').clientWidth})),
    triesKids: box('.tries > *'),
    form: box('form').map(b=>({...b, border: cs('form').border, shadow: cs('form').boxShadow})),
    formKids: box('form > *'),
    seg: box('.seg, [role=tablist], .modes').slice(0,2),
    segKids: box('.seg > *, [role=tablist] > *, .modes > *'),
    results: [...qa('main li, main article, .hit')].slice(0,2).map(n=>({el: desc(n), ...rect(n), kids: [...n.children].map(rect)})),
    main: box('main > *').slice(0,8),
    headers: [...qa('header')].map(n=>({el: desc(n), ...rect(n)})),
  })`],
  ['check', 1440, '/check?example=1', `({
    textarea: box('textarea').map(b=>({...b, resize: cs('textarea').resize, border: cs('textarea').border})),
    btns: box('.btn').map(b=>({...b, border: cs(b.el.split('.')[0]).border})),
    copy: box('button.btn-quiet').map(b=>({...b, bg: b.bg, border: getComputedStyle(q('button.btn-quiet')).border})),
    chipsText: [...qa('button.chip')].map(n=>({el: desc(n), text: n.textContent.trim().slice(0,30), ...rect(n), border: getComputedStyle(n).border, outline: getComputedStyle(n).outline, shadow: getComputedStyle(n).boxShadow, deco: getComputedStyle(n.querySelector('.chip-label')||n).textDecorationLine})),
    chipsList: [...qa('a.chip, span.chip')].map(n=>({el: desc(n), text: n.textContent.trim().slice(0,30), ...rect(n), border: getComputedStyle(n).border, outline: getComputedStyle(n).outline, shadow: getComputedStyle(n).boxShadow})),
    summary: box('.tally, .summary, .counts').slice(0,2),
    results: [...qa('main > * > *')].slice(0,30).map(n=>({el: desc(n), ...rect(n)})),
    pv: box('.pv, .pv-page, .pv img, .pv-page img').map(b=>({...b})),
    headers: [...qa('header')].map(n=>({el: desc(n), ...rect(n)})),
  })`],
  ['replay', 1440, '/r/cc-haiku-5-5-4e1c63-pc-4bd058594c.1?step=21', `({
    copy: box('button.btn').filter(b=>/Copy/.test(b.text)).map(b=>({...b, border: getComputedStyle([...document.querySelectorAll('button.btn')].find(n=>/Copy/.test(n.textContent))).border})),
    strong: box('strong').slice(0,2),
    h1: box('h1'),
    top: box('main > *, .rp-head, .rp-head > *').slice(0,12),
    headers: [...qa('header')].map(n=>({el: desc(n), ...rect(n)})),
  })`],
  ['replay', 390, '/r/cc-haiku-5-5-4e1c63-pc-4bd058594c.1?step=21', `({
    doc: {sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth},
    pv: box('.pv, .pv-page, .pv img, .pv-page img, .sheet, figure'),
    pvOv: [...qa('.pv, .pv-page')].map(n=>({el: desc(n), sw: n.scrollWidth, cw: n.clientWidth, ov: getComputedStyle(n).overflowX})),
    panes: box('main > *').slice(0,10),
    bar: box('.rp-bar, .rp-controls, .player, [class*=rp-]').slice(0,12),
  })`],
  ['check', 390, '/check?example=1', `({
    doc: {sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth},
    main: box('main').concat(box('main > *').slice(0,3)),
    plates: [...qa('main *')].filter(n=>{const s=getComputedStyle(n); return s.backgroundColor==='rgba(14, 22, 33, 0.09)' && n.getBoundingClientRect().width>200}).map(n=>({el: desc(n), ...rect(n), margin: getComputedStyle(n).margin, pad: getComputedStyle(n).padding})),
    pv: box('.pv, .pv-page'),
    btns: box('.btn'),
  })`],
  ['home', 390, '/', `({
    doc: {sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth},
    plates: [...qa('main *')].filter(n=>{const s=getComputedStyle(n); return s.backgroundColor==='rgba(14, 22, 33, 0.09)' && n.getBoundingClientRect().width>200}).map(n=>({el: desc(n), ...rect(n), margin: getComputedStyle(n).margin})),
    tries: box('.tries').map(b=>({...b, sw: q('.tries').scrollWidth, cw: q('.tries').clientWidth})),
    input: box('input').slice(0,1).map(b=>({...b, ph: q('input').placeholder, sw: q('input').scrollWidth, cw: q('input').clientWidth})),
    code: box('code').slice(0,1).map(b=>({...b, sw:q('code').scrollWidth, cw:q('code').clientWidth})),
    follow: box('section[aria-labelledby=follow-h] a, #follow-h ~ * a').slice(0,8),
    main: box('main > *').slice(0,12),
    header: box('header, header > *'),
  })`],
  ['citationbench', 1440, '/citationbench', `({
    th: box('th, thead td').map(b=>({...b, ta: getComputedStyle(q('th')).textAlign})),
    thAlign: [...qa('th')].map(n=>({t: n.textContent.trim().slice(0,14), ta: getComputedStyle(n).textAlign, x: r(n.getBoundingClientRect().left), right: r(n.getBoundingClientRect().right)})),
    td: [...qa('tbody tr')].slice(0,1).flatMap(tr=>[...tr.children].map(n=>({el: desc(n), t: n.textContent.trim().slice(0,14), ta: getComputedStyle(n).textAlign, ...rect(n)}))),
    rows: box('tbody tr'),
    dl: box('dl, dl > *').slice(0,6),
    sub: box('.sub, .byline, .meta, h1 ~ p').slice(0,4),
  })`],
  ['connect', 1440, '/connect', `({
    h3: [...qa('h3')].map(n=>({...rect(n), font: getComputedStyle(n).fontSize, code: n.querySelector('code')? getComputedStyle(n.querySelector('code')).fontSize : null, codeBg: n.querySelector('code')? getComputedStyle(n.querySelector('code')).backgroundColor : null, codePad: n.querySelector('code')? getComputedStyle(n.querySelector('code')).padding : null, next: n.nextElementSibling? {el: desc(n.nextElementSibling), ...rect(n.nextElementSibling), font: getComputedStyle(n.nextElementSibling).fontSize} : null})),
    rows: box('dl, dt, dd').slice(0,8),
    codeBoxes: box('pre, .code, .cmd, [class*=copy]').slice(0,12),
    ib: box('button.ib, a.ib'),
    first: box('main > *').slice(0,12),
  })`],
  ['record', 1440, '/d/arxiv/2305.15324', `({
    thumb: box('img, .thumb, .cover').slice(0,2),
    crumb: box('nav[aria-label], .crumb, .crumbs, .breadcrumb').slice(0,2),
    h1: box('h1'),
    meta: box('h1 ~ *').slice(0,4),
    versions: box('#versions-h ~ *, .version, .versions li, .versions a').slice(0,4),
    licence: box('#licence-h ~ *').slice(0,4),
    outline: box('.o-title, .o-page').slice(0,4),
    btns: box('.btn, input.field').slice(0,5),
    cols: box('main > *').slice(0,8),
  })`],
  ['library', 1440, '/library', `({
    rows: [...qa('main section, main li, main article')].slice(0,3).map(n=>({el: desc(n), ...rect(n), kids: [...n.children].map(c=>({el: desc(c), ...rect(c), font: getComputedStyle(c).fontSize}))})),
    name: box('.name').slice(0,2), count: box('.count').slice(0,2),
    chips: box('.name ~ * a, .pubs a, .orgs a').slice(0,3),
    sub: box('h1 ~ *').slice(0,2),
  })`],
  ['shelf', 1440, '/library/labs', `({
    filters: box('input.field, select.field').map(b=>({...b, border: getComputedStyle(q(b.el.split('.')[0]+'.field')).border})),
    rows: [...qa('main li, main article, .row')].slice(0,2).map(n=>({el: desc(n), ...rect(n), kids: [...n.querySelectorAll('*')].filter(c=>c.children.length===0).slice(0,8).map(c=>({el: desc(c), t: c.textContent.trim().slice(0,16), ...rect(c), font: getComputedStyle(c).fontSize}))})),
    count: box('p.count'), crumb: box('h1 ~ *, .crumb, .eyebrow').slice(0,3), top: box('main > *').slice(0,6),
    more: box('.btn'),
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
    window.cs = s => getComputedStyle(document.querySelector(s));
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
console.log(JSON.stringify(out, null, 1));

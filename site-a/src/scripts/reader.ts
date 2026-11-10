// The reader. One static shell serves every /d/<ns>/<id>/<version>/<anchor> address (the host
// rewrites those paths to it; see site/README.md), and this script draws the document from the
// snapshot's static files: the card, then page images with a text layer (open PDFs), the text
// re-set in our template (open web documents), or the source card (documents read at source).
import { KINDS, anchorLabel, atSource, citePath, formatDate, hostOf, licenceName, shortLabel, sourceLink, titleParts } from '../lib/cite';
import { API_BASE, DATA_BASE } from '../lib/env';
import { findQuote, highlightRects } from '../lib/quote';
import type { DocumentCard, QuoteCheck, UnitText } from '../lib/types';
import { closeLayer, copyText, icon, remember, toast } from '../lib/ui';

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);
const progress = (w: number | null) => {
  const bar = document.getElementById('progress');
  if (!bar) return;
  if (w === null) { bar.style.setProperty('--w', '1'); setTimeout(() => bar.classList.remove('on'), 200); } else { bar.classList.add('on'); requestAnimationFrame(() => bar.style.setProperty('--w', String(w))); }
};
const getJson = async <T>(url: string): Promise<T | null> => {
  try {
    const r = await fetch(url);
    return r.ok ? ((await r.json()) as T) : null;
  } catch {
    return null;
  }
};
const WINDOW = 150;   // paragraphs drawn either side of the target in a very long web document

async function open(root: HTMLElement) {
  const m = /^\/d\/([a-z0-9-]+)\/([A-Za-z0-9._-]+)\/([vr]\d+)\/([pb])(\d+)(?:-[pb]?(\d+))?\/?$/.exec(location.pathname);
  if (!m) return missing(root, 'No such address');
  progress(0.6);
  const [, ns, local, version, letter, first, last] = m;
  const docId = `${ns}:${local}`;
  const inline = document.getElementById('doc-card')?.textContent;
  let doc = inline ? (JSON.parse(inline) as DocumentCard) : await getJson<DocumentCard>(`${DATA_BASE}/docs/${ns}/${local}.json`);
  if (!doc) return missing(root, 'No such document', '/library', 'Library');
  // The published card is the latest version's. An older version's comes from the server.
  if (doc.version !== version) doc = (await getJson<DocumentCard>(`${API_BASE}/api/doc/${ns}/${local}/${version}`)) ?? doc;
  const summary = doc.versions.find((v) => v.version === version);
  const record = citePath(docId);
  if (!summary) return missing(root, `No version ${version}`, record, doc.title);
  const count = doc.version === version ? doc.unit_count : 0;
  const n = Number(first);
  const kind = doc.version === version ? (doc.anchor_kind === 'page' ? 'p' : 'b') : letter;
  if (letter !== kind || n < 1 || (count && n > count)) {
    return missing(root, `No ${anchorLabel(letter + first)} · ${count} ${kind === 'p' ? 'pages' : 'paragraphs'}`, record, doc.title);
  }
  start(root, { doc, version, target: `${letter}${n}`, end: last ? `${letter}${last}` : null, count: count || n, open: summary.tier === 'open', licence: summary.licence });
}

function missing(root: HTMLElement, why: string, href = '/search', label = 'Search') {
  progress(null);
  document.title = 'Not in the library · SafetyPage';
  root.innerHTML = `<div class="page"><header class="head"><h1>Not in the library</h1><p class="meta">${esc(why)}</p><div class="ctl"><a class="btn" href="${esc(href)}"><span>${esc(label)}</span></a></div></header></div>`;
}

interface Opened { doc: DocumentCard; version: string; target: string; end: string | null; count: number; open: boolean; licence: string }

function start(root: HTMLElement, o: Opened) {
  const { doc, version, target, count } = o;
  const ref = `${doc.doc_id}/${version}`;
  const paged = target[0] === 'p';
  const n = Number(target.slice(1));
  const mode = !o.open ? 'source' : paged ? 'pages' : 'text';
  const params = new URLSearchParams(location.search);
  const quote = params.get('q')?.trim() || null;
  const endAnchor = o.end ?? params.get('end');
  const host = hostOf(doc.source_url);
  const short = shortLabel(doc);
  const outline = doc.version === version ? doc.outline : [];
  const textUrl = (anchor: string) => `${DATA_BASE}/text/${ref.replace(':', '/')}/${anchor}.json`;
  const image = (anchor: string, width: number) => `${DATA_BASE}/pages/${ref.replace(':', '/')}/${anchor}.${width}.webp`;
  const cache = new Map<string, Promise<UnitText | null>>();
  const unit = (anchor: string) => {
    if (!cache.has(anchor)) cache.set(anchor, getJson<UnitText>(textUrl(anchor)));
    return cache.get(anchor)!;
  };

  document.title = `${short}, ${anchorLabel(target)} · SafetyPage`;
  root.dataset.mode = mode;
  // The bar is the shell's: where you are in the middle, what you can do here on the right.
  // Back is the shell's when this site is behind you; opened cold, it is Up, to the record.
  const recordHref = citePath(doc.version === version ? doc.doc_id : ref);
  const tp = titleParts(doc.title);
  document.getElementById('bar-m')!.innerHTML = `<a class="place" href="${recordHref}"><b>${esc(tp.main)}${tp.sub ? `<span class="sub">: ${esc(tp.sub)}</span>` : ''}</b><small>${esc(short)}</small></a>`;
  document.getElementById('bar-r')!.innerHTML = `<a class="ib" href="/search?doc=${encodeURIComponent(doc.doc_id)}" aria-label="Search in document">${icon('search')}</a><button class="ib" type="button" data-open="r-more" aria-label="More" aria-haspopup="menu">${icon('more')}</button>`;
  const back = document.querySelector<HTMLAnchorElement>('.bar .back');
  if (back?.hidden) { back.hidden = false; back.href = recordHref; back.querySelector(':scope > span:last-child')!.textContent = short; back.setAttribute('aria-label', `Back: ${short}`); }
  remember({ href: location.pathname, title: doc.title, at: anchorLabel(target) }, citePath(doc.doc_id));
  const contents = outline.length
    ? `<section class="layer" id="r-contents" data-layer="list" hidden aria-label="Contents"><div class="grab"></div><div class="head"><b>Contents</b><button class="ib" type="button" data-close aria-label="Close">${icon('close')}</button></div><div class="body menu-rows">${outline.map((item) =>
      `<a class="lvl" style="--level:${item.level - 1}" href="${citePath(item.cite)}" data-jump="${item.anchor}"><span class="o-t">${esc(item.title)}</span><span class="n">${esc(anchorLabel(item.anchor))}</span></a>`).join('')}</div></section>` : '';
  root.innerHTML = `
    <div class="r-find frost" data-qstatus hidden></div>
    <div data-body></div>
    <footer class="r-foot">
      ${outline.length ? `<button class="ib" type="button" data-open="r-contents" aria-label="Contents">${icon('contents')}</button>` : '<span class="r-gap"></span>'}
      <div class="r-scrub">${mode === 'pages' ? `<input type="range" min="1" max="${count}" value="${n}" aria-label="Page" data-scrub />` : `<i class="r-line"><i data-line style="width:${(n / Math.max(1, count)) * 100}%"></i></i>`}</div>
      ${mode === 'pages'
        ? `<button class="r-pg" type="button" data-open="r-goto" title="Go to page"><span data-here>${esc(anchorLabel(target))} / ${count}</span></button>`
        : `<span class="r-pg still"><span data-here>${esc(anchorLabel(target))}${count ? ` / ${count}` : ''}</span></span>`}
    </footer>
    ${contents}
    <section class="layer" id="r-goto" data-layer="tool" hidden aria-label="Go to page"><div class="grab"></div>
      <form class="body r-goto" data-goto><label class="find"><span>p.</span><input name="page" inputmode="numeric" autocomplete="off" value="${n}" aria-label="Page number" /><span>/ ${count}</span></label><button class="pill bare"><span>Go</span></button></form>
    </section>
    <section class="layer" id="r-more" data-layer="tool" data-shape="menu" hidden aria-label="More"><div class="grab"></div>
      <div class="body menu-rows">
        <button type="button" data-act="cite">${icon('quote')}<span class="k">Copy citation</span></button>
        <button type="button" data-act="url">${icon('link')}<span class="k">Copy link to this ${paged ? 'page' : 'paragraph'}</span></button>
        <a href="${esc(sourceLink(doc.source_url, target, paged))}" rel="noopener" data-source>${icon('external')}<span class="k">${esc(host)}</span></a>
        <a href="${recordHref}">${icon('about')}<span class="k">Record</span></a>
      </div>
    </section>
    <div class="selpop frost" data-selpop hidden role="toolbar" aria-label="Selection">
      <button data-act="quote">Copy quote</button><button data-act="link">Copy link</button><button data-act="check">Check</button>
    </div>`;
  let current = target;   // the page or paragraph in view
  root.querySelector('#r-more')!.addEventListener('click', (event) => {
    const act = (event.target as HTMLElement).closest<HTMLElement>('[data-act]')?.dataset.act;
    if (!act) return;
    copyText(act === 'cite' ? `${ref}/${current}` : location.origin + citePath(`${ref}/${current}`)).then(() => toast('Copied'), () => toast('Copy failed', 'close'));
    closeLayer();
  });
  const body = root.querySelector<HTMLElement>('[data-body]')!;
  const status = root.querySelector<HTMLElement>('[data-qstatus]')!;
  const say = (state: 'verified' | 'rejected', words: string, extra = '') => {
    status.hidden = false;
    status.innerHTML = `<span class="state" data-state="${state}">${icon(state === 'verified' ? 'check' : 'close')}<span>${words}</span></span><q></q>${extra}<button class="ib" type="button" data-unfind aria-label="Clear">${icon('close')}</button>`;
    status.querySelector('q')!.textContent = quote!.length > 140 ? quote!.slice(0, 140) + '…' : quote!;
    status.querySelector('[data-unfind]')!.addEventListener('click', () => {
      status.hidden = true;
      root.querySelectorAll('.hl').forEach((el) => el.remove());
      root.querySelectorAll('mark').forEach((el) => el.replaceWith(...el.childNodes));
      history.replaceState(history.state, '', location.pathname);
    });
  };
  const checkLink = () => `<a class="cite" href="/check?text=${encodeURIComponent(`"${quote}" (${ref}/${target})`)}">Check</a>`;

  // ---- pages: images with a text layer on demand, the highlight, the page indicator
  if (mode === 'pages') {
    body.className = 'desk';
    body.innerHTML = Array.from({ length: count }, (_, i) => {
      const a = `p${i + 1}`;
      const near = Math.abs(i + 1 - n) <= 1;
      return `<figure class="sheet" id="${a}" data-unit="${a}"><img src="${image(a, 800)}" srcset="${image(a, 800)} 800w, ${image(a, 1600)} 1600w" sizes="(max-width: 900px) 100vw, 860px" alt="${esc(doc.title)}, ${anchorLabel(a)}" loading="${near ? 'eager' : 'lazy'}" decoding="async"${a === target ? ' fetchpriority="high"' : ''} /><div class="textlayer" data-textlayer></div></figure>`;
    }).join('');
    const sheets = [...body.querySelectorAll<HTMLElement>('.sheet')];
    const measure = document.createElement('canvas').getContext('2d')!;
    measure.font = `100px ${getComputedStyle(document.documentElement).getPropertyValue('--sans')}`;
    const shape = (sheet: HTMLElement, page: UnitText) => { if (page.width && page.height) sheet.style.aspectRatio = `${page.width}/${page.height}`; };

    const layer = async (sheet: HTMLElement) => {
      const holder = sheet.querySelector<HTMLElement>('[data-textlayer]')!;
      if (holder.dataset.done) return;
      holder.dataset.done = '1';
      const page = await unit(sheet.dataset.unit!);
      if (!page?.words || !page.text || !page.width || !page.height) return;
      shape(sheet, page);
      const parts: string[] = [];
      page.words.forEach(([s, e, x0, y0, x1, y1], i) => {
        const next = page.words![i + 1]?.[0] ?? page.text!.length;
        const word = page.text!.slice(s, e);
        const size = ((y1 - y0) / page.width!) * 100 * 0.86;
        const natural = (measure.measureText(word).width / 100) * size;
        const scale = natural ? (((x1 - x0) / page.width!) * 100) / natural : 1;
        const text = esc(word + page.text!.slice(e, next).replace(/-?\n/, (m) => (m === '\n' ? ' ' : m)));
        parts.push(`<span style="left:${((x0 / page.width!) * 100).toFixed(3)}%;top:${((y0 / page.height!) * 100).toFixed(3)}%;font-size:${size.toFixed(3)}cqw;transform:scaleX(${scale.toFixed(4)})">${text}</span>`);
      });
      holder.innerHTML = parts.join('');
    };

    const input = root.querySelector<HTMLInputElement>('[data-goto] input')!;
    const source = root.querySelector<HTMLAnchorElement>('[data-source]')!;
    const scrub = root.querySelector<HTMLInputElement>('[data-scrub]')!;
    const hereLabel = root.querySelector<HTMLElement>('[data-here]')!;
    const fill = () => scrub.style.setProperty('--fill', `${((Number(scrub.value) - 1) / Math.max(1, count - 1)) * 100}%`);
    fill();
    scrub.addEventListener('input', () => { fill(); hereLabel.textContent = `p. ${scrub.value} / ${count}`; });
    scrub.addEventListener('change', () => go(`p${scrub.value}`, true));
    let settled = false;
    const here = new IntersectionObserver(
      (entries) => {
        const top = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (!top || !settled) return;
        const anchor = (top.target as HTMLElement).dataset.unit!;
        if (document.activeElement !== input) input.value = anchor.slice(1);
        current = anchor;
        if (document.activeElement !== scrub) { scrub.value = anchor.slice(1); fill(); }
        hereLabel.textContent = `${anchorLabel(anchor)} / ${count}`;
        source.href = sourceLink(doc.source_url, anchor, true);
        document.title = `${short}, ${anchorLabel(anchor)} · SafetyPage`;
        history.replaceState(history.state, '', citePath(`${ref}/${anchor}`) + (anchor === target ? location.search : ''));
      },
      { rootMargin: '-25% 0px -70% 0px' },
    );
    const go = (anchor: string, record = false) => {
      document.getElementById(anchor)?.scrollIntoView({ block: 'start' });
      if (record) history.replaceState(history.state, '', citePath(`${ref}/${anchor}`));
    };
    root.querySelector('[data-goto]')!.addEventListener('submit', (event) => {
      event.preventDefault();
      go(`p${Math.min(Math.max(1, Number(input.value) || 1), count)}`, true);
      input.blur();
      closeLayer();
    });
    root.querySelectorAll<HTMLAnchorElement>('[data-jump]').forEach((a) =>
      a.addEventListener('click', (event) => {
        event.preventDefault();
        go(a.dataset.jump!, true);
        closeLayer();
      }),
    );

    (async () => {
      // Every sheet takes the cited page's shape until its own arrives, so the page lands where it will stay.
      const page = await unit(target);
      if (page?.width && page.height) body.style.setProperty('--shape', `${page.width}/${page.height}`);
      go(target);
      progress(null);
      const near = new IntersectionObserver((entries) => entries.forEach((e) => e.isIntersecting && layer(e.target as HTMLElement)), { rootMargin: '100% 0px' });
      sheets.forEach((s) => { near.observe(s); here.observe(s); });
      if (quote) {
        const lastPage = endAnchor ? Number(endAnchor.slice(1)) : n;
        let firstMark: HTMLElement | null = null;
        let found = false;
        // A quote may run across a page break: look for it on each page of the range.
        for (let at = n; at <= Math.min(lastPage, count); at++) {
          const p = await unit(`p${at}`);
          if (!p?.text) continue;
          const ranges = findQuote(p.text, quote);
          const pieces = ranges ?? (lastPage > n ? somePieces(p.text, quote) : null);
          if (!pieces) continue;
          found = found || !!ranges || lastPage > n;
          const sheet = document.getElementById(`p${at}`)!;
          shape(sheet, p);
          for (const [s, e] of pieces) {
            for (const r of highlightRects(p, s, e)) {
              const mark = document.createElement('div');
              mark.className = 'hl';
              mark.style.cssText = `left:${r.left}%;top:${r.top}%;width:${r.width}%;height:${r.height}%`;
              sheet.append(mark);
              firstMark ??= mark;
            }
          }
        }
        if (found) {
          say('verified', `On ${anchorLabel(endAnchor ? `${target}-${endAnchor}` : target)}`);
          firstMark?.scrollIntoView({ block: 'center' });
        } else {
          say('rejected', `Not on ${anchorLabel(target)}`, checkLink());
          remote();
        }
      }
      setTimeout(() => (settled = true), 400);
    })();
  }

  // ---- text: the document's blocks, with the target marked and the quote inside it
  if (mode === 'text') {
    const tags: Record<string, string> = { quote: 'blockquote', code: 'pre' };
    const n0 = count > 2 * WINDOW + 100 ? Math.max(1, n - WINDOW) : 1;
    const n1 = count > 2 * WINDOW + 100 ? Math.min(count, n + WINDOW) : count;
    body.className = 'textdoc';
    body.innerHTML = `<header class="head"><h1${doc.title.length > 70 ? ' class="long"' : ''}>${esc(tp.main)}${tp.sub ? `<span class="sub">: ${esc(tp.sub)}</span>` : ''}</h1>${doc.authors.length ? `<p class="by">${esc(doc.authors.join(', '))}</p>` : ''}<p class="meta">${esc([doc.org, formatDate(doc.published), licenceName(o.licence)].filter(Boolean).join(' · '))}</p></header><div data-blocks aria-busy="true"></div>`;
    const holder = body.querySelector<HTMLElement>('[data-blocks]')!;
    const draw = (u: UnitText) => {
      const kind = u.kind ?? 'paragraph';
      const tag = kind === 'heading' ? `h${Math.min(4, (u.level ?? 1) + 1)}` : (tags[kind] ?? 'p');
      const num = u.anchor.slice(1);
      return `<div class="block" id="${u.anchor}" data-unit="${u.anchor}" data-kind="${kind}"><a class="gutter" href="${citePath(u.cite)}" aria-label="Link to paragraph ${num}">¶${num}</a><${tag} class="t">${esc(u.text ?? '')}</${tag}></div>`;
    };
    const load = async (from: number, to: number) => {
      const units = await Promise.all(Array.from({ length: to - from + 1 }, (_, i) => unit(`b${from + i}`)));
      return units.filter((u): u is UnitText => !!u?.text).map(draw).join('');
    };
    const more = (from: number, to: number, label: string, where: InsertPosition) => {
      if (from > to) return;
      const button = document.createElement('button');
      button.className = 'btn more morebtn';
      button.textContent = label;
      button.addEventListener('click', async () => {
        button.disabled = true;
        const a = where === 'afterbegin' ? Math.max(from, to - 2 * WINDOW + 1) : from;
        const b = where === 'afterbegin' ? to : Math.min(to, from + 2 * WINDOW - 1);
        button.insertAdjacentHTML(where === 'afterbegin' ? 'afterend' : 'beforebegin', await load(a, b));
        button.remove();
        if (where === 'afterbegin') more(from, a - 1, label, where);
        else more(b + 1, to, label, where);
      });
      holder.insertAdjacentElement(where, button);
    };
    (async () => {
      holder.innerHTML = await load(n0, n1);
      holder.removeAttribute('aria-busy');
      progress(null);
      more(1, n0 - 1, 'Earlier', 'afterbegin');
      more(n1 + 1, count, 'Later', 'beforeend');
      // where you are: the paragraph nearest the top, in the foot
      const hereLabel = root.querySelector<HTMLElement>('[data-here]')!;
      const line = root.querySelector<HTMLElement>('[data-line]');
      const seen = new IntersectionObserver((entries) => {
        const top = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (!top) return;
        current = (top.target as HTMLElement).dataset.unit!;
        hereLabel.textContent = `${anchorLabel(current)} / ${count}`;
        if (line) line.style.width = `${(Number(current.slice(1)) / Math.max(1, count)) * 100}%`;
      }, { rootMargin: '-15% 0px -70% 0px' });
      holder.querySelectorAll('.block').forEach((b) => seen.observe(b));
      root.querySelectorAll<HTMLAnchorElement>('[data-jump]').forEach((a) => a.addEventListener('click', (event) => {
        const to = document.getElementById(a.dataset.jump!);
        if (!to) return;   // outside the paragraphs drawn: the link loads it
        event.preventDefault();
        to.scrollIntoView({ block: 'start' });
        history.replaceState(history.state, '', citePath(`${ref}/${a.dataset.jump}`));
        closeLayer();
      }));
      const block = document.getElementById(target);
      if (!block) return;
      block.dataset.target = '';
      if (!quote) return void land(block, 'start');
      const node = block.querySelector('.t')!.firstChild as Text | null;
      const ranges = node ? findQuote(node.data, quote) : null;
      if (node && ranges) {
        for (const [s, e] of [...ranges].reverse()) {
          const range = document.createRange();
          range.setStart(node, s);
          range.setEnd(node, e);
          range.surroundContents(document.createElement('mark'));
        }
        say('verified', `In ${anchorLabel(target)}`);
        land(block.querySelector('mark')!, 'center');
      } else {
        land(block, 'center');
        say('rejected', `Not in ${anchorLabel(target)}`, checkLink());
        remote();
      }
    })();
  }

  // ---- source: what the library knows about this place, and the way to it at the source
  if (mode === 'source') {
    const what = paged ? 'page' : 'paragraph';
    const section = [...outline].reverse().find((item) => item.anchor[0] === target[0] && Number(item.anchor.slice(1)) <= n);
    const step = (to: number, glyph: string, dir: string) => (to >= 1 && (!count || to <= count)
      ? `<a class="btn" href="${citePath(`${ref}/${target[0]}${to}`)}" title="${dir}">${dir === 'Next' ? '' : icon(glyph)}<span>${esc(anchorLabel(`${target[0]}${to}`))}</span>${dir === 'Next' ? icon(glyph) : ''}</a>` : '<span></span>');
    body.className = 'desk';
    progress(null);
    body.innerHTML = `
      <section class="sourcecard" data-unit="${target}">
        <header class="head">
          <h1${doc.title.length > 70 ? ' class="long"' : ''}>${esc(tp.main)}${tp.sub ? `<span class="sub">: ${esc(tp.sub)}</span>` : ''}</h1>
          <p class="meta">${esc([doc.org, KINDS[doc.kind] ?? doc.kind, formatDate(doc.published), licenceName(o.licence)].filter(Boolean).join(' · '))}</p>
        </header>
        <p class="where"><b data-label>${esc(anchorLabel(target))}</b>${count ? `<span>/ ${count}</span>` : ''}${section ? `<span class="sect">${esc(section.title)}</span>` : ''}</p>
        <blockquote class="excerpt qcard" data-excerpt aria-busy="true"></blockquote>
        <a class="pill btn-primary" data-open-source href="${esc(sourceLink(doc.source_url, target, paged))}" rel="noopener">${icon('external')}<span>${paged ? esc(anchorLabel(target)) + ' at ' : ''}${esc(host)}</span></a>
        <form class="quotecheck" data-quotecheck>
          <label class="find">${icon('quote')}<input id="qc" name="quote" autocomplete="off" placeholder="Check a quote" aria-label="Check a quote against this ${what}" /></label><button class="btn"><span>Check</span></button>
          <p class="qc-result" data-result aria-live="polite"></p>
        </form>
        <nav class="pager" aria-label="${paged ? 'Pages' : 'Paragraphs'}">${step(n - 1, 'back', 'Previous')}${step(n + 1, 'forward', 'Next')}</nav>
      </section>`;
    const excerpt = body.querySelector<HTMLElement>('[data-excerpt]')!;
    const openLink = body.querySelector<HTMLAnchorElement>('[data-open-source]')!;
    // A web page has no page numbers: the link carries the passage's opening words, and the browser scrolls to them.
    const toPassage = (words: string) => {
      if (!paged) openLink.href = sourceLink(doc.source_url, target, false, words.replace(/…/g, '').split(/\s+/).filter(Boolean).slice(0, 8).join(' '));
    };
    getJson<UnitText[]>(`${API_BASE}/api/units/${ref.replace(':', '/')}/${target}`).then((units) => {
      excerpt.removeAttribute('aria-busy');
      const u = units?.[0];
      if (!u?.excerpt) return void (excerpt.hidden = !excerpt.dataset.quoted);
      if (excerpt.dataset.quoted) return;   // a checked quote is already shown
      excerpt.textContent = u.excerpt;
      if (paged) openLink.href = atSource(u.source_url);
      else if (!quote) toPassage(u.excerpt);
      if (u.anchor_label && paged) body.querySelector('[data-label]')!.textContent = u.anchor_label;
    });
    const result = body.querySelector<HTMLElement>('[data-result]')!;
    const form = body.querySelector<HTMLFormElement>('[data-quotecheck]')!;
    const input = form.querySelector<HTMLInputElement>('input')!;
    const check = async (words: string) => {
      result.innerHTML = '<i class="working"></i>';
      const c = await verify(words);
      if (!c) return void (result.textContent = 'Check unavailable');
      const where = c.locations[0];
      const head = `<span class="state" data-state="${c.passed ? 'verified' : 'rejected'}">${icon(c.passed ? 'check' : 'close')}<span>${c.passed ? `On ${anchorLabel(target)}` : `Not on ${anchorLabel(target)}`}</span></span> `;
      if (c.passed) {
        result.innerHTML = `${head}<span class="flag">${c.verdict === 'exact' ? 'Word for word' : 'Normalised'}</span>`;
        toPassage(words);
        // The words are on the page: show them as the passage, in place of the page's opening words.
        excerpt.removeAttribute('aria-busy');
        excerpt.dataset.quoted = '1';
        excerpt.hidden = false;
        excerpt.textContent = where?.text.replace(/\s+/g, ' ') ?? words;
      } else if (c.verdict === 'elsewhere' && where) result.innerHTML = `${head}<a class="cite" data-state="verified" href="${citePath(where.cite, words)}">${icon('check')}<span>${anchorLabel(where.anchor)}</span></a>`;
      else if (c.verdict === 'near_miss' && where) {
        result.innerHTML = `${head}<span class="flag">The page says</span><span class="closest"></span>`;
        result.querySelector('.closest')!.textContent = `“${where.text.replace(/\s+/g, ' ')}”`;
      } else result.innerHTML = `${head}<span class="flag">Not in the document</span>`;
    };
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      if (input.value.trim()) check(input.value.trim());
    });
    if (quote) {
      check(quote);
    }
  }

  function verify(words: string) {
    return fetch(`${API_BASE}/api/verify`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ quote: words, cite: `${ref}/${target}` }),
    }).then((r) => (r.ok ? (r.json() as Promise<QuoteCheck>) : null)).catch(() => null);
  }

  // Ask the checker for the real verdict: where the words are, or the nearest wording.
  async function remote() {
    const c = await verify(quote!);   // reading works without the server
    const where = c?.locations[0];
    if (!c || !where) return;
    if (c.verdict === 'elsewhere') say('rejected', `Not on ${anchorLabel(target)}`, `<a class="cite" data-state="verified" data-elsewhere href="${citePath(where.cite, quote)}">${icon('check')}<span>${anchorLabel(where.anchor)}</span></a>`);
    else if (c.verdict === 'near_miss') {
      say('rejected', `Not on ${anchorLabel(target)}`, `<span class="flag">The page says</span><span class="closest"></span>`);
      status.querySelector('.closest')!.textContent = `“${where.text.replace(/\s+/g, ' ')}”`;
    }
  }

  // ---- copy with citation
  const pop = root.querySelector<HTMLElement>('[data-selpop]')!;
  let picked: { text: string; anchor: string } | null = null;
  const selection = () => {
    const sel = document.getSelection();
    const text = sel?.toString().replace(/-\n/g, '').replace(/\s+/g, ' ').trim() ?? '';
    const holder = sel?.rangeCount ? (sel.getRangeAt(0).startContainer.parentElement?.closest<HTMLElement>('[data-unit]') ?? null) : null;
    if (!sel || sel.isCollapsed || text.length < 3 || !holder || !root.contains(holder) || mode === 'source') {
      pop.hidden = true;
      picked = null;
      return;
    }
    picked = { text, anchor: holder.dataset.unit! };
    const box = sel.getRangeAt(0).getBoundingClientRect();
    pop.hidden = false;
    pop.style.left = `${Math.min(Math.max(box.left + box.width / 2, 130), innerWidth - 130)}px`;
    pop.style.top = `${Math.max(box.top - 10, 56)}px`;
  };
  let timer = 0;
  document.addEventListener('selectionchange', () => {
    clearTimeout(timer);
    timer = window.setTimeout(selection, 150);
  });
  pop.addEventListener('mousedown', (event) => event.preventDefault());
  pop.addEventListener('click', (event) => {
    const act = (event.target as HTMLElement).dataset.act;
    if (!act || !picked) return;
    const cite = `${ref}/${picked.anchor}`;
    const brief = picked.text.length > 300 ? picked.text.slice(0, picked.text.lastIndexOf(' ', 300)) : picked.text;
    const url = location.origin + citePath(cite, brief);
    if (act === 'check') {
      location.href = `/check?text=${encodeURIComponent(`"${picked.text}" (${cite})`)}`;
      return;
    }
    const year = doc.published?.slice(0, 4);
    const text = act === 'link' ? url : `“${picked.text}” (${[short.replace(/ \d{4}$/, ''), `“${doc.title}”`, year, anchorLabel(picked.anchor)].filter(Boolean).join(', ')}) ${url}`;
    copyText(text).then(() => toast('Copied'), () => toast('Copy failed', 'close'));
    pop.hidden = true;
  });

}

/** Scroll to a place and stay on it while the text reflows (fonts arrive for a few seconds), until the reader scrolls. */
function land(el: Element, block: ScrollLogicalPosition) {
  const go = () => el.scrollIntoView({ block });
  go();
  document.fonts.addEventListener('loadingdone', go);
  const stop = () => document.fonts.removeEventListener('loadingdone', go);
  for (const type of ['wheel', 'touchstart', 'keydown', 'mousedown']) addEventListener(type, stop, { once: true, passive: true });
  setTimeout(stop, 4000);
}

/** For a quote that runs over a page break: the fragments of it that are on this page. */
function somePieces(text: string, quote: string): [number, number][] | null {
  const words = quote.split(/\s+/);
  for (let cut = words.length - 1; cut >= 3; cut--) {
    const head = findQuote(text, words.slice(0, cut).join(' '));
    if (head) return head;
    const tail = findQuote(text, words.slice(words.length - cut).join(' '));
    if (tail) return tail;
  }
  return null;
}

const root = document.querySelector<HTMLElement>('[data-reader]');
if (root) open(root);

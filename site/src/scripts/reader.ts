// The reader's behaviour: text layers, the quote highlight, the page indicator, and
// copy-with-citation. Plain DOM code; the page itself is static HTML.
import { anchorLabel, anchorNumber, citePath } from '../lib/cite';
import { API_BASE } from '../lib/env';
import { findQuote, highlightRects } from '../lib/quote';
import type { QuoteCheck, UnitText } from '../lib/types';

const root = document.querySelector<HTMLElement>('[data-reader]');
if (root) start(root);

function start(root: HTMLElement) {
  const mode = root.dataset.mode as 'pages' | 'text' | 'source';
  const ref = root.dataset.ref!;
  const base = root.dataset.base!;
  const doc = JSON.parse(root.dataset.doc!) as { title: string; short: string; published: string | null };
  const params = new URLSearchParams(location.search);
  const quote = params.get('q')?.trim() || null;
  const target = root.dataset.target!;
  const endAnchor = params.get('end');
  const status = root.querySelector<HTMLElement>('[data-qstatus]')!;
  const textUrl = (anchor: string) => `${base}/text/${ref.replace(':', '/')}/${anchor}.json`;
  const cache = new Map<string, Promise<UnitText>>();
  const unit = (anchor: string) => {
    if (!cache.has(anchor)) cache.set(anchor, fetch(textUrl(anchor)).then((r) => r.json()));
    return cache.get(anchor)!;
  };
  const say = (state: 'verified' | 'rejected', words: string, extra = '') => {
    status.hidden = false;
    status.innerHTML = `<span class="state" data-state="${state}">${words}</span><q></q>${extra}`;
    status.querySelector('q')!.textContent = quote!.length > 140 ? quote!.slice(0, 140) + '…' : quote!;
  };
  const checkLink = () => `<a class="link" href="/check?text=${encodeURIComponent(`"${quote}" (${ref}/${target})`)}">Check it</a>`;

  // ---- pages: text layers on demand, the highlight, the page indicator
  if (mode === 'pages') {
    const sheets = [...root.querySelectorAll<HTMLElement>('.sheet')];
    const measure = document.createElement('canvas').getContext('2d')!;
    measure.font = `100px ${getComputedStyle(document.documentElement).getPropertyValue('--sans')}`;

    const layer = async (sheet: HTMLElement) => {
      const holder = sheet.querySelector<HTMLElement>('[data-textlayer]')!;
      if (holder.dataset.done) return;
      holder.dataset.done = '1';
      const page = await unit(sheet.dataset.unit!);
      if (!page.words || !page.text || !page.width || !page.height) return;
      const parts: string[] = [];
      page.words.forEach(([s, e, x0, y0, x1, y1], i) => {
        const next = page.words![i + 1]?.[0] ?? page.text!.length;
        const word = page.text!.slice(s, e);
        const size = ((y1 - y0) / page.width!) * 100 * 0.86;
        const natural = (measure.measureText(word).width / 100) * size;
        const scale = natural ? (((x1 - x0) / page.width!) * 100) / natural : 1;
        const text = (word + page.text!.slice(e, next).replace(/-?\n/, (m) => (m === '\n' ? ' ' : m))).replace(/[&<]/g, (c) => (c === '&' ? '&amp;' : '&lt;'));
        parts.push(`<span style="left:${((x0 / page.width!) * 100).toFixed(3)}%;top:${((y0 / page.height!) * 100).toFixed(3)}%;font-size:${size.toFixed(3)}cqw;transform:scaleX(${scale.toFixed(4)})">${text}</span>`);
      });
      holder.innerHTML = parts.join('');
    };

    const near = new IntersectionObserver((entries) => entries.forEach((e) => e.isIntersecting && layer(e.target as HTMLElement)), { rootMargin: '100% 0px' });
    sheets.forEach((s) => near.observe(s));

    const input = root.querySelector<HTMLInputElement>('[data-goto] input')!;
    const source = root.querySelector<HTMLAnchorElement>('[data-source]');
    let settled = false;
    const here = new IntersectionObserver(
      (entries) => {
        const top = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (!top || !settled) return;
        const anchor = (top.target as HTMLElement).dataset.unit!;
        if (document.activeElement !== input) input.value = String(anchorNumber(anchor));
        if (source) source.href = source.href.replace(/#page=\d+/, `#page=${anchorNumber(anchor)}`);
        const keep = anchor === target ? location.search : '';
        history.replaceState(null, '', citePath(`${ref}/${anchor}`) + keep);
      },
      { rootMargin: '-25% 0px -70% 0px' },
    );
    sheets.forEach((s) => here.observe(s));

    const go = (anchor: string, record = false) => {
      document.getElementById(anchor)?.scrollIntoView({ block: 'start' });
      if (record) history.replaceState(null, '', citePath(`${ref}/${anchor}`));
    };
    root.querySelector('[data-goto]')!.addEventListener('submit', (event) => {
      event.preventDefault();
      const n = Math.min(Math.max(1, Number(input.value) || 1), sheets.length);
      go(`p${n}`, true);
      input.blur();
    });
    root.querySelectorAll<HTMLAnchorElement>('[data-jump]').forEach((a) =>
      a.addEventListener('click', (event) => {
        event.preventDefault();
        go(a.dataset.jump!, true);
        a.closest('details')!.removeAttribute('open');
      }),
    );

    const land = async () => {
      go(target);
      if (quote) {
        const last = endAnchor ? anchorNumber(endAnchor) : anchorNumber(target);
        let first: HTMLElement | null = null;
        let found = false;
        // A quote may run across a page break: look for it on each page of the range.
        for (let n = anchorNumber(target); n <= last; n++) {
          const page = await unit(`p${n}`);
          const ranges = page.text ? findQuote(page.text, quote) : null;
          const pieces = ranges ?? (last > anchorNumber(target) && page.text ? somePieces(page.text, quote) : null);
          if (!pieces) continue;
          found = found || !!ranges || last > anchorNumber(target);
          const sheet = document.getElementById(`p${n}`)!;
          for (const [s, e] of pieces) {
            for (const r of highlightRects(page, s, e)) {
              const mark = document.createElement('div');
              mark.className = 'hl';
              mark.style.cssText = `left:${r.left}%;top:${r.top}%;width:${r.width}%;height:${r.height}%`;
              sheet.append(mark);
              first ??= mark;
            }
          }
        }
        if (found) {
          say('verified', `On ${anchorLabel(endAnchor ? `${target}-${endAnchor}` : target)}`);
          first?.scrollIntoView({ block: 'center' });
        } else {
          say('rejected', `Not on ${anchorLabel(target)}`, checkLink());
          remote();
        }
      }
      setTimeout(() => (settled = true), 400);
    };
    land();
  }

  // ---- text: mark the target block and the quote inside it
  if (mode === 'text') {
    const block = document.getElementById(target);
    if (block) {
      block.dataset.target = '';
      block.scrollIntoView({ block: quote ? 'center' : 'start' });
      if (!quote) document.fonts.ready.then(() => block.scrollIntoView({ block: 'start' }));
      if (quote) {
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
          const mark = block.querySelector('mark')!;
          mark.scrollIntoView({ block: 'center' });
          document.fonts.ready.then(() => mark.scrollIntoView({ block: 'center' }));   // text reflows when the fonts arrive
        } else {
          say('rejected', `Not in ${anchorLabel(target)}`, checkLink());
          remote();
        }
      }
    }
  }

  if (mode === 'source' && quote) remote(true);

  // Ask the checker for the real verdict: where the words are, or the nearest wording.
  async function remote(only = false) {
    try {
      const response = await fetch(`${API_BASE}/api/verify`, {
        method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ quote, cite: `${ref}/${target}` }),
      });
      if (!response.ok) return;
      const check = (await response.json()) as QuoteCheck;
      const where = check.locations[0];
      if (check.passed) say('verified', `On ${anchorLabel(target)}`, '<span class="muted">checked against our copy</span>');
      else if (check.verdict === 'elsewhere' && where) say('rejected', `Not on ${anchorLabel(target)}`, `<a class="link" href="${citePath(where.cite, quote)}">It is on ${anchorLabel(where.anchor)}</a>`);
      else if (check.verdict === 'near_miss' && where) {
        say('rejected', `Not on ${anchorLabel(target)}`, `<span class="muted">The source says: </span><span class="closest"></span>`);
        status.querySelector('.closest')!.textContent = `“${where.text.replace(/\s+/g, ' ')}”`;
      } else if (only) say('rejected', `Not on ${anchorLabel(target)}`, checkLink());
    } catch {
      /* the checker is a server; reading works without it */
    }
  }

  // ---- copy with citation
  const pop = root.querySelector<HTMLElement>('[data-selpop]')!;
  let picked: { text: string; anchor: string } | null = null;
  const selection = () => {
    const sel = document.getSelection();
    const text = sel?.toString().replace(/-\n/g, '').replace(/\s+/g, ' ').trim() ?? '';
    const holder = sel?.rangeCount ? (sel.getRangeAt(0).startContainer.parentElement?.closest<HTMLElement>('[data-unit]') ?? null) : null;
    if (!sel || sel.isCollapsed || text.length < 3 || !holder || !root.contains(holder)) {
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
    const short = picked.text.length > 300 ? picked.text.slice(0, picked.text.lastIndexOf(' ', 300)) : picked.text;
    const url = location.origin + citePath(cite, short);
    if (act === 'check') {
      location.href = `/check?text=${encodeURIComponent(`"${picked.text}" (${cite})`)}`;
      return;
    }
    const year = doc.published?.slice(0, 4);
    const text = act === 'link' ? url : `“${picked.text}” (${[doc.short.replace(/ \d{4}$/, ''), `“${doc.title}”`, year, anchorLabel(picked.anchor)].filter(Boolean).join(', ')}) ${url}`;
    navigator.clipboard.writeText(text);
    const button = event.target as HTMLElement;
    const was = button.textContent;
    button.textContent = 'Copied';
    setTimeout(() => { button.textContent = was; pop.hidden = true; }, 900);
  });

  document.addEventListener('click', (event) => {
    const button = (event.target as HTMLElement).closest<HTMLElement>('[data-copy]');
    if (button) navigator.clipboard.writeText(button.dataset.copy!);
    const open = root.querySelector<HTMLDetailsElement>('details.contents[open]');
    if (open && !open.contains(event.target as Node)) open.removeAttribute('open');
  });
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

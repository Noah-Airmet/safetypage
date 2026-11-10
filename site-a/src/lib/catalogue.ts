// A shelf's catalogue: one compact row per document. The shelf page prints the newest rows as
// HTML; the rest arrive as /catalogue/<shelf>.json when a visitor filters or asks for more.
// Works in Node and the browser, so the page and the script draw a row the same way.
import { KINDS, formatDate, publisherOf, shortLabel, titleParts } from './cite';
import { pageImageUrl } from './env';
import type { DocumentCard } from './types';

/** [doc id, title, who, publisher, kind, published, read here?, units, paged?, version] */
export type Row = [string, string, string, string, string, string, 0 | 1, number, 0 | 1, string];

export const toRow = (d: DocumentCard): Row => [
  d.doc_id, d.title, d.authors.length ? shortLabel(d).replace(/ \d{4}$/, '') : (d.org ?? ''), publisherOf(d), d.kind,
  d.published ?? '', d.tier === 'open' ? 1 : 0, d.unit_count, d.anchor_kind === 'page' ? 1 : 0, d.version,
];

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);

const glyph = (name: string) => `<svg class="i" aria-hidden="true"><use href="/icons.svg#${name}"></use></svg>`;

/** A list row: the cover, the catalogue entry (title, subtitle, who), then the kind and date. `cloth` is the shelf's. */
export function rowHtml([id, title, who, , kind, published, open, units, paged, version]: Row, cloth: string): string {
  const { main, sub } = titleParts(title);
  const by = [who, `${units.toLocaleString('en')} ${paged ? (units === 1 ? 'page' : 'pages') : units === 1 ? 'paragraph' : 'paragraphs'}`, open ? '' : 'Read at source'].filter(Boolean).join(' · ');
  const cover = open && paged
    ? `<img alt="" loading="lazy" decoding="async" src="${esc(pageImageUrl(`${id}/${version}/p1`, 800))}" onload="this.classList.add('in')">`
    : glyph(open ? 'doc' : 'external');
  return `<a class="frow" href="/d/${esc(id.replace(':', '/'))}"><span class="cv" style="--cloth:${cloth}">${cover}</span><span class="ent"><span class="t name">${esc(main)}${sub ? `<span class="sub">: ${esc(sub)}</span>` : ''}</span><span class="a">${esc(by)}</span></span><span class="x">${esc([KINDS[kind] ?? kind, formatDate(published).replace(/^\d+ /, '')].filter(Boolean).join(' · '))}</span></a>`;
}

export interface Filter { q: string; publisher: string; kind: string; year: string; read: string }
export function matches(row: Row, f: Filter): boolean {
  if (f.publisher && row[3] !== f.publisher) return false;
  if (f.kind && row[4] !== f.kind) return false;
  if (f.year && !row[5].startsWith(f.year)) return false;
  if (f.read && (f.read === 'here') !== !!row[6]) return false;
  if (f.q) {
    const hay = (row[1] + ' ' + row[2]).toLowerCase();
    return f.q.toLowerCase().split(/\s+/).every((w) => hay.includes(w));
  }
  return true;
}

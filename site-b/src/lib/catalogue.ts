// A shelf's catalogue: one compact row per document. The shelf page prints the newest rows as
// HTML; the rest arrive as /catalogue/<shelf>.json when a visitor filters or asks for more.
// Works in Node and the browser, so the page and the script draw a row the same way.
import { KINDS, formatDate, publisherOf, shortLabel } from './cite';
import type { DocumentCard } from './types';

/** [doc id, title, who, publisher, kind, published, read here?, units, paged?] */
export type Row = [string, string, string, string, string, string, 0 | 1, number, 0 | 1];

export const toRow = (d: DocumentCard): Row => [
  d.doc_id, d.title, d.authors.length ? shortLabel(d).replace(/ \d{4}$/, '') : (d.org ?? ''), publisherOf(d), d.kind,
  d.published ?? '', d.tier === 'open' ? 1 : 0, d.unit_count, d.anchor_kind === 'page' ? 1 : 0,
];

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);

export function rowHtml([id, title, who, , kind, published, open, units, paged]: Row): string {
  const size = `${units.toLocaleString('en')} ${paged ? (units === 1 ? 'page' : 'pages') : units === 1 ? 'paragraph' : 'paragraphs'}`;
  return `<a href="/d/${esc(id.replace(':', '/'))}"><span class="name">${esc(title)}</span><span class="c kind">${esc(KINDS[kind] ?? kind)}</span><span class="c date">${esc(formatDate(published).replace(/^\d+ /, ''))}</span><span class="c size">${esc(size)}</span><span class="c read"${open ? ' data-here' : ''}>${open ? 'Read here' : 'At source'}</span>${who ? `<span class="sub">${esc(who)}</span>` : ''}</a>`;
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

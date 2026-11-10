// Finding a quote in a page's text, for the highlight. This places words on a page; it is not
// the verdict. Verdicts come from the core library's verify_quote, through the API.
// Same idea as safetypage.quote: match on a skeleton of case-folded letters and digits that
// keeps each character's source offset, whole words only, fragments in order.
import type { UnitText } from './types';

interface Skeleton { chars: string; offsets: number[] }

const isWord = (ch: string) => /[\p{L}\p{N}]/u.test(ch);

export function skeleton(text: string): Skeleton {
  let chars = '';
  const offsets: number[] = [];
  for (let i = 0; i < text.length; ) {
    const code = text.codePointAt(i)!;
    const ch = String.fromCodePoint(code);
    const folded = ch.normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase();
    for (const f of folded) {
      if (isWord(f)) { chars += f; offsets.push(i); }
    }
    i += ch.length;
  }
  return { chars, offsets };
}

/** The quote's fragments: split at ellipses and bracketed editorial insertions. */
export function fragments(quote: string): string[] {
  return quote.split(/\.{3,}|…|\[[^\]]{2,}\]/).map((s) => s.trim()).filter((s) => skeleton(s).chars.length > 0);
}

/** Character ranges [start, end) in `text` where the quote's fragments sit, in order; null if any is missing. */
export function findQuote(text: string, quote: string): [number, number][] | null {
  const source = skeleton(text);
  const ranges: [number, number][] = [];
  let from = 0;
  for (const fragment of fragments(quote)) {
    const needle = skeleton(fragment).chars;
    let at = source.chars.indexOf(needle, from);
    while (at !== -1) {
      const start = source.offsets[at];
      const last = source.offsets[at + needle.length - 1];
      const before = start > 0 ? text[start - 1] : ' ';
      const after = last + 1 < text.length ? text[last + 1] : ' ';
      if (!isWord(before) && !isWord(after)) {
        ranges.push([start, last + 1]);
        from = at + needle.length;
        break;
      }
      at = source.chars.indexOf(needle, at + 1);
    }
    if (at === -1) return null;
  }
  return ranges.length ? ranges : null;
}

export interface Rect { left: number; top: number; width: number; height: number }

/** Highlight boxes for a character range of a page, one per line, as percentages of the page. */
export function highlightRects(unit: UnitText, start: number, end: number): Rect[] {
  if (!unit.words || !unit.width || !unit.height) return [];
  const lines: { x0: number; y0: number; x1: number; y1: number }[] = [];
  for (const [s, e, x0, y0, x1, y1] of unit.words) {
    if (e <= start || s >= end) continue;
    const line = lines[lines.length - 1];
    const mid = (y0 + y1) / 2;
    if (line && mid > line.y0 && mid < line.y1 && x0 >= line.x0) {
      line.x1 = Math.max(line.x1, x1); line.y0 = Math.min(line.y0, y0); line.y1 = Math.max(line.y1, y1);
    } else lines.push({ x0, y0, x1, y1 });
  }
  const pad = 1.5;
  return lines.map((l) => ({
    left: ((l.x0 - pad) / unit.width!) * 100,
    top: ((l.y0 - pad / 2) / unit.height!) * 100,
    width: ((l.x1 - l.x0 + 2 * pad) / unit.width!) * 100,
    height: ((l.y1 - l.y0 + pad) / unit.height!) * 100,
  }));
}

/** A spine span clipped to one unit, as offsets into that unit's text. */
export function spanInUnit(unit: UnitText, span: [number, number]): [number, number] | null {
  if (unit.spine_start == null || unit.spine_end == null) return null;
  const start = Math.max(span[0], unit.spine_start) - unit.spine_start;
  const end = Math.min(span[1], unit.spine_end) - unit.spine_start;
  return end > start ? [start, end] : null;
}

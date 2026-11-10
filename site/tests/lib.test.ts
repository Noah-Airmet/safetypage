import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import { citePath, parseCite, anchorLabel, sourceLink } from '../src/lib/cite';
import { findQuote, highlightRects, spanInUnit } from '../src/lib/quote';
import { answerSegments, stateAt, holdAfter } from '../src/lib/replay';
import type { Trace, UnitText } from '../src/lib/types';

describe('cite', () => {
  it('parses cite strings and makes reader paths', () => {
    expect(parseCite('arxiv:2305.15324/v2/p6')).toEqual({ ns: 'arxiv', local: '2305.15324', version: 'v2', anchor: 'p6' });
    expect(parseCite('arxiv:2305.15324')?.version).toBeUndefined();
    expect(parseCite('not a cite')).toBeNull();
    expect(citePath('arxiv:2305.15324/v2/p6', 'main tools')).toBe('/d/arxiv/2305.15324/v2/p6?q=main%20tools');
    expect(anchorLabel('p6-p8')).toBe('pp. 6–8');
    expect(sourceLink('https://x.org/a.pdf', 'p6', true)).toBe('https://x.org/a.pdf#page=6');
  });
});

describe('findQuote', () => {
  const page = 'Model evaluation is\nnot the only tool avail-\nable for AI risk assessment. They are unable to refuse 3.5% of cases.';
  it('finds words across line breaks, hyphenation and case', () => {
    const [[s, e]] = findQuote(page, 'NOT the only tool available for AI risk assessment')!;
    expect(page.slice(s, e)).toBe('not the only tool avail-\nable for AI risk assessment');
  });
  it('does not skip words or match inside a word', () => {
    expect(findQuote(page, 'Model evaluation is the only tool')).toBeNull();
    expect(findQuote(page, 'able to refuse')).toBeNull();
  });
  it('finds fragments around an ellipsis, in order', () => {
    expect(findQuote(page, 'Model evaluation is … for AI risk assessment')).toHaveLength(2);
    expect(findQuote(page, 'for AI risk assessment … Model evaluation is')).toBeNull();
  });
});

describe('highlight', () => {
  const unit = { width: 100, height: 100, spine_start: 50, spine_end: 70, text: 'one two three',
    words: [[0, 3, 10, 10, 20, 14], [4, 7, 22, 10, 30, 14], [8, 13, 10, 16, 24, 20]] } as unknown as UnitText;
  it('draws one box per line', () => {
    expect(highlightRects(unit, 0, 13)).toHaveLength(2);
    expect(highlightRects(unit, 4, 7)).toHaveLength(1);
  });
  it('clips a spine span to the unit', () => {
    expect(spanInUnit(unit, [40, 60])).toEqual([0, 10]);
    expect(spanInUnit(unit, [80, 90])).toBeNull();
  });
});

describe('replay', () => {
  // A real CitationBench trace: four verified citations and two rejected.
  const trace = JSON.parse(fs.readFileSync('../citationbench/traces/cc-haiku-5-5-4e1c63/pc-4bd058594c.1.json', 'utf8')) as Trace;
  const last = trace.events.length - 1;
  it('ends on the tally the trace records', () => {
    const want = { verified: 0, cited: 0, rejected: 0 };
    for (const c of trace.answer!.citations) want[c.state]++;
    expect(stateAt(trace.events, last).tally).toEqual(want);
  });
  it('is a pure function of the step: scrubbing back gives the earlier state', () => {
    const early = JSON.stringify([...stateAt(trace.events, 3).hits]);
    stateAt(trace.events, last);
    expect(JSON.stringify([...stateAt(trace.events, 3).hits])).toBe(early);
    expect(stateAt(trace.events, 0).answer).toEqual([]);
  });
  it('shows a citation as pending until it is checked, then rejected on the page', () => {
    const cite = trace.events.findIndex((e) => e.kind === 'cite');
    expect(stateAt(trace.events, cite).answer.at(-1)).toMatchObject({ state: 'pending' });
    const rejected = trace.events.findIndex((e) => e.kind === 'verify' && e.state === 'rejected');
    // The run never opened the page: the cited paragraph is shown, with nothing outlined.
    expect(stateAt(trace.events, rejected).focus).toMatchObject({ cite: 'us-eop:ai-bill-of-rights/r1/b4', span: null });
    expect(holdAfter(trace.events, rejected)).toBeGreaterThanOrEqual(1400);
  });
  it('puts each citation where the answer wrote it, and keeps every word of the answer', () => {
    const segments = answerSegments(stateAt(trace.events, last).answer);
    const cites = segments.filter((s) => typeof s !== 'string');
    expect(cites).toHaveLength(trace.answer!.citations.length);
    const text = segments.filter((s) => typeof s === 'string').join('');
    expect(text).not.toContain('(arxiv:2306.11698/v5/p74)');
    expect(text).toContain('The count in the sentence is wrong');
    expect(typeof segments[0]).toBe('string');
  });
  it('places a citation with no cite string in the text where it arrived', () => {
    const parts = stateAt([
      { seq: 0, t_ms: 0, kind: 'answer', delta: 'One. ' },
      { seq: 1, t_ms: 1, kind: 'cite', cite_id: 'c1', cite: 'a:b/v1/p1' },
      { seq: 2, t_ms: 2, kind: 'answer', delta: 'Two.' },
    ], 2).answer;
    expect(answerSegments(parts).map((s) => (typeof s === 'string' ? s : s.cite_id))).toEqual(['One. ', 'c1', 'Two.']);
  });
});

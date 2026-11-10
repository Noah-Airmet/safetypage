// The replay's state at a step is a pure function of the events up to it, so scrubbing
// backwards costs nothing (docs/ARCHITECTURE.md section 10).
import type { CitationState, Trace, TraceEvent, Verdict } from './types';

export interface AnswerCite {
  type: 'cite'; cite_id: string; cite: string; quote: string | null;
  state: CitationState | 'pending'; reason: string | null; verdict: Verdict | null;
  span: [number, number] | null; closest: string | null;
}
export type AnswerPart = { type: 'text'; text: string } | AnswerCite;

export interface Focus { cite: string; span: [number, number] | null; kind: 'found' | 'reject' | null; cited?: string }

export interface ReplayState {
  hits: Map<string, number>;   // cite -> strongest relative score any search gave it, 0..1
  fresh: Set<string>;          // what the current step returned
  read: Set<string>;           // fetched
  answer: AnswerPart[];
  focus: Focus | null;
  tally: Record<CitationState, number>;
}

export function focusFor(c: AnswerCite): Focus {
  if (c.state === 'verified') return { cite: c.cite, span: c.span, kind: 'found' };
  if (c.state === 'rejected' && c.closest) return { cite: c.closest, span: c.span, kind: 'reject', cited: c.cite };
  return { cite: c.cite, span: null, kind: null };
}

export function stateAt(events: TraceEvent[], step: number): ReplayState {
  const state: ReplayState = { hits: new Map(), fresh: new Set(), read: new Set(), answer: [], focus: null, tally: { verified: 0, cited: 0, rejected: 0 } };
  const cites = new Map<string, AnswerCite>();
  for (let i = 0; i <= step && i < events.length; i++) {
    const e = events[i];
    const current = i === step;
    if (e.kind === 'tool') {
      const top = Math.max(1e-9, ...e.returned.map((r) => r.score ?? 0));
      for (const r of e.returned) {
        if (e.tool === 'search') state.hits.set(r.cite, Math.max(state.hits.get(r.cite) ?? 0, r.score ? r.score / top : 1));
        else state.read.add(r.cite);
        if (current) state.fresh.add(r.cite);
      }
      if (e.tool !== 'search' && e.returned[0]) state.focus = { cite: e.returned[0].cite, span: null, kind: null };
    } else if (e.kind === 'answer') {
      const last = state.answer[state.answer.length - 1];
      if (last?.type === 'text') last.text += e.delta;
      else state.answer.push({ type: 'text', text: e.delta });
    } else if (e.kind === 'cite') {
      const part: AnswerCite = { type: 'cite', cite_id: e.cite_id, cite: e.cite, quote: e.quote ?? null, state: 'pending', reason: null, verdict: null, span: null, closest: null };
      cites.set(e.cite_id, part);
      state.answer.push(part);
      state.focus = focusFor(part);
    } else if (e.kind === 'verify') {
      const part = cites.get(e.cite_id);
      if (!part) continue;
      Object.assign(part, { state: e.state, reason: e.reason ?? null, verdict: e.quote_verdict ?? null, span: e.span ?? null, closest: e.closest ?? null });
      state.tally[e.state]++;
      state.focus = focusFor(part);
    }
  }
  return state;
}

/** How long to hold on a step before the next, in ms at 1×: the recorded gap, with waits cut short. */
export function holdAfter(events: TraceEvent[], step: number): number {
  const next = events[step + 1];
  if (!next) return 0;
  const gap = next.t_ms - events[step].t_ms;
  const kind = events[step].kind;
  const floor = kind === 'verify' ? 1400 : kind === 'answer' ? 250 : 700;
  return Math.min(Math.max(gap, floor), 1800);
}

export const REASONS: Record<string, string> = {
  unresolved: 'No such page in the library',
  unseen: 'The run never opened this page',
  quote_elsewhere: 'The words are on another page',
  quote_near_miss: 'The page says something else',
  quote_not_found: 'The words are not in the document',
  unsupported: 'A judge found the page does not support this',
};

export const finalTally = (trace: Trace) => stateAt(trace.events, trace.events.length - 1).tally;

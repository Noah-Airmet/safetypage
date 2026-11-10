// Quote checks that have a permalink and a preview card: the landing page's two examples and
// every quoted citation in a trace. A check made in the checker is not stored (no write path).
import { createHash } from 'node:crypto';
import { allTraces, content } from './data';
import type { QuoteCheck } from './types';

export interface StoredCheck { id: string; quote: string; cite: string; passed: boolean; verdict: string; shown: string; span: [number, number] | null }

export const checkId = (cite: string, quote: string) => createHash('sha256').update(`${cite}\n${quote}`).digest('hex').slice(0, 10);

export function allChecks(): StoredCheck[] {
  const out = new Map<string, StoredCheck>();
  const add = (c: Omit<StoredCheck, 'id'>) => out.set(checkId(c.cite, c.quote), { id: checkId(c.cite, c.quote), ...c });
  const landing = content<{ verified: QuoteCheck; rejected: QuoteCheck }>('landing.json');
  for (const check of [landing.verified, landing.rejected]) {
    const where = check.locations[0];
    add({ quote: check.quote, cite: check.cite!, passed: check.passed, verdict: check.verdict, shown: where?.cite ?? check.cite!, span: where ? [where.spine_start, where.spine_end] : null });
  }
  for (const trace of allTraces()) {
    for (const e of trace.events) {
      if (e.kind !== 'verify' || !e.quote_verdict) continue;
      const cite = trace.events.find((c) => c.kind === 'cite' && c.cite_id === e.cite_id);
      if (cite?.kind !== 'cite' || !cite.quote) continue;
      add({ quote: cite.quote, cite: cite.cite, passed: e.state === 'verified', verdict: e.quote_verdict, shown: e.closest ?? cite.cite, span: e.span ?? null });
    }
  }
  return [...out.values()];
}

// The wire models the site reads, as in schemas/*.schema.json. Only the fields used here.

export type Tier = 'open' | 'link_only';
export type Verdict = 'exact' | 'normalized' | 'elsewhere' | 'near_miss' | 'not_found';
export type CitationState = 'verified' | 'cited' | 'rejected';

export interface OutlineItem { level: number; title: string; anchor: string; cite: string }
export interface VersionSummary {
  version: string; published: string | null; observed_at: string; tier: Tier; licence: string; latest: boolean;
}
export interface LicenceEvidence { kind: string; url: string; quote: string; observed_at: string }
export interface DocumentCard {
  doc_id: string; title: string; authors: string[]; org: string | null; kind: string;
  collection: string | null; published: string | null; source_url: string; version: string;
  versions: VersionSummary[]; tier: Tier; licence: string; anchor_kind: 'page' | 'block';
  fidelity: string; unit_count: number; outline: OutlineItem[];
  licence_evidence?: LicenceEvidence | null; summary?: string | null;
}
export type Word = [number, number, number, number, number, number];
export interface UnitText {
  cite: string; anchor: string; anchor_label: string; tier: Tier; text: string | null;
  excerpt?: string | null; source_url: string; kind?: string | null; level?: number | null;
  spine_start?: number | null; spine_end?: number | null;
  width?: number | null; height?: number | null; words?: Word[] | null;
}
export interface QuoteLocation { cite: string; anchor: string; spine_start: number; spine_end: number; text: string }
export interface QuoteDiff { op: string; quote: string; source: string }
export interface QuoteSegment {
  quote: string; verdict: Verdict; location: QuoteLocation | null; diff: QuoteDiff[]; similarity: number | null;
}
export interface QuoteCheck {
  quote: string; cite: string | null; verdict: Verdict; passed: boolean; reason: string; tier: Tier;
  fidelity: string; locations: QuoteLocation[]; segments: QuoteSegment[]; ambiguous: boolean;
  other_locations: QuoteLocation[];
}
export interface QuoteAudit { quote: string; check: QuoteCheck | null; error: string | null }
export interface CitationAudit {
  raw: string; cite: string; resolves: boolean; error: string | null; tier: Tier | null; quotes: QuoteAudit[];
}
export interface AnswerAudit {
  citations: CitationAudit[]; unattached_quotes: string[]; citation_count: number; resolved_count: number;
  quote_count: number; passed_count: number; summary: string; support_checked: boolean;
}
export interface Hit {
  cite: string; doc_id: string; version: string; anchor: string; anchor_label: string; doc_title: string;
  org: string | null; kind: string; date: string | null; tier: Tier; licence: string; score: number;
  snippet: string; match_spans: [number, number][]; source_url: string;
}
export interface SearchResponse {
  query: string; interpretation: string; arm: string; snapshot: string; total: number; hits: Hit[];
}

export type TraceEvent =
  | { seq: number; t_ms: number; kind: 'think'; text: string }
  | {
      seq: number; t_ms: number; kind: 'tool'; call_id: string; tool: string; args: Record<string, unknown>;
      returned: { cite: string; score?: number | null }[]; total?: number | null; verdict?: Verdict | null;
      found_at?: string | null; error?: string | null; latency_ms?: number | null;
    }
  | { seq: number; t_ms: number; kind: 'answer'; delta: string }
  | { seq: number; t_ms: number; kind: 'cite'; cite_id: string; cite: string; quote?: string | null }
  | {
      seq: number; t_ms: number; kind: 'verify'; cite_id: string; state: CitationState; reason?: string | null;
      resolves: boolean; seen: boolean; quote_verdict?: Verdict | null; span?: [number, number] | null;
      closest?: string | null; judgement?: { judge: string; label: string; agreement?: number | null } | null;
    };
export interface Trace {
  schema: string;
  header: {
    trace_id: string; run_id?: string | null; sample_id?: string | null; question: string; model: string;
    solver?: string | null; snapshot: string; arm: string; started_at: string;
    usage?: { input_tokens?: number; output_tokens?: number; cost_usd?: number | null };
  };
  events: TraceEvent[];
  answer?: { text: string; citations: { cite_id: string; cite: string; quote?: string | null; state: CitationState; reason?: string | null }[] } | null;
  scores?: Record<string, number>;
}

// CitationBench: schemas/citationbench/run-result.schema.json
export interface Estimate { mean: number | null; ci_low: number | null; ci_high: number | null; n: number }
export interface RunResult {
  schema: string; run_id: string; name: string; created_at: string; model: string; solver: string; surface: string;
  snapshot: string; questions: { file?: string; n?: number }; epochs: number; samples: number; errors: number;
  complete?: boolean; judge: { id: string; agreement: Record<string, unknown> | null } | null;
  measures: Record<string, Estimate>; by_method: Record<string, Record<string, Estimate>>;
  cost: { billing?: string; priced: boolean; price_table: string | null; total_usd: number | null; per_correct_usd: Estimate };
  config: Record<string, unknown>;
}

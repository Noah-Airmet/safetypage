// Build-time reading of a snapshot's public/ tree (docs/ARCHITECTURE.md section 7).
// SAFETYPAGE_PUBLIC_DIR points at it; the default is the fixture tree that `npm run data` writes
// (site/.data). The tree is never copied into the build: the host serves it at /data.
import fs from 'node:fs';
import path from 'node:path';
import type { DocumentCard, RunResult, Trace, UnitText } from './types';
import { publisherOf } from './cite';

export const PUBLIC_DIR = process.env.SAFETYPAGE_PUBLIC_DIR ?? path.resolve('.data');
// CitationBench's output (citationbench/README.md): one results file per run, one trace per sample.
const RESULTS_DIR = process.env.SAFETYPAGE_RESULTS_DIR ?? path.resolve('../citationbench/results');
const TRACES_DIR = process.env.SAFETYPAGE_TRACES_DIR ?? path.resolve('../citationbench/traces');

const readJson = <T>(file: string): T => JSON.parse(fs.readFileSync(file, 'utf8')) as T;

let cards: DocumentCard[] | undefined;
/** Every document card, newest first. 14,000 small files read once per build (about two seconds). */
export function allDocs(): DocumentCard[] {
  if (cards) return cards;
  const root = path.join(PUBLIC_DIR, 'docs');
  if (!fs.existsSync(root)) throw new Error(`No library data at ${PUBLIC_DIR}. Run "npm run data" or set SAFETYPAGE_PUBLIC_DIR.`);
  cards = fs.readdirSync(root).flatMap((ns) =>
    fs.readdirSync(path.join(root, ns)).filter((f) => f.endsWith('.json')).map((f) => {
      const card = readJson<DocumentCard>(path.join(root, ns, f));
      card.authors = card.authors.map((a) => a.replace(/\s+/g, ' ').trim());   // some sources wrap a name over two lines
      return card;
    }),
  );
  cards.sort((a, b) => (b.published ?? '').localeCompare(a.published ?? '') || a.doc_id.localeCompare(b.doc_id));
  return cards;
}

let byId: Map<string, DocumentCard> | undefined;
export const getDoc = (docId: string) => (byId ??= new Map(allDocs().map((d) => [d.doc_id, d]))).get(docId);

/** Whether a version's text is published under this anchor (open versions only). */
export const hasUnit = (docId: string, version: string, anchor: string) =>
  fs.existsSync(path.join(PUBLIC_DIR, 'text', ...docId.split(':'), version, `${anchor}.json`));

export interface LibraryCounts { snapshot: string | null; built: string | null; documents: number; units: number; pages: number; paragraphs: number; open: number }
let counts: LibraryCounts | undefined;
/** The library's numbers: from the cards, and the snapshot's id and date from its manifest when there is one. */
export function libraryCounts(): LibraryCounts {
  if (counts) return counts;
  const docs = allDocs();
  const sum = (kind: string) => docs.filter((d) => d.anchor_kind === kind).reduce((n, d) => n + d.unit_count, 0);
  const file = path.join(PUBLIC_DIR, '..', 'manifest.json');
  const manifest = fs.existsSync(file) ? readJson<{ snapshot_id: string; created_at: string }>(file) : null;
  const pages = sum('page'), paragraphs = sum('block');
  counts = {
    snapshot: manifest?.snapshot_id ?? null, built: manifest?.created_at ?? null, documents: docs.length,
    units: pages + paragraphs, pages, paragraphs, open: docs.filter((d) => d.tier === 'open').length,
  };
  return counts;
}

export interface Shelf { id: string; docs: DocumentCard[]; publishers: [string, number][]; kinds: [string, number][]; years: [string, number][] }
const tally = (values: string[]): [string, number][] => {
  const n = new Map<string, number>();
  for (const v of values) n.set(v, (n.get(v) ?? 0) + 1);
  return [...n].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
};
let shelves: Shelf[] | undefined;
/** The documents by shelf (a document's `collection`), each with the counts its filters show. */
export function allShelves(): Shelf[] {
  if (shelves) return shelves;
  const groups = new Map<string, DocumentCard[]>();
  for (const doc of allDocs()) {
    const id = doc.collection ?? 'other';
    if (!groups.has(id)) groups.set(id, []);
    groups.get(id)!.push(doc);
  }
  shelves = [...groups].map(([id, docs]) => ({
    id, docs, publishers: tally(docs.map(publisherOf)), kinds: tally(docs.map((d) => d.kind)),
    years: tally(docs.map((d) => d.published?.slice(0, 4) ?? '')).filter(([y]) => y).sort((a, b) => b[0].localeCompare(a[0])),
  }));
  return shelves;
}

const unitCache = new Map<string, UnitText[]>();
/** A version's units in reading order. Empty for a link-only version: its text is not published. */
export function unitsOf(docId: string, version: string): UnitText[] {
  const key = `${docId}/${version}`;
  const hit = unitCache.get(key);
  if (hit) return hit;
  const [ns, local] = docId.split(':');
  const dir = path.join(PUBLIC_DIR, 'text', ns, local, version);
  const units = fs.existsSync(dir)
    ? fs.readdirSync(dir).filter((f) => /^[pb]\d+\.json$/.test(f)).map((f) => readJson<UnitText>(path.join(dir, f)))
    : [];
  units.sort((a, b) => (a.spine_start ?? 0) - (b.spine_start ?? 0));
  unitCache.set(key, units);
  return units;
}

export const getUnit = (cite: string) => {
  const [docId, version, anchor] = cite.split('/');
  return unitsOf(docId, version).find((u) => u.anchor === anchor);
};

let traces: Trace[] | undefined;
export function allTraces(): Trace[] {
  if (traces) return traces;
  const files = fs.existsSync(TRACES_DIR) ? (fs.readdirSync(TRACES_DIR, { recursive: true }) as string[]).filter((f) => f.endsWith('.json')).sort() : [];
  traces = files.map((f) => readJson<Trace>(path.join(TRACES_DIR, f)));
  return traces;
}

/** The snapshot a run read, when it is not the one this site is built on (a build with no manifest is the test corpus the runs used). */
export const otherSnapshot = (trace: Trace): string | undefined => {
  const here = libraryCounts().snapshot;
  return here && trace.header.snapshot !== here ? trace.header.snapshot : undefined;
};

export function allRuns(): RunResult[] {
  if (!fs.existsSync(RESULTS_DIR)) return [];
  return fs.readdirSync(RESULTS_DIR).filter((f) => f.endsWith('.json')).map((f) => readJson<RunResult>(path.join(RESULTS_DIR, f)))
    .sort((a, b) => (b.measures.correct?.mean ?? 0) - (a.measures.correct?.mean ?? 0) || a.run_id.localeCompare(b.run_id));
}

/** The replay to show first: a real run with a rejected citation, the more verified ones beside it the better. */
export function featuredTrace(): Trace | undefined {
  const score = (t: Trace) => {
    const c = t.answer?.citations ?? [];
    return (c.some((x) => x.state === 'rejected') ? 100 : 0) + c.filter((x) => x.state === 'verified').length;
  };
  return [...allTraces()].sort((a, b) => score(b) - score(a))[0];
}

// Build-time reading of a snapshot's public/ tree (docs/ARCHITECTURE.md section 7).
// OTP_PUBLIC_DIR points at it; the default is the fixture tree that `npm run data` writes.
import fs from 'node:fs';
import path from 'node:path';
import type { DocumentCard, Trace, UnitText } from './types';

export const PUBLIC_DIR = process.env.OTP_PUBLIC_DIR ?? path.resolve('public/data');
const CONTENT = path.resolve('src/content');
const TRACES_DIR = process.env.OTP_TRACES_DIR ?? path.join(CONTENT, 'traces');

const readJson = <T>(file: string): T => JSON.parse(fs.readFileSync(file, 'utf8')) as T;

let cards: DocumentCard[] | undefined;
export function allDocs(): DocumentCard[] {
  if (cards) return cards;
  const root = path.join(PUBLIC_DIR, 'docs');
  if (!fs.existsSync(root)) throw new Error(`No library data at ${PUBLIC_DIR}. Run "npm run data" or set OTP_PUBLIC_DIR.`);
  cards = fs.readdirSync(root).flatMap((ns) =>
    fs.readdirSync(path.join(root, ns)).filter((f) => f.endsWith('.json')).map((f) => readJson<DocumentCard>(path.join(root, ns, f))),
  );
  cards.sort((a, b) => (b.published ?? '').localeCompare(a.published ?? '') || a.doc_id.localeCompare(b.doc_id));
  return cards;
}

export const getDoc = (docId: string) => allDocs().find((d) => d.doc_id === docId);

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

export function allTraces(): Trace[] {
  if (!fs.existsSync(TRACES_DIR)) return [];
  return fs.readdirSync(TRACES_DIR).filter((f) => f.endsWith('.json')).map((f) => readJson<Trace>(path.join(TRACES_DIR, f)));
}

export const content = <T>(name: string): T => readJson<T>(path.join(CONTENT, name));
export const contentFiles = (dir: string) =>
  fs.existsSync(path.join(CONTENT, dir)) ? fs.readdirSync(path.join(CONTENT, dir)).filter((f) => f.endsWith('.json')) : [];

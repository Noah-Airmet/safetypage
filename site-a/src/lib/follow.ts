// "Follow one evaluation across labs": a saved search over the labs' system and model cards,
// laid out by lab and date. Nothing here is curated: each topic is the queries below, run
// against the server when the site is built, and every row is a search hit.
import { api } from './api';
import { allDocs } from './data';
import type { DocumentCard, Hit } from './types';

export interface Topic { id: string; name: string; queries: string[]; about: string }
export const TOPICS: Topic[] = [
  { id: 'sabotage', name: 'Sabotage', queries: ['sabotage'], about: 'Whether a model could undermine oversight, evaluations or the work it is given.' },
  { id: 'sycophancy', name: 'Sycophancy', queries: ['sycophancy', 'sycophantic'], about: 'Telling people what they want to hear.' },
  { id: 'welfare', name: 'Model welfare', queries: ['"model welfare"', 'welfare'], about: 'What the labs report about the possible welfare of their models.' },
  { id: 'sandbagging', name: 'Sandbagging', queries: ['sandbagging'], about: 'Deliberately underperforming on an evaluation.' },
  { id: 'alignment-faking', name: 'Alignment faking', queries: ['"alignment faking"'], about: 'Behaving as trained while being watched, and otherwise when not.' },
  { id: 'reward-hacking', name: 'Reward hacking', queries: ['"reward hacking"'], about: 'Passing the test without doing the task.' },
  { id: 'deception', name: 'Deception', queries: ['deception', 'deceptive'], about: 'A model misleading the people it works with or for.' },
  { id: 'evaluation-awareness', name: 'Evaluation awareness', queries: ['"evaluation awareness"'], about: 'A model noticing that it is being tested.' },
];
const KINDS = ['system_card', 'model_card'];

interface DocumentHit { doc_id: string; hit_count: number; top: Hit[] }
interface Listing { documents: DocumentHit[]; next_cursor: string | null }

export interface Found { doc: DocumentCard; count: number; hits: Hit[] }
export interface Lab { org: string; found: Found[]; silent: DocumentCard[] }
export interface Followed { topic: Topic; labs: Lab[]; found: number; cards: number; from: string; to: string }

const byDate = (a: DocumentCard, b: DocumentCard) => (b.published ?? '').localeCompare(a.published ?? '') || a.title.localeCompare(b.title);

export async function follow(topic: Topic): Promise<Followed> {
  const cards = allDocs().filter((d) => KINDS.includes(d.kind));
  const hits = new Map<string, { count: number; hits: Map<string, Hit> }>();
  for (const query of topic.queries) {
    for (const kind of KINDS) {
      for (let cursor: string | null = '0'; cursor !== null; ) {
        const params = new URLSearchParams({ query, kind, mode: 'documents', limit: '25', cursor });
        // The server answers 400 when a filtered search finds nothing; here that is an answer, not an error.
        const page: Listing = await api<Listing>(`/api/search?${params}`).catch((error: Error) => {
          if (/said: 400 .*0 hits/.test(error.message)) return { documents: [], next_cursor: null };
          throw error;
        });
        for (const d of page.documents) {
          const entry = hits.get(d.doc_id) ?? { count: 0, hits: new Map<string, Hit>() };
          entry.count = Math.max(entry.count, d.hit_count);
          for (const h of d.top) entry.hits.set(h.cite, h);
          hits.set(d.doc_id, entry);
        }
        cursor = page.next_cursor;
      }
    }
  }
  const labs = new Map<string, Lab>();
  for (const doc of cards) {
    const org = doc.org ?? 'Other';
    if (!labs.has(org)) labs.set(org, { org, found: [], silent: [] });
    const entry = hits.get(doc.doc_id);
    if (entry) labs.get(org)!.found.push({ doc, count: entry.count, hits: [...entry.hits.values()].sort((a, b) => b.score - a.score).slice(0, 2) });
    else labs.get(org)!.silent.push(doc);
  }
  const list = [...labs.values()].sort((a, b) => b.found.length - a.found.length || b.silent.length - a.silent.length);
  for (const lab of list) { lab.found.sort((a, b) => byDate(a.doc, b.doc)); lab.silent.sort(byDate); }
  const years = cards.map((d) => d.published?.slice(0, 4)).filter((y): y is string => !!y).sort();
  return { topic, labs: list, found: hits.size, cards: cards.length, from: years[0] ?? '', to: years.at(-1) ?? '' };
}

/** The section a hit falls in, from the document's outline. */
export function sectionOf(doc: DocumentCard, hit: Hit): string | null {
  const n = Number(hit.anchor.slice(1));
  const item = [...doc.outline].reverse().find((o) => o.anchor[0] === hit.anchor[0] && Number(o.anchor.slice(1)) <= n);
  return item?.title ?? null;
}

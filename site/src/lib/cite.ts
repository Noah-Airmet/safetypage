// Cite strings and reader URLs: docs/ARCHITECTURE.md sections 2 and 3. Works in Node and the browser.
import type { DocumentCard } from './types';

export interface Cite { ns: string; local: string; version?: string; anchor?: string }

/** `arxiv:2305.15324/v2/p6` (or a ref that stops early) into its parts. */
export function parseCite(cite: string): Cite | null {
  const m = /^([a-z0-9-]+):([A-Za-z0-9._-]+)(?:\/([vr]\d+))?(?:\/([pb]\d+(?:-[pb]?\d+)?))?$/.exec(cite.trim());
  return m ? { ns: m[1], local: m[2], version: m[3], anchor: m[4] } : null;
}

/** The reader path for a cite string: `/d/arxiv/2305.15324/v2/p6`, with the quote as `?q=`. */
export function citePath(cite: string, quote?: string | null): string {
  const path = '/d/' + cite.replace(':', '/');
  return quote ? `${path}?q=${encodeURIComponent(quote)}` : path;
}

export const docIdOf = (cite: string) => cite.split('/')[0];
export const anchorOf = (cite: string) => parseCite(cite)?.anchor ?? '';
export const firstAnchor = (anchor: string) => anchor.split('-')[0];
export const anchorNumber = (anchor: string) => Number(firstAnchor(anchor).slice(1));

/** What a person calls the place when no label came with it. */
export function anchorLabel(anchor: string): string {
  const [a, b] = anchor.split('-');
  const n = a.slice(1);
  if (a[0] === 'p') return b ? `pp. ${n}–${b.replace(/^p/, '')}` : `p. ${n}`;
  return b ? `¶${n}–${b.replace(/^b/, '')}` : `¶${n}`;
}

// arXiv's PDFs are fetched from its bulk mirror; a reader is sent to arxiv.org.
export const atSource = (url: string) => url.replace(/^https:\/\/storage\.googleapis\.com\/arxiv-dataset\/arxiv\/arxiv\/pdf\/\d+\/([^#]+?)\.pdf/, 'https://arxiv.org/pdf/$1');

/** The site a link goes to, as a reader would name it: `anthropic.com`, not `www-cdn.anthropic.com`. */
export const hostOf = (url: string) => new URL(url).hostname.replace(/^(www(-cdn)?|cdn|assets)\./, '');

/** Opens the source at the place: `#page=N` for PDFs; a text fragment for HTML when we have words. */
export function sourceLink(sourceUrl: string, anchor: string | undefined, paged: boolean, words?: string): string {
  const base = sourceUrl.split('#')[0];
  if (!anchor) return base;
  if (paged) return `${base.replace(/^(https:\/\/arxiv\.org)\/abs\//, '$1/pdf/')}#page=${anchorNumber(anchor)}`;
  return words ? `${base}#:~:text=${encodeURIComponent(words)}` : base;
}

/** `Shevlane et al. 2023`, or the organisation when there are no authors. */
export function shortLabel(doc: Pick<DocumentCard, 'authors' | 'org' | 'published' | 'title'>): string {
  const year = doc.published?.slice(0, 4);
  if (doc.authors.length) {
    const surname = doc.authors[0].split(' ').pop();
    const who = doc.authors.length === 1 ? surname : doc.authors.length === 2
      ? `${surname} & ${doc.authors[1].split(' ').pop()}` : `${surname} et al.`;
    return year ? `${who} ${year}` : `${who}`;
  }
  const who = doc.org ?? doc.title;
  return year ? `${who} ${year}` : who;
}

const LICENCES: Record<string, string> = {
  'CC-BY-4.0': 'CC BY 4.0', 'CC-BY-SA-4.0': 'CC BY-SA 4.0', 'CC0-1.0': 'CC0 1.0', 'OGL-UK-3.0': 'OGL v3.0',
  'public-domain': 'Public domain', 'public-domain-us-gov': 'Public domain (US government work)',
  'arXiv-nonexclusive-1.0': 'arXiv non-exclusive licence', 'all-rights-reserved': 'All rights reserved',
  unknown: 'No licence statement found',
};
export const licenceName = (id: string) => LICENCES[id] ?? id;

export const KINDS: Record<string, string> = {
  paper: 'Paper', system_card: 'System card', model_card: 'Model card', framework: 'Framework',
  eval_report: 'Evaluation report', forum_post: 'Forum post', blog: 'Blog post', article: 'Article',
  government: 'Government', book: 'Book',
};

// A paper's publisher is where it was posted; everything else names its organisation.
const SOURCES: Record<string, string> = { arxiv: 'arXiv', acl: 'ACL Anthology', openreview: 'OpenReview', lw: 'LessWrong' };
export const publisherOf = (doc: Pick<DocumentCard, 'org' | 'doc_id'>) => doc.org ?? SOURCES[doc.doc_id.split(':')[0]] ?? 'Other';

// The shelves, in the order the library lists them. A collection not named here still gets a shelf.
export const SHELVES: Record<string, { name: string; about: string }> = {
  labs: { name: 'Lab system cards and frameworks', about: 'System cards, model cards, safety frameworks and policies from the labs that train frontier models.' },
  papers: { name: 'Research papers', about: 'Interpretability, alignment, evaluations and control, from arXiv and the ACL Anthology.' },
  'lab-research-web': { name: 'Lab research on the web', about: 'Research the labs publish as web pages: Transformer Circuits, Distill, alignment blogs.' },
  evaluators: { name: 'Evaluators and safety organisations', about: 'Independent evaluation reports and research: METR, Apollo, Redwood, Epoch, FAR.AI and others.' },
  government: { name: 'Government', about: 'NIST and CAISI, the UK AI Security Institute, the EU AI Office, the International AI Safety Report.' },
  forum: { name: 'Alignment Forum and LessWrong', about: 'Posts from the Alignment Forum, and LessWrong posts on AI safety.' },
  welfare: { name: 'Model welfare', about: 'Research on whether AI systems could be moral patients, and what follows.' },
};
export const shelfName = (id: string) => SHELVES[id]?.name ?? id[0].toUpperCase() + id.slice(1).replace(/[-_]/g, ' ');
export const shelfOrder = (id: string) => { const at = Object.keys(SHELVES).indexOf(id); return at < 0 ? 99 : at; };

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '';
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return m ? `${d ? d + ' ' : ''}${months[m - 1]} ${y}` : String(y);
}

/** A plain-text citation for copying with a quote. */
export function proseCitation(doc: DocumentCard, anchor: string, label?: string): string {
  const who = doc.authors.length ? shortLabel(doc).replace(/ \d{4}$/, '') : doc.org ?? '';
  const year = doc.published?.slice(0, 4);
  return [who, `“${doc.title}”`, year, label ?? anchorLabel(anchor)].filter(Boolean).join(', ');
}

export function bibtex(doc: DocumentCard): string {
  const year = doc.published?.slice(0, 4) ?? '';
  const key = ((doc.authors[0]?.split(' ').pop() ?? doc.org ?? 'doc') + year).toLowerCase().replace(/[^a-z0-9]/g, '');
  const fields = [
    `  title = {${doc.title}}`,
    doc.authors.length ? `  author = {${doc.authors.join(' and ')}}` : `  author = {{${doc.org ?? ''}}}`,
    year && `  year = {${year}}`,
    `  url = {${doc.source_url}}`,
  ].filter(Boolean);
  return `@misc{${key},\n${fields.join(',\n')}\n}`;
}

/** A benchmark question often quotes a sentence in a blockquote: split it into the lead, the quoted sentence and the rest. */
export function questionParts(question: string): { lead: string; quoted: string | null; rest: string } {
  const blocks = question.split(/\n\s*\n/).map((b) => b.trim()).filter(Boolean);
  const at = blocks.findIndex((b) => b.startsWith('>'));
  if (at < 0) return { lead: question.trim(), quoted: null, rest: '' };
  return {
    lead: blocks.slice(0, at).join(' '),
    quoted: blocks[at].replace(/^>\s?/gm, '').replace(/\s+/g, ' '),
    rest: blocks.slice(at + 1).join(' '),
  };
}

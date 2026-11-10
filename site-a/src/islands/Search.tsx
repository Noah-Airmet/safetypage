// The concordance. One result per document: its cover (the page that matched, where the library
// may show it), the catalogue entry, the snippet with its matches washed, and the pages.
import { useEffect, useRef, useState } from 'react';
import { KINDS, citePath, clothOfKind, formatDate, shelfName, titleParts } from '../lib/cite';
import { API_BASE, pageImageUrl } from '../lib/env';
import type { Hit, SearchResponse } from '../lib/types';
import { Icon, Pick } from './shared';

// The filters the server counts for every query, in the order they are shown.
const FILTERS = [
  { key: 'collection', label: 'Shelf', name: shelfName },
  { key: 'kind', label: 'Kind', name: (k: string) => KINDS[k] ?? k },
  { key: 'org', label: 'Publisher', name: (o: string) => o },
  { key: 'tier', label: 'Read', name: (t: string) => (t === 'open' ? 'Read here' : 'Read at source') },
] as const;
type Filters = Partial<Record<(typeof FILTERS)[number]['key'] | 'doc', string>>;
type Result = SearchResponse & { facets?: Record<string, Record<string, number>>; next_cursor?: string | null };
interface Group { first: Hit; hits: Hit[] }

function Snippet({ hit }: { hit: Hit }) {
  const out: React.ReactNode[] = [];
  let at = 0;
  for (const [s, e] of hit.match_spans) {
    if (s < at) continue;
    out.push(hit.snippet.slice(at, s), <mark key={s}>{hit.snippet.slice(s, e)}</mark>);
    at = e;
  }
  out.push(hit.snippet.slice(at));
  return <p className="rs snippet">{out}</p>;
}

/** One row per document, in first-seen order. */
function group(hits: Hit[]): Group[] {
  const byDoc = new Map<string, Group>();
  for (const hit of hits) {
    const g = byDoc.get(hit.doc_id);
    if (g) g.hits.push(hit); else byDoc.set(hit.doc_id, { first: hit, hits: [hit] });
  }
  return [...byDoc.values()];
}

const progress = (w: number | null) => {
  const bar = document.getElementById('progress');
  if (!bar) return;
  if (w === null) { bar.style.setProperty('--w', '1'); setTimeout(() => { bar.classList.remove('on'); bar.style.setProperty('--w', '0'); }, 200); }
  else { bar.classList.add('on'); bar.style.setProperty('--w', String(w)); }
};

export default function Search({ examples }: { examples: [string, string][] }) {
  const [query, setQuery] = useState<string | null>(null);
  const [filters, setFilters] = useState<Filters>({});
  const [result, setResult] = useState<Result | null>(null);
  const [status, setStatus] = useState<'idle' | 'working' | 'down'>('idle');
  const [message, setMessage] = useState('');
  const asked = useRef(0);

  const run = async (q: string, f: Filters, cursor?: string) => {
    const set = Object.fromEntries(Object.entries(f).filter(([, v]) => v)) as Record<string, string>;
    history.replaceState(history.state, '', `/search?${new URLSearchParams({ query: q, ...set })}`);
    if (!q.trim()) { setResult(null); return; }
    setStatus('working');
    progress(0.92);
    const mine = ++asked.current;
    try {
      const params = new URLSearchParams({ query: q, limit: '25', ...set });
      if (cursor) params.set('cursor', cursor);
      const response = await fetch(`${API_BASE}/api/search?${params}`);
      const body = await response.json();
      if (mine !== asked.current) return;
      if (!response.ok) { setMessage(/0 hits/.test(body.error ?? '') ? '' : 'Query not understood'); setResult(/0 hits/.test(body.error ?? '') ? { ...(body as Result), total: 0, hits: [] } : null); }
      else {
        setMessage('');
        setResult((was) => (cursor && was ? { ...body, hits: [...was.hits, ...body.hits] } : body));
      }
      setStatus('idle');
    } catch {
      if (mine === asked.current) setStatus('down');
    }
    progress(null);
  };

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const q = params.get('query') ?? '';
    const f: Filters = {};
    for (const key of [...FILTERS.map((x) => x.key), 'doc'] as const) if (params.get(key)) f[key] = params.get(key)!;
    setQuery(q);
    setFilters(f);
    if (q) run(q, f);
  }, []);

  const pick = (key: keyof Filters, value: string) => {
    const next = { ...filters, [key]: value };
    setFilters(next);
    run(query ?? '', next);
  };
  const phrase = /"([^"]{10,})"/.exec(query ?? '')?.[1];
  if (query === null) return <div className="results" />;

  if (!query.trim()) {
    return (
      <>
        <header className="head"><h1>Search</h1></header>
        <dl className="grammar">{examples.map(([q, what]) => <div key={q} style={{ display: 'contents' }}><dt><a className="exq" href={`/search?query=${encodeURIComponent(q)}`}>{q}</a></dt><dd>{what}</dd></div>)}</dl>
      </>
    );
  }

  const groups = result ? group(result.hits) : [];
  return (
    <>
      <header className="head">
        <h1 className="q">{query}</h1>
        <p className="meta" aria-live="polite">
          {status === 'down' ? 'Search unavailable' : message ? message : result ? (result.total === 0 ? 'No matches' : `${result.total.toLocaleString('en')} ${result.total === 1 ? 'match' : 'matches'}`) : ' '}
        </p>
      </header>
      <div className="facets">
        {status === 'down' && <button type="button" className="btn" onClick={() => run(query, filters)}>Retry</button>}
        {filters.doc && <button type="button" className="btn pick chosen" onClick={() => pick('doc', '')} aria-label={`In ${filters.doc}: search everything`}><span>{filters.doc}</span><Icon name="close" /></button>}
        {result?.facets && FILTERS.map(({ key, label, name }) => {
          const counts = Object.entries(result.facets![key] ?? {});
          if (counts.length < 2 && !filters[key]) return null;
          return <Pick key={key} id={`menu-${key}`} label={label} value={filters[key] ?? ''} options={counts.map(([value, n]) => ({ value, label: name(value), n }))} onPick={(v) => pick(key, v)} />;
        })}
      </div>
      <div className={status === 'working' && result ? 'results refining' : 'results'} aria-busy={status === 'working'}>
        {!result && status === 'working' && (
          <ol className="hits" aria-hidden="true">{[0, 1, 2, 3].map((i) => <li key={i} className="res skel"><span className="cv" /><span className="rb"><i /><i /><i /></span></li>)}</ol>
        )}
        {result && (
          <>
            <ol className="hits">
              {groups.map(({ first, hits }) => {
                const { main, sub } = titleParts(first.doc_title);
                const paged = first.tier === 'open' && first.anchor[0] === 'p';
                return (
                  <li key={first.cite} className="res">
                    <span className="cv" style={{ ['--cloth' as string]: clothOfKind(first.kind, first.doc_id) }}>
                      {paged ? <img alt="" loading="lazy" decoding="async" src={pageImageUrl(first.cite, 800)} onLoad={(e) => e.currentTarget.classList.add('in')} /> : <Icon name={first.tier === 'open' ? 'doc' : 'external'} />}
                    </span>
                    <div className="rb">
                      <a className="rt" href={citePath(first.cite, phrase)}><span className="doc">{main}</span>{sub && <span className="sub">: {sub}</span>}</a>
                      <span className="rm">{[first.org && <b key="o">{first.org}</b>, KINDS[first.kind] ?? first.kind, formatDate(first.date), first.tier === 'open' ? null : 'Read at source'].filter(Boolean).map((part, i) => <span key={i}>{i > 0 && ' · '}{part}</span>)}</span>
                      <Snippet hit={first} />
                      <span className="chips">
                        <a href={citePath(first.cite, phrase)}>{first.anchor_label}</a>
                        {hits.length > 1 && <span className="also">also</span>}
                        {hits.slice(1, 9).map((h) => <a key={h.cite} href={citePath(h.cite, phrase)}>{h.anchor_label.replace(/^(p\. |.*¶)/, (m) => (m.startsWith('p') ? '' : '¶'))}</a>)}
                      </span>
                    </div>
                  </li>
                );
              })}
            </ol>
            {result.total === 0 && <dl className="grammar">{examples.map(([q, what]) => <div key={q} style={{ display: 'contents' }}><dt><a className="exq" href={`/search?query=${encodeURIComponent(q)}`}>{q}</a></dt><dd>{what}</dd></div>)}</dl>}
            {result.next_cursor && <p><button className="btn more" disabled={status === 'working'} onClick={() => run(query, filters, result.next_cursor!)}>More</button></p>}
          </>
        )}
      </div>
    </>
  );
}

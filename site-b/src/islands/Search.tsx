// The concordance. Results are citations: each one opens its page.
import { useEffect, useRef, useState } from 'react';
import { KINDS, anchorLabel, citePath, formatDate, shelfName } from '../lib/cite';
import { API_BASE } from '../lib/env';
import type { Hit, SearchResponse } from '../lib/types';

const EXAMPLES = ['"alignment faking"', 'sabotage evaluation', 'sparse autoencoder*', 'sycophancy NEAR/10 evaluation'];
// The filters the server counts for every query, in the order they are shown.
const FILTERS = [
  { key: 'collection', every: 'Shelf', name: shelfName },
  { key: 'kind', every: 'Kind', name: (k: string) => KINDS[k] ?? k },
  { key: 'org', every: 'Publisher', name: (o: string) => o },
  { key: 'tier', every: 'Read anywhere', name: (t: string) => (t === 'open' ? 'Read here' : 'At source') },
] as const;
type Filters = Partial<Record<(typeof FILTERS)[number]['key'] | 'doc', string>>;
type Result = SearchResponse & { facets?: Record<string, Record<string, number>>; next_cursor?: string | null };

function Snippet({ hit }: { hit: Hit }) {
  const out: React.ReactNode[] = [];
  let at = 0;
  for (const [s, e] of hit.match_spans) {
    if (s < at) continue;
    out.push(hit.snippet.slice(at, s), <mark key={s}>{hit.snippet.slice(s, e)}</mark>);
    at = e;
  }
  out.push(hit.snippet.slice(at));
  return <p className="snippet">{out}</p>;
}

export default function Search() {
  const [query, setQuery] = useState('');
  const [filters, setFilters] = useState<Filters>({});
  const [result, setResult] = useState<Result | null>(null);
  const [status, setStatus] = useState<'idle' | 'working' | 'down'>('idle');
  const [message, setMessage] = useState('');
  const asked = useRef(0);

  const run = async (q: string, f: Filters, cursor?: string) => {
    const set = Object.fromEntries(Object.entries(f).filter(([, v]) => v)) as Record<string, string>;
    history.replaceState(null, '', `/search?${new URLSearchParams({ query: q, ...set })}`);
    if (!q.trim()) { setResult(null); return; }
    setStatus('working');
    const mine = ++asked.current;
    try {
      const params = new URLSearchParams({ query: q, limit: '25', ...set });
      if (cursor) params.set('cursor', cursor);
      const response = await fetch(`${API_BASE}/api/search?${params}`);
      const body = await response.json();
      if (mine !== asked.current) return;
      if (!response.ok) { setMessage(body.error ?? 'Query not understood'); setResult(null); }
      else {
        setMessage('');
        setResult((was) => (cursor && was ? { ...body, hits: [...was.hits, ...body.hits] } : body));
      }
      setStatus('idle');
    } catch {
      setStatus('down');
    }
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

  const submit = (q: string) => { setQuery(q); run(q, filters); };
  const pick = (key: keyof Filters, value: string) => {
    const next = { ...filters, [key]: value };
    setFilters(next);
    run(query, next);
  };
  // The query as the server read it, when that is not what was typed.
  const read = result?.interpretation.split('. ')[0].trim();
  const parsed = read && read !== query.trim() ? read : null;
  // A paragraph's label names its section before its number.
  const section = (hit: Hit) => hit.anchor_label.replace(/\s*(¶|p\. ?)\d+$/, '').trim() || null;
  const phrase = /"([^"]{10,})"/.exec(query)?.[1];

  return (
    <div className="search">
      <form className="ask" role="search" onSubmit={(e) => { e.preventDefault(); submit(query); }}>
        <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Words or &quot;a phrase&quot;" aria-label="Search the library" autoFocus autoComplete="off" />
        <button className="btn btn-primary">Search</button>
      </form>
      <p className="tries">
        {EXAMPLES.map((q) => <button type="button" key={q} onClick={() => submit(q)}>{q}</button>)}
      </p>
      {filters.doc && <p className="within"><span>In <a className="link mono" href={citePath(filters.doc)}>{filters.doc}</a></span><button className="btn" onClick={() => pick('doc', '')}>Search everything</button></p>}

      <div className="results" aria-live="polite" aria-busy={status === 'working'}>
        {status === 'down' && <p className="failed">Search unavailable <button className="btn" onClick={() => run(query, filters)}>Retry</button></p>}
        {message && <p className="failed">{message}</p>}
        {result && (
          <>
            {result.facets && (
              <div className="facets">
                {FILTERS.map(({ key, every, name }) => {
                  const counts = Object.entries(result.facets![key] ?? {});
                  if (counts.length < 2 && !filters[key]) return null;
                  return (
                    <select className="field" key={key} aria-label={every} value={filters[key] ?? ''} onChange={(e) => pick(key, e.target.value)}>
                      <option value="">{every}</option>
                      {counts.map(([value, n]) => <option key={value} value={value}>{name(value)} ({n.toLocaleString('en')})</option>)}
                    </select>
                  );
                })}
              </div>
            )}
            <p className="count"><span>{result.total === 0 ? 'No matches' : `${result.total.toLocaleString('en')} ${result.total === 1 ? 'place' : 'pages and paragraphs'}`}</span>{parsed && <span className="mono">{parsed}</span>}</p>
            <ol>
              {result.hits.map((hit) => (
                <li key={hit.cite}>
                  <a href={citePath(hit.cite, phrase)}>
                    <span className="doc">{hit.doc_title}</span>
                    <span className="pg">{anchorLabel(hit.anchor)}</span>
                    <Snippet hit={hit} />
                    <span className="meta">
                      {[section(hit), hit.org, KINDS[hit.kind] ?? hit.kind, formatDate(hit.date), hit.tier === 'open' ? 'Read here' : 'At source'].filter(Boolean).map((part) => <span key={part}>{part}</span>)}
                    </span>
                  </a>
                </li>
              ))}
            </ol>
            {result.next_cursor && <p className="morerow"><button className="btn" disabled={status === 'working'} onClick={() => run(query, filters, result.next_cursor!)}>More</button></p>}
          </>
        )}
      </div>
    </div>
  );
}

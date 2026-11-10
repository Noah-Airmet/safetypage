// The concordance. Results are citations: each one opens its page.
import { useEffect, useRef, useState } from 'react';
import { KINDS, citePath, formatDate, shelfName } from '../lib/cite';
import { API_BASE } from '../lib/env';
import type { Hit, SearchResponse } from '../lib/types';

const EXAMPLES = ['"alignment faking"', 'sabotage evaluation', 'sparse autoencoder*', 'sycophancy NEAR/10 evaluation'];
// The filters the server counts for every query, in the order they are shown.
const FILTERS = [
  { key: 'collection', every: 'Every shelf', name: shelfName },
  { key: 'kind', every: 'Every kind', name: (k: string) => KINDS[k] ?? k },
  { key: 'org', every: 'Every publisher', name: (o: string) => o },
  { key: 'tier', every: 'Read anywhere', name: (t: string) => (t === 'open' ? 'Read here' : 'Read at source') },
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
      if (!response.ok) { setMessage(body.error ?? 'The query could not be read.'); setResult(null); }
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
  const phrase = /"([^"]{10,})"/.exec(query)?.[1];

  return (
    <div className="search">
      <form className="searchbox" role="search" onSubmit={(e) => { e.preventDefault(); submit(query); }}>
        <input className="field" type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Words, &quot;a phrase&quot;, prefix*, a NEAR/5 b, -exclude" aria-label="Search the library" autoFocus />
        <button className="btn btn-primary">Search</button>
      </form>
      <p className="examples">
        <span>Try</span>
        {EXAMPLES.map((q) => <button type="button" key={q} onClick={() => submit(q)}>{q}</button>)}
      </p>
      {filters.doc && <p className="within">Inside <a className="link mono" href={citePath(filters.doc)}>{filters.doc}</a> <button className="link" onClick={() => pick('doc', '')}>Search everything</button></p>}

      <div className="results" aria-live="polite" aria-busy={status === 'working'}>
        {status === 'down' && <p className="note">Search runs on a server and it is not answering. Reading, citing and every link into the library still work.</p>}
        {message && <p className="note">{message}</p>}
        {result && (
          <>
            {result.facets && (
              <div className="facets">
                {FILTERS.map(({ key, every, name }) => {
                  const counts = Object.entries(result.facets![key] ?? {});
                  if (counts.length < 2 && !filters[key]) return null;
                  return (
                    <select className="field" key={key} aria-label={every.replace('Every ', '')} value={filters[key] ?? ''} onChange={(e) => pick(key, e.target.value)}>
                      <option value="">{every}</option>
                      {counts.map(([value, n]) => <option key={value} value={value}>{name(value)} ({n.toLocaleString('en')})</option>)}
                    </select>
                  );
                })}
              </div>
            )}
            <p className="count">{result.total.toLocaleString('en')} {result.total === 1 ? 'place' : 'pages and paragraphs'} · <span className="mono">{result.interpretation}</span></p>
            <ol>
              {result.hits.map((hit) => (
                <li key={hit.cite}>
                  <a href={citePath(hit.cite, phrase)}>
                    <span className="head"><span className="doc">{hit.doc_title}</span><span className="chip" data-state="cited"><span className="chip-label">{hit.anchor_label}</span></span></span>
                    <Snippet hit={hit} />
                    <span className="meta">{[hit.org, KINDS[hit.kind] ?? hit.kind, formatDate(hit.date), hit.tier === 'open' ? 'Read here' : 'Read at source'].filter(Boolean).join(' · ')} <span className="mono cite">{hit.cite}</span></span>
                  </a>
                </li>
              ))}
            </ol>
            {result.total === 0 && <p className="muted">Nothing matches every word. Fewer words find more.</p>}
            {result.next_cursor && <p className="more"><button className="btn" disabled={status === 'working'} onClick={() => run(query, filters, result.next_cursor!)}>More results</button></p>}
          </>
        )}
      </div>
    </div>
  );
}

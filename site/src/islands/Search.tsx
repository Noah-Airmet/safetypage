// The concordance. Results are citations: each one opens its page.
import { useEffect, useRef, useState } from 'react';
import { Icon } from './shared';
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

// The checker's worked example: what a paragraph with citations looks like.
const CHECK_EXAMPLE = '"not the only tool available for AI risk assessment" (arxiv:2305.15324/v2/p6)';

export default function Search({ documents }: { documents?: number }) {
  const [mode, setMode] = useState<'search' | 'check'>('search');
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
    if (params.get('mode') === 'check') setMode('check');
    if (q) run(q, f);
  }, []);

  // The wall stands under the composer until something is searched.
  const searched = !!result || !!message || status !== 'idle';
  useEffect(() => { document.body.classList.toggle('searched', searched); }, [searched]);

  const submit = (q: string) => { setQuery(q); run(q, filters); };
  // Search stays here, with its results under the composer; a paragraph goes to the checker.
  const send = () => {
    if (!query.trim()) return;
    if (mode === 'check') location.href = `/check?text=${encodeURIComponent(query.trim())}`;
    else submit(query);
  };
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
      <form className="composer" data-mode={mode} data-typed={query.trim() ? '' : undefined} role="search" onSubmit={(e) => { e.preventDefault(); send(); }}>
        <div className="cbox">
          <textarea rows={mode === 'check' ? 4 : 1} value={query} onChange={(e) => setQuery(e.target.value)} autoFocus autoComplete="off" enterKeyHint={mode === 'check' ? 'enter' : 'search'}
            placeholder={mode === 'check' ? 'A paragraph with citations' : documents ? `Search ${documents.toLocaleString('en')} AI safety documents` : 'Search'} aria-label={mode === 'check' ? 'Check a paragraph' : 'Search the library'}
            onKeyDown={(e) => { if (e.key === 'Enter' && !(e.shiftKey && mode === 'check')) { e.preventDefault(); send(); } }} />
          <button className="send" aria-label={mode === 'check' ? 'Check' : 'Search'}><Icon name="send" /></button>
        </div>
        <div className="crow">
          <div className="seg" role="radiogroup" aria-label="Mode">
            <button type="button" role="radio" aria-checked={mode === 'search'} onClick={() => setMode('search')}>Search</button>
            <button type="button" role="radio" aria-checked={mode === 'check'} onClick={() => setMode('check')}>Check</button>
          </div>
          {mode === 'search'
            ? <p className="tries">{EXAMPLES.map((q) => <button type="button" key={q} onClick={() => submit(q)}>{q}</button>)}</p>
            : <p className="tries"><button type="button" onClick={() => setQuery(CHECK_EXAMPLE)}>{CHECK_EXAMPLE}</button></p>}
        </div>
      </form>
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

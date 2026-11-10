// The concordance. Results are citations: each one opens its page.
import { useEffect, useState } from 'react';
import { KINDS, citePath, formatDate } from '../lib/cite';
import { API_BASE } from '../lib/env';
import type { Hit, SearchResponse } from '../lib/types';

const EXAMPLES = ['"risk assessment" evaluation', 'sparse autoencoder features', 'risk tolerance', 'curve detectors'];

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
  const [doc, setDoc] = useState<string | null>(null);
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [status, setStatus] = useState<'idle' | 'working' | 'down'>('idle');
  const [message, setMessage] = useState('');

  const run = async (q: string, within: string | null) => {
    if (!q.trim()) { setResult(null); return; }
    setStatus('working');
    try {
      const params = new URLSearchParams({ query: q, limit: '25' });
      if (within) params.set('doc', within);
      const response = await fetch(`${API_BASE}/api/search?${params}`);
      const body = await response.json();
      if (!response.ok) { setMessage(body.error ?? 'The query could not be read.'); setResult(null); }
      else { setMessage(''); setResult(body); }
      setStatus('idle');
    } catch {
      setStatus('down');
    }
  };

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const q = params.get('query') ?? '';
    setQuery(q);
    setDoc(params.get('doc'));
    run(q, params.get('doc'));
  }, []);

  const submit = (q: string) => {
    const params = new URLSearchParams({ query: q });
    if (doc) params.set('doc', doc);
    history.replaceState(null, '', `/search?${params}`);
    setQuery(q);
    run(q, doc);
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
      {doc && <p className="within">Inside <span className="mono">{doc}</span> <button className="link" onClick={() => { setDoc(null); run(query, null); }}>Search everything</button></p>}

      <div className="results" aria-live="polite" aria-busy={status === 'working'}>
        {status === 'down' && <p className="note">Search runs on a server and it is not answering. Reading, citing and every link into the library still work.</p>}
        {message && <p className="note">{message}</p>}
        {result && (
          <>
            <p className="count">{result.total} {result.total === 1 ? 'page' : 'pages'} · <span className="mono">{result.interpretation}</span></p>
            <ol>
              {result.hits.map((hit) => (
                <li key={hit.cite}>
                  <a href={citePath(hit.cite, phrase)}>
                    <span className="head"><span className="doc">{hit.doc_title}</span><span className="chip" data-state="cited"><span className="chip-label">{hit.anchor_label}</span></span></span>
                    <Snippet hit={hit} />
                    <span className="meta">{[KINDS[hit.kind] ?? hit.kind, formatDate(hit.date), hit.tier === 'open' ? 'Read here' : 'Read at source'].filter(Boolean).join(' · ')} <span className="mono cite">{hit.cite}</span></span>
                  </a>
                </li>
              ))}
            </ol>
            {result.total === 0 && <p className="muted">Nothing matches every word. Fewer words find more.</p>}
          </>
        )}
      </div>
    </div>
  );
}

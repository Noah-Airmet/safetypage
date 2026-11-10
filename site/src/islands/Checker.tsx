// Paste a paragraph with citations; each one comes back Verified, Page only or Rejected, with the reason.
import { useEffect, useState } from 'react';
import { anchorLabel, anchorOf, citePath, docIdOf } from '../lib/cite';
import { API_BASE } from '../lib/env';
import type { AnswerAudit, CitationAudit, CitationState, QuoteCheck } from '../lib/types';
import { Chip, PageView, citeLabel, useDocs } from './shared';

const EXAMPLE = `Model evaluation matters, but its authors do not oversell it. They write that it is "not the only tool available for AI risk assessment" (arxiv:2305.15324/v2/p6), and they call it "one of the main tools we have for AI risk assessment" (arxiv:2305.15324/v2/p3).

A looser summary claims that "Model evaluation is the only tool available for AI risk assessment" (arxiv:2305.15324/v2/p6). Cunningham et al. propose sparse autoencoders as an answer to polysemantic neurons (arxiv:2309.08600/v3/p2), and one version of this paragraph cited a page that does not exist (arxiv:2305.15324/v2/p41).`;

const stateOf = (c: CitationAudit): CitationState =>
  !c.resolves ? 'rejected' : c.quotes.length === 0 ? 'cited' : c.quotes.every((q) => q.check?.passed) ? 'verified' : 'rejected';

function Reason({ check, cite }: { check: QuoteCheck; cite: string }) {
  const here = anchorLabel(anchorOf(cite));
  const where = check.locations[0];
  if (check.verdict === 'exact') return <>On {here}, word for word.</>;
  if (check.verdict === 'normalized') return <>On {here}, allowing for case, punctuation and line breaks.</>;
  if (check.verdict === 'elsewhere' && where) return <>Not on {here}. The words are on <a className="link" href={citePath(where.cite, check.quote)}>{anchorLabel(where.anchor)}</a>.</>;
  if (check.verdict === 'near_miss' && where) {
    const diffs = check.segments.flatMap((s) => s.diff);
    return (
      <>Not on {here}. The page says “{where.text.replace(/\s+/g, ' ')}”
        {diffs.length > 0 && <span className="diffs">{diffs.map((d, i) => (
          <span key={i}>{d.op === 'insert' ? <>the page has <ins className="diff">{d.source}</ins></> : d.op === 'delete' ? <>the quote adds <del className="diff">{d.quote}</del></> : <><del className="diff">{d.quote}</del> is <ins className="diff">{d.source}</ins> on the page</>}</span>
        ))}</span>}
      </>
    );
  }
  return <>Not found anywhere in this document.</>;
}

export default function Checker() {
  const [text, setText] = useState('');
  const [checked, setChecked] = useState('');
  const [audit, setAudit] = useState<AnswerAudit | null>(null);
  const [status, setStatus] = useState<'idle' | 'working' | 'down'>('idle');
  const [open, setOpen] = useState<number | null>(null);
  const docs = useDocs(audit ? audit.citations.filter((c) => c.resolves).map((c) => docIdOf(c.cite)) : []);

  const run = async (input: string) => {
    if (!input.trim()) return;
    setStatus('working');
    try {
      const response = await fetch(`${API_BASE}/api/check`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ text: input }) });
      if (!response.ok) throw new Error();
      const body = (await response.json()) as AnswerAudit;
      setAudit(body);
      setChecked(input);
      const firstBad = body.citations.findIndex((c) => stateOf(c) === 'rejected' && c.resolves);
      setOpen(firstBad >= 0 ? firstBad : null);
      setStatus('idle');
      if (input.length < 1800) history.replaceState(null, '', `/check?text=${encodeURIComponent(input)}`);
    } catch {
      setStatus('down');
    }
  };

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const given = params.get('text') ?? (params.has('example') ? EXAMPLE : '');
    if (given) { setText(given); if (!/""/.test(given)) run(given); }
  }, []);

  const states = audit?.citations.map(stateOf) ?? [];
  const count = (s: CitationState) => states.filter((x) => x === s).length;

  // The checked text again, with each citation replaced by its chip.
  const marked: React.ReactNode[] = [];
  if (audit) {
    let at = 0;
    audit.citations.forEach((c, i) => {
      const found = checked.indexOf(c.raw, at);
      if (found < 0) return;
      const wrapped = checked[found - 1] === '(' && checked[found + c.raw.length] === ')';
      marked.push(checked.slice(at, wrapped ? found - 1 : found), <Chip key={i} state={states[i]} label={c.resolves ? citeLabel(c.cite, docs) : c.raw} onClick={() => { setOpen(i); document.getElementById(`c${i}`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }} current={open === i} />);
      at = found + c.raw.length + (wrapped ? 1 : 0);
    });
    marked.push(checked.slice(at));
  }

  return (
    <div className="checker">
      <form onSubmit={(e) => { e.preventDefault(); run(text); }}>
        <label className="sr" htmlFor="check-text">Text with citations</label>
        <textarea id="check-text" className="field" rows={7} value={text} onChange={(e) => setText(e.target.value)} placeholder={'Paste a paragraph. Put each quotation in quotation marks, followed by its citation:\n"the quoted words" (arxiv:2305.15324/v2/p6)'} />
        <div className="actions">
          <button className="btn btn-primary" disabled={status === 'working' || !text.trim()}>{status === 'working' ? 'Checking' : 'Check'}</button>
          <button type="button" className="btn" onClick={() => { setText(EXAMPLE); run(EXAMPLE); }}>Try an example</button>
          {audit && <button type="button" className="btn btn-quiet" onClick={() => navigator.clipboard.writeText(location.href)}>Copy link</button>}
        </div>
      </form>
      {status === 'down' && <p className="note">The checker runs on a server and it is not answering.</p>}

      {audit && (
        <div className="audit" aria-live="polite">
          <p className="summary">
            <span className="state" data-state="verified">{count('verified')} verified</span>
            <span className="state" data-state="cited">{count('cited')} page only</span>
            <span className="state" data-state="rejected">{count('rejected')} rejected</span>
          </p>
          <div className="marked prose">{marked.map((part, i) => (typeof part === 'string' ? part.split('\n\n').map((para, j) => <span key={`${i}-${j}`}>{j > 0 && <><br /><br /></>}{para}</span>) : part))}</div>

          <ol className="findings">
            {audit.citations.map((c, i) => (
              <li key={i} id={`c${i}`} data-open={open === i || undefined}>
                <div className="finding-head">
                  <Chip state={states[i]} label={c.resolves ? citeLabel(c.cite, docs) : c.raw} href={c.resolves ? citePath(c.cite, c.quotes[0]?.quote) : undefined} />
                  <span className="mono cite">{c.cite}</span>
                </div>
                {!c.resolves && <p className="why">{c.error}</p>}
                {c.resolves && c.quotes.length === 0 && <p className="why">The page exists. No quotation is attached to this citation, so there are no words to check.</p>}
                {c.quotes.map((q, j) => (
                  <div className="quote" key={j}>
                    <p className="q">“{q.quote}”</p>
                    <p className="why">{q.check ? <Reason check={q.check} cite={c.cite} /> : q.error}</p>
                    {q.check?.locations[0] && (open === i ? (
                      <div className="evidence">
                        <PageView cite={q.check.locations[0].cite.replace(/-p\d+$/, '')} span={[q.check.locations[0].spine_start, q.check.locations[0].spine_end]} kind={q.check.passed ? 'found' : 'reject'} doc={docs[docIdOf(c.cite)]} />
                      </div>
                    ) : <button className="link show" onClick={() => setOpen(i)}>Show the page</button>)}
                  </div>
                ))}
              </li>
            ))}
          </ol>
          {audit.unattached_quotes.length > 0 && <p className="note">{audit.unattached_quotes.length} quotation{audit.unattached_quotes.length > 1 ? 's have' : ' has'} no citation next to {audit.unattached_quotes.length > 1 ? 'them' : 'it'}, so {audit.unattached_quotes.length > 1 ? 'they were' : 'it was'} not checked.</p>}
          <p className="note">This checks that each page exists and contains the quoted words. It does not judge whether the page supports the claim made about it.</p>
        </div>
      )}
    </div>
  );
}

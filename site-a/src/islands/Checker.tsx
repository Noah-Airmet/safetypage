// Paste a paragraph with citations; each one comes back Verified, Page only or Rejected. The
// result shows the paragraph with its citations as chips, then each quotation beside the page
// it names: the passage lit where the words are there, the page's own wording where they are not.
import { useEffect, useRef, useState } from 'react';
import { anchorLabel, anchorOf, citePath, docIdOf } from '../lib/cite';
import { API_BASE } from '../lib/env';
import { grow } from '../lib/grow';
import { copyText, toast } from '../lib/ui';
import type { AnswerAudit, CitationAudit, CitationState, QuoteCheck } from '../lib/types';
import { Chip, Icon, PageView, State, Tally, citeLabel, useDocs } from './shared';

const stateOf = (c: CitationAudit): CitationState =>
  !c.resolves ? 'rejected' : c.quotes.length === 0 ? 'cited' : c.quotes.every((q) => q.check?.passed) ? 'verified' : 'rejected';

/** The server's reason a citation does not resolve, as a state: `No p. 41 · 20 pages`. */
const noPage = (error: string | null) => {
  const m = /has (\d+) (pages|paragraphs); there is no ([pb]\d+)/.exec(error ?? '');
  return m ? `No ${anchorLabel(m[3])} · ${m[1]} ${m[2]}` : 'Not in the library';
};

/** The verdict as a state, a flag, and the page's own words where the quotation departs from them. */
function Verdict({ check, cite }: { check: QuoteCheck; cite: string }) {
  const here = anchorLabel(anchorOf(cite));
  const where = check.locations[0];
  if (check.passed) return <p className="why"><State state="verified">On {here}</State><span className="flag">{check.verdict === 'exact' ? 'Word for word' : 'Normalised'}</span></p>;
  if (check.verdict === 'elsewhere' && where) return <p className="why"><State state="rejected">Not on {here}</State><Chip state="verified" label={anchorLabel(where.anchor)} href={citePath(where.cite, check.quote)} /></p>;
  if (check.verdict === 'near_miss' && where) {
    const diffs = check.segments.flatMap((s) => s.diff);
    const words = where.text.replace(/\s+/g, ' ').split(' ');
    const added = diffs.filter((d) => d.op !== 'delete').flatMap((d) => d.source.split(/\s+/));
    return (
      <>
        <p className="why"><State state="rejected">Not on {here}</State><span className="flag">The page says</span>{diffs.filter((d) => d.op !== 'insert').map((d, i) => <del className="diff" key={i}>{d.quote}</del>)}</p>
        <p className="says">“{words.map((w, i) => <span key={i}>{i > 0 && ' '}{added.includes(w.replace(/[^\p{L}\p{N}'-]/gu, '')) || added.includes(w) ? <ins className="diff">{w}</ins> : w}</span>)}”</p>
      </>
    );
  }
  return <p className="why"><State state="rejected">Not on {here}</State><span className="flag">Not in the document</span></p>;
}

export default function Checker({ example }: { example: string }) {
  const [text, setText] = useState('');
  const [checked, setChecked] = useState('');
  const [audit, setAudit] = useState<AnswerAudit | null>(null);
  const [status, setStatus] = useState<'idle' | 'working' | 'down'>('idle');
  const [open, setOpen] = useState<number | null>(null);
  const box = useRef<HTMLTextAreaElement>(null);
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
      if (input.length < 1800) history.replaceState(history.state, '', `/check?text=${encodeURIComponent(input)}`);
    } catch {
      setStatus('down');
    }
  };

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const given = params.get('text') ?? (params.has('example') ? example : '');
    if (given) { setText(given); if (!/""/.test(given)) run(given); }
  }, []);
  useEffect(() => { if (box.current) grow(box.current, { min: 3, max: 10 }); }, [text]);

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
      marked.push(checked.slice(at, wrapped ? found - 1 : found), <Chip key={i} state={states[i]} label={c.resolves ? citeLabel(c.cite, docs) : c.raw} onClick={() => { setOpen(i); document.getElementById(`c${i}`)?.scrollIntoView({ block: 'nearest' }); }} current={open === i} />);
      at = found + c.raw.length + (wrapped ? 1 : 0);
    });
    marked.push(checked.slice(at));
  }

  return (
    <div className="checker">
      <form className={text.trim() ? 'composer typed' : 'composer'} data-mode="check" onSubmit={(e) => { e.preventDefault(); run(text); }}>
        <div className="cbox">
          <textarea id="check-text" ref={box} rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder="Check a paragraph" aria-label="Text with citations"
            onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); run(text); } }} />
          <button className="send" type="submit" aria-label="Check" disabled={status === 'working'}><Icon name="send" /></button>
        </div>
        <div className="crow">
          <button className="cbtn" type="button" data-open="check-help" aria-label="What is checked"><Icon name="help" /></button>
          {status === 'working' && <i className="working" role="status" aria-label="Checking" />}
          {status === 'down' && <><span className="err">Check unavailable</span><button type="button" className="btn" onClick={() => run(text)}>Retry</button></>}
          {audit && status === 'idle' && <button type="button" className="btn" onClick={() => copyText(location.href).then(() => toast('Copied'), () => toast('Copy failed', 'close'))}><Icon name="link" /><span>Copy link</span></button>}
          <button type="button" className="btn eg" onClick={() => { setText(example); run(example); }}>Example</button>
        </div>
      </form>

      {audit && (
        <div className="audit" aria-live="polite">
          <p className="summary"><Tally counts={{ verified: count('verified'), cited: count('cited'), rejected: count('rejected') }} /></p>
          <div className="marked">{marked.map((part, i) => (typeof part === 'string' ? part.split('\n\n').map((para, j) => <span key={`${i}-${j}`}>{j > 0 && <><br /><br /></>}{para}</span>) : part))}</div>

          <ol className="findings">
            {audit.citations.map((c, i) => (
              <li key={i} id={`c${i}`} data-open={open === i || undefined}>
                <div className="finding-head">
                  <Chip state={states[i]} label={c.resolves ? citeLabel(c.cite, docs) : c.raw} href={c.resolves ? citePath(c.cite, c.quotes[0]?.quote) : undefined} />
                  {!c.resolves && <span className="flag">{noPage(c.error)}</span>}
                </div>
                {c.quotes.map((q, j) => (
                  <figure className="qcard" data-state={q.check?.passed ? 'verified' : 'rejected'} key={j}>
                    <blockquote className="q">“{q.quote}”</blockquote>
                    {q.check ? <Verdict check={q.check} cite={c.cite} /> : <p className="why"><span className="flag">{q.error}</span></p>}
                    {q.check?.locations[0] && (open === i ? (
                      <div className="evidence">
                        <PageView cite={q.check.locations[0].cite.replace(/-p\d+$/, '')} span={[q.check.locations[0].spine_start, q.check.locations[0].spine_end]} kind={q.check.passed ? 'found' : 'reject'} doc={docs[docIdOf(c.cite)]} />
                      </div>
                    ) : <button className="btn show" onClick={() => setOpen(i)}><Icon name="doc" /><span>{anchorLabel(q.check.locations[0].anchor)}</span></button>)}
                  </figure>
                ))}
              </li>
            ))}
          </ol>
          {audit.unattached_quotes.length > 0 && <p className="summary"><span className="flag">{audit.unattached_quotes.length} uncited {audit.unattached_quotes.length > 1 ? 'quotations' : 'quotation'}</span></p>}
        </div>
      )}
    </div>
  );
}

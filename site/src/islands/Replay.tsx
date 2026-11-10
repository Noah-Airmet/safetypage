// The replay: an agent's research run played back from a Trace file. The trace, the library
// and the answer share one scrubber, and the state at any step is computed from the events
// up to it (lib/replay.ts), so scrubbing in either direction is the same operation.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { anchorLabel, anchorOf, citePath, docIdOf, shortLabel } from '../lib/cite';
import { REASONS, focusFor, holdAfter, stateAt, type AnswerCite, type Focus } from '../lib/replay';
import type { DocumentCard, Trace, TraceEvent } from '../lib/types';
import { Chip, PageView } from './shared';

type DocLite = Pick<DocumentCard, 'doc_id' | 'title' | 'authors' | 'org' | 'published' | 'unit_count' | 'anchor_kind' | 'tier' | 'source_url'>;
interface Props { trace: Trace; docs: Record<string, DocLite>; librarySize: number }

const clock = (ms: number) => `${String(Math.floor(ms / 60000)).padStart(2, '0')}:${String(Math.floor(ms / 1000) % 60).padStart(2, '0')}`;
const SPEEDS = [1, 2, 4, 0.5];

export default function Replay({ trace, docs, librarySize }: Props) {
  const events = trace.events;
  const last = events.length - 1;
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [pinned, setPinned] = useState<Focus | null>(null);
  const [raw, setRaw] = useState(false);
  const [copied, setCopied] = useState(false);
  const state = useMemo(() => stateAt(events, step), [events, step]);
  const label = useCallback((cite: string) => {
    const doc = docs[docIdOf(cite)];
    return `${doc ? shortLabel(doc) : docIdOf(cite)} · ${anchorLabel(anchorOf(cite))}`;
  }, [docs]);

  const go = useCallback((to: number) => { setPinned(null); setStep(Math.min(Math.max(0, to), last)); }, [last]);

  // Start where the link says, otherwise play from the top.
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const at = params.get('step');
    if (at !== null) setStep(Math.min(Math.max(0, Number(at) || 0), last));
    else setPlaying(true);
    if (params.get('speed')) setSpeed(Number(params.get('speed')) || 1);
  }, [last]);

  useEffect(() => {
    if (!playing) return;
    if (step >= last) { setPlaying(false); return; }
    const timer = setTimeout(() => { setPinned(null); setStep((s) => s + 1); }, holdAfter(events, step) / speed);
    return () => clearTimeout(timer);
  }, [playing, step, speed, events, last]);

  useEffect(() => {
    if (!playing) history.replaceState(null, '', `${location.pathname}?step=${step}`);
  }, [playing, step]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest('input, textarea, button, a')) return;
      if (e.key === ' ') { e.preventDefault(); setPlaying((p) => !p); }
      if (e.key === 'ArrowRight') { setPlaying(false); go(step + 1); }
      if (e.key === 'ArrowLeft') { setPlaying(false); go(step - 1); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [go, step]);

  // Keep the current trace line in view inside its pane, without moving the page.
  const listRef = useRef<HTMLOListElement>(null);
  useEffect(() => {
    const list = listRef.current;
    const line = list?.querySelector<HTMLElement>('[aria-current="step"]');
    if (list && line) list.scrollTo({ top: line.offsetTop - list.clientHeight / 2 });
  }, [step]);

  const focus = pinned ?? state.focus;
  const focusDoc = focus ? docs[docIdOf(focus.cite)] : undefined;
  const touched = useMemo(() => {
    const versions = new Map<string, string>();
    for (const e of events) {
      const cites = e.kind === 'tool' ? e.returned.map((r) => r.cite) : e.kind === 'cite' ? [e.cite] : [];
      for (const c of cites) if (!versions.has(docIdOf(c))) versions.set(docIdOf(c), c.split('/')[1]);
    }
    return [...versions];
  }, [events]);
  const citeStates = new Map(state.answer.filter((p): p is AnswerCite => p.type === 'cite').map((c) => [c.cite, c.state]));
  const shown = events.slice(0, step + 1).filter((e) => e.kind !== 'answer' || events[e.seq - 1]?.kind !== 'answer' && events[e.seq - 1]?.kind !== 'verify');
  const reads = state.read.size;

  const line = (e: TraceEvent) => {
    if (e.kind === 'think') return <><span className="k">think</span><span className="think">{e.text}</span></>;
    if (e.kind === 'tool' && e.tool === 'search') return <><span className="k">search</span><span><span className="mono q">{String(e.args.query ?? '')}</span><span className="sub">{e.total ?? e.returned.length} {e.total === 1 ? 'page' : 'pages'}</span></span></>;
    if (e.kind === 'tool') return <><span className="k">{e.tool}</span><span>{e.returned[0] ? label(e.returned[0].cite) : String(e.args.id ?? '')}{e.error && <span className="sub bad">{e.error}</span>}</span></>;
    if (e.kind === 'answer') return <><span className="k">answer</span><span className="sub">writing</span></>;
    if (e.kind === 'cite') return <><span className="k">cite</span><span>{label(e.cite)}{e.quote && <span className="sub">“{e.quote.length > 60 ? e.quote.slice(0, 60) + '…' : e.quote}”</span>}</span></>;
    return <><span className="k">check</span><span><span className="state" data-state={e.state}>{e.state === 'cited' ? 'Page only' : e.state === 'verified' ? `Verified · ${e.quote_verdict === 'exact' ? 'word for word' : 'normalised'}` : 'Rejected'}</span>{e.reason && <span className="sub bad">{REASONS[e.reason] ?? e.reason}{e.closest && e.reason === 'quote_elsewhere' ? `: ${anchorLabel(anchorOf(e.closest))}` : ''}</span>}</span></>;
  };

  return (
    <div className="replay">
      <header className="rp-head">
        <div>
          <h1>{trace.header.question}</h1>
          <p className="rp-meta">{[trace.header.model, trace.header.started_at.slice(0, 10), `${events.length} steps`, `${reads} ${reads === 1 ? 'page' : 'pages'} read`, trace.header.usage?.cost_usd != null ? `$${trace.header.usage.cost_usd.toFixed(2)}` : null].filter(Boolean).join(' · ')}</p>
        </div>
        <p className="rp-tally" aria-label="Citations so far">
          <span className="state" data-state="verified">{state.tally.verified}<span className="sr"> verified</span></span>
          <span className="state" data-state="cited">{state.tally.cited}<span className="sr"> page only</span></span>
          <span className="state" data-state="rejected">{state.tally.rejected}<span className="sr"> rejected</span></span>
        </p>
      </header>

      <div className="rp-panes">
        <section className="rp-trace" aria-label="Trace">
          <h2 className="h2">Trace</h2>
          <ol ref={listRef}>
            {shown.map((e) => (
              <li key={e.seq} aria-current={e.seq === step || (events[step].kind === 'answer' && e.kind === 'answer' && e.seq === shown[shown.length - 1].seq) ? 'step' : undefined} data-kind={e.kind} data-bad={e.kind === 'verify' && e.state === 'rejected' || undefined}>
                <button type="button" onClick={() => { setPlaying(false); go(e.seq); }}>
                  <span className="t mono">{clock(e.t_ms)}</span>{line(e)}
                </button>
                {raw && e.seq === step && <pre className="code" tabIndex={0}>{JSON.stringify(e, null, 1)}</pre>}
              </li>
            ))}
          </ol>
        </section>

        <section className="rp-library" aria-label="Library">
          <h2 className="h2">Library <span className="h2-sub">{touched.length} of {librarySize} documents touched</span></h2>
          <ul className="shelf">
            {touched.map(([docId, version]) => {
              const doc = docs[docId];
              const n = doc?.unit_count ?? 1;
              const kind = doc?.anchor_kind === 'block' ? 'b' : 'p';
              return (
                <li key={docId}>
                  <a className="shelf-name" href={citePath(docId)}>{doc ? shortLabel(doc) : docId}</a>
                  <span className="cells" style={{ gridTemplateColumns: `repeat(${n}, minmax(0, 1fr))` }}>
                    {Array.from({ length: n }, (_, i) => {
                      const cite = `${docId}/${version}/${kind}${i + 1}`;
                      const hit = state.hits.get(cite);
                      const cs = citeStates.get(cite);
                      const mark = cs === 'rejected' ? 'rejected' : cs ? 'cited' : state.read.has(cite) ? 'read' : hit ? 'hit' : undefined;
                      return <i key={i} data-mark={mark} data-fresh={state.fresh.has(cite) || undefined} data-here={focus?.cite === cite || undefined} style={mark === 'hit' ? { opacity: 0.25 + 0.55 * hit! } : undefined} />;
                    })}
                  </span>
                </li>
              );
            })}
          </ul>
          <div className="rp-page">
            {focus ? (
              <>
                <PageView key={focus.cite} cite={focus.cite} span={focus.span} kind={focus.kind} doc={focusDoc} />
                <p className="rp-caption">
                  <span>{label(focus.cite)}{focus.cited && focus.cited !== focus.cite && <span className="bad"> · cited as {anchorLabel(anchorOf(focus.cited))}</span>}</span>
                  <a className="link" href={citePath(focus.cite)}>Open the page</a>
                </p>
              </>
            ) : <div className="pv pv-empty rp-wait"><p>The page the agent is reading appears here.</p></div>}
          </div>
        </section>

        <section className="rp-answer" aria-label="Answer">
          <h2 className="h2">Answer</h2>
          <div className="prose">
            {state.answer.length === 0 && <p className="muted wait">Not written yet.</p>}
            {state.answer.map((part, i) => part.type === 'text'
              ? <span key={i}>{part.text.split('\n\n').map((para, j) => <span key={j}>{j > 0 && <><br /><br /></>}{para}</span>)}</span>
              : <Chip key={i} state={part.state} label={label(part.cite)} current={focus?.cite === focusFor(part).cite && focus?.cited === focusFor(part).cited} onClick={() => { setPlaying(false); setPinned(focusFor(part)); }} />)}
          </div>
          {state.answer.filter((p): p is AnswerCite => p.type === 'cite' && p.state === 'rejected').map((c) => (
            <p className="rp-reason" key={c.cite_id}><span className="state" data-state="rejected">{label(c.cite)}</span> {REASONS[c.reason ?? ''] ?? c.reason}{c.closest && c.closest !== c.cite ? `: ${anchorLabel(anchorOf(c.closest))}` : ''}.</p>
          ))}
        </section>
      </div>

      <div className="rp-scrub">
        <button type="button" className="btn rp-play" onClick={() => { if (step >= last) go(0); setPlaying((p) => !p); }} aria-label={playing ? 'Pause' : 'Play'}>
          <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">{playing ? <path d="M4 2.5h3v11H4zM9 2.5h3v11H9z" fill="currentColor" /> : <path d="M4.5 2.5v11l9-5.5z" fill="currentColor" />}</svg>
        </button>
        <div className="rp-track">
          <div className="ticks" aria-hidden="true">
            {events.map((e) => <i key={e.seq} data-kind={e.kind} data-bad={e.kind === 'verify' && e.state === 'rejected' || undefined} data-past={e.seq <= step || undefined} style={{ left: `${(e.seq / last) * 100}%` }} />)}
          </div>
          <input type="range" min={0} max={last} value={step} onChange={(e) => { setPlaying(false); go(Number(e.target.value)); }} aria-label="Step" aria-valuetext={`Step ${step + 1} of ${events.length}`} />
        </div>
        <span className="mono rp-count">{step + 1} / {events.length}</span>
        <button type="button" className="btn btn-quiet rp-speed" onClick={() => setSpeed(SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length])} aria-label={`Speed ${speed}×`}>{speed}×</button>
        <button type="button" className="btn btn-quiet rp-raw" aria-pressed={raw} onClick={() => setRaw(!raw)}>Raw</button>
        <button type="button" className="btn" onClick={() => { navigator.clipboard.writeText(`${location.origin}${location.pathname}?step=${step}`); setCopied(true); setTimeout(() => setCopied(false), 1200); }}>{copied ? 'Copied' : 'Share'}</button>
      </div>
    </div>
  );
}

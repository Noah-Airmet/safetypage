// The replay: an agent's research run played back from a Trace file. The trace, the library
// and the answer share one scrubber, and the state at any step is computed from the events
// up to it (lib/replay.ts), so scrubbing in either direction is the same operation.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { anchorLabel, anchorOf, citePath, docIdOf, questionParts, shortLabel } from '../lib/cite';
import { REASONS, answerSegments, focusFor, holdAfter, stateAt, type AnswerCite, type Focus } from '../lib/replay';
import type { DocumentCard, Trace, TraceEvent } from '../lib/types';
import { Chip, Icon, PageView } from './shared';

type DocLite = Pick<DocumentCard, 'doc_id' | 'title' | 'authors' | 'org' | 'published' | 'unit_count' | 'anchor_kind' | 'tier' | 'source_url'>;
// `other`: the snapshot the run read, when it is not the one this site is built on. Its page and
// paragraph numbers are that snapshot's, so no page of the current library is shown for them.
interface Props { trace: Trace; docs: Record<string, DocLite>; librarySize: number; other?: string }

const clock = (ms: number) => `${String(Math.floor(ms / 60000)).padStart(2, '0')}:${String(Math.floor(ms / 1000) % 60).padStart(2, '0')}`;
const SPEEDS = [1, 2, 4, 0.5];
const TOOLS: Record<string, string> = { verify_quote: 'verify', check_answer: 'audit' };
const VERDICTS: Record<string, string> = { exact: 'on the page, word for word', normalized: 'on the page', elsewhere: 'on another page', near_miss: 'not these words', not_found: 'not found' };
const JUDGED: Record<string, string> = { supported: 'supports the claim', partially_supported: 'partly supports the claim', unsupported: 'does not support the claim' };

/** The answer's own light markdown: paragraphs, lists, bold and italic. Chips sit where the citations are. */
function Rich({ segments, chip }: { segments: (string | AnswerCite)[]; chip: (c: AnswerCite, key: number) => React.ReactNode }) {
  const inline = (text: string, key: string) =>
    text.split(/(\*\*[^*]+\*\*|\*[^*\n]+\*)/).map((piece, i) =>
      piece.startsWith('**') ? <strong key={key + i}>{piece.slice(2, -2)}</strong> : piece.startsWith('*') && piece.length > 2 ? <em key={key + i}>{piece.slice(1, -1)}</em> : piece);
  // Lines of nodes: a blank line starts a paragraph, "- " starts a list item.
  const blocks: { item: boolean; nodes: React.ReactNode[] }[] = [{ item: false, nodes: [] }];
  segments.forEach((seg, si) => {
    if (typeof seg !== 'string') { blocks[blocks.length - 1].nodes.push(chip(seg, si)); return; }
    seg.split('\n').forEach((lineText, li) => {
      if (li > 0) blocks.push({ item: false, nodes: [] });
      const block = blocks[blocks.length - 1];
      let text = lineText;
      if (block.nodes.length === 0 && /^\s*[-*] /.test(text)) { block.item = true; text = text.replace(/^\s*[-*] /, ''); }
      if (block.nodes.length === 0) text = text.replace(/^#+ /, '');
      if (text) block.nodes.push(...inline(text, `${si}-${li}-`));
    });
  });
  return <>{blocks.filter((b) => b.nodes.length).map((b, i) => <p key={i} className={b.item ? 'item' : undefined}>{b.nodes}</p>)}</>;
}

export default function Replay({ trace, docs, librarySize, other }: Props) {
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
    return `${doc ? shortLabel(doc) : docIdOf(cite)}, ${anchorLabel(anchorOf(cite))}`;
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

  const answerRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const pane = answerRef.current;
    const chip = pane?.querySelector<HTMLElement>('[aria-current="true"]');
    if (pane && chip && pane.scrollHeight > pane.clientHeight) pane.scrollTo({ top: chip.offsetTop - pane.clientHeight / 2, behavior: 'smooth' });
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
  const asked = questionParts(trace.header.question);
  const segments = useMemo(() => answerSegments(state.answer), [state]);

  const line = (e: TraceEvent) => {
    if (e.kind === 'think') return <><span className="k">think</span><span className="think">{e.text}</span></>;
    if (e.kind === 'tool' && e.tool === 'search') return <><span className="k">search</span><span><span className="mono q">{String(e.args.query ?? '')}</span>{e.error ? <span className="sub bad">error</span> : <span className="sub">{e.total ?? e.returned.length} {(e.total ?? e.returned.length) === 1 ? 'page' : 'pages'}</span>}</span></>;
    if (e.kind === 'tool') return <><span className="k">{TOOLS[e.tool] ?? e.tool}</span><span>{e.returned[0] ? label(e.returned[0].cite) : String(e.args.id ?? e.args.cite ?? '').replace(/^https?:\/\/[^/]+\/d\/([^/]+)\//, '$1:')}{e.verdict && <span className={e.verdict === 'exact' || e.verdict === 'normalized' ? 'sub' : 'sub bad'}>{VERDICTS[e.verdict]}</span>}{e.error && <span className="sub bad">error</span>}</span></>;
    if (e.kind === 'answer') return <><span className="k">answer</span><span className="sub">writing</span></>;
    if (e.kind === 'cite') return <><span className="k">cite</span><span>{label(e.cite)}{e.quote && <span className="sub">“{e.quote.length > 60 ? e.quote.slice(0, 60) + '…' : e.quote}”</span>}</span></>;
    return <><span className="k">check</span><span><span className="state" data-state={e.state}>{e.state === 'cited' ? 'Page only' : e.state === 'verified' ? `Verified, ${e.quote_verdict === 'exact' ? 'word for word' : 'normalised'}` : 'Rejected'}</span>{e.reason && <span className="sub bad">{REASONS[e.reason] ?? e.reason}{e.closest && e.reason === 'quote_elsewhere' ? `: ${anchorLabel(anchorOf(e.closest))}` : ''}</span>}{e.judgement && <span className="sub judge" title={e.judgement.judge}>judge: {JUDGED[e.judgement.label] ?? e.judgement.label}</span>}</span></>;
  };

  const usage = trace.header.usage?.cost_usd;
  const now = events[step];
  return (
    <div className="replay">
      <header className="rp-head">
        <div>
          {asked.quoted && <p className="rp-lead">{asked.lead}</p>}
          <h1>{asked.quoted ? `“${asked.quoted}”` : asked.lead}</h1>
          <p className="rp-meta">{[trace.header.model.split('/').pop(), trace.header.started_at.slice(0, 10), `${events.length} steps`, `${reads} ${reads === 1 ? 'page' : 'pages'} read`, `${touched.length} of ${librarySize.toLocaleString('en')} documents`, usage != null ? `$${usage.toFixed(usage < 0.1 ? 3 : 2)}` : null].filter(Boolean).map((part) => <span key={part}>{part}</span>)}</p>
        </div>
        <p className="rp-tally" aria-label="Citations so far">
          <span className="state" data-state="verified">{state.tally.verified}<span className="sr"> verified</span></span>
          <span className="state" data-state="cited">{state.tally.cited}<span className="sr"> page only</span></span>
          <span className="state" data-state="rejected">{state.tally.rejected}<span className="sr"> rejected</span></span>
        </p>
      </header>

      <div className="rp-panes">
        <section className="rp-trace" aria-label="Trace">
          <h2 className="h3">Trace</h2>
          <ol ref={listRef}>
            {shown.map((e) => (
              <li key={e.seq} aria-current={e.seq === step || (events[step].kind === 'answer' && e.kind === 'answer' && e.seq === shown[shown.length - 1].seq) ? 'step' : undefined} data-kind={e.kind} data-bad={e.kind === 'verify' && e.state === 'rejected' || undefined}>
                <button type="button" onClick={() => { setPlaying(false); go(e.seq); }}>
                  <span className="t">{clock(e.t_ms)}</span>{line(e)}
                </button>
                {raw && e.seq === step && <pre className="code" tabIndex={0}>{JSON.stringify(e, null, 1)}</pre>}
              </li>
            ))}
          </ol>
        </section>

        <section className="rp-stage" aria-label="The page being read">
          <div className="rp-page">
            {focus ? (
              other ? (
                <div className="pv pv-source">
                  <p className="muted">{anchorLabel(anchorOf(focus.cite))}</p>
                  <p className="pv-title">{focusDoc?.title ?? docIdOf(focus.cite)}</p>
                  <p className="muted">Snapshot <span className="mono">{other}</span></p>
                </div>
              ) : <PageView key={focus.cite} cite={focus.cite} span={focus.span} kind={focus.kind} doc={focusDoc} />
            ) : <div className="pv pv-empty" />}
          </div>
          <p className="rp-now" data-bad={now.kind === 'verify' && now.state === 'rejected' || undefined}><span className="t">{clock(now.t_ms)}</span>{line(now)}</p>
          <p className="rp-caption">
            {focus && <span>{label(focus.cite)}{focus.cited && focus.cited !== focus.cite && <span className="bad">, cited as {anchorLabel(anchorOf(focus.cited))}</span>}</span>}
            {focus && !other && <a className="link" href={citePath(focus.cite)}>Open the page</a>}
          </p>
          <ul className="books" aria-label="Documents touched">
            {touched.map(([docId, version]) => {
              const doc = docs[docId];
              const n = doc?.unit_count ?? 1;
              const kind = doc?.anchor_kind === 'block' ? 'b' : 'p';
              return (
                <li key={docId}>
                  <a className="book-name" href={citePath(docId)}>{doc ? shortLabel(doc) : docId}</a>
                  <span className="cells" style={{ gridTemplateColumns: `repeat(${n}, minmax(0, 1fr))`, gap: n > 60 ? 0 : undefined }}>
                    {Array.from({ length: n }, (_, i) => {
                      const cite = `${docId}/${version}/${kind}${i + 1}`;
                      const hit = state.hits.get(cite);
                      const cs = citeStates.get(cite);
                      const mark = cs === 'rejected' ? 'rejected' : cs ? 'cited' : state.read.has(cite) ? 'read' : hit ? 'hit' : undefined;
                      return <i key={i} data-mark={mark} data-fresh={state.fresh.has(cite) || undefined} data-here={focus?.cite === cite || undefined} style={mark === 'hit' ? { '--score': 0.35 + 0.65 * hit! } as React.CSSProperties : undefined} />;
                    })}
                  </span>
                </li>
              );
            })}
          </ul>
        </section>

        <section className="rp-answer" aria-label="Answer" ref={answerRef}>
          <h2 className="h3">Answer</h2>
          <div className="prose">
            {state.answer.length === 0 && <div className="rp-blank" aria-hidden="true"><i /><i /><i /></div>}
            <Rich segments={segments} chip={(part, key) => <Chip key={key} state={part.state} label={label(part.cite)} current={focus?.cite === focusFor(part).cite && (focus?.cited ?? focus?.cite) === part.cite} onClick={() => { setPlaying(false); setPinned(focusFor(part)); }} />} />
          </div>
          {state.answer.filter((p): p is AnswerCite => p.type === 'cite' && p.state === 'rejected').map((c) => (
            <p className="rp-reason" key={c.cite_id}><span className="state" data-state="rejected">{label(c.cite)}</span> {REASONS[c.reason ?? ''] ?? c.reason}{c.closest && c.closest !== c.cite ? `: ${anchorLabel(anchorOf(c.closest))}` : ''}</p>
          ))}
        </section>
      </div>

      <div className="rp-scrub">
        <button type="button" className="btn rp-play" onClick={() => { if (step >= last) go(0); setPlaying((p) => !p); }} aria-label={playing ? 'Pause' : 'Play'}>
          <Icon name={playing ? 'pause' : 'play'} />
        </button>
        <div className="rp-track">
          <div className="ticks" aria-hidden="true">
            {events.map((e) => <i key={e.seq} data-kind={e.kind} data-bad={e.kind === 'verify' && e.state === 'rejected' || undefined} data-past={e.seq <= step || undefined} style={{ left: `${(e.seq / last) * 100}%` }} />)}
          </div>
          <input type="range" min={0} max={last} value={step} onChange={(e) => { setPlaying(false); go(Number(e.target.value)); }} aria-label="Step" aria-valuetext={`Step ${step + 1} of ${events.length}`} />
        </div>
        <span className="rp-count">{step + 1} / {events.length}</span>
        <button type="button" className="btn btn-quiet rp-speed" onClick={() => setSpeed(SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length])} aria-label={`Speed ${speed}×`}>{speed}×</button>
        <button type="button" className="btn btn-quiet rp-raw" aria-pressed={raw} onClick={() => setRaw(!raw)}>Raw</button>
        <button type="button" className="btn" onClick={() => { navigator.clipboard.writeText(`${location.origin}${location.pathname}?step=${step}`); setCopied(true); setTimeout(() => setCopied(false), 1200); }}><Icon name={copied ? 'check' : 'link'} small />Copy link</button>
      </div>
    </div>
  );
}

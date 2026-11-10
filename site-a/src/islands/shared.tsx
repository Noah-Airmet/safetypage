// Pieces the interactive parts share: icons, the citation chip, document labels, a menu, and a
// page with a passage lit.
import { useEffect, useRef, useState } from 'react';
import { anchorLabel, anchorOf, docIdOf, hostOf, shortLabel, sourceLink, citePath } from '../lib/cite';
import { docUrl, pageImageUrl, textUrl } from '../lib/env';
import { highlightRects, spanInUnit } from '../lib/quote';
import { closeLayer, openLayerAt } from '../lib/ui';
import type { CitationState, DocumentCard, UnitText } from '../lib/types';

export const Icon = ({ name, sm }: { name: string; sm?: boolean }) => <svg className={sm ? 'i sm' : 'i'} aria-hidden="true"><use href={`/icons.svg#${name}`} /></svg>;

const WORDS = { verified: 'Verified', cited: 'Page only', rejected: 'Rejected', pending: 'Being checked' };

export function Chip(props: { state: CitationState | 'pending'; label: string; href?: string; onClick?: () => void; current?: boolean }) {
  const inner = (<>{props.state === 'verified' && <Icon name="check" />}{props.state === 'rejected' && <Icon name="close" />}<span className="sr">{WORDS[props.state]}: </span><span className="chip-label">{props.label}</span></>);
  if (props.onClick) return <button type="button" className="cite chip" data-state={props.state} aria-current={props.current || undefined} onClick={props.onClick}>{inner}</button>;
  if (props.href) return <a className="cite chip" data-state={props.state} href={props.href}>{inner}</a>;
  return <span className="cite chip" data-state={props.state}>{inner}</span>;
}

/** A state in words with its glyph: On p. 6, Not on p. 6, Verified, Rejected. */
export function State({ state, children }: { state: CitationState; children: React.ReactNode }) {
  return <span className="state" data-state={state}>{state === 'verified' && <Icon name="check" />}{state === 'rejected' && <Icon name="close" />}{children}</span>;
}

export function Tally({ counts }: { counts: Record<CitationState, number> }) {
  return (
    <span className="tally">
      <span data-state="verified"><b>{counts.verified}</b> verified</span>
      <span data-state="cited"><b>{counts.cited}</b> page only</span>
      <span data-state="rejected"><b>{counts.rejected}</b> rejected</span>
    </span>
  );
}

/** One button naming its choice (inverted once one is chosen), opening a menu of the choices. */
export function Pick(props: { id: string; label: string; value: string; options: { value: string; label: string; n?: number }[]; onPick: (value: string) => void }) {
  const menu = useRef<HTMLElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const chosen = props.options.find((o) => o.value === props.value && o.value);
  return (
    <>
      <button type="button" ref={button} className={chosen ? 'btn pick chosen' : 'btn pick'} aria-haspopup="menu" onClick={() => menu.current && openLayerAt(menu.current, button.current)}>
        <span>{chosen ? chosen.label : props.label}</span><Icon name="expand" />
      </button>
      <section ref={menu} className="layer" id={props.id} data-layer="tool" data-shape="menu" hidden aria-label={props.label}>
        <div className="grab" />
        <div className="body menu-rows" role="menu">
          {[{ value: '', label: 'Any' }, ...props.options].map((o) => (
            <button type="button" key={o.value} role="menuitemradio" aria-checked={o.value === props.value} onClick={() => { closeLayer(); props.onPick(o.value); }}>
              <Icon name="check" sm /><span className="k">{o.label}</span>{'n' in o && o.n != null && <span className="n">{o.n.toLocaleString('en')}</span>}
            </button>
          ))}
        </div>
      </section>
    </>
  );
}

const jsonCache = new Map<string, Promise<unknown>>();
export function getJson<T>(url: string): Promise<T | null> {
  if (!jsonCache.has(url)) jsonCache.set(url, fetch(url).then((r) => (r.ok ? r.json() : null)).catch(() => null));
  return jsonCache.get(url) as Promise<T | null>;
}

/** Document cards for a set of doc ids, as they arrive. */
export function useDocs(docIds: string[]): Record<string, DocumentCard> {
  const [docs, setDocs] = useState<Record<string, DocumentCard>>({});
  const key = [...new Set(docIds)].sort().join(' ');
  useEffect(() => {
    let live = true;
    for (const id of key ? key.split(' ') : []) {
      getJson<DocumentCard>(docUrl(id)).then((card) => live && card && setDocs((d) => ({ ...d, [id]: card })));
    }
    return () => { live = false; };
  }, [key]);
  return docs;
}

export const citeLabel = (cite: string, docs: Record<string, Pick<DocumentCard, 'authors' | 'org' | 'published' | 'title'>>) => {
  const doc = docs[docIdOf(cite)];
  const anchor = anchorOf(cite);
  return [doc ? shortLabel(doc) : docIdOf(cite), anchor && anchorLabel(anchor)].filter(Boolean).join(' · ');
};

/** One page with a passage lit (or outlined, for a rejection). A page read at its source shows the way there. */
export function PageView(props: { cite: string; span?: [number, number] | null; kind?: 'found' | 'reject' | null; doc?: Pick<DocumentCard, 'title' | 'source_url' | 'tier'>; quote?: string | null }) {
  const { cite, span, kind, doc } = props;
  const [unit, setUnit] = useState<UnitText | null | undefined>(undefined);
  useEffect(() => {
    let live = true;
    setUnit(undefined);
    getJson<UnitText>(textUrl(cite)).then((u) => live && setUnit(u));
    return () => { live = false; };
  }, [cite]);
  const anchor = anchorOf(cite);
  if (unit === undefined) return <div className="pv pv-empty" aria-busy="true" />;
  if (unit === null || !unit.text) {
    return (
      <div className="pv pv-source" tabIndex={0}>
        <p className="pv-where">{anchorLabel(anchor)} · Read at source</p>
        <p className="pv-title">{doc?.title ?? docIdOf(cite)}</p>
        {doc && <a className="btn" href={sourceLink(doc.source_url, anchor, anchor.startsWith('p'))} rel="noopener"><Icon name="external" /><span>{hostOf(doc.source_url)}</span></a>}
      </div>
    );
  }
  const range = span ? spanInUnit(unit, span) : null;
  if (!unit.width || !unit.height) {
    const text = unit.text;
    return (
      <div className="pv pv-text" tabIndex={0}>
        <p className="pv-where">{unit.anchor_label}</p>
        <p className="pv-para">{range ? <>{text.slice(0, range[0])}<mark data-kind={kind ?? undefined}>{text.slice(range[0], range[1])}</mark>{text.slice(range[1])}</> : text}</p>
      </div>
    );
  }
  const rects = range ? highlightRects(unit, range[0], range[1]) : [];
  const top = rects.length ? Math.min(...rects.map((r) => r.top)) : 0;
  const shift = Math.max(0, top - 14);
  return (
    <div className="pv pv-page">
      <div className="sheet" style={{ aspectRatio: `${unit.width}/${unit.height}`, transform: `translateY(-${shift.toFixed(2)}%)` }}>
        <img src={pageImageUrl(cite, 1600)} alt={`${doc?.title ?? ''} ${unit.anchor_label}`} width={Math.round(unit.width)} height={Math.round(unit.height)} />
        {rects.map((r, i) => <div key={i} className="hl" data-kind={kind === 'reject' ? 'reject' : undefined} style={{ left: `${r.left}%`, top: `${r.top}%`, width: `${r.width}%`, height: `${r.height}%` }} />)}
      </div>
    </div>
  );
}

export { citePath };

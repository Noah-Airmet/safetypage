// Link preview cards, drawn at build time with Satori and resvg. 1200 x 630, paper theme.
// The footer is the wordmark and nothing else.
import fs from 'node:fs';
import { createRequire } from 'node:module';
import satori from 'satori';
import { Resvg } from '@resvg/resvg-js';

const require = createRequire(import.meta.url);
const font = (pkg: string, file: string) => fs.readFileSync(require.resolve(`@fontsource/${pkg}/files/${file}`));
const fonts = [
  { name: 'Serif', data: font('source-serif-4', 'source-serif-4-latin-400-normal.woff'), weight: 400 as const, style: 'normal' as const },
  { name: 'Serif', data: font('source-serif-4', 'source-serif-4-latin-600-normal.woff'), weight: 600 as const, style: 'normal' as const },
  { name: 'Sans', data: font('ibm-plex-sans', 'ibm-plex-sans-latin-500-normal.woff'), weight: 500 as const, style: 'normal' as const },
  { name: 'Mono', data: font('ibm-plex-mono', 'ibm-plex-mono-latin-400-normal.woff'), weight: 400 as const, style: 'normal' as const },
];

const INK = '#1c1b18', INK2 = '#5e5b53', BG = '#fbfaf6', ACCENT = '#1a5fd0', REJECT = '#b23c25', RULE = '#dedbd2';

type Node = { type: string; props: Record<string, unknown> };
const h = (type: string, style: Record<string, unknown>, ...children: (Node | string | null | false | undefined)[]): Node => ({
  type, props: { style: { display: 'flex', ...style }, children: children.filter((c) => c !== null && c !== false && c !== undefined) },
});
const clip = (text: string, max: number) => (text.length > max ? text.slice(0, text.lastIndexOf(' ', max)) + '…' : text);

export interface Card {
  rubric: string;
  title: string;
  /** A mark before the line under the title: verified, rejected, or none. */
  state?: 'verified' | 'rejected' | 'cited';
  line?: string;
  detail?: string;
  quote?: boolean;
}

export async function renderCard(card: Card): Promise<Uint8Array<ArrayBuffer>> {
  const colour = card.state === 'rejected' ? REJECT : card.state === 'verified' ? ACCENT : INK2;
  const size = card.title.length > 150 ? 40 : card.title.length > 90 ? 48 : card.title.length > 50 ? 58 : 70;
  const mark = card.state === 'verified'
    ? h('div', { width: 22, height: 22, borderRadius: 11, background: colour })
    : card.state === 'cited'
      ? h('div', { width: 22, height: 22, borderRadius: 11, border: `4px solid ${colour}` })
      : card.state === 'rejected'
        ? h('div', { fontFamily: 'Sans', fontSize: 34, color: colour, lineHeight: 1 }, '×')
        : null;
  const tree = h('div', { width: 1200, height: 630, background: BG, color: INK },
    h('div', { width: 20, height: 630, background: card.state === 'rejected' ? REJECT : ACCENT }),
    h('div', { width: 1040, height: 520, margin: '58px 70px 52px', flexDirection: 'column' },
      h('div', { fontFamily: 'Sans', fontSize: 26, color: INK2 }, clip(card.rubric, 70)),
      h('div', { fontFamily: 'Serif', fontSize: size, lineHeight: 1.16, marginTop: 26, letterSpacing: -0.5, flexGrow: 1, width: 1040 }, card.quote ? `“${clip(card.title, 210)}”` : clip(card.title, 210)),
      card.line ? h('div', { alignItems: 'center', gap: 16, fontFamily: 'Sans', fontSize: 32, color: colour, marginBottom: card.detail ? 8 : 24 }, mark, card.line) : null,
      card.detail ? h('div', { fontFamily: 'Serif', fontSize: 28, color: INK2, marginBottom: 24 }, clip(card.detail, 70)) : null,
      h('div', { borderTop: `2px solid ${RULE}`, paddingTop: 20, fontFamily: 'Serif', fontWeight: 600, fontSize: 30, width: 1040 }, 'On the Page'),
    ),
  );
  const svg = await satori(tree as never, { width: 1200, height: 630, fonts });
  return new Uint8Array(new Resvg(svg).render().asPng());
}

export const png = (bytes: Uint8Array<ArrayBuffer>) => new Response(bytes, { headers: { 'Content-Type': 'image/png' } });

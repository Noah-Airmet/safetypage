// Link preview cards, drawn at build time with Satori and resvg. 1200 x 630, always the dark
// canvas: a cloth spine tooled in gilt down the left edge, the serif for what is read, Geist for the rest.
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
  { name: 'Sans', data: font('geist-sans', 'geist-sans-latin-400-normal.woff'), weight: 400 as const, style: 'normal' as const },
  { name: 'Sans', data: font('geist-sans', 'geist-sans-latin-500-normal.woff'), weight: 500 as const, style: 'normal' as const },
];

const INK = '#EDEBE4', INK2 = '#A6A39B', INK3 = '#86837B', BG = '#0D0D0C', ACCENT = '#1AADFF', CLOTH = '#34507D', GILT = '#D3B26A';

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
  const colour = card.state === 'verified' ? ACCENT : INK2;
  const size = card.title.length > 150 ? 40 : card.title.length > 90 ? 48 : card.title.length > 50 ? 58 : 70;
  const mark = card.state === 'verified'
    ? h('div', { width: 22, height: 22, borderRadius: 11, background: colour })
    : card.state === 'cited'
      ? h('div', { width: 22, height: 22, borderRadius: 11, border: `4px solid ${colour}` })
      : card.state === 'rejected'
        ? h('div', { fontFamily: 'Sans', fontSize: 38, color: INK3, lineHeight: 1 }, '×')
        : null;
  const tree = h('div', { width: 1200, height: 630, background: BG, color: INK },
    h('div', { width: 28, height: 630, background: CLOTH, flexDirection: 'column', justifyContent: 'space-between', padding: '26px 0' },
      h('div', { flexDirection: 'column', gap: 7 }, h('div', { width: 28, height: 3, background: GILT }), h('div', { width: 28, height: 2, background: GILT })),
      h('div', { width: 28, height: 2, background: GILT }),
    ),
    h('div', { width: 1040, height: 520, margin: '58px 62px 52px 70px', flexDirection: 'column' },
      h('div', { fontFamily: 'Sans', fontSize: 26, color: INK3 }, clip(card.rubric, 70)),
      h('div', { fontFamily: 'Serif', fontSize: size, lineHeight: 1.16, marginTop: 26, letterSpacing: -0.5, flexGrow: 1, width: 1040 }, card.quote ? `“${clip(card.title, 210)}”` : clip(card.title, 210)),
      card.line ? h('div', { alignItems: 'center', gap: 16, fontFamily: 'Sans', fontSize: 32, color: colour, marginBottom: card.detail ? 8 : 24 }, mark, card.line) : null,
      card.detail ? h('div', { fontFamily: 'Serif', fontSize: 28, color: INK2, marginBottom: 24, textDecoration: card.state === 'rejected' ? 'none' : 'none' }, clip(card.detail, 70)) : null,
      h('div', { fontFamily: 'Sans', fontWeight: 400, fontSize: 32, letterSpacing: -1.4, color: INK, width: 1040 }, 'SafetyPage'),
    ),
  );
  const svg = await satori(tree as never, { width: 1200, height: 630, fonts });
  return new Uint8Array(new Resvg(svg).render().asPng());
}

export const png = (bytes: Uint8Array<ArrayBuffer>) => new Response(bytes, { headers: { 'Content-Type': 'image/png' } });

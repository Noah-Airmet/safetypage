// ui-check (~/development/tools/ui-check): what to check on this site, on the real library.
// Build against a snapshot and serve it first (site/README.md, "On the real library"):
//   node scripts/serve.mjs dist 4412
// UI_CHECK_SCHEME=dark runs the same pages in the dark theme, with its own screenshots.
const q = encodeURIComponent;
const dark = process.env.UI_CHECK_SCHEME === 'dark';
export default {
  base: process.env.UI_CHECK_BASE ?? 'http://localhost:4412',
  scheme: dark ? 'dark' : 'light',
  dir: dark ? 'ui-check/dark' : 'ui-check',
  pages: [
    { name: 'home', path: '/', states: [{ name: 'rejected', click: ['.claim[data-pick="rejected"]'] }] },
    { name: 'library', path: '/library' },
    { name: 'shelf', path: '/library/labs' },
    { name: 'shelf-filtered', path: '/library/papers?year=2024&q=sparse' },
    { name: 'record', path: '/d/arxiv/2305.15324' },
    { name: 'record-source', path: '/d/anthropic/claude-opus-5-5-system-card' },
    { name: 'reader', path: `/d/arxiv/2305.15324/v2/p6?q=${q('not the only tool available for AI risk assessment')}` },
    { name: 'reader-text', path: '/d/distill/zoom-in/r1/b21' },
    // Read at source: a system card, a Transformer Circuits paper, an Alignment Forum post, an arXiv paper.
    { name: 'reader-source-card', path: `/d/anthropic/claude-opus-5-5-system-card/r1/p135?q=${q('reviewed the highest-scoring reports on the deliberate sabotage dimension')}` },
    { name: 'reader-source-circuits', path: '/d/anthropic/2024-scaling-monosemanticity/r1/b20' },
    { name: 'reader-source-forum', path: '/d/lw/LNA8mubrByG7SFacm/r1/b85' },
    { name: 'reader-source-arxiv', path: '/d/arxiv/2401.05566/v3/p5' },
    { name: 'search-empty', path: '/search', mask: ['.wall'] },
    { name: 'search', path: `/search?query=${q('"alignment faking"')}` },
    { name: 'follow', path: '/follow/sabotage' },
    // The page beside the findings arrives after the check and Chrome redraws it once at full
    // quality, so two captures can differ in its fine lines: it is left out of the comparison.
    { name: 'check', path: '/check?example=1', mask: ['.evidence .sheet img'] },
    { name: 'replay', path: '/r/cc-haiku-5-5-4e1c63-pc-4bd058594c.1?step=21' },
    { name: 'citationbench', path: '/citationbench', mask: ['.board tbody', '.facts'] },   // rows change as runs land
    { name: 'connect', path: '/connect' },
  ],
  widths: [1440, 390],
};

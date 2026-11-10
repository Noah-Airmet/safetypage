// ui-check (~/development/tools/ui-check): what to check on this site, on the real library.
// Build against a snapshot and serve it first (README.md, "On the real library"):
//   node scripts/serve.mjs dist 4398
// The site is dark only. The design doc the review reads is the Gospel Scholar Archive's.
const q = encodeURIComponent;
export default {
  base: 'http://localhost:4398',
  scheme: 'dark',
  dir: 'ui-check',
  designDoc: '/Users/noahairmet/development/homelab/gsa-dash/DESIGN.md',
  pages: [
    { name: 'home', path: '/', mask: ['.wall'], states: [{ name: 'check', click: ['[data-mode="check"]'] }, { name: 'help', click: ['[data-open="help"]'] }] },
    { name: 'library', path: '/library', states: [{ name: 'sidebar', click: ['#side-btn'] }] },
    { name: 'shelf', path: '/library/labs', states: [{ name: 'menu', click: ['[data-pick="publisher"]'] }] },
    { name: 'shelf-filtered', path: '/library/papers?year=2024&q=sparse' },
    { name: 'record', path: '/d/arxiv/2305.15324', states: [{ name: 'cite', click: ['[data-open="cite-pop"]'] }] },
    { name: 'record-source', path: '/d/anthropic/claude-opus-5-5-system-card' },
    { name: 'reader', path: `/d/arxiv/2305.15324/v2/p6?q=${q('not the only tool available for AI risk assessment')}`, states: [{ name: 'more', click: ['[data-open="r-more"]'] }] },
    { name: 'reader-text', path: '/d/distill/zoom-in/r1/b21' },
    { name: 'reader-source', path: `/d/anthropic/claude-opus-5-5-system-card/r1/p135?q=${q('reviewed the highest-scoring reports on the deliberate sabotage dimension')}` },
    { name: 'search', path: `/search?query=${q('"alignment faking"')}` },
    { name: 'follow', path: '/follow/sabotage' },
    { name: 'check', path: '/check?example=1' },
    { name: 'replay', path: '/r/cc-sonnet-5-5-43677d-pc-7abbdba8ab.1?step=14' },
    { name: 'citationbench', path: '/citationbench' },
    { name: 'connect', path: '/connect' },
    { name: 'about', path: '/about' },
  ],
  widths: [1440, 390],
};

// ui-check (~/development/tools/ui-check): what to check on this site.
// Start the site first: `npm run api` and `npm run dev -- --port 4391`.
const q = encodeURIComponent;
export default {
  base: 'http://localhost:4391',
  pages: [
    { name: 'home', path: '/', states: [{ name: 'rejected', click: ['.chip[data-state="rejected"]'] }] },
    { name: 'library', path: '/library' },
    { name: 'record', path: '/d/arxiv/2305.15324' },
    { name: 'record-source', path: '/d/example/link-only-eval-report' },
    { name: 'reader', path: `/d/arxiv/2305.15324/v2/p6?q=${q('not the only tool available for AI risk assessment')}` },
    { name: 'reader-text', path: `/d/distill/zoom-in/r1/b21?q=${q('Features are the fundamental unit of neural networks')}` },
    { name: 'reader-source', path: '/d/example/link-only-eval-report/r1/p2' },
    { name: 'search', path: `/search?query=${q('"risk assessment" evaluation')}` },
    { name: 'check', path: '/check?example=1' },
    { name: 'replay', path: '/r/cc-sonnet-5-5-43677d-pc-7abbdba8ab.1?step=14' },
    { name: 'citationbench', path: '/citationbench', mask: ['.board tbody', '.facts'] },   // rows change as runs land
    { name: 'connect', path: '/connect' },
  ],
  widths: [1440, 390],
};

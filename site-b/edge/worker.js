// The one edge rule the static site needs, as a Cloudflare Pages worker. The build copies this
// to dist/_worker.js with the library's address filled in, and dist/_routes.json sends only
// /d/* here, so every other page is a plain file.
//
//   /d/<ns>/<id>/<version>/<anchor>   the reader's shell (/reader), with the document's title
//                                     and preview tags written in, so a citation link unfurls
//                                     as "Shevlane et al. 2023, p. 6"
//   /d/<ns>/<id>/<version>            the document's record page, when that version has no page
//                                     of its own (it is the latest)
//   /d/<ns>/<id>                      the record page, a file

const DATA = '__DATA_BASE__';   // where the snapshot's public files are served
const READER = /^\/d\/([a-z0-9-]+)\/([A-Za-z0-9._-]+)\/([vr]\d+)\/([pb])(\d+)(?:-[pb]?\d+)?\/?$/;
const VERSION = /^(\/d\/[a-z0-9-]+\/[A-Za-z0-9._-]+)\/[vr]\d+\/?$/;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const reader = READER.exec(url.pathname);
    if (reader) {
      const shell = await env.ASSETS.fetch(new URL('/reader', url));
      // The card is fetched to name the page in the preview. If the library's origin is slow or
      // down, the shell goes out as it is and the browser reports what it finds.
      const card = await fetch(`${DATA}/docs/${reader[1]}/${reader[2]}.json`, { signal: AbortSignal.timeout(2500), cf: { cacheEverything: true, cacheTtl: 86400 } })
        .then((r) => (r.ok ? r.json() : r.status === 404 ? null : undefined)).catch(() => undefined);
      if (card === undefined) return shell;
      const version = card?.versions.find((v) => v.version === reader[3]);
      if (!version) return new Response((await env.ASSETS.fetch(new URL('/404', url))).body, { status: 404, headers: { 'content-type': 'text/html; charset=utf-8' } });
      return named(shell, url, card, version, reader[4], reader[5]);
    }
    // An older version has a record page of its own; the latest version's is the document's.
    const page = await env.ASSETS.fetch(request);
    const record = VERSION.exec(url.pathname);
    return record && page.status === 404 ? env.ASSETS.fetch(new URL(record[1], url)) : page;
  },
};

function named(shell, url, card, version, letter, n) {
  const where = letter === 'p' ? `p. ${n}` : `¶${n}`;
  const title = `${shortLabel(card)}, ${where}`;
  const description = `${card.title}, ${where}. ${version.tier === 'open' ? 'Read the page here.' : 'Search it, check a quote, and open it at its source.'}`;
  const here = url.origin + url.pathname;
  const set = (name, value) => ({ element: (e) => e.setAttribute(name, value) });
  let page = new HTMLRewriter()
    .on('title', { element: (e) => e.setInnerContent(`${title} · SafetyPage`) })
    .on('meta[name="description"], meta[property="og:description"]', set('content', description))
    .on('meta[property="og:title"]', set('content', title))
    .on('meta[property="og:url"]', set('content', here))
    .on('link[rel="canonical"]', set('href', here))
    .on('head', { element: (e) => e.append(`<script id="doc-card" type="application/json">${JSON.stringify(card).replace(/</g, '\\u003c')}</script>`, { html: true }) });
  // An open PDF page is its own preview image.
  if (version.tier === 'open' && letter === 'p') {
    const image = `${DATA}/pages/${card.doc_id.replace(':', '/')}/${version.version}/p${n}.800.webp`;
    page = page.on('meta[property="og:image"], meta[name="twitter:image"]', set('content', image)).on('meta[property^="og:image:"]', { element: (e) => e.remove() });
  }
  return page.transform(shell);
}

// `Shevlane et al. 2023`, or the organisation when there are no authors (as in src/lib/cite.ts).
function shortLabel(card) {
  const year = card.published?.slice(0, 4);
  const surname = (name) => (name.includes(',') ? name.split(',')[0] : name.trim().split(/\s+/).pop()).trim();
  const who = !card.authors.length ? (card.org ?? card.title)
    : card.authors.length === 1 ? surname(card.authors[0])
    : card.authors.length === 2 ? `${surname(card.authors[0])} & ${surname(card.authors[1])}` : `${surname(card.authors[0])} et al.`;
  return year ? `${who} ${year}` : who;
}

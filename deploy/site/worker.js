// The edge rule for the static site, as a Cloudflare Worker in front of the built files.
//
//   /d/<ns>/<id>/<version>/<anchor>   the reader's shell (/reader), with the document's card and
//                                     its title and preview tags written in, so a citation link
//                                     unfurls as "Shevlane et al. 2023, p. 6"
//   /d/<ns>/<id>/<version>            the document's record page, when that version has no page
//                                     of its own (it is the latest)
//   /data/…                           the snapshot's public/ tree, from the R2 bucket bound as DATA
//   /api/…, /mcp, /x/…                the search server (API_ORIGIN)
//
// Everything else is a static file and never reaches this code.

const READER = /^\/d\/([a-z0-9-]+)\/([A-Za-z0-9._-]+)\/([vr]\d+)\/([pb])(\d+)(?:-[pb]?\d+)?\/?$/;
const VERSION = /^(\/d\/[a-z0-9-]+\/[A-Za-z0-9._-]+)\/[vr]\d+\/?$/;
const TYPES = { json: 'application/json', webp: 'image/webp', pdf: 'application/pdf', html: 'text/html; charset=utf-8' };

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    if (path.startsWith('/api/') || path === '/mcp' || path.startsWith('/x/')) {
      return fetch(new Request(env.API_ORIGIN + path + url.search, request));
    }

    if (path.startsWith('/data/')) {
      const object = await env.DATA.get(decodeURIComponent(path.slice('/data/'.length)));
      if (!object) return new Response('Not found', { status: 404 });
      const headers = new Headers({ 'content-type': TYPES[path.split('.').pop()] ?? 'application/octet-stream', 'cache-control': 'public, max-age=3600', etag: object.httpEtag });
      return new Response(object.body, { headers });
    }

    const reader = READER.exec(path);
    if (reader) {
      const [, ns, id, version, letter, n] = reader;
      const object = await env.DATA.get(`docs/${ns}/${id}.json`);
      if (!object) return notFound(env, url);
      const card = await object.json();
      const v = card.versions.find((x) => x.version === version);
      if (!v) return notFound(env, url);
      const where = letter === 'p' ? `p. ${n}` : `¶${n}`;
      const title = `${shortLabel(card)}, ${where}`;
      const description = `${card.title}, ${where}. ${v.tier === 'open' ? 'Read the page here.' : 'Search it, check a quote, and open it at its source.'}`;
      // An open PDF page is its own preview image.
      const image = v.tier === 'open' && letter === 'p' ? `${url.origin}/data/pages/${ns}/${id}/${version}/p${n}.800.webp` : null;
      const here = url.origin + path;
      const set = (name, value) => ({ element: (e) => e.setAttribute(name, value) });
      let page = new HTMLRewriter()
        .on('title', { element: (e) => e.setInnerContent(`${title} · SafetyPage`) })
        .on('meta[name="description"], meta[property="og:description"]', set('content', description))
        .on('meta[property="og:title"]', set('content', title))
        .on('meta[property="og:url"]', set('content', here))
        .on('link[rel="canonical"]', set('href', here))
        .on('head', { element: (e) => e.append(`<script id="doc-card" type="application/json">${JSON.stringify(card).replace(/</g, '\\u003c')}</script>`, { html: true }) });
      if (image) page = page.on('meta[property="og:image"], meta[name="twitter:image"]', set('content', image)).on('meta[property^="og:image:"]', { element: (e) => e.remove() });
      return page.transform(await env.ASSETS.fetch(new URL('/reader', url)));
    }

    // An older version has a record page of its own; the latest version's is the document's.
    const page = await env.ASSETS.fetch(request);
    const record = VERSION.exec(path);
    return record && page.status === 404 ? env.ASSETS.fetch(new URL(record[1], url)) : page;
  },
};

const notFound = async (env, url) => new Response((await env.ASSETS.fetch(new URL('/404', url))).body, { status: 404, headers: { 'content-type': TYPES.html } });

// `Shevlane et al. 2023`, or the organisation when there are no authors (as in site/src/lib/cite.ts).
function shortLabel(card) {
  const year = card.published?.slice(0, 4);
  const surname = (name) => name.trim().split(/\s+/).pop();
  const who = !card.authors.length ? (card.org ?? card.title)
    : card.authors.length === 1 ? surname(card.authors[0])
    : card.authors.length === 2 ? `${surname(card.authors[0])} & ${surname(card.authors[1])}` : `${surname(card.authors[0])} et al.`;
  return year ? `${who} ${year}` : who;
}

// Where the browser finds things. API_BASE is the origin of the search server and the library's
// public files (PUBLIC_API_BASE; empty means this site's own origin). DATA_BASE is where the
// snapshot's public files are; astro.config.mjs works it out from the API origin and the snapshot.
export const API_BASE: string = (import.meta.env.PUBLIC_API_BASE ?? '').replace(/\/$/, '');
export const DATA_BASE: string = (import.meta.env.PUBLIC_DATA_BASE ?? '/data').replace(/\/$/, '');
/** The MCP endpoint's address, given the site's origin. */
export const mcpUrl = (site: string) => `${API_BASE || site}/mcp`;

const dataPath = (area: string, cite: string) => {
  const [docId, version, anchor] = cite.split('/');
  return `${DATA_BASE}/${area}/${docId.replace(':', '/')}/${version}/${anchor}`;
};
export const textUrl = (cite: string) => `${dataPath('text', cite)}.json`;
export const pageImageUrl = (cite: string, width: 800 | 1600) => `${dataPath('pages', cite)}.${width}.webp`;
export const docUrl = (docId: string) => `${DATA_BASE}/docs/${docId.replace(':', '/')}.json`;

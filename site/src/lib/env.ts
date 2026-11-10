// Where the browser finds things. Both default to the same origin.
export const DATA_BASE: string = (import.meta.env.PUBLIC_DATA_BASE ?? '/data').replace(/\/$/, '');
export const API_BASE: string = (import.meta.env.PUBLIC_API_BASE ?? '').replace(/\/$/, '');
export const MCP_URL: string = import.meta.env.PUBLIC_MCP_URL ?? '';

const dataPath = (area: string, cite: string) => {
  const [docId, version, anchor] = cite.split('/');
  return `${DATA_BASE}/${area}/${docId.replace(':', '/')}/${version}/${anchor}`;
};
export const textUrl = (cite: string) => `${dataPath('text', cite)}.json`;
export const pageImageUrl = (cite: string, width: 800 | 1600) => `${dataPath('pages', cite)}.${width}.webp`;
export const docUrl = (docId: string) => `${DATA_BASE}/docs/${docId.replace(':', '/')}.json`;

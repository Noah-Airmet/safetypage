// Build-time calls to the search server (docs/SERVER.md). The landing page's two quote checks
// and the follow pages' saved searches are made against the snapshot the site is built for,
// so what is printed is what the server says. SAFETYPAGE_API names the server.
const API = (process.env.SAFETYPAGE_API ?? 'http://127.0.0.1:8791').replace(/\/$/, '');
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const cache = new Map<string, Promise<unknown>>();

async function call<T>(path: string, body?: unknown): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    try {
      const response = await fetch(API + path, body === undefined ? undefined : { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
      if (response.status === 429 && attempt < 30) { await sleep(2000); continue; }   // the server's rate limit
      if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
      return (await response.json()) as T;
    } catch (error) {
      const down = error instanceof TypeError;   // not listening yet
      if (!down || attempt >= 20) throw new Error(`The build asks the search server at ${API}${path} and it ${down ? 'is not answering' : 'said: ' + (error as Error).message}. Start it, or set SAFETYPAGE_API.`);
      await sleep(1000);
    }
  }
}

/** One call per distinct request for the whole build. */
export function api<T>(path: string, body?: unknown): Promise<T> {
  const key = path + (body === undefined ? '' : JSON.stringify(body));
  if (!cache.has(key)) cache.set(key, call<T>(path, body));
  return cache.get(key) as Promise<T>;
}

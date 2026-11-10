// What every room's script shares: icons from the sprite, copying, the Copied chip, and the
// layers (a popover or panel on desktop, a sheet on a phone; one at a time; Escape, a press
// outside or a drag down closes the one that's open).
export const esc = (s: string) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);
export const icon = (name: string, cls = '') => `<svg class="i${cls ? ' ' + cls : ''}" aria-hidden="true"><use href="/icons.svg#${name}"></use></svg>`;

export async function copyText(text: string): Promise<void> {
  if (navigator.clipboard && isSecureContext) return navigator.clipboard.writeText(text);
  const ta = Object.assign(document.createElement('textarea'), { value: text, readOnly: true, className: 'offscreen' });
  document.body.append(ta);
  ta.select();
  ta.setSelectionRange(0, text.length);
  const ok = document.execCommand('copy');
  ta.remove();
  if (!ok) throw new Error('copy refused');
}

let toastTimer = 0;
export function toast(words: string, glyph = 'check') {
  let el = document.querySelector<HTMLElement>('.toast');
  if (!el) {
    el = document.createElement('div');
    el.className = 'toast frost';
    el.setAttribute('role', 'status');
    document.body.append(el);
  }
  el.innerHTML = `${icon(glyph)}<span>${esc(words)}</span>`;
  requestAnimationFrame(() => el!.classList.add('on'));
  clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => el!.classList.remove('on'), 1400);
}

/** Copy, and say so on the control itself with the drawn check. */
export async function copyFrom(button: HTMLElement, text: string) {
  try {
    await copyText(text);
    button.classList.add('done');
    const use = button.querySelector('use');
    const was = use?.getAttribute('href');
    use?.setAttribute('href', '/icons.svg#check');
    toast('Copied');
    setTimeout(() => { button.classList.remove('done'); if (was) use?.setAttribute('href', was); }, 1400);
  } catch {
    toast('Copy failed', 'close');
  }
}

// ---- layers
const phone = () => matchMedia('(max-width: 720px)').matches;
let openLayer: { el: HTMLElement; anchor: HTMLElement | null; scrim: HTMLElement; pushed: boolean } | null = null;

export function closeLayer(fromHistory = false) {
  const cur = openLayer;
  if (!cur) return;
  openLayer = null;
  cur.el.classList.add('out');
  cur.scrim.classList.remove('on');
  cur.anchor?.setAttribute('aria-expanded', 'false');
  const done = () => { if (openLayer?.el !== cur.el) cur.el.hidden = true; cur.scrim.remove(); };
  setTimeout(done, phone() ? 280 : 160);
  if (cur.pushed && !fromHistory && history.state?.layer) history.back();
  cur.el.dispatchEvent(new CustomEvent('layer:close'));
}

export function openLayerAt(el: HTMLElement, anchor: HTMLElement | null) {
  if (openLayer?.el === el) return closeLayer();
  closeLayer();
  const kind = el.dataset.layer ?? 'tool';
  const sheet = phone();
  el.classList.remove('popover', 'panel', 'as-sheet', 'up');
  el.classList.add('frost', sheet ? 'as-sheet' : kind === 'list' ? 'panel' : 'popover', 'out');
  el.style.cssText = '';
  el.hidden = false;
  const scrim = document.createElement('div');
  scrim.className = sheet && kind === 'list' ? 'scrim' : 'scrim clear';
  scrim.addEventListener('click', () => closeLayer());
  el.before(scrim);
  if (!sheet && kind !== 'list' && anchor) {
    const a = anchor.getBoundingClientRect();
    const w = el.offsetWidth, h = el.offsetHeight;
    const left = a.left + a.width / 2 < innerWidth / 2 ? Math.max(6, a.left) : Math.min(innerWidth - w - 6, a.right - w);
    const below = a.bottom + 8 + h <= innerHeight - 6 || a.top - 8 - h < 6;
    el.style.left = `${Math.max(6, left)}px`;
    el.style.top = `${below ? a.bottom + 8 : a.top - 8 - h}px`;
    el.style.transformOrigin = `${a.left + a.width / 2 < innerWidth / 2 ? 'left' : 'right'} ${below ? 'top' : 'bottom'}`;
    if (!below) el.classList.add('up');
  }
  anchor?.setAttribute('aria-expanded', 'true');
  let pushed = false;
  if (sheet) { history.pushState({ ...(history.state ?? {}), layer: el.id }, ''); pushed = true; }
  openLayer = { el, anchor, scrim, pushed };
  requestAnimationFrame(() => requestAnimationFrame(() => { el.classList.remove('out'); scrim.classList.add('on'); }));
  if (!sheet) (el.querySelector<HTMLElement>('[autofocus], input, [data-first]') ?? null)?.focus({ preventScroll: true });
  el.dispatchEvent(new CustomEvent('layer:open'));
}

let wired = false;
export function wireLayers() {
  if (wired) return;
  wired = true;
  document.addEventListener('click', (event) => {
    const t = event.target as HTMLElement;
    const opener = t.closest<HTMLElement>('[data-open]');
    if (opener) {
      const el = document.getElementById(opener.dataset.open!);
      if (el) { event.preventDefault(); openLayerAt(el, opener); }
      return;
    }
    if (t.closest('[data-close]')) closeLayer();
  });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && openLayer) { event.stopPropagation(); closeLayer(); } }, true);
  addEventListener('popstate', () => { if (openLayer?.pushed) closeLayer(true); });
  addEventListener('resize', () => { if (openLayer && !phone()) closeLayer(); });
  // a sheet drags down by its grabber or its head; a pull of a quarter of its height, or a flick, closes it
  let drag: { y: number; t: number; el: HTMLElement } | null = null;
  document.addEventListener('pointerdown', (event) => {
    const t = event.target as HTMLElement;
    const el = t.closest<HTMLElement>('.layer.as-sheet');
    if (!el || !(t.closest('.grab') || t.closest('.head')) || t.closest('button, a, input')) return;
    drag = { y: event.clientY, t: event.timeStamp, el };
    el.classList.add('dragging');
  });
  document.addEventListener('pointermove', (event) => {
    if (drag) drag.el.style.transform = `translateY(${Math.max(0, event.clientY - drag.y)}px)`;
  });
  const end = (event: PointerEvent) => {
    if (!drag) return;
    const { el, y, t } = drag;
    drag = null;
    const dy = event.clientY - y;
    el.classList.remove('dragging');
    el.style.transform = '';
    if (dy > el.offsetHeight / 4 || dy / Math.max(1, event.timeStamp - t) > 0.6) closeLayer();
  };
  document.addEventListener('pointerup', end);
  document.addEventListener('pointercancel', end);
}

// ---- the documents this device opened, newest first (the sidebar's Continue)
export interface Recent { href: string; title: string; at: string }
export function remember(entry: Recent, docPath: string) {
  try {
    const list = (JSON.parse(localStorage.getItem('sp-recent') ?? '[]') as (Recent & { doc: string })[]).filter((r) => r.doc !== docPath);
    list.unshift({ ...entry, doc: docPath });
    localStorage.setItem('sp-recent', JSON.stringify(list.slice(0, 5)));
  } catch { /* storage is off: nothing to continue */ }
}

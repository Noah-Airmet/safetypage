// The shell: the sidebar and its toggle, the bar's hairline and Back, the layers, Copy.
import { copyFrom, esc, wireLayers, type Recent } from '../lib/ui';

const root = document.documentElement;
const phone = () => matchMedia('(max-width: 720px)').matches;
const button = document.getElementById('side-btn')!;
const scrim = document.getElementById('scrim')!;

function setSidebar(open: boolean, keep = true) {
  root.classList.toggle('side-open', open);
  root.classList.toggle('side-docked', !phone());
  button.setAttribute('aria-expanded', String(open));
  scrim.hidden = !(open && phone());
  requestAnimationFrame(() => scrim.classList.toggle('on', open && phone()));
  if (keep && !phone()) { try { localStorage.setItem('sp-sidebar', open ? 'open' : 'shut'); } catch { /* not kept */ } }
}
button.addEventListener('click', () => setSidebar(!root.classList.contains('side-open')));
scrim.addEventListener('click', () => setSidebar(false));
button.setAttribute('aria-expanded', String(root.classList.contains('side-open')));
addEventListener('resize', () => {
  const docked = !phone();
  if (docked !== root.classList.contains('side-docked')) setSidebar(docked && localStorage.getItem('sp-sidebar') === 'open', false);
});
requestAnimationFrame(() => requestAnimationFrame(() => root.classList.add('ready')));

// the phone card shuts with a swipe to the left
let sx = 0, sy = 0;
document.getElementById('sidebar')!.addEventListener('touchstart', (e) => { sx = e.touches[0].clientX; sy = e.touches[0].clientY; }, { passive: true });
document.getElementById('sidebar')!.addEventListener('touchend', (e) => {
  const dx = e.changedTouches[0].clientX - sx, dy = e.changedTouches[0].clientY - sy;
  if (phone() && dx < -50 && Math.abs(dy) < 40) setSidebar(false);
}, { passive: true });

// the bar's hairline appears only once the page scrolls under it
const bar = document.querySelector<HTMLElement>('.bar')!;
const under = () => bar.classList.toggle('under', scrollY > 4);
addEventListener('scroll', under, { passive: true });
under();

// Back is the browser's Back, named for where it goes, and absent when nothing of this site is behind.
// A room that has an Up of its own (the reader) sets data-up on the control before this runs.
const back = document.querySelector<HTMLAnchorElement>('.bar .back');
try {
  const names = JSON.parse(sessionStorage.getItem('sp-names') ?? '{}') as Record<string, string>;
  names[location.pathname] = document.body.dataset.name || document.title.replace(/ · SafetyPage$/, '');
  sessionStorage.setItem('sp-names', JSON.stringify(names));
  const from = document.referrer && new URL(document.referrer).origin === location.origin ? new URL(document.referrer).pathname : null;
  if (back && from && from !== location.pathname && history.length > 1) {
    back.querySelector(':scope > span:last-child')!.textContent = names[from] ?? '';
    back.setAttribute('aria-label', `Back: ${names[from] ?? ''}`);
    back.hidden = false;
    back.addEventListener('click', (event) => { event.preventDefault(); history.back(); });
  }
} catch { /* no session storage: no Back */ }

wireLayers();

document.addEventListener('click', (event) => {
  const el = (event.target as HTMLElement).closest<HTMLElement>('[data-copy]');
  if (el) copyFrom(el, el.dataset.copy!);
});

// "/" searches from anywhere; "[" is the sidebar
document.addEventListener('keydown', (event) => {
  if (event.metaKey || event.ctrlKey || event.altKey || (event.target as HTMLElement).closest('input, textarea, select, [contenteditable]')) return;
  if (event.key === '[') setSidebar(!root.classList.contains('side-open'));
  if (event.key === '/') {
    const field = document.querySelector<HTMLInputElement | HTMLTextAreaElement>('.bar .find input, .composer textarea');
    event.preventDefault();
    if (field) field.focus(); else location.href = '/search';
  }
});

// Continue: the documents this device opened
try {
  const list = JSON.parse(localStorage.getItem('sp-recent') ?? '[]') as Recent[];
  const holder = document.getElementById('sb-continue');
  if (holder && list.length) {
    holder.hidden = false;
    holder.insertAdjacentHTML('beforeend', list.map((r) => `<a class="row" href="${esc(r.href)}" title="${esc(r.title)}"><svg class="i" aria-hidden="true"><use href="/icons.svg#doc"></use></svg><span class="one">${esc(r.title)}</span><span class="at">${esc(r.at)}</span></a>`).join(''));
  }
} catch { /* nothing to continue */ }

// the bar's search field keeps the query it is showing
const q = new URLSearchParams(location.search).get('query');
const field = document.querySelector<HTMLInputElement>('.bar .find input');
if (q && field && location.pathname === '/search') field.value = q;

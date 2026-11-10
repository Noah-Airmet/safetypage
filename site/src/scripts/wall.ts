// The wall: first pages from the library in columns that drift in alternating directions, paused
// under the pointer and still under reduced motion. Drawn from the list the page carries.
const wall = document.getElementById('wall');
if (wall) {
  const pages = JSON.parse(wall.dataset.wall!) as { href: string; src: string; title: string }[];
  const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);
  const list = pages.map((p) => [Math.random(), p] as const).sort((a, b) => a[0] - b[0]).map(([, p]) => p);
  const draw = () => {
    if (!wall.clientWidth) return;
    const phone = innerWidth < 700, colw = phone ? 104 : 164, gap = phone ? 12 : 18, per = 5;
    const cols = Math.ceil(wall.clientWidth / (colw + gap)) + 1;
    if (wall.dataset.cols === String(cols)) return;
    wall.dataset.cols = String(cols);
    wall.style.setProperty('--colw', colw + 'px');
    wall.style.setProperty('--gap', gap + 'px');
    let k = 0, covers = '', backs = '';
    for (let c = 0; c < cols; c++) {
      let once = '';
      for (let i = 0; i < per; i++) {
        const p = list[k++ % list.length];
        once += `<a class="wcover" href="${esc(p.href)}" title="${esc(p.title)}"><img alt="" decoding="async" fetchpriority="low" src="${esc(p.src)}" onload="this.classList.add('in')" onerror="this.closest('a').classList.add('gone')"></a>`;
      }
      const dur = (per * (colw * 1.3 + gap)) / (10 + ((c * 5) % 7));
      const col = `class="wcol${c % 2 ? ' down' : ''}" style="--dur:${dur.toFixed(1)}s;--delay:-${(Math.random() * dur).toFixed(1)}s"`;
      covers += `<div ${col}>${once}${once.replace(/<a /g, '<a tabindex="-1" aria-hidden="true" ')}</div>`;
      backs += `<div ${col}>${'<i></i>'.repeat(per * 2)}</div>`;
    }
    wall.querySelector('.wtrack')!.innerHTML = covers;
    wall.querySelector('.wbacks')!.innerHTML = backs;
  };
  draw();
  let t = 0;
  new ResizeObserver(() => { clearTimeout(t); t = window.setTimeout(draw, 200); }).observe(wall);
}

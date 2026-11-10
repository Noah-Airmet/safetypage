// A text box that grows with what you write, between a least and a most number of lines, then
// scrolls. It is measured on a hidden twin, never by setting it to auto and back, so its height
// eases and never jumps.
const twins = new WeakMap<HTMLTextAreaElement, HTMLTextAreaElement>();

export function grow(ta: HTMLTextAreaElement, { min = 1, max = 8 } = {}) {
  let twin = twins.get(ta);
  if (!twin) {
    twin = ta.cloneNode() as HTMLTextAreaElement;
    for (const a of ['id', 'name', 'aria-label']) twin.removeAttribute(a);
    twin.setAttribute('aria-hidden', 'true');
    twin.tabIndex = -1;
    twin.style.cssText = 'position: absolute; left: 0; top: 0; height: 0; overflow: hidden; visibility: hidden; pointer-events: none; transition: none';
    ta.after(twin);
    twins.set(ta, twin);
  }
  twin.style.width = ta.clientWidth + 'px';
  twin.style.fontFamily = getComputedStyle(ta).fontFamily;
  twin.value = ta.value;
  const cs = getComputedStyle(ta), line = parseFloat(cs.lineHeight);
  const pad = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom), text = twin.scrollHeight - pad;
  ta.style.height = Math.min(max * line, Math.max(min * line, text)) + pad + 'px';
  ta.style.overflowY = text > max * line + 1 ? 'auto' : 'hidden';
}

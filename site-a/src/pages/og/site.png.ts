import { png, renderCard } from '../../lib/og';
import { getDoc } from '../../lib/data';
import { anchorLabel, anchorOf, shortLabel } from '../../lib/cite';
import { EXAMPLE } from '../../lib/checks';

// The site's card shows the thing itself: a quotation, checked against the page it names.
export async function GET() {
  const doc = getDoc(EXAMPLE.cite.split('/')[0])!;
  return png(await renderCard({
    rubric: doc.title,
    title: EXAMPLE.verified,
    quote: true,
    state: 'verified',
    line: `${shortLabel(doc)} · ${anchorLabel(anchorOf(EXAMPLE.cite))}`,
  }));
}

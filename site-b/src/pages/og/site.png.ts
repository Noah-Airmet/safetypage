import { png, renderCard } from '../../lib/og';
import { allDocs } from '../../lib/data';

export async function GET() {
  return png(await renderCard({
    rubric: `A library of the AI safety record · ${allDocs().length} documents`,
    title: 'We check that the page says it, and show you the page.',
    state: 'verified',
    line: 'Every citation checked against the page it names',
  }));
}

import type { APIContext } from 'astro';
import { png, renderCard } from '../../../lib/og';
import { allTraces } from '../../../lib/data';
import type { Trace } from '../../../lib/types';

export const getStaticPaths = () => allTraces().map((trace) => ({ params: { id: trace.header.trace_id }, props: { trace } }));

export async function GET({ props }: APIContext) {
  const trace = (props as { trace: Trace }).trace;
  const count = (s: string) => trace.answer?.citations.filter((c) => c.state === s).length ?? 0;
  return png(await renderCard({
    rubric: `Replay · ${trace.header.model}`, title: trace.header.question,
    line: `${count('verified')} verified · ${count('cited')} page only · ${count('rejected')} rejected`,
  }));
}

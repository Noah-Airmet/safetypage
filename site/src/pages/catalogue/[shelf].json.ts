// /catalogue/<shelf>.json: every document on a shelf, one compact row each, newest first.
import type { APIContext } from 'astro';
import { allShelves, type Shelf } from '../../lib/data';
import { toRow } from '../../lib/catalogue';

export const getStaticPaths = () => allShelves().map((shelf) => ({ params: { shelf: shelf.id }, props: { shelf } }));
export const GET = ({ props }: APIContext) => Response.json((props as { shelf: Shelf }).shelf.docs.map(toRow));

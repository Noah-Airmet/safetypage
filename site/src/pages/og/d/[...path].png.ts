// Preview cards for a document, a version and a page.
import type { APIContext } from 'astro';
import { png, renderCard } from '../../../lib/og';
import { allDocs, unitsOf } from '../../../lib/data';
import { KINDS, anchorLabel, formatDate, licenceName, shortLabel } from '../../../lib/cite';
import type { DocumentCard } from '../../../lib/types';

export function getStaticPaths() {
  const paths: { params: { path: string }; props: { doc: DocumentCard; version: string; anchor?: string } }[] = [];
  for (const doc of allDocs()) {
    const stem = doc.doc_id.replace(':', '/');
    paths.push({ params: { path: stem }, props: { doc, version: doc.version } });
    for (const v of doc.versions) {
      paths.push({ params: { path: `${stem}/${v.version}` }, props: { doc, version: v.version } });
      let anchors = unitsOf(doc.doc_id, v.version).map((u) => u.anchor);
      if (!anchors.length && v.version === doc.version) anchors = Array.from({ length: doc.unit_count }, (_, i) => `${doc.anchor_kind === 'page' ? 'p' : 'b'}${i + 1}`);
      for (const anchor of anchors) paths.push({ params: { path: `${stem}/${v.version}/${anchor}` }, props: { doc, version: v.version, anchor } });
    }
  }
  return paths;
}

export async function GET({ props }: APIContext) {
  const { doc, version, anchor } = props as { doc: DocumentCard; version: string; anchor?: string };
  const v = doc.versions.find((x) => x.version === version)!;
  const where = v.tier === 'open' ? 'Read here' : 'Read at source';
  const count = unitsOf(doc.doc_id, version).length || doc.unit_count;
  const rubric = [KINDS[doc.kind] ?? doc.kind, doc.authors.length ? shortLabel(doc).replace(/ \d{4}$/, '') : doc.org, formatDate(v.published ?? doc.published)].filter(Boolean).join(' · ');
  return png(await renderCard(anchor
    ? { rubric, title: doc.title, state: 'cited', line: `${anchorLabel(anchor)} of ${count}`, detail: `${where} · ${licenceName(v.licence)}` }
    : { rubric, title: doc.title, line: `${where} · ${licenceName(v.licence)}`, detail: `${count} ${doc.anchor_kind === 'page' ? 'pages' : 'paragraphs'} · version ${version}` }));
}

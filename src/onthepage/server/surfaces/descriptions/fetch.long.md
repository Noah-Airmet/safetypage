Read the library. id is what search returned or what you want to open:
- a document, arxiv:2305.15324 (or a version, arxiv:2305.15324/v2): its record card, with authors, licence, versions and the outline, each section with the id of where it starts;
- a page or paragraph, arxiv:2305.15324/v2/p6 or distill:zoom-in/r1/b12: its full text;
- a range of up to 8, arxiv:2305.15324/v2/p6-p8.
A result url works as an id too.

Each unit comes back with the url to cite. Long reads are cut at max_tokens (default 6000) with a note saying how to continue. view="image" adds a page image link for openly licensed PDFs.

Link-only documents: their licence does not allow the full text, so you get the record, the outline, each unit's opening words and a source_url that opens the page at the source. You can still cite them, search inside them and check quotes against them.

-- The corpus: documents, their versions, the text of record, and how we know each licence.
-- One working copy is written by ingestion; a snapshot holds a frozen copy (see docs/ARCHITECTURE.md).
-- Identity is the doc id and content hashes. Nothing here is keyed by a file path.

CREATE TABLE documents (
    doc_id      TEXT PRIMARY KEY,                 -- 'arxiv:2305.15324'
    ns          TEXT NOT NULL,
    local_id    TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN (
                    'paper', 'system_card', 'model_card', 'framework', 'eval_report',
                    'forum_post', 'blog', 'article', 'government', 'book')),
    title       TEXT NOT NULL,
    authors     TEXT NOT NULL DEFAULT '[]',       -- JSON array of names, in order
    org         TEXT,                             -- 'Anthropic', 'UK AISI', 'NIST'
    collection  TEXT,                             -- the shelf: 'interpretability', 'system-cards'
    published   TEXT,                             -- 'YYYY', 'YYYY-MM' or 'YYYY-MM-DD'
    source_url  TEXT NOT NULL,                    -- the document's landing page at the source
    added_at    TEXT NOT NULL,
    UNIQUE (ns, local_id),
    CHECK (doc_id = ns || ':' || local_id)
) STRICT;

-- A version is one immutable state of a document's bytes. A changed arXiv version, a re-uploaded
-- system card or an edited post is a new row, never an update.
CREATE TABLE versions (
    version_id      INTEGER PRIMARY KEY,
    doc_id          TEXT NOT NULL REFERENCES documents (doc_id),
    label           TEXT NOT NULL,                -- 'v2' (publisher's numbering) or 'r2' (ours)
    seq             INTEGER NOT NULL,             -- order within the document; the highest is latest
    anchor_kind     TEXT NOT NULL CHECK (anchor_kind IN ('page', 'block')),
                                                  -- 'page': cited by PDF page; 'block': by paragraph
    fidelity        TEXT NOT NULL CHECK (fidelity IN ('text_layer', 'html', 'ocr')),
                                                  -- where the text of record came from
    published       TEXT,
    observed_at     TEXT NOT NULL,                -- when we fetched these bytes
    source_url      TEXT NOT NULL,                -- this version's own file at the source
    content_sha256  TEXT NOT NULL,                -- the rendition the text of record was read from
    licence         TEXT NOT NULL,                -- canonical id; set only from a licence fact
    tier            TEXT NOT NULL CHECK (tier IN ('open', 'link_only')),
                                                  -- computed by licence.decide_tier, never by hand
    next_block      INTEGER NOT NULL DEFAULT 1,   -- the next b<n> to mint; never goes down
    UNIQUE (doc_id, label),
    UNIQUE (doc_id, seq)
) STRICT;

-- Append-only. The newest fact for a version is the one in force.
CREATE TABLE licence_facts (
    fact_id          INTEGER PRIMARY KEY,
    version_id       INTEGER NOT NULL REFERENCES versions (version_id),
    licence          TEXT NOT NULL,
    evidence_kind    TEXT NOT NULL CHECK (evidence_kind IN (
                         'licence_link', 'page_statement', 'publisher_rule', 'statute', 'manual')),
    evidence_url     TEXT NOT NULL,
    evidence_quote   TEXT NOT NULL,
    evidence_sha256  TEXT,
    observed_at      TEXT NOT NULL,
    producer         TEXT NOT NULL
) STRICT;
CREATE INDEX licence_facts_version ON licence_facts (version_id, fact_id);

-- Raw files in the blob store, by content hash. Private for link-only versions.
CREATE TABLE renditions (
    version_id  INTEGER NOT NULL REFERENCES versions (version_id),
    kind        TEXT NOT NULL CHECK (kind IN ('pdf', 'html', 'latex', 'text')),
    sha256      TEXT NOT NULL,
    bytes       INTEGER NOT NULL,
    media_type  TEXT NOT NULL,
    source_url  TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (version_id, kind)
) STRICT, WITHOUT ROWID;

-- The text of record for paged versions: the PDF's own text layer, one row per physical page.
CREATE TABLE pages (
    version_id   INTEGER NOT NULL REFERENCES versions (version_id),
    page         INTEGER NOT NULL CHECK (page >= 1),  -- physical index; the n of p<n> and #page=n
    label        TEXT,                                -- the printed page number, when it differs
    width        REAL,                                -- PDF points
    height       REAL,
    text         TEXT NOT NULL,
    spine_start  INTEGER NOT NULL,                    -- offsets of this page in the version's spine
    spine_end    INTEGER NOT NULL,
    PRIMARY KEY (version_id, page)
) STRICT, WITHOUT ROWID;

-- Word boxes for the reader's highlight: JSON [[char_start, char_end, x0, y0, x1, y1], ...],
-- offsets into pages.text, coordinates in PDF points from the top-left.
CREATE TABLE page_words (
    version_id  INTEGER NOT NULL,
    page        INTEGER NOT NULL,
    words       TEXT NOT NULL,
    PRIMARY KEY (version_id, page),
    FOREIGN KEY (version_id, page) REFERENCES pages (version_id, page)
) STRICT, WITHOUT ROWID;

-- Blocks: paragraphs, headings, captions, figures. For a 'block' version they are the text of
-- record and the unit of citation. For a 'page' version they are a structure overlay: each block
-- points at the stretch of the page text it covers.
CREATE TABLE blocks (
    version_id   INTEGER NOT NULL REFERENCES versions (version_id),
    anchor       INTEGER NOT NULL CHECK (anchor >= 1),  -- the n of b<n>; minted once, never reused
    seq          INTEGER NOT NULL,                      -- reading order
    kind         TEXT NOT NULL CHECK (kind IN (
                     'heading', 'paragraph', 'list_item', 'caption', 'figure', 'table',
                     'equation', 'footnote', 'quote', 'code', 'reference')),
    level        INTEGER,                               -- heading depth, 1 = top
    label        TEXT,                                  -- 'Figure 3', 'Table 2', '3.1'
    section      TEXT NOT NULL DEFAULT '[]',            -- JSON array: the headings above this block
    text         TEXT NOT NULL,
    spine_start  INTEGER,                               -- NULL when an overlay block was not placed
    spine_end    INTEGER,
    page_start   INTEGER,                               -- 'page' versions only
    page_end     INTEGER,
    source_id    TEXT,                                  -- the source's own id (LaTeXML 'S3.p2')
    bbox         TEXT,                                  -- JSON [page, x0, y0, x1, y1], optional
    PRIMARY KEY (version_id, anchor),
    UNIQUE (version_id, seq)
) STRICT, WITHOUT ROWID;

CREATE TABLE outline (
    version_id  INTEGER NOT NULL REFERENCES versions (version_id),
    seq         INTEGER NOT NULL,
    level       INTEGER NOT NULL CHECK (level >= 1),
    title       TEXT NOT NULL,
    anchor      TEXT NOT NULL,                          -- where the section starts: 'p12' or 'b40'
    PRIMARY KEY (version_id, seq)
) STRICT, WITHOUT ROWID;

-- Where an anchor went: across versions (v1 p6 is v2 p7) or after a re-parse retired a block.
-- Append-only, so an old citation can always be followed forward.
CREATE TABLE anchor_map (
    from_version_id  INTEGER NOT NULL REFERENCES versions (version_id),
    from_anchor      TEXT NOT NULL,
    to_version_id    INTEGER NOT NULL REFERENCES versions (version_id),
    to_anchor        TEXT NOT NULL,
    relation         TEXT NOT NULL CHECK (relation IN ('same', 'moved', 'split', 'merged', 'reparsed')),
    method           TEXT NOT NULL,
    confidence       REAL,
    PRIMARY KEY (from_version_id, from_anchor, to_version_id, to_anchor)
) STRICT, WITHOUT ROWID;

-- Provenance for every metadata value that is not the text itself. Re-running a producer adds a
-- row; nothing is overwritten. documents.* holds the value currently preferred.
CREATE TABLE facts (
    fact_id       INTEGER PRIMARY KEY,
    subject       TEXT NOT NULL,                        -- a doc id or 'doc_id/version'
    field         TEXT NOT NULL,
    value         TEXT NOT NULL,                        -- JSON
    source        TEXT NOT NULL,                        -- where it was read: a URL or an API name
    producer      TEXT NOT NULL,                        -- the code, model or person that produced it
    input_sha256  TEXT,
    retrieved_at  TEXT NOT NULL,
    confidence    REAL
) STRICT;
CREATE INDEX facts_subject ON facts (subject, field, fact_id);

-- The retrieval unit is the citation unit: one row per PDF page of a paged version, one per block
-- of an unpaged version. Search indexes exactly these rows, for every retrieval arm.
CREATE VIEW units AS
SELECT v.version_id, v.doc_id, v.label AS version, 'p' || p.page AS anchor, p.page AS seq,
       'page' AS kind, p.label, p.text, p.spine_start, p.spine_end, v.tier,
       v.doc_id || '/' || v.label || '/p' || p.page AS cite
  FROM pages p JOIN versions v USING (version_id)
 WHERE v.anchor_kind = 'page'
UNION ALL
SELECT v.version_id, v.doc_id, v.label, 'b' || b.anchor, b.seq,
       b.kind, b.label, b.text, b.spine_start, b.spine_end, v.tier,
       v.doc_id || '/' || v.label || '/b' || b.anchor
  FROM blocks b JOIN versions v USING (version_id)
 WHERE v.anchor_kind = 'block';

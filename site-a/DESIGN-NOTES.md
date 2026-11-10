# Design notes

This front end applies the Gospel Scholar Archive's design system (GSA, `gsa-dash/DESIGN.md`
in Noah's homelab repo) to SafetyPage. That document is the source of truth for the rules;
this file says what was taken as it stands and what had to be added because SafetyPage holds
things GSA does not. Noah's test for every screen (2026-11-10): "show don't tell".

## Taken as it stands

- **Tokens** (`src/styles/tokens.css`): the canvas, surface, fills, inks, the one blue accent,
  the seven bookcloths, gilt, the frost, shadows, the type scale, radii by size, spacing, the
  plate and bar geometry, the two curves and their durations, the z-scale. Dark only.
- **Type**: Source Serif 4 for what is read, Geist for what is operated and for tool headings,
  Instrument Serif for names at 32px and up, Geist Mono only for syntax (queries, cite
  strings, commands, tool signatures, the trace's verbs).
- **The shell**: one bar in three zones (where you can go, where you are, what you can do
  here), the sidebar as the map (a frosted card, docked on desktop, floating over a dimmed
  page on phones, toggled from one corner, `[`), Back named for where it goes, Up as the
  breadcrumb over a title, `/` to search.
- **Layers**: a popover or menu at its control and a panel on the right on desktop; a fit
  sheet on phones with a grabber; one at a time; Escape and a press outside close it.
- **Components**: the icon button and its plate, rows, the segmented control, the composer,
  the bar's search field, folder cards fanning three covers over cloth, list rows, search
  results with washed matches and page chips, the quote card, skeletons, the progress line,
  Copy with the drawn check, the walkthrough's steps and address rows, About's numbers and
  spines, the reader's bar, foot, scrubber and find pill.
- **Words**: names, values, states and controls. No sentences in the chrome. Help sits behind
  a closed `?`.
- **Glyphs**: the same set (OpenAI's product icons, MIT), one per meaning, in
  `public/icons.svg`.

## Added for SafetyPage

| | What | Why |
|---|---|---|
| A document's cover | Its first page when the library may show it (an openly licensed PDF); otherwise a bare binding in its shelf's cloth with a glyph: `doc` read here, `external` read at its source. 17:22, not 2:3. | Documents have no covers. The glyph and the missing page image show the licence tier without a sentence. |
| Shelves and cloth | The seven shelves take the seven cloths (`SHELVES` in `src/lib/cite.ts`). | Cloth says which shelf, never state. |
| The three citation states | **Verified**: the accent, with the drawn check. **Page only**: ink on a fill. **Rejected**: struck through and dim, with the close glyph, never hidden. | GSA has one accent and no red; its "Not on page" quote is ink-3 with a flag. Rejection is shown by the strike and by the page's own wording beside it. |
| A rejected quote on the page | The nearest wording outlined with a dashed ink line; the words the quotation dropped washed in the accent. | The accent stays "here on the page". |
| Flags | A small filled label for a verdict's detail: `Word for word`, `The page says`, `Judge`, `Early runs`. | GSA's quote card has one (`Not on page`). |
| Record page | Cover, the catalogue entry, Read (the one inverted control), Contents as rows, Versions, Licence with the evidence as a quote card, Cite as a tool popover. | GSA opens a book directly; a document here has versions and a licence to show. |
| Read at source | The reader's third mode: the title, the place, the library's opening words as a quote card, one inverted control that opens the source at the page, a field to check a quote. | Three quarters of the library is not shown here. |
| Home | The composer's modes are Search and Check; the wall is first pages (`src/lib/wall.ts`), dimmed a step so the room stays dark. No Field. | The two things the library does. |
| Follow a topic | A strip of lanes, one per lab, each card a mark by date, lit in the accent where it mentions the topic; then results by lab. | No equivalent in GSA. |
| CitationBench | A table without rules: rank band, agent, each measure a number over a gauge. Measures explained behind one closed control. | No equivalent in GSA. |
| Replay | Trace, page and answer side by side; the transport is GSA's player island (play, the steps as ticks, count, speed). | A run is played, so it gets the player. |
| Stats | Only on About the library, as GSA has it. | Stats live on About. |

## Not carried over

The Field (home's WebGL texture), the reader's page tones, Hold, page turning and two-page
layout, sheet detents beyond fit, the split window, and everything about audio.

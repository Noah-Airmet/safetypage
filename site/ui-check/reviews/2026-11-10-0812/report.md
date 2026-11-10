**Review done: 13 findings, 11 pages clean.** Every geometric claim below was measured in the browser at the stated width; judgment calls are marked.

## Findings, most severe first

1. **Replay and Check, 390: the page preview is cropped on both sides, cutting lines mid-word.** `.pv-page .sheet` is 537px wide inside a 358px `.pv-page`; on replay it sits at x −63 (79px cut left, 100px right), on check at x −111 (127px left, 52px right). Lines read "relevant t", "Parliamer". No design-doc rule (site has none). Shots: `replay-390-closed--3-wrap.png`, `check-390-closed.png`. Fix: below 600px scale the sheet to the frame width and centre the crop on the highlight only vertically.

2. **Search 1440 and 390, Home 390: the example-query row clips mid-word with no scroll hint.** `p.tries` is `overflow-x: auto` with the scrollbar hidden and no mask: content 722px in a 552px box on /search (fourth chip cut at "sycophan"), in 368px on home 390 ("spars"). Shots: `search-1440-closed.png`, `search-390-closed--3-wrap.png`, `home-390-closed--3-wrap.png`. Fix: add a right-edge fade mask, or wrap the chips, or trim the list to what fits.

3. **Home 1440 and 390, Connect 390: command and URL boxes clip mid-token; the hero placeholder clips too.** `.codeline code` is 588px of text in a 430px box on home 1440 (ends at "http://"), 300px at 390 ("http safe"); the same on connect 390. The home `input` placeholder has 222px of room and is cut to "AI safety docu" at 390. Shots: `home-1440-closed.png`, `home-390-closed--3-wrap.png`, `connect-390-closed.png`. Fix: `text-overflow: ellipsis` on the code, and a shorter placeholder below 600px.

4. **Persistent plates bleed 12px past the column edge everywhere else aligns to.** The hover-plate bleed (`margin-inline: -12px`) is fine while invisible, but four plates are always filled: home `.claim[aria-pressed]` x100–604 under a search box at 112–592; record `.versions a` x948–1340 above the Licence card at 960–1328; follow `nav.switch a` active pill x100 beside the title at 112; check `li#c1` selected card x100–796 under a textarea at 112. Shots: `home-1440-closed.png`, `record-1440-closed.png`, `follow-1440-closed--5-head.png`, `check-1440-closed.png`. Fix: either give filled plates the column edge (no negative margin) or make their neighbours bleed too; pick one.

5. **Home 1440: heading-to-content rhythm breaks in the right column.** "Library", "New from the labs" and "Connect" put 24px between h2 and first content; the "Check", "Replay" and "CitationBench" teasers put 4px (h2 bottom 1712.8, tally top 1716.8) and stack 16px apart, while sections are 64px apart. Same 28px/500 heading, three different distances. Shot: `home-1440-closed.png`. Fix: 24px under those three headings, or demote them to the 20px list-name size since they are links, not sections.

6. **Home vs Search: the primary search box is drawn two ways.** Home `.ask input` is 56px tall, radius 12, with a 48px labelled "Search" button and 120px right padding; `/search .cbox` is 48px, radius 12, with a 40px icon-only arrow button and a Search/Check toggle beneath. Shots: `home-1440-closed.png`, `search-1440-closed.png`. Fix: one composer component on both pages.

7. **Check vs Replay: "Copy link" is two buttons.** On /check it is `.btn.btn-quiet` (transparent, grey text, 12px padding); on /r it is `.btn` (filled rgba(14,22,33,.05), ink text, 16px padding). Same label, icon and 40px height. Related: the "Check" verb is a primary dark button on /check but a filled secondary in the reader's quote-check form. Shots: `check-1440-closed.png`, `replay-1440-closed.png`, `reader-source-card-1440-closed--5-quotecheck.png`. Fix: quiet for Copy link in both places; primary for Check in both.

8. **CitationBench 1440: the interval plot has no visible header and sits apart from the number it plots.** `th.whisk` holds only visually-hidden text ("Correct, with its 95% interval"), occupies x1027–1171 between "Claim support" and "$ / correct", two columns away from "Correct" at 625–694. Every "Claim support" cell and three of four "$ / correct" cells are "–". Judgment on placement; measured positions. Shot: `citationbench-1440-closed.png`. Fix: move the plot beside Correct with a visible header, and drop columns that are all dashes until they have data.

9. **Replay 1440: `strong` renders at weight 700.** The rest of the site's heaviest text is 500 (titles, names) and 600 (wordmark); the right-pane leads ("The citation target is right.") are 700/16px. Shot: `replay-1440-closed.png`. Fix: `strong { font-weight: 500 }` or 600.

10. **Check, both widths: the textarea shows a resize grip though it autosizes.** `textarea.field` has `field-sizing: content` and `resize: vertical`, so a borderless 8px-radius field carries a browser grip in its corner. Shot: `check-390-closed--5-form.png`. Fix: `resize: none`.

11. **Check 1440: the same paragraph is set at two leadings.** `textarea` is 17px/27.2px; the annotated copy `.marked.prose` below is 17px/30.6px. Shot: `check-1440-closed.png`. Fix: match the leading, or set the textarea to 1.8 if the chips need the room.

12. **Shelf 1440: two field styles in one filter row.** `input.field` is white; the four `select.field` beside it are filled rgba(14,22,33,.05) at weight 500, same 40px height and radius. Judgment whether selects-as-buttons is intended. Shot: `shelf-1440-closed.png`. Fix: white fields throughout the row, or a filled input.

13. **Check 1440: the preview crop cuts the figure's row labels.** `.sheet` is 537.6px in a 480px frame, offset −28.8px each side, so "Model evaluation:" reads "del evaluation:". Low; the home crop of the same page shows the label. Shot: `check-1440-closed.png`. Fix: crop to the page's text column rather than a fixed zoom.

## Clean pages

Library, shelf, shelf-filtered, record-source (beyond the shared version-row bleed in finding 4), reader, reader-text, reader-source-card, reader-source-circuits, reader-source-forum, reader-source-arxiv, connect at 1440, citationbench at 390. The full-page screenshots of follow, reader and record-source repeat their content; that is a stitching artifact, not duplicated DOM. Each has one `header.bar`.

## Confidence

Findings 1 through 7 and 9 through 11 are measured and I am confident in them; the fixes are mechanical. Finding 4 is measured but the remedy is a design decision: the bleed is a deliberate hover-plate convention, and a designer should decide whether persistent plates keep it. Finding 8 is a judgment about table layout and finding 12 about field styling; both need a human eye. Finding 13 is minor and may be an accepted trade of the zoomed crop. Scratch scripts and raw measurements are in the review folder as `sweep.mjs`, `probe.mjs`, `probe2.mjs`, `sweep-1440.json`, `sweep-390.json` and `probe.txt`.

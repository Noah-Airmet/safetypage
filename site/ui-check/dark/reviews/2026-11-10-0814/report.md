**Review of the dark theme, 2026-11-10 08:14 run.** Measurements were taken with a dark-scheme copy of the measure helper, saved as `/Users/noahairmet/development/safetypage/site/ui-check/dark/reviews/2026-11-10-0814/measure-dark.mjs`, because the stock helper opens pages in the light scheme, where the fonts differ.

## Findings, most severe first

1. **Check, 1440. A full stop sits alone on its own line.** `.prose .chip[data-state=rejected]` for `arxiv:2305.15324/v2/p41`. The chip is `white-space: nowrap` and ends at x 780 in a column that ends at 784, so the "." that follows wraps to x 112 on the next line. Measured: chip right 780.4, next glyph "." at (112, 833), one line below. Screenshot `check-1440-closed.png`. Fix: keep punctuation with the chip (wrap chip plus trailing punctuation in a nowrap span, or let the chip label break).

2. **Record, 390. A lone "/" ends the licence URL.** `.evidence-card blockquote`. The URL breaks with `overflow-wrap: anywhere`, leaving the final slash on its own line. Measured: line boxes (32, 1382, w 322) and (32, 1407, w 5). Screenshot `record-390-closed.png`. Fix: drop the trailing slash from the displayed URL, or set the quote in the 14px sans so it fits one line.

3. **Home and Search, both widths. The example-query row is clipped mid-glyph with no fade.** `.tries` has `overflow-x: auto` and a hidden scrollbar. Measured on home 1440: row 102 to 592, scrollWidth 704, fourth example starts at 577 so only 15px of "sycophancy NEAR/10 evaluation" shows. Search 1440: row ends at 1072, last example spans 999.7 to 1228.5. Screenshots `home-1440-closed--3-wrap.png`, `search-1440-closed--3-wrap.png`, `home-390-closed--3-wrap.png`. Fix: drop the fourth example at this width, or add a mask-image fade on the right edge.

4. **Home, 1440. The page crop jumps when you switch claims.** `.hero-page .sheet`. The verified pane positions the sheet at top 106, the rejected pane at 112, so the page image shifts 6px on click. Measured: sheet y 106 vs 112. Screenshots `home-1440-closed--3-wrap.png` vs `home-1440-rejected--3-wrap.png`. Fix: compute one crop offset for both panes from the shared sentence.

5. **Home, 1440. Side-by-side headings have different gaps to their content.** `.agent .h2` vs `.rooms .h2`. "Connect" to its code line is 24px, "Check" to its tally is 4px, on the same row. Measured: 1712.8 to 1736.8 vs 1712.8 to 1716.8. Screenshot `home-1440-closed.png`. Fix: give the rooms' sub-lines the same 12px below the heading as every other `.h2`, or drop the Connect gap to match.

6. **Record, 1440. Two sidebar cards disagree about the column edge.** `.versions a` bleeds 12px left (x 948) so "v2" aligns with the "Versions" heading at 960, while `.evidence-card` sits flush at 960 and its text starts at 976. Measured. Screenshot `record-1440-closed--8-side.png`. Fix: bleed the evidence card by the same 12px (margin-inline -12, padding 12) so both texts start at 960.

7. **Shelf, 1440. The last list column hangs short of the page edge.** `.cat > a .c.read`. Size column is right-aligned to 1208, but "At source" / "Read here" is left-aligned at 1224 and its text ends at 1285, leaving 43px of ragged space before the 1328 edge where the header field and footer end. The home "New from the labs" list right-aligns its last column. Measured. Screenshot `shelf-1440-closed.png`. Fix: right-align the read column, or make it a fixed-width label that ends at 1328.

8. **Replay, 1440. The wordmark moves.** `header .wordmark` is at x 32 on the replay page and x 112 on every other page, because the replay widens `.wrap`. Measured. Screenshot `replay-1440-closed.png`. Fix: keep the header on the standard 112 gutter and widen only the replay's own panes.

9. **Reader source card (forum), 390. The primary button wraps to two lines at line-height 1.** `.sourcecard .btn-primary`. "Read this paragraph at alignmentforum.org" wraps inside a 310px button; height 44 with two 14px lines. Measured. Screenshot `reader-source-forum-390-closed--3-reader.png`. Fix: shorten the label at phone width ("Read at alignmentforum.org"), or allow line-height 1.3 when it wraps.

10. **Check, both widths. The findings list repeats a cite id.** The rejected `arxiv:2305.15324/v2/p41` chip is followed by the same string in mono. Judgment. Screenshot `check-1440-closed.png`. Fix: omit the mono id when the chip label already is the id.

11. **Check, both widths. One row, three button styles.** `.btn-primary` (filled light), `.btn` (filled dark), `.btn-quiet` with an icon (no fill, padding 12 vs 16). Measured paddings 16/16/12. Screenshot `check-1440-closed--6-form.png`. Fix: make "Copy link" a quiet text link away from the pair, or style it as a `.btn` like "Try an example".

12. **Reader (PDF), 1440. The status line mixes type sizes.** `.qstatus .state` is 14px/500, the quote beside it is 16px/400. The same result on the source card is 14px + 14px. Measured. Screenshot `reader-1440-closed--4-reader.png`. Fix: set the quote at 14px, ink-2.

13. **Reader, 1440. The go-to-page field is 36px tall between 40px buttons.** `.goto .field` 36 at y 14, `.contents summary` and `.rsource` 40 at y 12. Page-level fields are 40 (record, shelf). Measured. Screenshot `reader-1440-closed--5-goto.png`. Fix: use 40 (`--control`) for the field, or 36 for the bar's buttons.

14. **Home, 1440. The Follow grid ignores the two-column line.** `.topics a` columns start at 100/416/732/1048 while the sections above and below split at 112/656. Measured. Screenshot `home-1440-closed--5-wrap.png`. Judgment on severity. Fix: a 4-column grid whose third column starts at 656 (two columns per half).

15. **Home, 390. Hover plates reach 4px from the screen edge.** `.claim`, `.rows > a`, `.topics a`, `.rooms a` are at x 4 to 386 while content sits at 16. Measured. Screenshot `home-390-closed--3-wrap.png`. Judgment. Fix: reduce the bleed to 8px at the phone gutter, or drop it.

16. **Check, both widths. The textarea shows a resize grip.** `textarea` has `resize: vertical`; the grip draws at the corner. Measured. Screenshot `check-1440-closed--6-form.png`. Judgment. Fix: `resize: none` with auto-grow, or keep it and accept the grip.

17. **Document titles are set three ways.** Record: 44px Instrument Serif. Text reader (`.textdoc h1`): 28px Instrument Serif. Source card (`.sourcecard h1`): 28px Source Serif 600. Measured. Judgment, since the contexts differ. Fix: pick one face for a document's name inside a sheet.

18. **CitationBench, 1440. The whisker column has no visible header.** `th` text is screen-reader only. Judgment. Screenshot `citationbench-1440-closed.png`. Fix: a short visible label such as "95% interval".

19. **Home rejected state, 390. Extra dashed lines above the marked sentence.** The screenshot shows dashed underlines on the two lines above the marked range. The DOM holds only two `.hl` boxes at (293, 629) and (27, 639), so this may be a capture artefact of the 1px dashed outline at 3x. Screenshot `home-390-rejected--3-wrap.png`. Needs a human on a real phone.

## Pages found clean

Library (both widths), shelf-filtered, reader-text, search-empty, follow (chart, switch and lab sections line up at both widths), connect, citationbench apart from item 18, and the circuits and arXiv source cards apart from the shared items above.

## Confidence

Items 1 to 9, 12 and 13 are measured in the browser and I am confident in them. Items 10, 11, 14 to 18 are judgment calls where the numbers are right but a designer may decide the difference is intended. Item 19 I could not confirm from the DOM and should be checked on a device. One non-UI note: the arXiv source card's "Opening words" shows figure-label text ("Before After Before After…"), which is a data extraction issue rather than a layout one.

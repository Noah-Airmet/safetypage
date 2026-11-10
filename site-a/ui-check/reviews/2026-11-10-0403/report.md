I reviewed all 44 whole-page shots and the relevant crops, then measured every suspect in the live page. The report is also saved at `/Users/noahairmet/development/safetypage/site-a/ui-check/reviews/2026-11-10-0403/report.md` with the raw measurements in `out/`.

# UI review, site-a

Judged against `gsa-dash/DESIGN.md` and Karri's standard. Type sizes and radii were audited on every page at both widths: every text size is on the scale and every radius is a token, so nothing there.

## Findings, most to least severe

1. **The address row is drawn three ways.** connect 1440 `.addr` / `.sigs li`; record 1440 `#cite-pop .addr`. Connect's MCP and command rows: 46 tall, r16, padding 6/14, 34px Copy plate (concentric, 16 = 10 + 6). Connect's link rows: 33.5 tall, r16, padding 8/14. Tool and route rows: 35.5 tall, r10. The Cite popover's rows: 42 tall, r10, padding 4/12, same 34px r10 plate 4px inside (not concentric). Rule: §8 "reuse it, don't copy it"; §5 concentric corners. Shots `connect-1440-closed.png`, `record-1440-cite.png`. Fix: one `.addr` geometry everywhere, including the popover.

2. **CitationBench gauges and numbers don't line up across a row.** citationbench 1440 `.board td.num .gauge`, `.v`. The Correct gauge is 103.7px (fills its cell); the next three are a fixed 112px. Cells without a gauge (the "–", every Questions count) draw their number at y 297.8 while measures sit at 292.8: a 5px baseline step. Shot `citationbench-1440-closed.png`. Fix: one gauge width, and reserve the gauge's height under gauge-less numbers.

3. **Facet picks wrap three-and-one on phones, and the field stops short.** shelf, search, shelf-filtered 390 `.facets`. Publisher, Kind, Year on one line (y 269.4), Read alone on the next (y 313.4); same on search. The shelf's filter field is 320 wide in a 358 row, leaving 38px empty. Shots `shelf-390-closed.png`, `search-390-closed.png`. Fix: full-width field, picks in one row that fits.

4. **Punctuation floats after inline citation chips.** check 1440/390 `.marked .cite.chip`. 8px right padding and the next text starts at the chip's edge (gap 0), so on unboxed chips you read "p. 6 , and", "p. 3 ).", "p. 6 . Cunningham". Shot `check-1440-closed.png`. Fix: no right padding on unboxed chips, punctuation tight to the label.

5. **The reader's foot isn't mirrored at 1440.** reader, reader-text, reader-source 1440 `.r-foot` (padding 0 15px 0 7px). Contents is 7px from the left edge; the page count is 15px from the right. At 390 both are 7. Rule: §5 Mirrored. Shot `reader-1440-closed--4-r-foot.png`. Fix: 7px both sides at every width.

6. **The record head sits 48px above its content; every other room uses 32.** record, record-source, both widths, `.rec-top` margin-bottom 48. Library, shelf, search, follow, check, about all use 32. Rule: §5 head rhythm, content `--s-6` under the head. Shot `record-1440-closed.png`. Fix: 32.

7. **"Search in document" lines up with nothing.** record 1440 `.find.inside`, a fixed 420px ending at x 750; the control row runs to 1310, the Contents column ends at 886. Shot `record-1440-closed.png`. Fix: size it to the Contents column or the control row.

8. **Menu rows in phone sheets use two icon sizes and two label starts.** shelf-menu 390 `#menu-publisher .menu-rows button` (16px icon, label x 64); reader-more 390 `#r-more .menu-rows button` (20px icon, label x 68). Rule: §8 the row, §10 `--icon-md`. Shots `shelf-390-menu--9-menu-publisher.png`, `reader-390-more--3-reader.png`. Fix: one icon size, one label column.

9. **The replay trace clips rows mid-line at its top.** replay 1440 `.rp-trace ol` (overflow auto, scrollTop 342, no mask). The "answer" row (145.8 to 179.2) and the first "cite" row (180.2 to 252.7) straddle the list top at 218.7, so the first thing shown is a quote missing its "00:12 cite" label. Shot `replay-1440-closed.png`. Fix: scroll to a row boundary, or a fade mask.

10. **The page crop cuts into the page.** about 1440/390 `.pagepane .sheet`: 688.8 wide in a 626.2 box at 1440 (31px lost each side), 422 in 358 at 390; the figure's left labels lose their first letters ("odel valuation:"). Shot `about-1440-closed.png`. Fix: crop vertically only, or to the text block's measured edge.

11. **The composer's `?` is a third control size.** home and check, both widths, `.crow .cbtn`: 32×32 beside a 36px segmented control and 36px buttons, in a system whose plate is 34. Rule: §5 `--plate`, §8 the icon button. Shot `home-1440-closed--4-composer.png`. Fix: an `.ib` with the 34px plate.

12. **The section line wraps and indents itself.** reader-source 390 `.where .sect` wraps under "p. 135 / 230" and lands at x 24, 8px in, carrying its own margin-left. Shot `reader-source-390-closed.png`. Fix: flex-wrap with `gap`, no margin on the span.

13. **The quote is shown twice on the read-at-source page.** reader-source both widths: `.excerpt.qcard` and the prefilled `#qc` field 76px below carry the same words; at 390 the field truncates them. Judgment. Fix: empty field with a placeholder, Check on the card.

14. **The quote card is a filled figure on Check and a bare button on About.** check `figure.qcard` (fill on every card) vs about `button.qcard.claim` (fill-2 when chosen, transparent otherwise). Judgment plus measured. Fix: one ground; chosen state by the accent rule.

15. **Step 2 is a heading with nothing under it.** connect both widths: "Ask" is a lone 19px heading, then 64px of air before "Try it". Judgment. Fix: give it a body or fold it into one step.

16. **Sideways scrollers cut content at the edge with no hint.** citationbench 390 `.scroll` (985 in 390, mask none, "1(" visible at the edge); about 390 `.stacks` (866 in 390, third spine cut). Fix: a right-edge fade, or a narrower phone board.

17. **"Read here" means two things on one page.** record: the Versions row's control and, 170px lower, the licence's statement. Judgment. Fix: name the licence state differently.

18. **One rejected chip is boxed, two are bare.** check `.cite.chip[aria-current]` carries fill-2 as the current finding and reads as a fourth state. Judgment. Fix: mark current by rule or underline, not a plate.

## Clean

Home at both widths in all three states (composer, segment and help popover measure to the tokens). Library at both widths, sidebar open and shut. Shelf and shelf-filtered at 1440 (head rhythm 8/16/32 exact). Search at 1440. Follow at both widths. Reader and reader-text apart from the foot. Replay at 390. Connect at 390 beyond the shared items.

## Confidence

Findings 1 to 12 are measured and I'd act on them as they stand; 5, 6 and 11 also break a written rule. 13 to 18 are judgment calls for a designer to confirm. Three things in the screenshots are capture artefacts, not the site: blank covers below the first screen on the long shelf pages and the blank page image on About at 390 are lazy or late images, and the faint Cite popover and Publisher menu in the full-page shots were caught mid-animation.

You are a meticulous product designer reviewing a website's UI for visual craft problems, the way Karri Saarinen (Linear's CEO) marked up an agent-built app. His critique of that app: vertical and horizontal alignment missing (panes' top bars at different heights, list items not starting on one line), buttons both rounded and square and in various sizes, inconsistent spacing, duplicated sections, a stray gap above an input. That is the level of detail that counts here: 2 to 8 pixel inconsistencies a top designer winces at, not taste.

The site's code is in /Users/noahairmet/development/safetypage/site. The site has no written design system, so judge against Karri's standard and the site's own most common choices (the spacing, sizes and shapes it uses most are its de facto system).

The live site is at http://localhost:4412. Its pages:
- home: http://localhost:4412/
- library: http://localhost:4412/library
- shelf: http://localhost:4412/library/labs
- shelf-filtered: http://localhost:4412/library/papers?year=2024&q=sparse
- record: http://localhost:4412/d/arxiv/2305.15324
- record-source: http://localhost:4412/d/anthropic/claude-opus-5-5-system-card
- reader: http://localhost:4412/d/arxiv/2305.15324/v2/p6?q=not%20the%20only%20tool%20available%20for%20AI%20risk%20assessment
- reader-text: http://localhost:4412/d/distill/zoom-in/r1/b21
- reader-source-card: http://localhost:4412/d/anthropic/claude-opus-5-5-system-card/r1/p135?q=reviewed%20the%20highest-scoring%20reports%20on%20the%20deliberate%20sabotage%20dimension
- reader-source-circuits: http://localhost:4412/d/anthropic/2024-scaling-monosemanticity/r1/b20
- reader-source-forum: http://localhost:4412/d/lw/LNA8mubrByG7SFacm/r1/b85
- reader-source-arxiv: http://localhost:4412/d/arxiv/2401.05566/v3/p5
- search-empty: http://localhost:4412/search
- search: http://localhost:4412/search?query=%22alignment%20faking%22
- follow: http://localhost:4412/follow/sabotage
- check: http://localhost:4412/check?example=1
- replay: http://localhost:4412/r/cc-haiku-5-5-4e1c63-pc-4bd058594c.1?step=21
- citationbench: http://localhost:4412/citationbench
- connect: http://localhost:4412/connect

Screenshots are in /Users/noahairmet/development/safetypage/site/ui-check/dark/reviews/2026-11-10-0814/shots, at widths 1440 and 390 (a width under 600 is a phone). `shots.txt` beside that folder lists them. `<page>-<width>-<state>.png` is the whole page; `<page>-<width>-<state>--<n>-<part>.png` are crops of its header, nav, sections, cards, dialogs and forms at 2 to 3 times scale. Start with the whole pages at each width, then the crops: a whole page is too downscaled to show a 2px problem.

Measure before you report. Vision misjudges a few pixels; the browser doesn't. Use the helper:

    node /Users/noahairmet/development/tools/ui-check/lib/measure.mjs <url> <width> '<expression>' [--click <selector>]

It prints the expression's value as JSON once the page has drawn; `box(selector)` gives every visible match's rect, font, colour, radius, padding and margin. For example `node /Users/noahairmet/development/tools/ui-check/lib/measure.mjs http://localhost:4412 390 'box("header a, header button")'`. Every geometric finding needs a measurement; a judgment call (hierarchy, wording) says "judgment".

Already checked automatically, so don't re-report these unless you measure a real exception: icons centred in their controls, hover plates centred, concentric corners at card edges, flex-row children sharing a centre line, controls covered by other things, horizontal scroll, top-bar items across panes sharing a centre line, siblings in a column sharing a left edge and a content start, boxed side-by-side controls sharing a height and a radius, WCAG AA contrast, names and target sizes.

Spend your effort on what those can't catch:
- alignment between things that aren't siblings (a page title against the content column under it, a header's logo against the page's left edge)
- one component drawn two ways (the same button, card, list row or form field with different sizes, radii, padding or type in two places)
- spacing rhythm that differs between similar places (heading to content, section to section, page to page)
- type: too many sizes or weights, a size between the steps the site otherwise uses
- duplicated or redundant content; words that explain what the design should show
- anything that looks unfinished at the phone width: crushed text, a lone word or icon on its own line, a row of three that wraps to two and one
- anything a top designer would wince at

Do not edit any file in the site. You may write scratch scripts only in the review folder above the screenshots.

Report, ranked most to least severe, at most 20 findings. For each: the page and width, the element (a selector), what's wrong, the measurement that proves it (or "judgment"), the design-doc rule it breaks if any, the screenshot file, and the fix you'd make in a sentence. Then name the pages you found clean. End with a paragraph: which findings you're confident in, and which a human designer should confirm. Don't pad: a clean site gets a short report.

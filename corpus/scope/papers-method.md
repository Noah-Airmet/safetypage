# Papers and forum posts: how the lists were made

Compiled 2026-11-09. Scripts are in `scripts/` (`run_all.sh` gives the order), and the raw pulls are in `data/`. Numbers below come from `scripts/stats.py`.

## Outputs

| File | Rows | What |
|---|---|---|
| `papers.jsonl` | **6,826** | Research papers: 6,132 on arXiv, 694 without an arXiv version (ACL Anthology, OpenReview, PMLR) |
| `forum-posts.jsonl` | **5,698** | The default forum rule: all Alignment Forum posts plus AI-tagged LessWrong posts with karma ≥100 or curated |
| `forum-posts-candidates.jsonl` | 10,300 | The wider net (karma ≥25). Each row's `included_via` says which rules it meets, so any threshold can be applied later. |

Extra fields: `versions[].licence_source`, `citation_count_source`, `openalex_id`, `acl_id`/`acl_url`. Forum rows also carry `licence_note` and `crosspost`.

## Paper inclusion rule

A paper is in if at least one route brings it in. There is one exception. Two kinds of route are broad: StampyAI's 2023 arXiv scrape, which includes general ML, game theory and economics, and org pages that are general publication lists or blog posts whose links include citations (EleutherAI, Anthropic Alignment Science blog, METR, Timaeus). A paper that arrives **only** by those routes must also match the safety keyword pattern (`scripts/topics.py: SAFETY_RE`) in its title or abstract. The gate dropped 1,290 papers.

### Routes

| Route (`included_via`) | Source | Papers | Only by this route |
|---|---|---|---|
| `list:slade` | Slade Byrd's AI Safety Literature DB (sladebyrd.com/ai-safety-db), the papers table, read through the public Supabase endpoint its own front end uses | 3,775 | 2,838 |
| `venue:<conf>-<year>` | AI Safety Research Tracker (github.com/SomaxSoma/AI-Safety-Research-Tracker): safety papers at ICLR, ICML and NeurIPS 2019–2026, classified by an LLM. Titles were matched to arXiv by exact normalised title against the arXiv snapshot, plus 400 through the arXiv API. 83% resolved. | 2,328 | 1,531 |
| `org:<name>` | arXiv links on org pages, rendered in a headless browser and followed one level: CHAI 380, Anthropic Alignment Science blog 264, EleutherAI 64, Timaeus 51, METR 49, Anthropic /research 42, CAIS 33, Redwood 7 (after the gate) | 806 | 256 |
| `list:stampy-ard` | StampyAI alignment-research-dataset, `arxiv.jsonl` (HF, last modified 2023-11-16), after the gate | 669 | 322 |
| `venue:blackboxnlp` | Every BlackboxNLP paper 2018–2026, from the ACL Anthology XML on GitHub | 366 | 350 |
| `citation:openalex` | Cited by ≥8 seed papers in OpenAlex `referenced_works`, with a safety keyword in the title. The seeds are 6,500 arXiv papers from the routes above, mapped by arXiv DOI and landing URL. | 261 | 217 |
| `venue:trustnlp` | TrustNLP workshop papers with a safety keyword in the title | 41 | 36 |

**Overlap is low.** 5,550 papers (81%) come by one route family, 1,147 by two, 129 by three or more. The largest overlaps are Slade × tracker (722), Stampy × org pages (302) and Slade × org pages (248). Each list reflects its maker's classifier, so the union is wide and the intersection is thin.

**Citation-expansion counts at other thresholds** (candidates not already in the seed set, before the keyword filter → after the title filter): k≥5: 3,492 → 565; k≥8: 1,812 → 303; k≥10: 1,326 → 222; k≥20: 445 → 71. I used k≥8. The expansion leans towards adversarial-robustness and backdoor papers, because Slade's DB is 28% adversarial robustness.

**Recall check:** 48 of 49 canonical papers are present (`scripts/canon.txt`: Concrete Problems, debate, RLHF, IOI, CCS, CAI, SAEs, RepE, AI Control, Sleeper Agents, alignment faking, emergent misalignment, CoT monitorability, Taking AI Welfare Seriously, Butlin et al., and more). The one miss is FGSM (1412.6572), which is arguably out of scope. Llama 2 was correctly excluded.

**Size:** 6,826 is above the 3–6k "whole corpus" aim before system cards and posts are counted. A tighter core would be the 1,276 papers with ≥2 route families, plus org, citation and BlackboxNLP papers. Alternatively, the overnight local-model labelling in arch-1 §1.9 can triage the 5,550 single-route papers.

## arXiv metadata and licences

- **Source:** `librarian-bots/arxiv-metadata-snapshot` on Hugging Face (CC0). It is a weekly mirror of Cornell's Kaggle snapshot, which is built from arXiv's OAI-PMH data. The latest `update_date` is 2026-10-23. It covers all 6,132 IDs and gives the version list with dates, the licence, the DOI and the journal-ref. It took 15 s locally, against about 5 h for OAI `GetRecord` at arXiv's limit of one request per 3 s. `ListRecords` on `set=cs` timed out twice.
- **How arXiv reports licences (checked at source):** OAI-PMH `arXiv` and `arXivRaw` carry **one** `<license>` element per paper, and the arXivRaw XSD has no licence inside `<version>`. That value is the current licence. The abs page for a specific version, `arxiv.org/abs/<id>vN`, links that version's own licence. I tested this on four papers first submitted 1996–2003 and now CC BY 4.0: each v1 page shows `arxiv.org/licenses/assumed-1991-2003/`, and each latest page shows CC BY 4.0. So **licences are per version, only the abs page per version exposes old versions' licences, and the OAI value applies only to the latest version.** In an 11-paper sample from this corpus, v1 and latest matched in every case.
- **What `versions` holds:** each version has its date. The latest version's licence comes from OAI. An earlier version's licence is `null` with `licence_source: "not checked"` unless it was fetched. Fetching every version page at robots.txt `Crawl-delay: 15` would take about 2 days for the ~13k versions. It only matters for older versions we would host. 3,747 of 6,132 papers have more than one version.
- **Licence split (latest version), all 6,826 papers:** CC BY 4.0: 3,144. arXiv default: 2,500. Unknown (non-arXiv, non-ACL): 544. CC BY-NC-SA 4.0: 243. CC BY-NC-ND 4.0: 197. CC BY-SA 4.0: 173. CC0: 24. CC BY 3.0: 1. **3,342 papers (49%) are openly licensed for hosting** (BY, BY-SA or CC0). This includes 150 ACL papers under the Anthology's CC BY 4.0 rule from 2016. The open share rises by year: 13% (2020), 42% (2021), 50% (2023), 59% (2025), 65% (2026). That matches the scout's 400-paper sample.
- **`has_arxiv_html`:** checked by `HEAD arxiv.org/html/<id>` for a 40-paper sample only (see below). Everything else is `null`. A full check at 15 s per request is about 29 h, and `scripts/arxiv_web_check.py html` is resumable for an overnight run.
- **Venue and DOI:** DOIs on 5,758 papers (arXiv DOI where nothing better), venue on 6,343 (journal-ref, tracker or ACL venue, or OpenAlex source). `citation_count` on 5,934 (OpenAlex `cited_by_count`, else Semantic Scholar's count via Slade's DB).

**HTML sample (40 IDs, 2026-11-09):** 38 return 200 from `arxiv.org/html/<id>` (95%). Two return 404: Induction Heads (2209.11895), whose arXiv source is a PDF, and 2210.08340. arXiv's HTML coverage of this field is therefore high but not total, and PDF-only submissions (common for Anthropic's Transformer Circuits arXiv copies) never get HTML. The sample results are in `data/arxiv_html_check.jsonl` and merged into `papers.jsonl`.

## Forum posts

- **Access:** the LessWrong GraphQL API (`/graphql`, anonymous). I harvested all 55,057 posts newest-first, 500 per request, 3 s apart, following robots.txt `Crawl-Delay: 3`. That is metadata only, with no bodies. AF posts are LW posts with `af: true`. A cross-check against `alignmentforum.org/graphql` for Jan–Feb 2024 matched exactly (75/75). LessWrong also publishes an agent guide (`/api/SKILL.md`) with markdown endpoints.
- **Rule (default):** all AF posts (4,697, events excluded), plus non-AF LW posts with an AI tag (`scripts/lw_tags.py`: the core "AI" tag plus 116 narrower AI-safety tags) that are curated or have karma ≥100.

| LW threshold (AF and curated always in) | Posts |
|---|---|
| karma ≥25 | 10,300 |
| karma ≥50 | 7,488 |
| **karma ≥100 (default)** | **5,698** |
| karma ≥200 | 5,022 |

- **Link-posts:** 783 in the default set. 85 point to a paper in `papers.jsonl` (`linkpost_to_paper`), matched by arXiv ID, DOI or URL.
- **Recall against Slade's forum table:** of 4,264 LW/AF posts there, 4,217 are in the harvest. The default rule keeps 2,462 (58%) and the ≥25 rule keeps 3,396 (80%). Slade includes many low-karma posts.
- Karma inflates over time because of strong votes. One fixed threshold under-admits 2015–2019 posts. A per-year percentile would be fairer if that matters.

### Licence and terms (LessWrong / AF)

- The LW FAQ links the Terms of Use: a MIRI PDF dated 2015 (`intelligence.org/files/PrivacyandTerms-Lesswrong.com.pdf`). Under them, users "own all rights in and to [their] User-Generated Content" and grant MIRI a non-exclusive licence "for the normal and intended purposes of the Website". **There is no open licence**, so every post defaults to `licence: "unknown"`, which is the snippets-plus-link tier.
- **Automated access conflict:** the same 2015 terms prohibit "using a spider, scraper, or other automated technology to access the Website". But the live site publishes `robots.txt` with `Crawl-Delay: 3`, an open GraphQL API, and an `/api/SKILL.md` that invites AI agents to read posts through `/api/...`. I collected metadata only, at the crawl delay. Whether to ingest post bodies at scale is worth asking Lightcone (Noah), along with the licence question.
- **Open-licence exceptions found:**
  - Posts **hosted on the EA Forum** and cross-posted to LW on or after 2022-12-01 are CC BY 4.0. The EA Forum requires CC BY for all content posted from that date, but not for link-posts and not retroactively. That covers 28 posts in the default set and 149 in the wide set, flagged `licence: "CC-BY-4.0"` with evidence.
  - Posts **hosted on LW and mirrored to EAF** (221 in the default set) carry a `licence_note`. Whether EAF's rule covers them is unconfirmed.
  - gwern.net states CC-0 for its content: 11 posts by `gwern` carry a note to confirm. I found no LW-wide or AF-sequence licence. Other author blogs I checked (Cold Takes, Planned Obsolescence, Bounded Regret, Neel Nanda, Chris Olah, AI Impacts, Joe Carlsmith, TurnTrout) showed no licence statement in the fetched HTML, which proves only absence on the page I fetched.

## Known gaps

- **Org pages:** Apollo, FAR.AI, MATS, Goodfire, Google DeepMind and OpenAI pages gave 0 arXiv links (JS shells, own-page links, or 403). Their papers enter only through other routes. Following each org's paper pages one level deeper, or using an author-ID route (OpenAlex authorships), would close this.
- **OpenReview** is not used directly (the API returns 403 without login). Venue coverage comes from the tracker, and only for ICLR, ICML and NeurIPS. SaTML, NeurIPS/ICML/ICLR safety workshops, AAAI, FAccT and ACL main-track safety papers come in only when another route has them.
- **Forward citation expansion** ("papers citing ≥k seeds") is not done. OpenAlex's keyless budget is $0.10/day, about 1,000 list calls, shared per IP. This run used about 290. A free OpenAlex key gives $1/day, but signing up needs an email, so that's Noah's call.
- **Welfare and consciousness papers:** only 90 are tagged welfare, and most arrive via the Anthropic blog route. The model-welfare literature is the other agent's part.
- **Stampy** stops at 2023-11. Slade's DB is thin before 2023: 341 papers in 2023, 146 before.
- **Topics** come from transparent regexes plus the source lists' own categories (Slade `primary_area`, tracker subarea). 278 papers have none. They are a first pass and not a classifier.
- **Title-only matches** (tracker, ACL) resolve to the first arXiv ID when two papers share a title. That is rare but possible.
- arXiv copies of Transformer Circuits papers are in only when a route other than Slade lists their arXiv ID (Toy Models 2209.10652 is; Induction Heads 2209.11895 is not), because Slade files them under the Transformer Circuits venue, which is the other agent's shelf. Join the two lists on title.
- The 694 non-arXiv papers have `versions: []`. 544 of them have `licence: "unknown"` (OpenReview, PMLR, NeurIPS); the venue licences were not checked.

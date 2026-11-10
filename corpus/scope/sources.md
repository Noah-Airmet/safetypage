# Sources for the non-arXiv inventory

Index pages, sitemaps and feeds behind `labs.jsonl`, `lab-research-web.jsonl`, `evaluators.jsonl`, `government.jsonl` and `welfare.jsonl`. All were checked on 2026-11-09. "Complete" means the source listed everything I found by other routes. The build scripts are in `scripts/web-inventory/`. `seeds/*.py` selects documents from these sources, `enrich.py` fetches and verifies each one, and `finalize.py` splits them into the five files and reads licences from each document's own text. `check_urls.py` re-checks every URL.

## Frontier labs

| Publisher | Source | Completeness / caveats |
|---|---|---|
| Anthropic | https://www.anthropic.com/sitemap.xml (588 URLs, with `lastmod`) | Complete for web pages. PDFs are not in the sitemap. I harvested them from every page the sitemap lists (216 Anthropic-hosted PDFs) and then selected from those. |
| Anthropic | https://www.anthropic.com/system-cards | Complete index of system cards. Anthropic hosts several byte-different copies of the same card (for example three Claude 4 cards of 120, 123 and 124 pages, and two Opus 4.6 cards of 212 and 213 pages). Each copy is recorded and grouped with `version_of`. |
| Anthropic | https://www.anthropic.com/responsible-scaling-policy | Every RSP version from 1.0 to 3.4 with redlines, risk reports, and a dated update log. Complete. |
| Anthropic | https://www.anthropic.com/transparency (+ `/model-report`, `/system-trust-reporting`) | Transparency hub. It links some card variants that are not on the system-cards index. |
| Anthropic | https://alignment.anthropic.com/ | Alignment Science Blog index, 90 entries. Complete. I kept the entries hosted on the blog itself; the ones that point to anthropic.com or arXiv are covered elsewhere. |
| Anthropic | https://transformer-circuits.pub/ | Index of the thread, 57 entries including every monthly update. Complete as far as the index goes. Companion pages such as the per-paper method appendices are not indexed separately. |
| OpenAI | https://openai.com/sitemap.xml (index of sub-sitemaps: `/safety/`, `/publication/`, `/research/`, `/security/`, `/global-affairs/`, `/disrupting-malicious-uses/`, …) | Complete URL list. openai.com returns HTTP 403 to curl and to a headless browser after a few requests, so most openai.com pages are `verified: false`. |
| OpenAI | https://openai.com/news/rss.xml | 1,370 items back to 2015, with title, date and category. This is the best refresh source and is fetchable when the pages themselves are not. Every openai.com title and date in the inventory comes from it. |
| OpenAI | https://deploymentsafety.openai.com/sitemap.xml | Deployment Safety Hub: 36 HTML system cards and addenda, with every section as a sub-page. Fetchable. Complete for 2025 onwards. |
| OpenAI | https://github.com/openai/model_spec (CHANGELOG.md, CC0) and https://model-spec.openai.com/ | Every Model Spec version, 2024-05-08 to 2026-10-29. Complete. |
| OpenAI | cdn.openai.com PDFs | There is no index. I found the PDFs in crawled pages and in the International AI Safety Report bibliography, and confirmed each by fetching it. Older system-card PDFs that I could not find on any page are missing (see the gaps below). |
| Google DeepMind | https://deepmind.google/sitemap.xml | Model-card pages only (23). The blog is not in the sitemap. |
| Google DeepMind | https://deepmind.google/frontier-safety/ | Frontier Safety Framework v1.0–3.1 and the per-model FSF reports. Complete. |
| Google DeepMind | https://deepmind.google/models/model-cards/ (pages link PDFs under storage.googleapis.com/deepmind-media/Model-Cards/) | Current model cards only. Superseded cards drop off the index, and older ones are at modelcards.withgoogle.com and storage.googleapis.com/model-cards/ (not crawled). |
| Google DeepMind | https://deepmind.google/blog/rss.xml (last 100 posts, from 2025-11 onward) plus the Wayback CDX list for `deepmind.google/blog/` (698 URLs) | Safety-relevant posts selected by keyword. Posts on the pre-2023 deepmind.com blog are not covered. |
| Google DeepMind | https://deepmindsafetyresearch.medium.com/sitemap/sitemap.xml plus Wayback CDX | 32 posts. Medium returns 403 to scripted fetches, so these are `verified: false`. |
| Many labs | https://metr.org/fsp | METR's index of published frontier safety policies, with versions. It is the best cross-lab refresh source for frameworks. |
| Meta, Microsoft, Amazon, xAI, NVIDIA, Cohere, NAVER, G42, Magic | Each framework's own URL, taken from metr.org/fsp. Model cards came from GitHub (Llama) and data.x.ai (Grok). | xAI has no model-card index, and cards after Grok 4.1 were not found. Microsoft's Responsible AI Transparency Reports come through aka.ms redirects. |

## Lab research on the web

| Publisher | Source | Completeness |
|---|---|---|
| Distill | https://distill.pub/rss.xml and https://distill.pub/archive/ | 52 articles. A fixed set (Distill has been on hiatus since 2021). CC BY 4.0. |
| Anthropic, OpenAI, GDM | As above | Selected by topic. Economics, science-applications and product posts are excluded. |

## Independent evaluators and safety organisations

Every row below is a sitemap, expanded with `smx.py` (which handles sitemap indexes):

| Publisher | Source | Paths kept |
|---|---|---|
| METR | https://metr.org/sitemap.xml | `blog/`, `notes/`, `evaluations/` and top-level reports. Spanish and Chinese translations excluded. |
| Apollo Research | https://www.apolloresearch.ai/sitemap.xml | `science/`, `governance/`, `blog/`, `monitoring/` |
| Redwood Research | https://blog.redwoodresearch.org/sitemap.xml (Substack), plus www.redwoodresearch.org/research | all `/p/` posts |
| FAR.AI | https://far.ai/sitemap.xml | `research/`, `blog/`, `news/` |
| Transluce | https://transluce.org/sitemap.xml | investigations and research write-ups |
| Goodfire | https://www.goodfire.ai/sitemap.xml (redirects to goodfire.com) | `research/`, `blog/` |
| Palisade Research | https://palisaderesearch.org/sitemap.xml | `research/`, `blog/` |
| Epoch AI | https://epoch.ai/sitemap.xml (index) | `publications/`, `gradient-updates/` (the data and benchmark hubs are excluded) |
| Center for AI Safety | https://safe.ai/sitemap.xml | `blog/`, `work/` |
| ARC | https://www.alignment.org/sitemap.xml | `blog/`, `theory` |
| Frontier Model Forum | https://www.frontiermodelforum.org/sitemap.xml | issue briefs, technical reports, updates, testimony |
| CLTR | https://www.longtermresilience.org/sitemap.xml | AI-related `reports/` |
| SaferAI | https://www.safer-ai.org/sitemap.xml | `research/` |
| Irregular | https://www.irregular.com/sitemap.xml | `research/` (CC BY-NC-ND 4.0, stated on each page) |
| Future of Life Institute | https://futureoflife.org/sitemap.xml | AI Safety Index editions and documents only |
| GovAI | https://www.governance.ai/research (page links) | `research-paper/` pages. No sitemap. |
| Concordia AI | https://concordia-ai.com/research/ (page links) | No sitemap. |
| Andon Labs, SecureBio, AI Lab Watch | Index pages | Only their index pages and named evaluations. |

## Government and intergovernmental

| Publisher | Source | Completeness |
|---|---|---|
| NIST AI series | Probed `https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.<series>.pdf` for 100-1 to 800-4, including ipd and 2pd drafts | 27 PDFs resolved. Second public drafts and finals that use other suffixes (for example AI 800-1 2pd) may be missing. I found no NIST index that lists the whole AI series, so NIST's publication search (https://www.nist.gov/publications) is the refresh route. |
| NIST / CAISI | https://www.nist.gov/sitemap.xml (110k URLs), filtered for CAISI/AISI, plus https://www.nist.gov/blogs/caisi-research-blog | CAISI evaluations (DeepSeek, Kimi K2, DeepSeek V4 Pro, GLM-5.2, GLM-5.3, Kimi K3 with UK AISI), and the 2024 US/UK pre-deployment tests of Claude 3.5 Sonnet and o1. |
| US presidential documents | https://www.federalregister.gov/api/v1/documents.json?conditions[term]=artificial%20intelligence&conditions[type][]=PRESDOCU | Complete for executive orders and memoranda published in the Federal Register. OMB memos are not in the Federal Register and were added by direct URL. |
| UK DSIT / AISI on GOV.UK | https://www.gov.uk/api/search.json (`filter_organisations=ai-security-institute`, plus queries) and https://www.gov.uk/api/content/<path> for attachments | OGL v3.0. |
| UK AI Security Institute | https://www.aisi.gov.uk/sitemap.xml | 218 URLs. Blog and research pages, including pre-deployment evaluation write-ups. No licence statement on aisi.gov.uk. |
| International AI Safety Report | https://internationalaisafetyreport.org/sitemap.xml and /publications | 2025 report, first and second key updates (Oct and Nov 2025), 2026 report and summaries. OGL v3.0. The May 2024 interim report is on GOV.UK. |
| EU AI Office / AI Act | https://digital-strategy.ec.europa.eu/sitemap.xml (policy pages), then each library page's `ec.europa.eu/newsroom/dae/redirection/document/<id>` links | English documents only; translations skipped. Library pages are not in the sitemap and were reached through the policy pages. The AI Act was amended by OJ L 2026/1744 (in force 2026-07-27). |
| OECD / G7 | https://oecd.ai/en/transparency (the Hiroshima reporting framework's published reports) | The site is a JavaScript app, so the individual company reports are not enumerated. This is the biggest government gap. |

## Model welfare

| Publisher | Source | Completeness |
|---|---|---|
| Eleos AI Research | https://eleosai.org/research | All posts. |
| NYU CMEP | https://sites.google.com/nyu.edu/mindethicspolicy/publications | Journal articles listed there. Several publishers (ScienceDirect, T&F, OUP) return 403 to scripts. |
| Rethink Priorities | https://rethinkpriorities.org/sitemap.xml (`research-area/`), plus /digital-consciousness/ | Digital-minds items only. |
| Anthropic | System cards since Claude Opus 4 | Recorded as pointers to the welfare section of each card. |

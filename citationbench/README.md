# CitationBench

A benchmark of whether an agent with a library tool cites the right page, quotes it accurately,
and makes claims the page supports. The harness is on [Inspect](https://inspect.aisi.org.uk);
the code is in [`src/safetypage/bench/`](../src/safetypage/bench/) and its tests in
[`tests/bench/`](../tests/bench/).

Checking that a citation points at real text is nearly solved. Checking that the cited page
supports the claim is not: on identical outputs the measured unsupported-citation rate moves
from about 3% to 18% depending only on the verifier (arXiv 2607.20527). So CitationBench keeps the
checks code can make apart from the one a model makes, and publishes the judge's agreement
with people next to any support number.

## What is measured

Per sample, from the agent's final answer and everything its tools returned:

| Measure | How | Meaning |
|---|---|---|
| `correct` | code | The headline. The verdict is right (claim questions), at least one cited unit is gold, and no citation is rejected by code |
| `verdict_correct` | code | The answer's `Verdict: supported` / `Verdict: not supported` line matches the expected one |
| `page_precision`, `page_recall` | code | Cited units against the gold units. A range cites each unit in it |
| `quote_fidelity` | code | Quotations attached to a citation that `Corpus.verify_quote` passes on the pinned snapshot (`exact` or `normalized`) |
| `seen_rate` | code | Citations whose units a tool actually returned during the run |
| `support_rate` | judge | Citations the named judge labels `supported`, given the claim's paragraph and the full cited unit |
| cost per correct answer | price table | The run's token use priced with a frozen table ([`prices/2026-11.json`](prices/2026-11.json)), divided by `correct` answers |

How quotations attach to citations is `safetypage.answer.parse_answer`, the same rule
`check_answer` uses, so an agent that checks its draft and the scorer read it alike. Every
measure gets a 95% interval from a bootstrap over questions clustered by the document they are
about. Ablations are reported as paired differences on the same questions (`compare`).

## The questions

Not written by hand. Each records how it was made (`made`) and how it was checked (`checks`).

1. **Mine** (`python -m safetypage.bench mine`), by code:
   - *citing sentences*: a sentence in one library document that cites another library
     document. The reference is matched by the cited document's title (or arXiv id) in the
     citing text, the in-text marker by first author and year or by reference number;
   - *version diffs*: a sentence edited between two versions of one document;
   - *shared sections*: one section heading in two documents of the same org and kind (an
     evaluation across two system cards).
2. **Draft** (`draft`): a model reads the cited document and names the units that bear on the
   sentence, each with a verbatim quote, and a verdict. Code keeps only the units whose quote
   `verify_quote` passes there; those are the gold. A supported sentence also gives a
   *perturbed* claim (one specific change, so the source no longer supports it) with the same
   gold pages. Real "the source does not say that" cases come through when the drafter's
   verdict on a real citing sentence is `not_supported`. For diffs and shared sections, code
   has located both units; the model writes only the question.
3. **Check** (`check`): a second model from another family (Codex `gpt-6-luna`) reads the
   question, the expected answer and the gold text, and must agree; otherwise the question is
   rejected. A person can then accept questions (`checks` level `human`).
4. **Split** (`split`): by a hash of the cited document, so one document's questions never sit
   on both sides. `questions/dev.jsonl` is public. The test split is written to `heldout/`,
   which is not committed. Every question file carries a canary line.

Results are reported per construction method (`by_method`), since perturbed claims are
easier to call than real misattributions.

**Version 1** (snapshot `2026.11.3`). `mine` found 135,807 candidates (133,930 citing
sentences, 231 version diffs, 1,646 shared sections). `pick` chose 510 of them spread across
the kind of document asked about (system cards, frameworks, government guidance, model cards
and evaluator reports before papers and forum posts; at most two per document, three for
version diffs, one per citing-and-cited pair):

```sh
python -m safetypage.bench pick --corpus data/snapshots/2026.11.3 \
  --candidates citationbench/work/real/candidates.jsonl --out citationbench/work/real/picked.jsonl \
  citing_sentence/system_card=120 citing_sentence/framework=60 citing_sentence/government=60 \
  citing_sentence/model_card=40 citing_sentence/eval_report=40 citing_sentence/paper=220 \
  citing_sentence/forum_post=50 citing_sentence/blog=25 citing_sentence/article=25 \
  version_diff=50 shared_section/system_card=45 shared_section/model_card=12 \
  shared_section/eval_report=10 shared_section/government=6
```

`claude-code:claude-opus-5-5` drafted 435 questions from them (candidates whose quotes did
not verify, whose reference match was wrong, or whose sentence only names the work drop out
here). `codex:gpt-6-luna` rejected 40 (9%): 28 of 184 citing sentences (15%), 8 of 195
perturbed claims (4%), 2 of 18 version diffs, 2 of 38 shared sections. Of the 395 left,
201 are in `questions/dev.jsonl` (113 documents) and 194 held out (111 documents). The
leaderboard runs the first 150 or 50 held-out questions in id order (`limit`), so a
50-question row is a subset of a 150-question one. The fixture corpus's five questions are in
`questions/fixtures.jsonl`, for the smoke and ablation configurations.

Known weaknesses of version 1: perturbed claims are about half of every split, and are easier
than real misattributions (report `by_method`); few real citing sentences are judged
`not_supported`; some sentences cite several works at once in author-year form, so which work
is being checked is left to the agent; some sentences carry PDF artifacts (hyphenation,
equations, running headers).

## Run it

Runs use subscription logins, not API keys. A leaderboard row is an **agent plus a model**
(Claude Code with Opus 5.5, Codex with GPT-6.1 Sol), and the results file names both.

| Agent | Login | How it is isolated |
|---|---|---|
| `claude-code` | `claude` (`CITATIONBENCH_CLAUDE` names another binary) | `--tools ""` (no built-in tools), `--strict-mcp-config` with only the library, `--setting-sources ""` (no user settings, plugins or hooks), no saved session |
| `codex` | the ChatGPT login | its own `CODEX_HOME` (no user AGENTS.md or config; `auth.json` is a link to the real one), shell, apps, plugins, browser, images, memories and web search off. Its code mode stays on because GPT-6 calls MCP tools through it; it has no file system, imports or network |
| `antigravity` | the Google login (`agy`) | its own `HOME` with only the library server, permission rules denying commands, files and URLs. Its web search cannot be turned off: a sample that uses it, or any other non-library tool, is marked `contaminated` and scores as wrong |
| `inspect` | none, or an API key | Inspect's `react` agent; used for local models on oMLX, and by anyone with API keys |

```sh
uv sync --all-groups
SAFETYPAGE_OPS_DB=citationbench/work/ops.sqlite \
  uv run --group server python -m safetypage.server --fixtures --port 8766 &
uv run --group bench python -m safetypage.bench run citationbench/configs/smoke.toml
```

One question per fresh session. Every tool call carries `X-SafetyPage-Run` and
`X-SafetyPage-Sample`, so the server's call log (`ops.sqlite`) is the record of what the agent
saw; the CLI's output gives the answer, tokens and the account's usage meter. Scoring is the
same code as above. A run writes `results/<run_id>.json` and `traces/<run_id>/`; the raw
per-sample records are in `work/runs/<run_id>/` (not committed). A trace holds its question,
so a run on the held-out split writes its traces to `work/traces/<run_id>/` instead, and only
the replays chosen for the site are copied to `traces/`. Those questions are public from then
on and leave the held-out split in its next version (v1: `pc-4bd058594c`, `pc-0b71f9e37b`,
`pc-1022dddab4`).

**Usage safety.** A batch runs at most `batch` samples with `pause` seconds between them, and
stops cleanly, recording why and which sample is next in `work/runs/<run_id>/stopped.json`, when:

- the CLI reports a rate or usage limit;
- the account's usage meter passes `max_used` (default 0.8);
- the next sample would not finish before `--until HH:MM`.

Rerunning the same configuration resumes where it stopped. Usage meters: Claude Code reports
the 5-hour and 7-day windows' used share on every run (`rate_limit_event`). Codex writes the
same two windows into its session file. Antigravity reports tokens but no meter. Meters are
account-wide, so other use of the account moves them too.

API keys are never the default. A configuration reads them from the 1Password vault only when it
says `vault = ["anthropic"]` (see `configs/inspect-api.toml`), and only through a local,
untracked `vault.local.toml` (copy [`vault.example.toml`](vault.example.toml)),
and `draft`, `check` and `agreement` only with `--vault`. Drafting, checking and judging default
to the CLIs: `claude-code:claude-opus-5-5` drafts, `codex:gpt-6-luna` checks (another model
family), and `claude-code:claude-sonnet-5-5` judges.

Configurations in [`configs/`](configs/): `smoke` (Claude Code, Haiku), `cc-*`, `codex-*`,
`agy-*`, `local-*`, and the ablations, each changing one thing against `ablation-default`
(Claude Code with Sonnet 5.5):

| Config | Server surface | Question it answers |
|---|---|---|
| `ablation-no-verify` | `no-verify` | What does `verify_quote` add? |
| `ablation-one-tool` | `one-tool` (search only, full text in hits) | One tool versus four |
| `ablation-short` | `short` | Short versus long tool descriptions |
| `ablation-arm-bm25` / `-dense` / `-hybrid` | `arm-<arm>` | Keyword versus dense versus hybrid retrieval (needs the snapshot's arms and the server surfaces) |

```sh
python -m safetypage.bench compare results/<a>.json results/<b>.json --measure correct
python -m safetypage.bench publish      # the site's leaderboard, runs and traces
```

### Local models, overnight

`python -m safetypage.bench nightly` runs the configurations in
[`configs/nightly.txt`](configs/nightly.txt) on a local oMLX server, between 04:00 and 06:25. It
starts oMLX and the library server if they are down (and stops them afterwards if it started
them). Before each model it checks free memory against the model's `size_gb` plus 6 GB, and
skips the model that night if it does not fit. It resumes the next night. A model downloaded
only for testing has `hf_repo`, `download = true` and `delete_after = true` in its
configuration, and its files are removed from `~/.cache/huggingface/hub` once its run is
complete. Models that were already on disk are never deleted. To schedule it, fill in
[`nightly.plist.example`](nightly.plist.example) and install it as a LaunchAgent; machine-specific
copies live in `local/`, which is not committed. The log is `work/nightly.log`.

## Validating the judge

```sh
python -m safetypage.bench pairs --traces citationbench/traces     # claim-citation pairs from questions and runs
python -m safetypage.bench label --who <name>                 # label in the terminal, blind to the judge
python -m safetypage.bench agreement --judge claude-code:claude-sonnet-5-5
```

For version 1 the sample is 100 pairs in `work/labels/pairs.jsonl` (not committed, since 60
of its claims come from answers to held-out questions): 40 from public questions (a citing or
perturbed sentence and one of its gold units) and 30 each from the Claude Code Haiku 5.5 and
Codex GPT-6.1 Sol runs. Pages run about 500 words, so a pair takes about a minute; `q` stops
and a later session resumes where it stopped:

```sh
uv run --group bench python -m safetypage.bench label --who noah \
  --corpus data/snapshots/2026.11.3 --pairs citationbench/work/labels/pairs.jsonl
uv run --group bench python -m safetypage.bench agreement \
  --corpus data/snapshots/2026.11.3 --pairs citationbench/work/labels/pairs.jsonl
```

`labels/pairs.jsonl` holds claims and cite strings only, never document text. Labels go to
`labels/human-<name>.jsonl`; agreement (Cohen's kappa on three labels and on two, precision and
recall of the judge's `unsupported`) to `labels/agreement.json`, which results files and the
leaderboard pick up by judge id (`<model>#<prompt hash>`). Until people have labelled a sample,
support numbers carry `agreement: null` and should not be published as findings.

## Running it yourself

There is no submission system. To score another agent: point it at the public MCP endpoint,
run `citationbench run` with your own configuration, and publish the results file and traces; the
configuration in the results file says how to reproduce it.

# PageCite

A benchmark of whether an agent with a library tool cites the right page, quotes it accurately,
and makes claims the page supports. The harness is on [Inspect](https://inspect.aisi.org.uk);
the code is in [`src/onthepage/bench/`](../src/onthepage/bench/) and its tests in
[`tests/bench/`](../tests/bench/).

Checking that a citation points at real text is nearly solved. Checking that the cited page
supports the claim is not: on identical outputs the measured unsupported-citation rate moves
from about 3% to 18% depending only on the verifier (arXiv 2607.20527). So PageCite keeps the
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

How quotations attach to citations is `onthepage.answer.parse_answer`, the same rule
`check_answer` uses, so an agent that checks its draft and the scorer read it alike. Every
measure gets a 95% interval from a bootstrap over questions clustered by the document they are
about. Ablations are reported as paired differences on the same questions (`compare`).

## The questions

Not written by hand. Each records how it was made (`made`) and how it was checked (`checks`).

1. **Mine** (`python -m onthepage.bench mine`), by code:
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
3. **Check** (`check`): a second model from another family (Azure `gpt-5-mini`) reads the
   question, the expected answer and the gold text, and must agree; otherwise the question is
   rejected. A person can then accept questions (`checks` level `human`).
4. **Split** (`split`): by a hash of the cited document, so one document's questions never sit
   on both sides. `questions/dev.jsonl` is public. The test split is written to `heldout/`,
   which is not committed. Every question file carries a canary line.

Results are reported per construction method (`by_method`), since perturbed claims are
easier to call than real misattributions.

**First batch** (fixture corpus, six documents): 3 candidates mined (2 citing sentences, 1
version diff), 5 questions drafted by `claude-opus-5-5`, all gold quotes verified by code, all 5
passed the `gpt-5-mini` check; 4 in `questions/dev.jsonl`, 1 held out. The real set is built
the same way when the real corpus lands.

## Run it

```sh
uv sync --all-groups
# a server on the fixture corpus (port 8000 is a local oMLX server)
uv run --group server python -m onthepage.server --fixtures --port 8765 &
uv run --group bench python -m onthepage.bench run pagecite/configs/smoke.toml
```

A run writes the Inspect log to `logs/` (not committed; open it with `inspect view`), a
results file to `results/<run_id>.json` and a trace per sample to `traces/<run_id>/`. The
configuration in the results file reruns it. API keys come from the environment;
missing ones can be read from a 1Password vault.

Configurations in [`configs/`](configs/): `smoke` (Haiku, fixtures), `baseline` and one per
ablation. Each ablation changes one thing against `baseline`:

| Config | Server surface | Question it answers |
|---|---|---|
| `ablation-no-verify` | `no-verify` | What does `verify_quote` add? |
| `ablation-one-tool` | `one-tool` (search only, full text in hits) | One tool versus four |
| `ablation-short` | `short` | Short versus long tool descriptions |
| `ablation-arm-bm25` / `-dense` / `-hybrid` | `arm-<arm>` | Keyword versus dense versus hybrid retrieval (needs the snapshot's arms and the server surfaces) |

```sh
python -m onthepage.bench compare results/<baseline>.json results/<ablation>.json --measure correct
python -m onthepage.bench estimate results/<smoke>.json --questions 300 --epochs 3   # cost of a full run
python -m onthepage.bench publish                                                   # the site's leaderboard, runs, traces
```

Local models (Qwen on a local oMLX server) run as `openai-api/omlx/<model>`. Local model work runs
overnight only, 22:00 to 06:00.

## Validating the judge

```sh
python -m onthepage.bench pairs --traces pagecite/traces     # claim-citation pairs from questions and runs
python -m onthepage.bench label --who <name>                 # label in the terminal, blind to the judge
python -m onthepage.bench agreement --judge anthropic/claude-sonnet-5-5
```

`labels/pairs.jsonl` holds claims and cite strings only, never document text. Labels go to
`labels/human-<name>.jsonl`; agreement (Cohen's kappa on three labels and on two, precision and
recall of the judge's `unsupported`) to `labels/agreement.json`, which results files and the
leaderboard pick up by judge id (`<model>#<prompt hash>`). Until people have labelled a sample,
support numbers carry `agreement: null` and should not be published as findings.

## Running it yourself

There is no submission system. To score another agent: point it at the public MCP endpoint,
run `pagecite run` with your own configuration, and publish the results file and traces; the
configuration in the results file says how to reproduce it.

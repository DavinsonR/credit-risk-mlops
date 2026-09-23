# credit-risk-mlops

A credit decisioning system with model risk governance, built on real US public
data. The model is not the point. **The point is that it survives an audit — and
that I ran the audit against myself first.**

> 🇪🇸 [Versión en español](README.es.md) · Engineering log: [NOTES.md](NOTES.md) ·
> Architecture decisions: [docs/adr/](docs/adr/)

---

## What it found

Every project shows the run that worked. This one ships the ledger of what broke,
because that is the part you cannot fake and the part that predicts how someone
works. Each row links to the artifact that proves it.

| # | What broke | Why it matters |
|---|---|---|
| 1 | **AUC 0.9461** looked great. `TermInMonths` is overwritten when a loan is liquidated — the field leaked the outcome. Remove it and the ablation drops to **0.6621** | [ADR 0002](docs/adr/0002-terminmonths-es-fuga.md) · I deleted my best number on purpose |
| 2 | The temporal split crossed a cyclical base rate. Validation scored *worse* than test and PSI hit **4.08**. Redesigned around two measured criteria | [ADR 0003](docs/adr/0003-diseno-del-split-temporal.md) |
| 3 | `exports/metrics.json` was hand-editable. **I wrote AUC 0.95 into it and every gate passed.** The fingerprint did not cover the code either | [docs/AUDIT.md](docs/AUDIT.md) · both closed |
| 4 | The adverse-action compliance checker used `"\b"` in a non-raw string — that is the **backspace** character, not a word boundary. The control silently matched nothing | Week 8 · found by testing the checker against bad output |
| 5 | I reported LLM inconsistency as a finding about local inference. It was **my measurement**: the first generation after a model loads is not deterministic. With warm-up, one arm went 0% → 83% | [ADR 0009](docs/adr/0009-la-plantilla-gana-al-llm.md) |
| 6 | The authorship hook **failed open**. `grep` returns non-zero both when it finds nothing and when it cannot search. With `sh.exe` lacking `/usr/bin` on PATH: `grep: command not found`, exit 0, **AI trailer accepted silently** | Now fails closed · 18 tests |
| 7 | `run all` printed **`APPROVED: 8 gates passed`** after training crashed. The gates read committed metrics, so they passed with no new model | [tests/test_run_aborta.py](tests/test_run_aborta.py) |
| 8 | **CI was red for 8 consecutive commits** while I wrote "lint green, N tests" in five commit messages. A test asserted local git config that CI never sets | Fixed · plus [`run ci-local`](scripts/ci_local.py), which reproduces CI before pushing |
| 9 | Two published numbers **did not replicate on another machine**: the DuckDB/PySpark benchmark (29.3x → 14.3x) and LLM consistency (0.83 → 0.33). I had presented single-machine measurements as properties of the system | Both retracted and re-stated as ranges |
| 10 | `MODEL_CARD.md` listed **7 gates of 8** — its generator never called the fairness one, the only gate the model fails. And `VALIDATION_REPORT.md` printed `PASS` for that gate in §3.1 while §5 said "promotion blocked" | Root cause was mine: one boolean meant two things. Now `passed` ≠ `threshold_met` |
| 11 | Three modules defined their analysis sample with `glob("*.parquet")`. **The filesystem decided what "62.4M applications" meant.** Downloading three more years for the event study would have silently moved the observed-disparity numbers, the backend benchmark and that headline — and no test would have failed, because every test reads the same directory the code does | Found by being about to trip it · the window now comes from `config.yaml` · [tests](tests/test_hmda_shard_selection.py) |
| 12 | The hybrid-LLM instrumentation passed its new fields **only on the error branch** of `evaluate()`. On every success — i.e. every case being analysed — they arrived empty, pandas read `NaN`, `.astype(bool)` made it `False`, and the report printed a conclusion about a field that was never filled | [ADR 0009 rev. 3](docs/adr/0009-la-plantilla-gana-al-llm.md) · the analysis now refuses to conclude without instrumentation |
| 13 | The browser demo **had never been clicked.** The SBA-guarantee field carried `step="1000"` and a default of `187500` — 75% of the loan, the correct figure — which is not a multiple of 1000. The form was born invalid, so the button did nothing. The ONNX model loaded, parity was verified, and the one thing nobody had done was press the button | [tests/test_web_demo_form.py](tests/test_web_demo_form.py) · now live and bilingual |
| 14 | **Nothing read `.env`.** `.env.example` said "copy to .env", the harness said "keys in .env", and the providers called `os.environ.get(...)`, which only sees real environment variables. Following the repo's own instruction left Groq and Gemini "unavailable" — no error, no hint | Found while writing [docs/LLM_PROVIDERS.md](docs/LLM_PROVIDERS.md) · [`crmlops.env`](src/crmlops/env.py) · 8 tests |
| 15 | The `.pbip` declared a report artifact that **did not exist** — only the semantic model had been written. Power BI Desktop cannot open a project whose report is missing, so the first line of the guide was unrunnable. The scaffold test missed it because it checked a hand-written file list instead of what the `.pbip` itself declares | Found while writing [docs/POWERBI.md](docs/POWERBI.md) · the test now follows the artifact chain |
| 16 | `run ci-local` copied the working tree over a clean clone of HEAD but **never deleted anything**, so a file the commit removes stayed alive in the clone. A deletion that breaks CI was invisible to the control built to catch exactly that. Checking whether the source file exists is not enough either: `git ls-files` lists the index, and a file already removed with `git add -A` is not in it | Found by deleting the legacy `report.json` · it now diffs against `HEAD` |

Full log in [NOTES.md](NOTES.md) and [docs/AUDIT.md](docs/AUDIT.md). Nine of these
**failed silently or reported success** — which is the failure mode the whole project
is built to hunt, found in its own tooling.

---

## What it is

| Model | Source | Target | Regulatory anchor |
|---|---|---|---|
| **A — Default / Loss** | SBA 7(a) FOIA · 1.96M loans, FY1991–2026 | Charge-off (PD) + severity (LGD) | [SR 26-2](docs/adr/0012-el-ancla-regulatoria-cambio.md) |
| **B — Underwriting / Access** | HMDA · **62.4M applications**, FY2020–2024 | Denial | ECOA / Reg B |

The event study below runs on a wider window — **93.4M applications, FY2018–2025** —
declared separately in `config.yaml` so that extending it cannot move the published
model's numbers. That separation exists because it once failed to: see defect 11.

HMDA row counts are verified against the CFPB's own published aggregations: a
download that finishes is not a download that is **complete**.

## The numbers, with their counterweight

Declining the riskiest 10% of the FY2017–2018 test portfolio would have avoided
**$276.3M** in charge-offs — 2.15x what declining at random achieves, and **$942.1M**
of the period's realized loss was absorbed by the SBA, i.e. by the taxpayer.

And the part a sales deck leaves out: doing that **forgoes $1.99B in good lending
volume** — 7.2x the loss avoided. Both numbers ship in the same payload
([`exports/web/resumen.json`](exports/web/resumen.json)), because a headline that
shows only the numerator is not a headline.

| | |
|---|---|
| AUC (test, out-of-time) | **0.7005** |
| Margin over the interpretable WoE scorecard | **+0.0311** |
| Calibration error (ECE) | **0.0107** |
| Under a 2007-style regime | **AUC 0.5456**, and it underestimates risk 8x |

That last row is not a caveat, it is a deliverable: `run stress` exists to answer
what happens when the regime changes.

## Causal inference

The model answers *"who will default?"*. The lever the SBA actually controls demands
a different question — *"what happens if we change the guarantee percentage?"* —
because **the SBA does not originate loans, it guarantees them.**

`run causal` answers it, and the answer is that **it cannot be answered with this
data.** Three diagnostics over 1,398,416 loans:

| Diagnostic | Measurement | Consequence |
|---|---|---|
| Does the treatment have its own variation? | **R² = 0.9145** on (processing method × $10k size) cells | No overlap: DML and causal forests have nothing to exploit |
| Is there an RD at the $150,000 threshold? | **83.1%** of the ±$5k window sits *exactly* at $150,000 | Density destroyed — assignment is not locally random |
| Is the raw gradient composition? | **+7.76 pp** raw → **+4.79 pp** within the same size band | A residual survives, and its sign is what adverse selection predicts |

**No effect is published.** An estimator applied where its assumptions fail produces
a number, not an estimate. What ships is the non-identification, with its three
measurements — [ADR 0013](docs/adr/0013-el-efecto-de-la-garantia-no-esta-identificado.md).

This also names the assumption inside the project's own headline: the $276.3M is
computed by ranking on predicted PD and assuming a decline erases the loss. Two
causal claims inside a number presented as a prediction.

### The 2022 rate shock: the gap did not widen, it came back

ADR 0013 said the alternative design was the 2022 rate shock on HMDA — exogenous,
large, with protected classes in the data and **pre-periods to falsify against**.
`run event-study` is that design, over **93.4M applications, FY2018–2025**.

Its first result is not a coefficient. It is that the project's own week-6 finding
was measured against the wrong baseline.

| | Black–White denial gap |
|---|---|
| FY2018–2019 — ordinary rates | **15.70 pp** |
| FY2020–2021 — refi boom | 13.14 pp |
| FY2023–2025 — post-shock | **15.73 pp** |

**The post-shock gap sits 0.03 pp from the pre-pandemic gap.** Measured against 2021
the widening is +2.59 pp — and that is the number in circulation. It measures the refi
boom ending. The five-year panel had exactly one comparable pre-shock year, so there
was no way to see this.

Of the movement against 2021, a Kitagawa decomposition (exact, no residual) puts
**65% on recomposition of the applicant pool** — refinancing collapsed 92% and it was
the lowest-denial segment — and the rest on rates within segment. In FY2024 the
within-segment term is **negative**: gaps narrowed inside segments while the aggregate
rose.

And no causal effect is published, for three measured reasons:

| Check | Result |
|---|---|
| Parallel pre-trends (threshold declared *before* estimating) | **Fails**: +2.37 pp in 2018, monotone — a trend, not noise |
| The textbook fix — extrapolate the pre-trend | Manufactures **+5.61 pp**, because the trend it extrapolates *is* the boom the shock ends |
| Differential selection into the applicant pool | **17.2 pp**: Black applications fell 40%, white ones 57% |

[ADR 0014](docs/adr/0014-el-shock-de-tasas-revirtio-la-brecha-no-la-amplio.md). The
conclusion resembles ADR 0013 — no effect published — but the content is the opposite.
In SBA there was nothing to falsify *with*. Here there was, the test ran, and **the
falsification is what closes the case**. A design that cannot fail its own test is not
identifying anything; it just has not looked.

## Monitoring

A charge-off takes a **median of 51 months** to appear. At 12 months you can see
about **1%** of the defaults a cohort will eventually have. So performance monitoring
on young cohorts is impossible, and this project **refuses to fake it**.

| Signal | `run <task>` | What it detects |
|---|---|---|
| Label maturity | `maturity` | Which cohorts can be evaluated at all, comparing rates at **matched maturity** |
| Population drift | `drift` | PSI per feature and on the score, plus **unsupported mass** in categoricals |
| Decision | `retrain-check` | The three triggers, and what retraining does and does not fix |

**What it found on its first run:** the SBA changed the `business_age` category
scheme between FY2018 and FY2021. Today **84%** of its values fall into categories
the model never saw. It carries the **second-highest information value** in the
interpretable baseline (0.0536, behind `initial_rate` at 0.1461), and serving maps
unseen categories to "unknown" — so the model does not degrade, it **loses the
variable entirely and keeps answering with the same confidence**.
[ADR 0011](docs/adr/0011-la-fuente-cambio-el-vocabulario.md).

**And what it cost to fix.** ADR 0011 argued that harmonising the vocabulary would
cost resolution — four age bands collapse into one. Arguing is not measuring, so
`run harmonize` trains the production model twice, same split, same seed, changing
only that vocabulary:

| | AUC (test) | Coverage of FY2024–2026 |
|---|---|---|
| Raw vocabulary | 0.7005 | **15.4%** |
| Harmonised | 0.6990 | **90.1%** |

**0.0015 of AUC buys back 74.7 points of coverage.** The intuition was right in
direction and negligible in magnitude — and written without measuring, that same
sentence would have justified doing nothing. What does not move: 9.7% stays
unsupported, because `Change of Ownership` is not an age but a form of acquisition,
and mapping it would be inventing the data.

## Promotion gates

Ten gates. A model is not promoted unless it passes them, and CI runs them on every
PR.

| Gate | What it guarantees |
|---|---|
| `config_coherente` | The metrics correspond to the current `config.yaml` |
| `integridad` | Metrics are **recomputed** from saved predictions, not believed |
| `auc_test` | Absolute discrimination floor |
| `margen_sobre_baseline` | The challenger beats the interpretable scorecard by ≥0.02 |
| `drop_oot` | Out-of-time degradation stays within 2x natural variation |
| `brier_test` | Beats the no-skill predictor (constant = base rate) |
| `ece_test` | Predicted and observed agree within 2 percentage points |
| `hmda:disparate_impact` | Four-fifths rule per protected class. **Currently 0.7639, so the access model is not promoted** |
| `reporte:MODEL_CARD.md` | The model card describes the published metrics, not older ones |
| `reporte:VALIDATION_REPORT.md` | Same for the validation report |

Every threshold has its derivation written next to it in `config.yaml`. None was
chosen because the model passed it — see [docs/AUDIT.md](docs/AUDIT.md).

The verdict distinguishes two things that used to be conflated: **`passed`** means
"the build does not break" and **`threshold_met`** means "the model complies". For
the fairness gate they differ, and it now reads `NO CUMPLE (build ok: no se promueve)`.

## Verify it yourself

No number in this README is worth more than the command that reproduces it. One
prerequisite: [`uv`](https://docs.astral.sh/uv/) — Python 3.12 and every dependency
are installed by the project.

```powershell
.\run setup      # Python 3.12 + dependencies + authorship hook
.\run test       # the suite. Prints its own count; do not trust mine
.\run gates      # the ten gates, recomputed from saved predictions
```

Those three need **no data download**: `exports/metrics.json` is committed and the
integrity gate recomputes its metrics from the stored predictions, so the model can
be audited without access to the sources. It is why CI downloads nothing.

```powershell
.\run acquire    # SBA 7(a), 861 MB, SHA256-verified against the manifest
.\run all        # train -> gates -> model card -> economics (stops at first failure)
.\run reproduce  # retrains and ASSERTS the metrics are identical to the committed ones
.\run ci-local   # runs what CI runs, in a clean clone, before you push
```

**Or just score a loan:** the production ONNX artifact runs in the browser, with no
server and nothing leaving the page —
[proyecto-davirson-git.vercel.app/credit-risk-demo](https://proyecto-davirson-git.vercel.app/credit-risk-demo/index.html?lang=en).
Set business age to `Change of Ownership` to watch defect row 11's cousin in action:
the category is not in the contract, so it scores as unknown and the model answers
with the same confidence.

Step-by-step for every level, optional extras and known problems:
**[docs/INSTALL.md](docs/INSTALL.md)**. On Linux/macOS every task is a `make` target.
Two more procedures live next to it: **[docs/POWERBI.md](docs/POWERBI.md)** (build the
report) and **[docs/LLM_PROVIDERS.md](docs/LLM_PROVIDERS.md)** (turn on the Groq and
Gemini arms).

## What this is not

- **Not in production, and its exposure is zero.** Under SR 26-2, materiality follows
  purpose and exposure; this is a reference exercise and says so in its own
  validation report.
- **Not a compliance assessment.** SR 26-2 and the EU AI Act Annex IV are used as a
  structure and a vocabulary, not as a certification.
- **Not an automated credit decision.** It is an input to a human one.
- **Reject inference is not solved.** Only approved loans have outcomes, so the model
  describes risk *conditional on having been approved*. It is discussed, not fixed.
- **The ONNX artifact is not hash-stable.** The model reproduces — 5 identical graph
  nodes, bit-identical predictions on 20,000 rows — but re-exporting yields different
  bytes. The distinction matters in a project that sells auditability, so it is
  written down.

## What is missing

The ten-week scope is closed. What remains is written down and prioritised by how
much it changes the outcome, not by when it came up — **[docs/ROADMAP.md](docs/ROADMAP.md)**,
with the click-by-click version in **[docs/CHECKLIST.md](docs/CHECKLIST.md)**.

Three of the original eleven items remain, and **none of them is code**: two free API
keys, opening in Power BI Desktop a report that is already written and validated against
Microsoft's schemas, and twenty-one deliberately empty paragraphs in the engineering log
that only their author can fill — and that, written by anyone else, would not serve the
purpose they exist for.

## License

MIT (code). Source data keeps its own licensing — see
[docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

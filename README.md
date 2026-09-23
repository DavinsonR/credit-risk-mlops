# credit-risk-mlops

A credit decisioning system governed the way a bank's model risk function governs
one, built end to end on **64M+ real US public records**: ingestion, modeling,
causal analysis, fair-lending audit, serving, monitoring and an LLM layer for
regulatory notices.

The model is not the point. **The point is that it survives an audit — and that I
ran the audit against myself first.**

> 🇪🇸 [Versión en español](README.es.md) · Architecture decisions: [docs/adr/](docs/adr/) ·
> Defect log: [docs/DEFECTS.md](docs/DEFECTS.md) · Engineering log: [NOTES.md](NOTES.md)

**Stack:** Python 3.12 · DuckDB · LightGBM · scikit-learn · optbinning (WoE scorecard) ·
PyTorch · MLflow · ONNX Runtime · FastAPI · Docker · PySpark · Power BI (PBIP/TMDL) ·
GitHub Actions · `uv`

---

## At a glance

| | |
|---|---|
| Data | **1.96M** SBA 7(a) loans (FY1991–2026) · **62.4M** HMDA applications (FY2020–2024) · **93.4M** for the event study (FY2018–2025) |
| Discrimination | **AUC 0.7005** out-of-time, **+0.0311** over an interpretable WoE scorecard |
| Calibration | **ECE 0.0107** |
| Business impact | **$276.3M** in charge-offs avoided by declining the riskiest 10% — **2.15x** random |
| Governance | **10 promotion gates** in CI; metrics are **recomputed** from stored predictions, never trusted |
| Documentation | **14 ADRs**, a model card, and a validation report structured on SR 26-2 and EU AI Act Annex IV |
| Serving | One ONNX artifact, **three runtimes** (FastAPI, serverless, in-browser WASM), parity-tested |
| Try it | [Score a loan in the browser](https://proyecto-davirson-git.vercel.app/credit-risk-demo/index.html?lang=en), no server, nothing leaves the page |

## What it demonstrates

| Capability | Evidence |
|---|---|
| **Model risk governance** | Promotion gates that recompute metrics and fingerprint config *and* modeling code; changing either without retraining fails the build |
| **Leakage detection** | A contamination audit that caught a post-origination field inflating AUC to 0.946 — [ADR 0002](docs/adr/0002-terminmonths-es-fuga.md) |
| **Out-of-time validation and stress** | Split designed around cyclical base rates and label censoring; a 2007-style regime scored as a deliverable — [ADR 0003](docs/adr/0003-diseno-del-split-temporal.md) |
| **Causal inference** | Two designs, two measured non-identifications, zero effects published without identification — [ADR 0013](docs/adr/0013-el-efecto-de-la-garantia-no-esta-identificado.md), [ADR 0014](docs/adr/0014-el-shock-de-tasas-revirtio-la-brecha-no-la-amplio.md) |
| **Fair lending** | Four-fifths rule per protected class; the access model is **blocked from promotion** at 0.7639 |
| **Production monitoring** | Label maturity, PSI and unsupported-mass drift, and an explicit retrain decision |
| **LLM engineering** | Adverse-action notices with a deterministic fallback, programmatic evals and no LLM-as-judge — [ADR 0009](docs/adr/0009-la-plantilla-gana-al-llm.md) |
| **Reproducibility** | `run reproduce` retrains and asserts the metrics are identical to the committed ones; `run ci-local` reproduces CI before a push |

---

## Two models, two regulatory regimes

| Model | Source | Target | Regulatory anchor |
|---|---|---|---|
| **A — Default / Loss** | SBA 7(a) FOIA · 1.96M loans, FY1991–2026 | Charge-off (PD) + severity (LGD) | [SR 26-2](docs/adr/0012-el-ancla-regulatoria-cambio.md) |
| **B — Underwriting / Access** | HMDA · **62.4M applications**, FY2020–2024 | Denial | ECOA / Reg B |

SBA files are acquired through URL discovery and verified against a SHA256 manifest.
HMDA row counts are verified against the CFPB's own published aggregations: a
download that finishes is not a download that is **complete**. Every analysis window
is declared in `config.yaml`, so extending the event-study window cannot move the
published model's numbers.

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

The alternative design is the 2022 rate shock on HMDA — exogenous, large, with
protected classes in the data and **pre-periods to falsify against**. `run
event-study` runs it over **93.4M applications, FY2018–2025**, and its first result
is that the project's own earlier finding was measured against the wrong baseline.

| | Black–White denial gap |
|---|---|
| FY2018–2019 — ordinary rates | **15.70 pp** |
| FY2020–2021 — refi boom | 13.14 pp |
| FY2023–2025 — post-shock | **15.73 pp** |

**The post-shock gap sits 0.03 pp from the pre-pandemic gap.** Measured against 2021
the widening is +2.59 pp — and that is the number in circulation. It measures the refi
boom ending.

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

[ADR 0014](docs/adr/0014-el-shock-de-tasas-revirtio-la-brecha-no-la-amplio.md). In
SBA there was nothing to falsify *with*. Here there was, the test ran, and **the
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

**And what it costs to fix.** `run harmonize` trains the production model twice, same
split, same seed, changing only that vocabulary:

| | AUC (test) | Coverage of FY2024–2026 |
|---|---|---|
| Raw vocabulary | 0.7005 | **15.4%** |
| Harmonised | 0.6990 | **90.1%** |

**0.0015 of AUC buys back 74.7 points of coverage.** What does not move: 9.7% stays
unsupported, because `Change of Ownership` is not an age but a form of acquisition,
and mapping it would be inventing the data.

## The LLM layer

Denying credit under ECOA/Reg B **legally obliges** you to state the specific principal
reasons. That is the one place a language model has a real job here: SHAP picks the
factors, the model only rewrites them in plain language — and **its output is validated
against the template before being used**, so the worst case is exactly the baseline.

The harness compares five arms on the same six notices, with four programmatic metrics
(no LLM-as-judge) and **two runs per case**, because a legal document that changes
between executions is indefensible.

| Arm | Faithfulness | Compliant | Readability | Consistency | Passes |
|---|---|---|---|---|---|
| **Deterministic template** | 1.00 | 1.00 | 44.8 | **1.00** | **100%** |
| **gpt-oss-120b · hybrid (Groq)** | 1.00 | 1.00 | **52.3** | **1.00** | **100%** |
| gemini-flash-lite · alone | 1.00 | 1.00 | 57.8 | **0.00** | 0% |
| qwen2.5:7b · hybrid (local) | 1.00 | 1.00 | 53.4 | 0.67 | 67% |
| llama3.2:3b · alone (local) | 0.50 | 1.00 | 74.6 | 0.50 | 0% |

**Gemini answered all twelve calls faithfully and never produced the same text twice**,
at temperature 0. For a document whose obligation is legal, that disqualifies on its own
— no argument about prose quality required.

The hybrid over Groq is the only arm that ties the template on every gate and beats it
on readability, in both languages. **The template still ships**: the challenger is
equally good and more fragile — it needs a network, a third party and a quota.

Consistency figures are published only from repeated runs, never from a single one.

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

The verdict separates two questions: **`passed`** means "the build does not break"
and **`threshold_met`** means "the model complies". For the fairness gate they differ,
and it reads `NO CUMPLE (build ok: no se promueve)`.

## Engineering discipline

Every defect found during the build is logged with its root cause and the control that
now prevents it — **[docs/DEFECTS.md](docs/DEFECTS.md)**. The adversarial audit of the
governance layer lives in [docs/AUDIT.md](docs/AUDIT.md), and each
design decision has an [ADR](docs/adr/).

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

On Linux/macOS every task is a `make` target.

**Or just score a loan:** the production ONNX artifact runs in the browser, with no
server and nothing leaving the page —
[proyecto-davirson-git.vercel.app/credit-risk-demo](https://proyecto-davirson-git.vercel.app/credit-risk-demo/index.html?lang=en).
Set business age to `Change of Ownership` to see the monitoring finding live: the
category is not in the contract, so it scores as unknown and the model answers with
the same confidence.

Step-by-step for every level, optional extras and known problems:
**[docs/INSTALL.md](docs/INSTALL.md)**. Two more procedures live next to it:
**[docs/POWERBI.md](docs/POWERBI.md)** (open the report in Desktop) and
**[docs/LLM_PROVIDERS.md](docs/LLM_PROVIDERS.md)** (the hosted LLM arms).

## Scope

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

What comes next is prioritised by how much it changes the outcome:
**[docs/ROADMAP.md](docs/ROADMAP.md)**.

## License

MIT (code). Source data keeps its own licensing — see
[docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

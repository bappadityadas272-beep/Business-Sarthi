# ML_PLAN: models, data, evaluation

> Principle: **simple, honest and checkable beats clever.** Each model below states the problem, the approach, why it was chosen, the alternatives rejected, inputs, outputs, and how we evaluate it. All numbers in the UI come from these models or from plain arithmetic, never from the LLM.

## 1. Model map

| ID | Name | Feature | Approach | Priority |
|---|---|---|---|---|
| ML1 | Location score | F2 | Transparent weighted scoring over OSM features | P1 |
| ML2 | Set-up forecast | F1 | LightGBM (Huber loss, monotone) P50 + ratio band + conformal calibration, trained on synthetic data (DEC-35) | P0 |
| ML3 | Re-forecast | F5 | Shrinkage blend of ML2 prior and shop's own history; ETS for trend and weekly seasonality | P0 |
| ML4 | Stock advice | F3 | Reorder point from demand mean and variability; dead-stock rule | P0 |
| ML5 | Review engine | F5 | Indicator calculation + YAML rule table (grow / hold / pivot) | P0 |
| ML6 | Alert engine | F6 | Rules plus robust z-score for dips | P0 |
| ML7 | Scheme matcher | F4 | Rule-based eligibility filter + embedding retrieval | P1 |
| ML8 | Chatbot | F7 | Router + tools + RAG + LLM with guard | P0 |
| ML9 | Expansion simulator | F8 | Monte Carlo over ML2/ML3 uncertainty | P2 |
| ML10 | Pricing helper | F9 | Margin arithmetic against category targets | P2 |

## 2. Data strategy

**Reality:** we have no real shop dataset. Be explicit about it everywhere.

| Source | Use | Notes |
|---|---|---|
| **Synthetic generator** (`data/synthetic/generate.py`) | Trains ML2 and ML3 priors; seeds demo shops; tests | All outputs tagged `is_synthetic=true`. Parameters set from public sources where possible (assumed, documented in `data/synthetic/config.yaml`) |
| **Public retail dataset** (one of: a grocery or retail daily sales dataset) | Validates only that the *method* (quantile GBM, conformal, seasonal baseline) behaves sensibly on real retail time series | **Licence check is a checkpoint (D-02).** Candidates to check: UCI Online Retail II; Kaggle grocery or store-sales datasets (many are competition-only, so verify terms before use). Never ship a dataset whose licence forbids it |
| OpenStreetMap | Location features | ODbL, attribution required |
| Scheme KB | RAG | Hand-curated JSON from official pages; each entry has `source_url`, `last_verified`, `verified` |

**Synthetic generator spec** (D-01):

- Unit: one shop, daily sales by category for 24 months.
- Drivers (each with a plausible, documented parameter range): base footfall from catchment (homes, schools, transit count), competitor count within 500 m (negative effect), shop size, weekday pattern (weekend uplift), monthly pay-day pattern (first week uplift), festival spikes (calendar list in config), slow growth trend, noise, rare shock (a month of low sales).
- Categories: staples, dairy, snacks and beverages, household, personal care.
- Margins by category from config (assumed ranges, such as 8 to 20 percent); fixed costs from rent and staff.
- Output tables: `shops.csv` (static features), `daily.csv` (shop, day, category, sales, purchases), `labels.csv` (first-3-month and 12-month revenue for supervised training).
- A `--demo` flag writes the Ramesh Kirana shop with a seeded dip month and EMI squeeze.
- Seeded and reproducible (`--seed`).

**Caveat to state in the UI and README:** because the training data is synthetic, forecast accuracy on real shops is **unknown** until a pilot. The prototype demonstrates the pipeline.

## 3. ML1: Location score (F2)

- **Problem:** rank a chosen pin for a given shop type.
- **Features (within 500 m, from Overpass):** count of competing shops of the same type, residential buildings or apartments, schools, markets or bus stops, banks or ATMs (footfall proxies).
- **Approach:** `score = 100 * sum(w_i * normalise(feature_i))` with weights in `data/rules/location_weights.yaml`. Competitor count enters with a negative weight but saturates (a few competitors signal demand; many signal saturation). Return the score, the top 3 positive and negative drivers, and the counts.
- **Why this approach:** no labelled success data exists, so a learned model would be fabricated. A transparent score is explainable and editable.
- **Rejected:** a trained model on synthetic labels (circular); a black-box location API (cost, licence).
- **Starter product mix:** lookup table by shop type and nearby profile (for example more school-related stationery and snacks near schools), in `data/rules/product_mix.yaml`.
- **Evaluation:** unit tests on hand-made scenarios; manual sanity check on 5 real localities.

## 4. ML2: Set-up forecast (F1)

- **Problem:** before the shop opens, estimate monthly revenue for months 1 to 12 as a range.
- **Inputs:** shop type, size (sq ft), location features (ML1 inputs), rent, staff, budget, city tier, opening month.
- **Targets:** monthly revenue in month k (k = 1..12).
- **Model (as built, DEC-35, DEC-36):** one LightGBM P50 model with Huber loss and monotonic constraints (more competitors never increase revenue), month index and calendar month as features; P10 = P50 x r10 and P90 = P50 x r90 from out-of-fold ratios, re-set by conformal calibration (M-04). Leaf size by shop-grouped CV on training shops. *Originally planned: one LightGBM per quantile with `objective="quantile"`; LightGBM does not allow monotonic constraints with that objective.* Budget is not a model input (DEC-33).
- **Ramp-up:** new shops start below steady state. The training data encodes a ramp curve so month 1 is lower than month 6.
- **Calibration:** after training, apply split conformal prediction on a calibration set to widen or narrow the P10 to P90 band to hit target coverage.
- **Derived outputs (plain arithmetic):** gross profit = revenue x blended margin; operating profit = gross profit minus rent, staff and other fixed costs; break-even revenue = fixed costs / margin; payback months = investment / cumulative operating profit, reported as a range from P10 to P90 paths.
- **Explainability:** SHAP top drivers (or LightGBM feature contributions) shown as plain-language phrases.
- **Why this approach:** tabular data, small, needs quantiles, trains in seconds, and works with monotonic constraints.
- **Rejected:** deep learning (no data, no benefit); a single point forecast (false precision); Prophet or ARIMA (no history exists at set-up).
- **Evaluation:** see section 8. Because training is synthetic, the evaluation proves the code and calibration, not real-world accuracy.

## 5. ML3: Re-forecast (F5)

- **Problem:** after 1 to 3 months of real logs, update the forecast.
- **Approach (shrinkage blend):**
  1. Prior = ML2 forecast for the same horizon.
  2. Own model = ETS (additive trend, weekly seasonality) on daily total sales via `statsmodels` `ExponentialSmoothing`, aggregated to months; with fewer than 28 days use a level-only model.
  3. Blend weight `w = n_days / (n_days + k)` on own model, with `k` tunable in `data/rules/blend.yaml` (first proposed as about 60; set to 10 by cross-validation on synthetic training shops, DEC-55). More data means more trust in the shop's own history.
  4. Interval: combine ETS residual spread with the prior band, then rescale using the shop's observed error against its original forecast. A final band multiplier, chosen on training shops for about 80% coverage, is applied (DEC-55; details in DEC-56).
- **Gaps:** missing days are marked missing (not zero). If more than 30 percent of days are missing, `confidence = low` and the review says so.
- **Why:** classical, robust on short series, easy to explain ("we trust your own sales more as we see more of them").
- **Rejected:** LSTM or transformers (no data); fitting GBM per shop (too few points).
- **Evaluation:** backtest on synthetic shops with rolling origin; compare with seasonal-naive and with the prior only.

## 6. ML4: Stock advice (F3)

- **Reorder point:** `ROP = mean_daily_demand x lead_time_days + z x std_daily_demand x sqrt(lead_time_days)`, with z = 1.28 (about 90 percent service level) by default, lead time per supplier (default 2 days).
- **Reorder quantity:** days of cover target (default 7) x mean daily demand minus on-hand stock.
- **Dead stock:** an item with no sale in 30 days and on-hand above 0.
- **Overstock:** on-hand above 21 days of cover.
- **ABC tagging:** top 20 percent of items by revenue are A items; alerts prioritise them.
- **Demand estimate:** exponentially weighted mean of daily unit sales, per item (falls back to the category average for new items). Settings and definitions are in `data/rules/stock.yaml` (DEC-57 to DEC-60): half-life 7 days, new item = under 14 days of history, days that ended with an empty shelf are left out, B = next 30 percent of items.
- **Why:** textbook, transparent, needs only sales and stock logs.
- **Evaluation:** simulation on synthetic shops: stock-out days and average on-hand days of cover versus a "reorder when empty" baseline.

## 7. ML5 and ML6: Review and alert engines

**Indicators (computed from the last 90 days):**

| Indicator | Definition |
|---|---|
| `revenue_vs_p50` | actual revenue / original forecast P50 for the same months |
| `gross_margin` | gross profit / revenue |
| `dscr` | monthly operating profit / EMI (if a loan exists) |
| `cash_runway_days` | cash buffer / average daily net outflow when negative, else null |
| `growth_rate` | slope of monthly revenue over the period |
| `stockout_days`, `dead_stock_value` | from ML4 |
| `data_completeness` | share of days logged |

**Decision table** (`data/rules/review_rules.yaml`; thresholds are our initial assumptions, to tune with pilot data; document each change in `DECISIONS.md`):

| Decision | Condition (first match wins, top to bottom) |
|---|---|
| **Pivot** | `dscr < 1.0` for 2 months **or** `revenue_vs_p50 < 0.6` **or** `cash_runway_days < 30` |
| **Grow** | `revenue_vs_p50 >= 1.0` **and** `dscr >= 1.5` **and** `growth_rate > 0` **and** `data_completeness >= 0.7` |
| **Hold** | everything else |

Each decision returns the top reasons (the indicator values that triggered it), up to 3 actions from `data/rules/actions.yaml` (for example "reduce slow stock", "check scheme eligibility for a working-capital loan", "consider extending hours"), and a `confidence` value.

**Alerts** (`data/rules/alert_rules.yaml`): sales dip (7-day sales below 70 percent of trailing 28-day average, with robust z-score below -2), low stock (item at or under ROP), EMI due in 5 days with projected cash below EMI, dead stock threshold, data gap (no log for 3 days). Alerts carry `severity` (info, warn, critical) and a message key for localisation. Exact definitions (finished days only, robust z on daily totals, minimum logged days, no EMI alert when cash is unknown) are in `backend/app/ml/alerts.py` and DEC-61 to DEC-63.

**Why rules, not a learned classifier:** no labelled outcomes exist; rules are auditable and match how an advisor would explain a decision. Revisit once pilot outcomes exist.

## 8. Evaluation plan

| Model | Metric | Target (our own, prototype) |
|---|---|---|
| ML2 | WAPE vs the peer-median baseline (DEC-37) on held-out synthetic shops | At least 10% lower |
| ML2 | Pinball loss (alpha 0.1, 0.5, 0.9) | Reported, lower than the unconstrained baseline |
| ML2 | P10 to P90 empirical coverage | 75% to 85% |
| ML3 | Rolling-origin WAPE at 1, 2 and 3 months of history | Lower than prior only after 2 months |
| ML4 | Stock-out days and cover days vs "reorder when empty" | Fewer stock-outs without more than 25% higher average stock |
| ML5 | Hand-labelled scenario set (20 cases) | 100% agreement with expected decisions |
| ML6 | Seeded-event detection on synthetic series | Recall at least 90% on injected dips, false alarms under 1 per shop per month |
| ML7 | 20 owner profiles with expected schemes | Top-3 contains the expected scheme in at least 80% |
| ML8 | 30-question evaluation set (`eval/chat_eval.jsonl`) | Grounded in at least 90%; refuses unsupported questions correctly in at least 90% |

Method check on the **public dataset**: show that quantile GBM plus conformal calibration reaches 75% to 85% coverage and beats seasonal-naive there. This is the only evidence of real-world behaviour; report it honestly.

## 9. ML7: Scheme matcher (F4)

- **Knowledge base:** `data/kb/schemes.json`, one entry per scheme: `id`, `name`, `type` (loan, subsidy, guarantee), `eligibility` (structured: sector, max_investment, age_range, category, state or null), `benefit_summary`, `how_to_apply`, `source_url`, `last_verified`, `verified` (false until a human checks the official page). Start with a short list of well-known central schemes (for example PM Mudra Yojana, PMEGP, Stand-Up India, CGTMSE guarantee, Udyam registration), each filled **only from the official page** and marked `verified: false` until checked.
- **Matching:** hard filters from structured eligibility (shop type, investment size, state, owner category if given) first; then rank by embedding similarity between the owner's need (free text from chat or intake) and the scheme summary.
- **Output:** list of schemes with "why it may fit", missing requirements, link, `last_verified`, and the notice "Check the official page before applying."
- **Embeddings:** `intfloat/multilingual-e5-small` (Hindi and English), vectors stored in a NumPy file (FAISS optional), index rebuilt by `python -m app.rag.build_index`.

## 10. ML8: Chatbot (F7)

- **Router:** rules first (keywords and intents), LLM classification as fallback. Intents: `my_numbers`, `schemes`, `how_to`, `smalltalk`, `out_of_scope`.
- **Tools** (plain Python functions over the database): `get_forecast`, `get_latest_review`, `get_stock_advice`, `get_alerts`, `get_profit_summary(period)`, `match_schemes(profile)`.
- **Prompting:** system prompt states the role, the owner's language, "use only the facts provided", "if a fact is missing say you do not know", short sentences, no legal or financial guarantees. Facts and sources are inserted as a structured block.
- **Guard (`llm/guard.py`):** extract all numbers in the answer; each must appear in the tool outputs (allowing formatting such as lakh or thousand separators); scheme names must exist in the KB. On failure, fall back to a template that prints the tool result directly.
- **Languages:** answer in the question's language; Hindi, English and Hinglish are supported first.
- **Provider abstraction:** `LLMClient.generate(system, messages, max_tokens) -> str`; providers: `gemini`, `claude`, `stub` (deterministic, used in tests).
- **Safety:** refuse medical, legal and investment-return guarantees; add the notice on scheme answers.
- **Cost control:** cache identical questions per shop per day; cap tokens.

## 11. ML9 and ML10 (P2)

- **Expansion simulator:** options such as "add one product line", "extend hours", "second counter". Each option changes the revenue uplift distribution (assumed ranges in `data/rules/expansion.yaml`, flagged as assumptions) and costs; run 1,000 Monte Carlo draws over the re-forecast uncertainty; report payback range and probability that payback is under 12 months.
- **Pricing helper:** compare category margin with target margin from config; flag categories below target; suggest the price change needed to reach the target, with a note that demand may react.

## 12. Reproducibility and model files

- Fixed random seeds; training scripts in `backend/app/ml/train.py` with a `make train` target.
- Save models with `joblib` to `backend/data/models/` with a `model_card.json` (training data hash, date, metrics, `is_synthetic`).
- The app loads a model card at start and shows "Prototype model trained on synthetic data" in the About screen.

## 13. Known limitations (state these in the demo)

- Forecast accuracy on real shops is unmeasured.
- Location score weights are expert assumptions.
- Review thresholds are initial assumptions.
- The 81% survival figure and the 10% and 40% reductions are scenario assumptions, not model outputs.
- Scheme data may be out of date; always verify on the official page.

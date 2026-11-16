## ML3 re-forecast (M-06)

**All data here is SYNTHETIC (`is_synthetic=true`).** This backtest checks the method and the code. It says nothing about accuracy on real shops.

- Rolling origin: forecast made at the end of month 1, 2 and 3 (about 30, 60 and 90 days of history), scored on the next 3 full months. Only days up to the origin are given to the model.
- Shops: 200 held-out TEST shops for scoring; 300 TRAINING shops (seeded sample) for tuning, with out-of-fold ML2 priors.
- Settings scored (from `data/rules/blend.yaml`): k = 10, band multiplier = 3.7.

### Target

Blend WAPE lower than prior-only after 2 months of history: **MET** (2 months: yes; 3 months: yes).

### WAPE and coverage on TEST shops (no gaps)

| History | Shop-months | Blend WAPE | Prior only | ETS only | Last-week naive | Blend P10-P90 coverage | Prior coverage | Blend width | Prior width |
|---|---|---|---|---|---|---|---|---|---|
| 1 month(s) | 600 | 10.5% | 19.9% | 12.7% | 17.6% | 82.3% | 79.8% | 50.6% | 58.5% |
| 2 month(s) | 600 | 8.8% | 19.5% | 9.2% | 11.7% | 84.5% | 81.3% | 56.3% | 59.5% |
| 3 month(s) | 600 | 6.8% | 19.3% | 6.9% | 8.9% | 83.2% | 82.5% | 47.7% | 59.9% |

Width = (P90 - P10) / P50, averaged. Own models fitted: ets_damped_trend_weekly x 600.

Band rescale by the observed error: at its lower limit for 37.5% of the test cases, at its upper limit for 2.0%.

### Choice of k (TRAINING shops only) and sensitivity

On training shops (all three origins pooled) the lowest blend WAPE is at **k = 10**. For every k the band multiplier is the one whose TRAINING coverage is closest to 80%. The TEST columns only show how each setting behaves; nothing was chosen on test shops.

| k | Training WAPE | Band multiplier (training) | Test WAPE, 1 month | 2 months | 3 months | Test coverage, 1 month | 2 months | 3 months | Test width, 2 months |
|---|---|---|---|---|---|---|---|---|---|
| 5 | 8.9% | 5 | 11.1% | 8.9% | 6.8% | 72.8% | 79.7% | 83.7% | 66.7% |
| 10 (lowest training WAPE) (in blend.yaml) | 8.6% | 3.7 | 10.5% | 8.8% | 6.8% | 82.3% | 84.5% | 83.2% | 56.3% |
| 15 | 8.7% | 2.7 | 10.4% | 8.9% | 6.9% | 83.0% | 83.5% | 79.7% | 46.3% |
| 30 | 9.5% | 1.7 | 11.6% | 9.5% | 7.5% | 83.5% | 82.7% | 79.8% | 36.7% |
| 60 | 11.3% | 1.4 | 13.8% | 11.3% | 9.2% | 83.0% | 85.3% | 82.5% | 37.8% |
| 120 | 13.6% | 1.2 | 16.0% | 13.8% | 11.8% | 78.5% | 81.2% | 80.7% | 39.3% |
| 240 | 15.7% | 1.2 | 17.7% | 15.9% | 14.4% | 79.7% | 81.8% | 83.5% | 45.3% |

### Missing days (TEST shops, days removed at random from the history)

| Days missing | Blend WAPE, 1 month | 2 months | 3 months | Blend coverage, 2 months | Prior-only WAPE, 2 months |
|---|---|---|---|---|---|
| 0% | 10.5% | 8.8% | 6.8% | 84.5% | 19.5% |
| 10% | 12.9% | 8.5% | 6.6% | 94.3% | 19.5% |
| 30% | 13.9% | 10.1% | 7.6% | 99.2% | 19.5% |
| 50% | 13.1% | 10.4% | 8.2% | 99.0% | 19.5% |

Missing days are skipped by the model (never counted as zero sales). Above 30% missing the service returns confidence `low` with the reason.

### Notes and honest reading

- **The target is met on synthetic shops**, at every history length, and for every k that was tried. This is the easy
  part: the set-up forecast knows only the shop's profile and location, the re-forecast has seen the shop's real sales.
- **The set-up forecast adds little once sales exist.** The shop's own model alone (ETS) is already far better than
  prior-only, and the blend at the chosen k is only slightly better than ETS alone at 1 and 2 months and equal at 3
  months. Cross-validation therefore picks a small k (10; ML_PLAN first proposed about 60). Synthetic daily sales are
  probably smoother than real kirana logs, so this k is likely too trusting of early sales for real shops. It must be
  re-tuned on pilot data (DEC-55).
- **The band formula was too narrow as first built.** With no multiplier, P10 to P90 covered about 65% of test months
  instead of 80%. A single multiplier, chosen on training shops only, brings coverage on test shops to 82% to 85%. The
  multiplier is large (3.7 at k = 10), which says the ETS residual spread understates the error of a forecast several
  months ahead. Treat the band as calibrated by experiment on synthetic shops, not as derived from theory.
- **The band does not get much narrower.** At the chosen setting the re-forecast band is 48% to 56% of P50 wide, against
  about 59% for the set-up forecast. The re-forecast improves the centre much more than it narrows the range. A larger k
  gives a narrower band at similar coverage but a worse centre (see the k table); the human chose the lower error.
- **The rescale by observed error often sits at its limit**: for more than a third of test cases it is at its lower
  limit (0.5), because many shops track their set-up forecast closely in the first months. The limits are assumptions.
- **Missing days:** accuracy falls gently (see the table) and stays far better than prior-only even with half the days
  missing. The band becomes too wide when days are missing (coverage well above 80%), because the multiplier was tuned on
  complete histories. That is the cautious direction, but it is a miscalibration and is reported as such.
- **Limits of this backtest:** origins only at month ends; only the next 3 months are scored; gaps are random single days
  (real gaps come in runs); tuning used a seeded sample of 300 of the 600 training shops; all shops come from one
  generator, so every number here is about the generator, not about real shops.

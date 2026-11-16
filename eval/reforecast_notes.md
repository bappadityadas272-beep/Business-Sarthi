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

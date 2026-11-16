## ML6 alerts: sales dip (synthetic data)

**All shops here are synthetic (`is_synthetic = true`). Nothing below is evidence about real shops.**

Rule under test (`data/rules/alert_rules.yaml`, initial assumptions, not tuned): the average of the last 7 finished days is below 70% of the average of the 28 days before them, **and** the robust z-score is below -2. Robust z = (median of the last 7 days - median of the base days) / (1.4826 x MAD of the base days).

### Target

Recall at least 90% on injected dips of 35% or deeper, detected within 14 days, and fewer than 1 false alarm per shop per month (ML_PLAN section 8; which dips count and the 14 days were chosen by the human, DEC-61). **MET** on synthetic shops: recall 95.3% (632 dips), 0.000 false alarms per shop per month.

### False alarms (test shops with no dip in the generator)

| Shops | Shop-months scored | False alarms | Per shop per month | Shops with at least one | Days under a false alert | Alarms starting within 35 days after a festival |
|---|---|---|---|---|---|---|
| 171 | 3972 | 0 | 0.000 | 0 | 0.00% | 0 of 0 |

One alarm is one unbroken run of days on which the rule holds.

### Recall on injected dips (5 dips per shop, one per copy)

| Dip depth | Dips | Detected within 14 days | Median days until the alert |
|---|---|---|---|
| 25% to 30% | 120 | 19.2% | 7 |
| 30% to 35% | 103 | 57.3% | 7 |
| 35% to 45% | 247 | 88.7% | 6 |
| 45% to 60% | 385 | 99.5% | 5 |
| **35% or deeper (target)** | 632 | **95.3%** | 5 |

Dips last 14 to 30 days and are 25% to 60% deep, both drawn evenly at random (seed 2026). A dip of exactly 30% sits on the threshold, so the two mildest rows are outside what the rule is built to catch. 0 dips were left out because the unchanged series already alerted in the same window.

### The generator's own dips (30 days long, test shops that have one)

| Dip depth | Dips | Detected within 14 days | Median days until the alert |
|---|---|---|---|
| 25% to 30% | 8 | 25.0% | 8 |
| 30% to 35% | 6 | 33.3% | 7 |
| 35% to 45% | 7 | 71.4% | 5 |
| 45% to 60% | 8 | 100.0% | 4 |

29 shops. These dips were not placed by this script. About half are milder than 35%; the sample is small.

### Sensitivity: 20% of days not logged (at random)

| Case | Recall, dips of 35% or deeper | False alarms per shop per month |
|---|---|---|
| every day logged | 95.3% | 0.000 |
| 20% of days missing | 94.1% | 0.000 |

### What was not evaluated

Low stock, dead stock, EMI due and data gap are exact rules with no statistics; they are covered by hand-calculated unit tests (`backend/tests/test_alerts.py`), not by this simulation.

### Notes and honest reading

- **Zero false alarms is a property of the synthetic data, not of the rule.** The generator has daily noise of about
  12%, festivals and a weekly pattern, but no closed days, strikes, bad-weather weeks or supplier problems. Real shops
  will produce false alarms; how many is unknown until pilot data exists. The figure must not be quoted as an expected
  rate.
- **The rule is blind to mild dips by design.** It catches about 1 in 5 dips of 25% to 30% and about 3 in 5 of 30% to
  35%. Dips of 35% to 45% are caught 89% of the time, below the 90% line on their own; the target is met because deeper
  dips are caught almost always. The band on which the target is judged was chosen by the human before the run (DEC-61).
- **Detection takes about 5 to 7 days** of low sales, because the 7-day average has to fall. A one-week dip that then
  recovers may never alert.
- **The generator's own dips** (29 test shops) are a small sample: 5 of 7 detected in the 35% to 45% band. About half
  of them are milder than 35%.
- **The injected dips are simple:** a sudden, flat cut of all categories. A slow slide over several weeks is not
  tested and would be caught late or not at all, because the 28-day base slides with it.
- **No tuning was done.** Thresholds are the ML_PLAN assumptions; the robust z definition and the minimum number of
  logged days (4 of 7 and 14 of 28) were fixed before the first run (DEC-63).
- With 20% of days missing the result barely changes; longer gaps (a whole missing week) switch the rule off, and the
  data-gap alert takes over.
- Not yet wired to the database: storing, de-duplicating and resolving alerts is B-08, the daily job is B-09. The EMI
  alert needs the owner's opening cash, which arrives with M-08; until then it stays silent (DEC-62).

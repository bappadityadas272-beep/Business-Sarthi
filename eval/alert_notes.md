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

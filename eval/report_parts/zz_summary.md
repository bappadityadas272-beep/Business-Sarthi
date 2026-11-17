## Summary of every ML_PLAN section 8 target

Every MET result above is on SYNTHETIC data or hand-written cases: it shows the method and the code behave as designed, not that the advice is right for real shops. No real-world accuracy has been measured.

| Target | Status | Measured on |
|---|---|---|
| ML2 WAPE at least 10% below the peer median | MET | synthetic |
| ML2 pinball loss reported, lower than the "unconstrained baseline" | PARTLY: reported and below the peer-quantile baseline at P10, P50 and P90; the "unconstrained baseline" is not defined in the docs and no model without the monotone constraints was compared | synthetic |
| ML2 P10 to P90 coverage 75% to 85% | MET | synthetic |
| ML3 blend beats prior-only only after 2 months | MET | synthetic |
| ML4 fewer stock-outs, stock at most +25% | MET | synthetic |
| ML5 20 hand-labelled scenarios, 100% agreement | MET | hand-written cases |
| ML6 recall at least 90%, under 1 false alarm per shop-month | MET | synthetic |
| ML7 top-3 scheme match at least 80% | NOT MEASURED | needs the team's KB |
| ML8 grounded and refusals at least 90% | NOT MEASURED | needs the team's 30 questions |
| Public-data method check | NOT MEASURED | needs D-02 |

## ML5 grow / hold / pivot review (M-08)

- Engine `app/ml/review.py` with the thresholds of `data/rules/review_rules.yaml` as they are (initial assumptions of ML_PLAN, untested on real shops).
- Cases: `backend/tests/review_scenarios.yaml`, 20 scenarios written and worked out by hand (each has a `why` with the arithmetic). They are rule-checking cases, not shop data.

### Target

100% agreement with the hand-labelled decisions on 20 cases (ML_PLAN section 8): **MET** (20 of 20).

### Scenarios

| Scenario | Expected | Engine | Reasons given | Confidence | Agrees |
|---|---|---|---|---|---|
| healthy_shop_grows | grow | grow | revenue_vs_p50, dscr, growth_rate | medium | yes |
| grow_exactly_on_every_threshold | grow | grow | revenue_vs_p50, dscr, growth_rate | medium | yes |
| no_setup_forecast | hold | hold | revenue_vs_p50 | low | yes |
| flat_sales_growth_exactly_zero | hold | hold | growth_rate | medium | yes |
| good_numbers_but_only_two_thirds_logged | hold | hold | data_completeness | low | yes |
| revenue_half_of_forecast | pivot | pivot | revenue_vs_p50 | medium | yes |
| revenue_exactly_60_percent | hold | hold | revenue_vs_p50, growth_rate | medium | yes |
| emi_not_covered_in_the_last_two_months | pivot | pivot | dscr | medium | yes |
| one_bad_month_only | hold | hold | dscr, growth_rate | medium | yes |
| two_bad_months_then_recovery | hold | hold | dscr, growth_rate | medium | yes |
| dscr_exactly_one_for_two_months | hold | hold | dscr, growth_rate | medium | yes |
| cash_runs_out_in_20_days | pivot | pivot | cash_runway_days | medium | yes |
| cash_runway_exactly_30_days | hold | hold | growth_rate | medium | yes |
| losing_cash_but_opening_cash_never_entered | hold | hold | growth_rate | medium | yes |
| strong_sales_but_cash_figure_negative | grow | grow | revenue_vs_p50, dscr, growth_rate | medium | yes |
| strong_sales_but_burning_cash | pivot | pivot | cash_runway_days | medium | yes |
| healthy_shop_without_a_loan | grow | grow | revenue_vs_p50, growth_rate, data_completeness | medium | yes |
| half_the_days_missing_and_sales_poor | pivot | pivot | revenue_vs_p50 | low | yes |
| half_the_days_missing_and_sales_good | hold | hold | data_completeness | low | yes |
| no_sales_data_at_all | hold | hold | data_completeness, revenue_vs_p50, dscr | low | yes |

### Notes and honest reading

- **This checks the rules, not the advice.** The cases and the code come from the same written rules, so full agreement shows the code does what the rules say, including at each threshold edge. It does not show that the thresholds (DSCR 1.0 and 1.5, revenue at 60% and 100% of P50, 30 days of runway, 70% logged days) are right for real kirana shops; that needs owners' outcomes we do not have.
- **The cases were written by the coding model** in the M-08 session and checked by hand arithmetic; no shop owner or domain expert has reviewed them. Some details of DEC-66 still await the human's confirmation.
- Decisions on the demo shops (SYNTHETIC data) are shown by `scripts/demo_run.py` step 6, not scored here.

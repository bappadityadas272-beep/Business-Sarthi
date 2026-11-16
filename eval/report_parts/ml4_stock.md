## ML4 stock advice (M-07)

**All shops are SYNTHETIC (`is_synthetic = true`).** The generator has no items: each category of a shop is simulated as one item whose demand is that category's daily sales in rupees (DEC-57). Every setting in `data/rules/stock.yaml` is an assumption.

- Rule: order when on hand + on order is at or below the reorder point (z = 1.28, lead time 2 days), quantity = 7 days of demand minus on hand and on order.
- Baseline: order the same 7 days of demand, but only when the shelf is empty (DEC-58).
- Both see only their own sales, start with the same stock, and the first 28 days are not scored.
- Demand estimate: days that ended with an empty shelf are left out (DEC-59).
- Half-life chosen on 200 calibration shops of the ML2 split (not test shops); results below are for 200 test shops.

### Target

Fewer stock-out days than the baseline, with average stock at most 1.25x the baseline (ML_PLAN section 8). **MET** on synthetic shops at the chosen half-life (7 days): item stock-out days per 30 days 4.05 against 9.57; average stock 0.95x the baseline. The rule had fewer stock-out days than the baseline for 100% of the test items.

### Choice of the demand half-life (calibration shops)

| Half-life | Policy | Item stock-out days per 30 | Shop days with any item empty per 30 | Lost sales | Average cover (days) | Average stock vs baseline |
|---|---|---|---|---|---|---|
| 7 | reorder rule | 4.04 | 14.15 | 6.1% | 2.1 | 0.95x |
| 7 | reorder when empty | 9.57 | 22.11 | 26.8% | 2.2 | 1.00x |
| 14 | reorder rule | 4.15 | 14.46 | 6.4% | 2.0 | 0.94x |
| 14 | reorder when empty | 9.64 | 22.52 | 27.0% | 2.2 | 1.00x |

Chosen: **7 days**: 7 days has fewer stock-out days and its average stock is 1.02x that of 14 days (within the 1.10x limit used for 'similar stock').

### TEST shops

| Half-life | Policy | Item stock-out days per 30 | Shop days with any item empty per 30 | Lost sales | Average cover (days) | Average stock vs baseline |
|---|---|---|---|---|---|---|
| 7 | reorder rule | 4.05 | 14.16 | 6.1% | 2.1 | 0.95x |
| 7 | reorder when empty | 9.57 | 22.05 | 26.8% | 2.2 | 1.00x |
| 14 | reorder rule | 4.15 | 14.48 | 6.3% | 2.0 | 0.94x |
| 14 | reorder when empty | 9.63 | 22.42 | 26.9% | 2.2 | 1.00x |

### Sensitivity: the other treatment of empty-shelf days (TEST shops)

Here a day that ended with an empty shelf counts as a day of low sales for both policies. This was the first version of the rule; it missed the stock limit, which is why DEC-59 changed the estimate.

| Half-life | Policy | Item stock-out days per 30 | Shop days with any item empty per 30 | Lost sales | Average cover (days) | Average stock vs baseline |
|---|---|---|---|---|---|---|
| 7 | reorder rule | 4.23 | 14.68 | 6.3% | 1.9 | 1.44x |
| 7 | reorder when empty | 12.15 | 20.97 | 33.9% | 1.3 | 1.00x |
### Notes and honest reading

- **The target was missed by the first version of the rule and is met only after a change to the demand estimate.**
  At first a day with an empty shelf counted as a day of low sales. The rule then cut stock-out days by about 65% but
  held 1.44x the baseline's average stock (limit 1.25x), mostly because the baseline's own estimate collapsed after each
  stock-out and it ordered too little. The human chose to leave empty-shelf days out of the estimate (DEC-59). The
  thresholds (z, lead time, cover) were not changed. Both variants are shown above.
- **The rule still runs out too often.** About 4 item-days in 30 end with an empty shelf and about 6% of demand is lost,
  which is worse than the roughly 90% service level that z = 1.28 suggests. Likely reasons: the weekly pattern and
  festival peaks are not in the estimate (a plain weighted mean), growing shops are under-estimated, and a day that ends
  at exactly zero counts as a stock-out day even if no sale was lost. This was not tuned away.
- **"Shop days with any item empty" is high for both policies** (about 14 against 22 in 30) because a shop has five
  simulated items and one empty item is enough. With real shops and many more items this number would be higher still;
  it is a strict measure.
- **The baseline is a simple strawman.** A real owner reorders before the shelf is completely empty. The gap to a real
  owner's habit is unknown and is not claimed here.
- **Limits:** one item per category with demand in rupees, not real items or units; a fixed 2-day lead time with no
  supplier delays, minimum order sizes or cash limits; the simulation knows what is on order, the app does not (it has no
  purchase orders), so in the app an item stays on the reorder list until the purchase is recorded; the category-average
  fallback for new items could not be tested in the simulation (one item per category) and is covered only by unit tests.
- The half-life choice (7 against 14 days) makes almost no difference on this data; 7 was kept by the stated rule.

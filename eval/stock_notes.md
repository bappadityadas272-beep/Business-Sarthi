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

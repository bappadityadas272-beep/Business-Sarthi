# PUBLIC_DATA: the public dataset used to check the forecasting method (D-02)

> **Purpose.** ML_PLAN section 2 and section 8 allow ONE public retail dataset, used **only** to check that the
> *method* (gradient boosting P50 + conformal band, versus a seasonal-naive baseline) behaves sensibly on real
> retail sales. It is **not** training data for the app's ML2 model, it is never shipped with the app, and the
> raw file is **never committed** to git.

## Chosen dataset

| Field | Value |
|---|---|
| Name | Online Retail II |
| Publisher | UCI Machine Learning Repository |
| Official page | https://archive.ics.uci.edu/dataset/502/online+retail+ii |
| DOI | https://doi.org/10.24432/C5CG6D |
| Creator | Daqing Chen |
| What it is | Every transaction of one UK-based, non-store online retailer between 01/12/2009 and 09/12/2011 (1,067,371 rows, as stated on the official page) |
| Columns (from the official page) | InvoiceNo, StockCode, Description, Quantity, InvoiceDate, UnitPrice, CustomerID, Country. The downloaded file may name some of them `Invoice`, `Price` and `Customer ID`; `eval/public_validation.py` accepts both spellings |
| File offered | `online_retail_ii.xlsx` (about 43.5 MB per the official page; a zip of the same size is also offered) |
| Licence | **Creative Commons Attribution 4.0 International (CC BY 4.0)** |
| Licence wording on the official page | "This dataset is licensed under a Creative Commons Attribution 4.0 International (CC BY 4.0) license. This allows for the sharing and adaptation of the datasets for any purpose, provided that the appropriate credit is given." |
| Required credit (citation given on the official page) | Chen, D. (2012). Online Retail II [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5CG6D |
| Date licence checked | 2026-11-18 (official UCI page read on that date) |
| Checked by | coding assistant session on branch `feature/ml-validation`; a human should re-open the page once before the result is quoted publicly (`verified: false` until then) |

## Is our use allowed?

**Yes, with attribution.** CC BY 4.0 allows sharing and adaptation for any purpose, including commercial, if
appropriate credit is given and changes are indicated. Our use is narrower than that:

- we download the file locally, aggregate it to weekly revenue per product, and compute error and coverage
  metrics;
- we publish only **aggregate metrics** (WAPE, pinball loss, coverage) in a report, with the citation above and a
  note that the data was filtered and aggregated (that is the "indicate changes" part of CC BY 4.0);
- we do **not** redistribute the raw file, do not commit it, and do not ship it in the app or the Docker image.

Every report produced from this dataset must carry: the citation above, the licence name with a link to
https://creativecommons.org/licenses/by/4.0/, and the sentence "Filtered and aggregated to weekly revenue per
product by Business Sarthi; not the original data."

## Privacy

The dataset has a `CustomerID` column (a pseudonymous number). `eval/public_validation.py` **never loads it**:
the column is excluded when the file is read. Product descriptions are also dropped after cleaning. No
per-customer result is computed or reported.

## Honest limits of this check

- It is **one UK online gift-ware retailer**, not an Indian kirana shop. Its seasonality (a strong
  pre-Christmas peak), product mix and customers (many wholesalers) differ from ours. A good result shows the
  method is not broken on real retail data; it says **nothing** about accuracy for Indian shops.
- The unit of a "series" is one product's weekly revenue, not one shop's monthly revenue, because the dataset
  has only one seller. ML2 forecasts a new shop from its profile with no sales history; this check forecasts a
  product from its own past weeks. What is shared is the method: LightGBM P50 with Huber loss, a ratio band
  re-set by split conformal calibration on held-out series, and the same metrics.
- Only about two years of data: a 52-week seasonal-naive baseline can only be scored on the second year.

## Where the raw file goes (never committed)

Put the downloaded file(s) in `eval/public_data/` (that folder has its own `.gitignore` that ignores everything
except itself). Either:

- the original `online_retail_ii.xlsx` (needs the `openpyxl` package, which is **not** in the backend image), or
- one CSV per sheet exported from it (for example `online_retail_ii_2009_2010.csv` and
  `online_retail_ii_2010_2011.csv`), which needs nothing extra.

Then run, from the repo root (Phase B, when Docker is free):

```text
docker compose run --rm -T -w /repo/backend backend python ../eval/public_validation.py --data ../eval/public_data
```

## Candidates considered and not chosen

| Candidate | Why not |
|---|---|
| Kaggle grocery or store-sales competition datasets (for example Favorita, M5) | Competition data are governed by each competition's rules, which often limit use to the competition. Not checked in detail this session; not used, so no licence claim is made about them (`verified: false`) |

## Change log of this file

- 2026-11-18: created (D-02 licence check). Licence read from the official UCI page on this date.

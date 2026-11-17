## ML7, ML8 and the public-data check: not measured yet

These ML_PLAN section 8 targets have **no result**. They are listed so that a missing number is not mistaken for a met target.

| Target | Status | What is missing | Who |
|---|---|---|---|
| ML7: top-3 holds the expected scheme for at least 80% of 20 owner profiles | NOT MEASURED | `data/kb/schemes.json` does not exist (D-03). `tests/test_schemes.py` gives 20/20, but on a test-only fixture whose profiles were written in the same session, with the fallback embedder: that proves the code path, not matching quality. | Team: the KB (D-03) and 20 real profiles |
| ML8: grounded in at least 90%, correct refusals in at least 90% of 30 questions | NOT MEASURED | `eval/chat_eval.jsonl` does not exist (C-08 BLOCKED). The 8-question smoke set (written by the coding model, labelled `smoke: true`) gave grounded 7/8 = 88%, below the target, refusals 8/8, with Gemini on 2026-11-17; the one miss was a provider outage. That is a smoke check, not this target. | Team: the 30 questions |
| Public dataset: quantile GBM + conformal reaches 75% to 85% coverage and beats seasonal-naive | NOT MEASURED | `data/PUBLIC_DATA.md` does not exist (D-02, licence check). This is the only planned evidence of real-world behaviour, so **there is none yet**. | Team: D-02 |

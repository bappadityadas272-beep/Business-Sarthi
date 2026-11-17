# Scheme knowledge base (checkpoint D-03, written by the team)

`schemes.json` in this folder is the **only** place the app takes scheme or loan facts from (AGENTS rule 3).
It does not exist yet. Until it does, the chatbot says it has no verified scheme information.

## Rules

- Copy every fact from the scheme's **official page** only. Do not guess limits, ages or categories.
  If the page does not say, use `null` (= no limit) only when the page clearly has no limit; otherwise put the
  condition in `other_requirements` as text, which the app always shows as "please confirm".
- `source_url`: the official https page you copied from. `last_verified`: the date you checked it (YYYY-MM-DD).
- `verified`: `false` until a second person re-checks the entry against the page (R-04). Unverified entries are
  shown with an "unverified" label.
- Never put a `test_only` file here; made-up test schemes live in `backend/tests/fixtures/kb/`.

## Format

The exact format is `schemes.schema.json` (generated from `backend/app/rag/kb.py`; do not edit it by hand).

```text
{
  "version": 1,
  "schemes": [
    {
      "id": "lowercase-id",
      "name": "Name as on the official page",
      "name_hi": "Hindi name, optional",
      "type": "loan | subsidy | guarantee | registration",
      "eligibility": {
        "sectors": ["retail", "trading", "manufacturing", "services"] or null,
        "min_investment": null or rupees,
        "max_investment": null or rupees,
        "age_min": null or years,
        "age_max": null or years,
        "categories": ["general", "sc", "st", "obc", "women", "minority", "pwd", "ex_servicemen"] or null,
        "states": ["State name"] or null,
        "other_requirements": ["anything the code cannot check, in plain words"]
      },
      "benefit_summary": "What the owner gets, in plain English (from the page)",
      "benefit_summary_hi": "Hindi summary, optional",
      "how_to_apply": "Where and how to apply (from the page)",
      "source_url": "https://official.page/...",
      "last_verified": "YYYY-MM-DD",
      "verified": false,
      "verified_by": "optional: who re-checked it"
    }
  ]
}
```

Every eligibility key must be present. A list means "the owner must match at least one"; use `null`, never `[]`,
for "anyone".

## Check and build

```sh
docker compose run --rm backend make kb-check   # fails with the scheme id and field of every problem
docker compose run --rm backend make kb-index   # builds the search index (backend/data/kb_index/, not committed)
```

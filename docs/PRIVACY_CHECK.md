# PRIVACY_CHECK: self-review against ARCHITECTURE section 11 (Q-05)

> **Not legal advice.** This is the team's own engineering check that the prototype does what ARCHITECTURE section 11
> and AGENTS.md say about personal data. It is written with the DPDP Act 2023 in mind but has not been reviewed by a
> lawyer. A legal review is required before any real pilot (see the last section).
> Reviewed 2026-11-17 on commit `ca15816` plus the Q-05 changes (DEC-94, DEC-95). Every ticked item names the code
> and the automated test that proves it; the tests run in CI on every push (DEC-93).

## Checklist

| # | Requirement | Status | Where it is enforced | Proof (test) |
|---|---|---|---|---|
| 1 | **Consent first:** no shop data is stored or computed before the owner's `shop_data` consent exists (AGENTS rule 5) | [x] | `app/api/deps.py` `consented_user`, `owned_shop_consented` | `test_access_sweep.py::test_without_consent_nothing_is_stored_or_computed` (every shop route, read from the OpenAPI schema), `::test_creating_a_shop_needs_consent` |
| 2 | **Purpose-specific consent:** each purpose is separate and stated; only `shop_data` is required (DEC-43) | [x] | `app/services/consent.py` `PURPOSES` | `test_profile_consent.py::test_list_shows_every_purpose` |
| 3 | **Hosted LLM only with its own consent:** chat sends the (redacted) question and the shop figures it needs to the hosted provider only after the optional `hosted_llm` consent; without it every answer is a code-made template and the provider is never called, not even to route (DEC-95) | [x] | `app/services/chat.py` `answer` | `test_chat_api.py::test_without_the_hosted_llm_consent_the_provider_is_never_called`, `::test_hosted_llm_consent_is_optional_and_listed` |
| 4 | **Withdraw:** any consent can be withdrawn; after withdrawing `shop_data`, new writes and computations are refused; the consent history is kept | [x] | `DELETE /api/consents` (`app/api/me.py`) | `test_profile_consent.py::test_withdraw_blocks_new_writes_keeps_data_and_history`, `test_access_sweep.py::test_without_consent_nothing_is_stored_or_computed` |
| 5 | **Delete:** `DELETE /api/me/data` removes the account and every row tied to it (consent history too), the in-memory copies, and makes the old token useless (DEC-84) | [x] | `app/services/privacy.py` `delete_user_data` | `test_privacy.py` (all 7 tests, including `test_every_row_of_the_owner_goes_and_nothing_else`, `test_in_memory_copies_go_too`) |
| 6 | **Minimisation, stored fields:** the phone number is the only personal identifier; no Aadhaar, PAN, e-mail, address, birth date, caste or religion column exists | [x] | `app/models/` | `test_access_sweep.py::test_no_table_has_a_column_for_identity_documents_or_contact_details` (user table is exactly `id, phone, language, created_at`) |
| 7 | **Minimisation, scheme profile:** age, category, state and the free-text need of the scheme matcher are request-only, never stored (DEC-86) | [x] | `app/api/schemes.py`, `app/services/schemes.py` | `test_access_sweep.py::test_scheme_profile_fields_are_never_stored` (scans every table for a marker sent in the request) |
| 8 | **Minimisation, chat text:** phone, Aadhaar and PAN numbers typed into chat are replaced by `[redacted]` before the router, the LLM, the answer cache and the database see them (DEC-94) | [x] | `app/services/privacy.py` `redact_identifiers`, called first in `chat.answer` | `test_chat_api.py::test_identifiers_are_redacted`, `::test_amounts_and_ordinary_text_stay`, `::test_a_typed_phone_or_aadhaar_reaches_neither_the_llm_nor_the_database` |
| 9 | **Own data only:** another owner's shop answers 404 `shop_not_found`, the same as a missing shop, on every route that takes a shop (path, query or body) | [x] | `app/api/deps.py` `_own_shop`; chat, SOS and schemes call it | `test_access_sweep.py::test_another_owners_shop_looks_missing` (all 26 shop operations), `::test_another_owners_notification_cannot_be_marked_read` |
| 10 | **Login everywhere:** every operation except health, ready, about and the two OTP calls needs a token | [x] | `app/api/deps.py` `current_user` | `test_access_sweep.py::test_every_non_public_operation_needs_a_login` (every documented operation) |
| 11 | **Logs:** one JSON object per line; phones masked to the last 2 digits; keys, tokens, prompts and request bodies never logged; a redactor on every line (DEC-90) | [x] | `app/obs.py` | `test_hardening.py::test_phones_and_keys_are_masked`, `::test_log_lines_are_json_and_masked`, `::test_mock_otp_log_line_shows_only_the_last_two_digits`, `::test_a_crash_answers_500_without_internals`; `test_privacy.py::test_the_log_line_has_no_phone` |
| 12 | **No real data in the prototype:** all shop data is SYNTHETIC and labelled (`is_synthetic`), demo owners are fictional (`is_demo`), and the OTP is a mock | [x] | `data/synthetic/generate.py`, `app/seed.py`, `app/services/auth.py` | `test_synthetic.py`, `test_seed.py`; `GET /api/about` shows the assumption flags (`test_hardening.py::test_about_shows_the_model_card_and_assumption_flags`) |
| 13 | **No secrets in git:** `.env`, databases and model files are ignored; keys come only from the environment; CI has no secrets (DEC-93) | [x] | `.gitignore`, `app/config.py`, `.github/workflows/ci.yml` | Scan on 2026-11-17 of the whole git history (`git log -p --all`) for Gemini, Anthropic and private-key patterns and `LLM_API_KEY=<value>`: **0 hits**; no `.env`, `*.db` or `*.joblib` file was ever committed. Each commit's staged diff is scanned the same way |
| 14 | **Dev tools off in production:** with `DEV_MODE=0` the mock-OTP echo and `/api/dev/*` are gone (404, not in the docs) (DEC-91) | [x] | `app/obs.py` `DevGate`, `app/main.py` `SarthiAPI.openapi` | `test_hardening.py::test_dev_routes_look_absent_when_dev_mode_is_off` |

All 14 items are ticked for the prototype.

## Limits, said plainly

- **Redaction is a pattern safety net (DEC-94).** It catches 10-digit Indian mobiles (with +91, 0, a space or a dash),
  12-digit Aadhaar numbers (with or without spaces) and PAN numbers. It does **not** catch a number written in
  words, split in an unusual way, typed in Devanagari digits, or other identifiers (bank account, voter ID, a
  name). Owners should still be told not to type personal details into chat.
- **Stored data stays after withdrawing `shop_data`** until delete-my-data (DEC-84); reading it is still allowed.
  Resolving or muting an existing alert also works without consent: it flags a row that already exists and stores
  no new shop data (`NO_CONSENT_NEEDED` in `test_access_sweep.py` lists each such route with its reason).
- **Backups are not deleted** by delete-my-data; RUNBOOK section 4 says to delete them by hand (DEC-84).
- **Phone numbers are stored in clear** in the database (needed for login). SQLite on the laptop has no encryption
  at rest.
- **The hosted provider's own retention** of what chat sends (after the owner's `hosted_llm` consent) is governed by
  the provider's terms, which this check has not reviewed.
- **The consent texts the owner reads do not exist yet**: the frontend (F-*) must word each purpose in Hindi and
  English, including what `hosted_llm` sends and to whom.
- Rate limits are per process and in memory (DEC-90).

## Before any real pilot (outside this checklist)

- A legal review against the DPDP Act 2023 and its rules (notice, consent manager, grievance officer, breach
  reporting, retention periods, children's data).
- A real SMS OTP provider, HTTPS, encryption at rest and managed backups with deletion.
- A data processing agreement with the LLM provider, or a provider choice that keeps data in India if required.

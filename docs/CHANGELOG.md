# CHANGELOG

Newest first. Format: date, checkpoint IDs, what changed, notes for the next person.

## 2026-11-16: S-01 repo scaffold

- Moved `AGENTS.md` back to the repo root so `tools/build_master.py` works again (it was broken by the rename into `docs/`). DEC-16.
- Created the ARCHITECTURE section 9 folder tree (`backend/`, `frontend/`, `data/`, `eval/`) with `.gitkeep` placeholders.
- Added `.gitignore` (`.env`, `*.db`, `backend/data/models`, `node_modules`, `__pycache__`, `.venv`, plus `data/synthetic/out/` for generated data) and `.env.example` with empty values only.
- No `LICENSE` yet; waiting for team approval (DEC-17). Python and dependency decisions recorded as DEC-18 and DEC-19.

## 2026-11-16: documentation pack created (no checkpoint)

- Added `AGENTS.md`, `docs/SPEC.md`, `ARCHITECTURE.md`, `ML_PLAN.md`, `CHECKPOINTS.md`, `DECISIONS.md`, `CHANGELOG.md`, generated `MASTER.md`, and `tools/` scripts.
- Decisions DEC-01 to DEC-15 recorded.
- No application code exists. Start with checkpoint S-01.
- Open items for the team: choose a licence (S-01), choose the public dataset (D-02), pick the LLM provider and get an API key (C-01).

## History before the doc pack (context, not code)

- 2026-11: Screening deck (8 slides) submitted on Unstop for The Corporate Glitch '26. Finals on 21 Nov; demo optional.
- 2026-11: Public repository created with README, banner and vector-art assets.

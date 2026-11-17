"""Scheme knowledge base: format, validation and loading (C-02, ML_PLAN section 9, AGENTS rule 3).

The team writes `data/kb/schemes.json` (D-03) from official pages only. This module defines the format and refuses
a file with a missing source URL, a missing `last_verified` date or bad eligibility fields. It holds no scheme
facts itself. `data/kb/schemes.schema.json` is generated from these models (`python -m app.rag.kb --schema`).

Eligibility: every key must be present; `null` means "no limit / anyone". `other_requirements` are conditions the
code cannot check; they are always shown to the owner as "please confirm".

Run `python -m app.rag.kb` (or `make kb-check`) to validate. Exit 1 on any error or if the file is missing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError, field_validator, model_validator

from app.config import REPO_ROOT, get_settings

SECTORS = ("retail", "trading", "manufacturing", "services")
CATEGORIES = ("general", "sc", "st", "obc", "women", "minority", "pwd", "ex_servicemen")
SHOP_TYPE_SECTORS = {"kirana": {"retail", "trading"}}        # a kirana shop is retail trade
SCHEMA_PATH = REPO_ROOT / "data" / "kb" / "schemes.schema.json"


class Eligibility(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sectors: list[Literal["retail", "trading", "manufacturing", "services"]] | None = Field(
        ..., description="null = any sector")
    min_investment: float | None = Field(..., ge=0, description="INR, project cost or loan size; null = no minimum")
    max_investment: float | None = Field(..., gt=0, description="INR; null = no maximum")
    age_min: int | None = Field(..., ge=0, le=120)
    age_max: int | None = Field(..., ge=0, le=120)
    categories: list[Literal["general", "sc", "st", "obc", "women", "minority", "pwd", "ex_servicemen"]] | None = \
        Field(..., description="the owner must be in at least one; null = anyone")
    states: list[str] | None = Field(..., description="state names; null = all of India")
    other_requirements: list[str] = Field(default_factory=list, description="shown as 'please confirm'")

    @model_validator(mode="after")
    def _ranges(self) -> Eligibility:
        if self.min_investment is not None and self.max_investment is not None \
                and self.min_investment > self.max_investment:
            raise ValueError("min_investment is above max_investment")
        if self.age_min is not None and self.age_max is not None and self.age_min > self.age_max:
            raise ValueError("age_min is above age_max")
        for name in ("sectors", "categories", "states"):
            v = getattr(self, name)
            if v is not None and not v:
                raise ValueError(f"{name}: use null for 'anyone', not an empty list")
        return self


class Scheme(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,40}$")
    name: str = Field(min_length=2, max_length=120)
    name_hi: str | None = None
    type: Literal["loan", "subsidy", "guarantee", "registration"]
    eligibility: Eligibility
    benefit_summary: str = Field(min_length=10, max_length=1200)
    benefit_summary_hi: str | None = Field(default=None, max_length=1200)
    how_to_apply: str = Field(min_length=5, max_length=1200)
    source_url: HttpUrl
    last_verified: date
    verified: bool
    verified_by: str | None = None

    @field_validator("source_url")
    @classmethod
    def _https(cls, v: HttpUrl) -> HttpUrl:
        if v.scheme != "https":
            raise ValueError("source_url must be https")
        return v

    @field_validator("last_verified")
    @classmethod
    def _not_future(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("last_verified is in the future")
        return v

    def text(self) -> str:
        """What the index embeds: names, type, summaries and how to apply (both languages when given)."""
        parts = [self.name, self.name_hi, self.type, self.benefit_summary, self.benefit_summary_hi, self.how_to_apply]
        return "\n".join(p for p in parts if p)


class KnowledgeBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    test_only: bool = False                  # fixtures under backend/tests only; never in data/kb
    schemes: list[Scheme] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> KnowledgeBase:
        ids = [s.id for s in self.schemes]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            raise ValueError(f"duplicate scheme ids: {dup}")
        return self


class KBMissing(FileNotFoundError):
    pass


class KBInvalid(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def default_path() -> Path:
    return Path(get_settings().kb_path)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path | None = None) -> KnowledgeBase:
    path = path or default_path()
    if not path.exists():
        raise KBMissing(str(path))
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise KBInvalid([f"not valid JSON: line {e.lineno} column {e.colno}: {e.msg}"]) from e
    try:
        kb = KnowledgeBase.model_validate(raw)
    except ValidationError as e:
        raise KBInvalid([_where(raw, err) for err in e.errors()]) from e
    if kb.test_only and path.resolve().is_relative_to((REPO_ROOT / "data").resolve()):
        raise KBInvalid(["test_only knowledge base inside data/: test fixtures belong under backend/tests"])
    return kb


def _where(raw, err: Mapping[str, Any]) -> str:
    loc = list(err["loc"])
    label = ".".join(str(x) for x in loc)
    if len(loc) >= 2 and loc[0] == "schemes" and isinstance(loc[1], int):
        try:
            label = f"scheme {raw['schemes'][loc[1]].get('id', '?')!r}: " + ".".join(str(x) for x in loc[2:])
        except (KeyError, IndexError, TypeError, AttributeError):
            pass
    return f"{label}: {err['msg']}"


def json_schema() -> dict:
    s = KnowledgeBase.model_json_schema()
    s["$comment"] = "Generated by `python -m app.rag.kb --schema` from backend/app/rag/kb.py. Do not edit by hand."
    return s


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate the scheme knowledge base (make kb-check).")
    ap.add_argument("--kb", type=Path, default=None, help="file to check (default: KB_PATH, data/kb/schemes.json)")
    ap.add_argument("--schema", action="store_true", help="write data/kb/schemes.schema.json and exit")
    a = ap.parse_args(argv)
    if a.schema:
        SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
        SCHEMA_PATH.write_text(json.dumps(json_schema(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {SCHEMA_PATH.relative_to(REPO_ROOT).as_posix()}")
        return 0
    path = a.kb or default_path()
    try:
        kb = load(path)
    except KBMissing:
        print(f"FAIL {path}: file not found. The team writes it from official pages (checkpoint D-03).")
        return 1
    except KBInvalid as e:
        print(f"FAIL {path}: {len(e.errors)} problem(s)")
        for msg in e.errors:
            print(f"  - {msg}")
        return 1
    unverified = [s.id for s in kb.schemes if not s.verified]
    print(f"OK {path}: {len(kb.schemes)} schemes, {len(unverified)} unverified"
          + (f" ({', '.join(unverified)}; shown with an 'unverified' label until R-04)" if unverified else "")
          + (" [TEST ONLY]" if kb.test_only else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""C-02: KB validation (make kb-check), the fallback embedder and the index. Uses TEST ONLY fixtures."""
import copy
import json
from pathlib import Path

import numpy as np
import pytest

from app.rag import index as ixmod
from app.rag import kb as kbmod
from app.rag.embed import FALLBACK_NAME, HashEmbedder

FIX = Path(__file__).parent / "fixtures" / "kb" / "schemes_test_only.json"
RAW = json.loads(FIX.read_text(encoding="utf-8"))


def write(tmp_path: Path, data) -> Path:
    p = tmp_path / "schemes.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def broken(change) -> dict:
    d = copy.deepcopy(RAW)
    change(d["schemes"][0])
    return d


def test_fixture_is_valid_and_test_only(capsys):
    kb = kbmod.load(FIX)
    assert kb.test_only and len(kb.schemes) == 6
    assert kbmod.main(["--kb", str(FIX)]) == 0
    out = capsys.readouterr().out
    assert "OK" in out and "1 unverified" in out and "test-sc-st-startup" in out and "[TEST ONLY]" in out


@pytest.mark.parametrize(("label", "change", "needle"), [
    ("no source_url", lambda s: s.pop("source_url"), "source_url"),
    ("http source_url", lambda s: s.update(source_url="http://example.org/x"), "https"),
    ("bad source_url", lambda s: s.update(source_url="not a url"), "source_url"),
    ("no last_verified", lambda s: s.pop("last_verified"), "last_verified"),
    ("bad date", lambda s: s.update(last_verified="01/02/2026"), "last_verified"),
    ("future date", lambda s: s.update(last_verified="2999-01-01"), "future"),
    ("no verified flag", lambda s: s.pop("verified"), "verified"),
    ("no eligibility", lambda s: s.pop("eligibility"), "eligibility"),
    ("missing eligibility key", lambda s: s["eligibility"].pop("states"), "states"),
    ("unknown eligibility key", lambda s: s["eligibility"].update(income=5), "income"),
    ("bad sector", lambda s: s["eligibility"].update(sectors=["farming"]), "sectors"),
    ("bad category", lambda s: s["eligibility"].update(categories=["rich"]), "categories"),
    ("empty list", lambda s: s["eligibility"].update(states=[]), "null"),
    ("negative amount", lambda s: s["eligibility"].update(max_investment=-1), "max_investment"),
    ("min above max", lambda s: s["eligibility"].update(min_investment=5e6, max_investment=1e6), "min_investment"),
    ("age range", lambda s: s["eligibility"].update(age_min=50, age_max=20), "age_min"),
    ("bad type", lambda s: s.update(type="gift"), "type"),
])
def test_kb_check_fails(tmp_path, capsys, label, change, needle):
    p = write(tmp_path, broken(change))
    with pytest.raises(kbmod.KBInvalid) as e:
        kbmod.load(p)
    assert any(needle in m for m in e.value.errors), (label, e.value.errors)
    assert kbmod.main(["--kb", str(p)]) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out and "test-shop-loan" in out        # errors name the scheme


def test_kb_check_missing_file_and_bad_json(tmp_path, capsys):
    assert kbmod.main(["--kb", str(tmp_path / "nope.json")]) == 1
    assert "D-03" in capsys.readouterr().out
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    assert kbmod.main(["--kb", str(p)]) == 1
    assert "not valid JSON" in capsys.readouterr().out


def test_duplicate_ids(tmp_path):
    d = copy.deepcopy(RAW)
    d["schemes"].append(copy.deepcopy(d["schemes"][0]))
    with pytest.raises(kbmod.KBInvalid, match="duplicate"):
        kbmod.load(write(tmp_path, d))


def test_test_only_file_refused_inside_data(monkeypatch, tmp_path):
    fake_root = tmp_path
    (fake_root / "data" / "kb").mkdir(parents=True)
    p = fake_root / "data" / "kb" / "schemes.json"
    p.write_text(FIX.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(kbmod, "REPO_ROOT", fake_root)
    with pytest.raises(kbmod.KBInvalid, match="test_only"):
        kbmod.load(p)


def test_schema_file_matches_models():
    """data/kb/schemes.schema.json is generated; regenerate with python -m app.rag.kb --schema."""
    on_disk = json.loads(kbmod.SCHEMA_PATH.read_text(encoding="utf-8"))
    assert on_disk == kbmod.json_schema()


def test_hash_embedder_is_deterministic_and_normalised():
    e = HashEmbedder()
    a = e.embed(["दुकान ऋण", "Shop LOAN"])
    b = HashEmbedder().embed(["दुकान ऋण", "shop loan"])
    assert np.allclose(a, b)                              # same across instances, case-folded
    assert np.allclose(np.linalg.norm(a, axis=1), 1.0)
    assert e.embed([]).shape == (0, e.dim)
    assert float(np.linalg.norm(e.embed(["!!!"])[0])) == 0.0    # no words: a zero vector, not NaN


# C-02 acceptance: top-1 retrieval on 10 queries, Hindi and English (fallback embedder, TEST ONLY KB).
QUERIES = [
    ("loan for shop stock and working capital", "test-shop-loan"),
    ("subsidy for women entrepreneurs", "test-women-grant"),
    ("credit guarantee without collateral", "test-credit-guarantee"),
    ("scheduled caste tribe founder enterprise loan", "test-sc-st-startup"),
    ("QR code UPI digital payments kit", "test-state-digital-kit"),
    ("दुकान के माल के लिए ऋण", "test-shop-loan"),
    ("महिला उद्यमी सब्सिडी", "test-women-grant"),
    ("बिना जमानत गारंटी", "test-credit-guarantee"),
    ("यूपीआई क्यूआर कोड किट", "test-state-digital-kit"),
    ("व्यवसाय पंजीकरण प्रमाणपत्र", "test-udyam-registration"),
]


def test_top1_retrieval_ten_queries():
    ix = ixmod.build(FIX, HashEmbedder())
    misses = [(q, want, ix.search(q, 1)[0]) for q, want in QUERIES if ix.search(q, 1)[0][0] != want]
    assert not misses, misses


def test_index_write_load_and_staleness(tmp_path):
    kb_path = write(tmp_path, RAW)
    out = tmp_path / "ix"
    built = ixmod.build(kb_path, HashEmbedder())
    card = json.loads(ixmod.write(built, out).read_text(encoding="utf-8"))
    assert card["embedder"] == FALLBACK_NAME and card["n"] == 6 and card["test_only"] is True
    loaded = ixmod.load(kb_path, out, HashEmbedder())
    assert loaded.source == "file" and np.allclose(loaded.vectors, built.vectors)
    d = copy.deepcopy(RAW)
    d["schemes"][0]["benefit_summary"] += " Changed."
    write(tmp_path, d)                                     # KB changed: the saved index is stale
    assert ixmod.load(kb_path, out, HashEmbedder()).source == "built_in_memory"
    assert ixmod.load(kb_path, tmp_path / "empty", HashEmbedder()).source == "built_in_memory"


def test_build_index_cli(tmp_path, capsys):
    assert ixmod.main(["--kb", str(FIX), "--out", str(tmp_path), "--embedder", "fallback"]) == 0
    assert "FALLBACK" in capsys.readouterr().out
    assert (tmp_path / ixmod.VECTORS).exists()
    assert ixmod.main(["--kb", str(tmp_path / "missing.json"), "--out", str(tmp_path)]) == 1

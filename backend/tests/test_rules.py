"""D-04: every rule file validates; broken files are rejected with the file name."""
import shutil

import pytest
import yaml

from app.rules import FILES, RULES_DIR, RuleFileError, load_rules


def test_all_rule_files_validate():
    r = load_rules()
    assert [d.decision for d in r.review.decisions] == ["pivot", "grow", "hold"]
    assert r.blend.k == 60
    assert r.alerts.rules.sales_dip.ratio_below == 0.70


def test_every_file_is_flagged_as_assumption():
    for name in FILES:
        assert yaml.safe_load((RULES_DIR / name).read_text(encoding="utf-8"))["assumption"] is True


def test_blend_weight_grows_with_data():
    b = load_rules().blend
    assert b.weight(0) == 0.0
    assert b.weight(60) == pytest.approx(0.5)
    assert b.weight(30) < b.weight(90)


def _broken(tmp_path, name, mutate):
    d = tmp_path / "rules"
    shutil.copytree(RULES_DIR, d)
    data = yaml.safe_load((d / name).read_text(encoding="utf-8"))
    mutate(data)
    (d / name).write_text(yaml.safe_dump(data), encoding="utf-8")
    return d


@pytest.mark.parametrize("name,mutate", [
    ("review_rules.yaml", lambda d: d["decisions"].pop()),                       # no fallback
    ("review_rules.yaml", lambda d: d["decisions"][0]["conditions"][0].update(indicator="vibes")),
    ("alert_rules.yaml", lambda d: d["rules"]["sales_dip"].update(ratio_below=1.5)),
    ("alert_rules.yaml", lambda d: d["rules"]["emi_due"].update(severity="panic")),
    ("blend.yaml", lambda d: d.update(k=-1)),
    ("actions.yaml", lambda d: d["actions"].append(dict(d["actions"][0]))),     # duplicate id
    ("location_weights.yaml", lambda d: d["features"]["schools"].update(weight=0.9)),  # sum != 1
    ("location_weights.yaml", lambda d: d["competitors"].update(weight=0.3)),   # must be negative
    ("product_mix.yaml", lambda d: d["shop_types"]["kirana"]["base"].update(dairy=0.5)),
    ("product_mix.yaml", lambda d: d["shop_types"]["kirana"]["profiles"]["near_schools"]["adjust"]
        .update(snacks_beverages=0.2)),                                          # does not net to 0
    ("expansion.yaml", lambda d: d["options"]["extend_hours"]["uplift"].update(low=0.5)),
    ("expansion.yaml", lambda d: d.update(unknown_key=1)),                      # extra keys forbidden
    ("investment_split.yaml", lambda d: d["remainder_split"].update(stock=0.9)),  # sum != 1
])
def test_invalid_files_are_rejected(tmp_path, name, mutate):
    with pytest.raises(RuleFileError, match=name):
        load_rules(_broken(tmp_path, name, mutate))


def test_missing_file_is_reported(tmp_path):
    d = tmp_path / "rules"
    shutil.copytree(RULES_DIR, d)
    (d / "blend.yaml").unlink()
    with pytest.raises(RuleFileError, match="blend.yaml: file missing"):
        load_rules(d)

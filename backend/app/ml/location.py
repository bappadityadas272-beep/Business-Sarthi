"""ML1 location score and starter product mix (M-02, ML_PLAN section 3, DEC-08).

score = 100 * clip(sum_i w_i * min(x_i / cap_i, 1) + w_c * min(max(0, competitors - free_count) / cap_c, 1), 0, 1)

A transparent weighted score over nearby counts, not a learned model: no labelled success data exists. Every weight,
cap and mix share comes from data/rules/location_weights.yaml and product_mix.yaml and is a proposed ASSUMPTION
(DEC-21). Pure functions: no HTTP, no database.
"""
from app.rules import CATEGORIES, LocationWeights, ProductMix

TOP_DRIVERS = 3


def contributions(counts: dict[str, int], w: LocationWeights) -> dict[str, float]:
    """Each feature's share of the 0-1 score (competitors negative)."""
    out: dict[str, float] = {name: f.weight * min(counts.get(name, 0) / f.cap, 1.0) for name, f in w.features.items()}
    extra = max(0, counts.get("competitors", 0) - w.competitors.free_count)
    out["competitors"] = w.competitors.weight * min(extra / w.competitors.cap, 1.0)
    return out


def score(counts: dict[str, int], w: LocationWeights) -> dict:
    parts = contributions(counts, w)
    raw = sum(parts.values())
    drivers = [{"feature": k, "count": int(counts.get(k, 0)), "points": round(100 * v, 1),
                "direction": "up" if v > 0 else "down"} for k, v in parts.items() if v != 0]
    pos = sorted((d for d in drivers if d["direction"] == "up"), key=lambda d: (-float(d["points"]), d["feature"]))
    neg = sorted((d for d in drivers if d["direction"] == "down"), key=lambda d: (d["points"], d["feature"]))
    return {"score": round(100 * min(max(raw, 0.0), 1.0)), "raw": round(raw, 4),
            "positive_drivers": pos[:TOP_DRIVERS], "negative_drivers": neg[:TOP_DRIVERS]}


def starter_mix(counts: dict[str, int], mix: ProductMix, shop_type: str = "kirana") -> dict:
    """Base shares by shop type, nudged by every nearby profile that applies, clipped at 0 and re-normalised."""
    st = mix.shop_types[shop_type]
    shares = dict(st.base)
    applied, items = [], []
    for name, p in st.profiles.items():
        if counts.get(p.feature, 0) >= p.min_count:
            applied.append({"profile": name, "feature": p.feature, "count": int(counts.get(p.feature, 0)),
                            "min_count": p.min_count})
            for cat, d in p.adjust.items():
                shares[cat] += d
            items += [i for i in p.suggest_items if i not in items]
    shares = {c: max(shares[c], 0.0) for c in CATEGORIES}
    total = sum(shares.values())
    lines = [{"category": c, "share": round(shares[c] / total, 4)} for c in CATEGORIES]
    return {"lines": sorted(lines, key=lambda x: (-x["share"], CATEGORIES.index(x["category"]))),
            "profiles_applied": applied, "suggest_items": items}

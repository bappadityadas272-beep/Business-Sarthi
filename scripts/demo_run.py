"""Demo driver: ARCHITECTURE section 12, steps 1 to 8, over HTTP only (no imports from the app).

    docker compose up -d                                   # API with the SYNTHETIC demo shops seeded
    docker compose exec backend make demo                  # or: python scripts/demo_run.py [--url ...] [--strict]

Each step prints PASS, FAIL or MISSED. MISSED = a known, recorded gap that is not a bug in the code (for example the
scheme half of step 7 while the team's scheme knowledge base, data/kb/schemes.json, does not exist: DEC-74).
Exit code: 1 if any step FAILED; with --strict also 1 if any step is MISSED; else 0.

Inputs used here come from the demo script itself (budget 5 lakh, rent 15,000) and from the DEMO-001 entry of
data/synthetic/config.yaml (pin, size 200 sq ft, city tier 2). Everything the API returns for the demo shops is
SYNTHETIC. The run needs DEV_MODE=1 (mock OTP echo and advance-time) and leaves the clock moved 2 days on the first
run; the demo-run owner deletes its own data at the end (B-11).
"""
import argparse
import json
import os
import sys
import time

import httpx

RAMESH, SUNITA, VISITOR = "+919000000001", "+919000000002", "+919000000090"
IDEA = {"name": "Demo run kirana (idea)", "shop_type": "kirana", "lat": 26.8467, "lon": 80.9462, "size_sqft": 200,
        "city_tier": 2, "budget": 500000, "monthly_rent": 15000}
EXPECTED_DECISION = {RAMESH: "pivot", SUNITA: "grow"}
EXPECTED_ALERTS = {"sales_dip", "low_stock", "dead_stock", "emi_due"}


class Step(Exception):
    def __init__(self, status: str, msg: str):
        super().__init__(msg)
        self.status = status


def need(cond: bool, msg: str) -> None:
    if not cond:
        raise Step("FAIL", msg)


class Api:
    def __init__(self, url: str):
        self.http = httpx.Client(base_url=url.rstrip("/") + "/api", timeout=120)
        self.token: str | None = None

    def call(self, method: str, path: str, ok=(200,), **kw) -> httpx.Response:
        headers = {"authorization": f"Bearer {self.token}"} if self.token else {}
        r = self.http.request(method, path, headers=headers, **kw)
        if r.status_code not in ok:
            raise Step("FAIL", f"{method} {path} -> HTTP {r.status_code} {r.text[:200]}")
        return r

    def login(self, phone: str) -> dict:
        self.token = None
        req = self.call("POST", "/auth/otp/request", json={"phone": phone}).json()
        need(req.get("is_mock") is True, "OTP request is not labelled mock")
        need(bool(req.get("dev_otp")), "no dev_otp echo: the API must run with DEV_MODE=1 for the demo")
        tok = self.call("POST", "/auth/otp/verify", json={"phone": phone, "otp": req["dev_otp"]}).json()
        self.token = tok["access_token"]
        return tok

    def own_shop(self) -> dict:
        shops = self.call("GET", "/shops").json()
        need(len(shops) >= 1, "demo owner has no shop: run `make seed`")
        return shops[0]

    def chat(self, shop_id: int, message: str) -> dict:
        headers = {"authorization": f"Bearer {self.token}"}
        events, event = {}, None
        with self.http.stream("POST", "/chat", json={"shop_id": shop_id, "message": message}, headers=headers) as r:
            if r.status_code != 200:
                raise Step("FAIL", f"POST /chat -> HTTP {r.status_code}")
            text = []
            for line in r.iter_lines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:") and event:
                    data = json.loads(line[5:].strip())
                    if event == "delta":
                        text.append(data["text"])
                    else:
                        events[event] = data
        need("meta" in events and "done" in events, "chat stream lacks meta or done event")
        return {"text": "".join(text), **events["meta"], **events["done"]}


def wait_ready(api: Api, seconds: int) -> None:
    end = time.time() + seconds
    while True:
        try:
            if api.http.get("/health").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        if time.time() > end:
            raise SystemExit(f"API not reachable at {api.http.base_url} after {seconds} s")
        time.sleep(3)


def step1(api: Api, ctx: dict) -> str:
    tok = api.login(VISITOR)
    api.call("PUT", "/me", json={"language": "hi"})
    api.call("POST", "/consents", ok=(200, 201), json={"purpose": "shop_data"})
    me = api.call("GET", "/me").json()
    cons = {c["purpose"]: c["active"] for c in api.call("GET", "/consents").json()}
    need(me["language"] == "hi" and cons.get("shop_data") is True, "language or consent not stored")
    return f"mock OTP login (new user: {tok['is_new_user']}), language hi, shop_data consent active"


def step2(api: Api, ctx: dict) -> str:
    shop = api.call("POST", "/shops", ok=(200, 201), json=IDEA).json()
    ctx["idea_id"] = shop["id"]
    need(shop["budget"] == 500000 and shop["monthly_rent"] == 15000, "idea not stored as entered")
    return f"idea shop {shop['id']} at the DEMO-001 pin, budget 5,00,000, rent 15,000"


def step3(api: Api, ctx: dict) -> str:
    sid = ctx["idea_id"]
    r = api.http.get(f"/shops/{sid}/location-score", headers={"authorization": f"Bearer {api.token}"})
    if r.status_code == 404 and "Not Found" in r.text:
        raise Step("FAIL", "GET /shops/{id}/location-score is not built yet (M-02)")
    need(r.status_code == 200, f"location-score -> HTTP {r.status_code}")
    loc = r.json()
    need("score" in loc and loc.get("starter_mix"), "location score or starter mix missing")
    fc = api.call("POST", f"/shops/{sid}/forecast", json={}).json()
    m = fc["months"]
    need(len(m) >= 3 and all(x["p10"] <= x["p50"] <= x["p90"] for x in m), "forecast months are not ordered ranges")
    need(fc["is_estimate"] and fc["trained_on_synthetic"], "forecast not labelled as an estimate on synthetic data")
    need(fc["break_even"]["revenue_monthly"] > 0 and "typical_months" in fc["payback"], "break-even or payback missing")
    need(fc["investment_split"]["budget"] == 500000, "investment split does not use the budget")
    pb = fc["payback"]
    return (f"location score {loc['score']}, {len(loc['starter_mix'])} starter-mix lines; month 1 sales "
            f"{m[0]['p10']:,}-{m[0]['p90']:,} (P50 {m[0]['p50']:,}); payback {pb['fastest_months']}/"
            f"{pb['typical_months']}/{pb['slowest_months']} months (fast/typical/slow)")


def step4(api: Api, ctx: dict) -> str:
    api.login(RAMESH)
    shop = api.own_shop()
    ctx["ramesh"] = shop["id"]
    logs = api.call("GET", f"/shops/{shop['id']}/logs").json()
    need(logs["days_logged"] == 88, f"expected 88 pre-loaded days, found {logs['days_logged']}")
    return f"Ramesh Kirana (shop {shop['id']}, SYNTHETIC): {logs['days_logged']} logged days"


def step5(api: Api, ctx: dict) -> str:
    alerts = api.call("GET", f"/shops/{ctx['ramesh']}/alerts", params={"status": "all"}).json()
    kinds = {a["kind"] for a in alerts}
    need(EXPECTED_ALERTS <= kinds, f"missing alerts: {sorted(EXPECTED_ALERTS - kinds)}")
    dip = next(a for a in alerts if a["kind"] == "sales_dip")
    need(not dip["still_active"] and not dip["resolved"], "sales dip should be no longer active but still open")
    return f"alerts {sorted(kinds)}; sales dip open and no longer active"


def step6(api: Api, ctx: dict) -> str:
    def latest(phone: str):
        api.login(phone)
        sid = api.own_shop()["id"]
        r = api.call("GET", f"/shops/{sid}/reviews/latest", ok=(200, 404))
        return r.json() if r.status_code == 200 else None

    if latest(RAMESH) is None or latest(SUNITA) is None:
        adv = api.call("POST", "/dev/advance-time", json={"days": 2}).json()
        need(adv["errors"] == 0, f"daily job reported {adv['errors']} errors")
        moved = f"advanced 2 days to {adv['today']}, {adv['reviews_created']} reviews created"
    else:
        moved = "reviews already exist (clock was advanced by an earlier run)"
    out = []
    for phone, want in EXPECTED_DECISION.items():
        rv = latest(phone)
        need(rv is not None, f"no review after advancing time for {phone[-2:]}")
        need(rv["decision"] == want, f"expected {want}, got {rv['decision']}")
        need(len(rv["reasons"]) > 0, "review has no reasons")
        out.append(f"{want} ({len(rv['reasons'])} reasons)")
    return f"{moved}; Ramesh {out[0]}, Sunita {out[1]}"


def step7(api: Api, ctx: dict) -> str:
    api.login(RAMESH)
    sid = api.own_shop()["id"]
    notes = []
    for q, lang in (("Is mahine ka profit kitna hai?", "hinglish"), ("इस महीने का मुनाफा कितना है?", "hi"),
                    ("What is my profit this month?", "en")):
        t = api.chat(sid, q)
        need(t["language"] == lang and t["intent"] == "my_numbers", f"{q!r}: routed {t['intent']}/{t['language']}")
        # failed / llm_unavailable: the owner sees the code-made template instead of the LLM text (DEC-73)
        need(t["guard"] in ("passed", "template", "failed", "llm_unavailable"), f"{q!r}: guard {t['guard']}")
        facts = [f for s in t["sources"] for f in s["facts"] if f["key"] == "operating_profit"]
        need(bool(facts) and all(f.get("source_label") for s in t["sources"] for f in s["facts"]),
             f"{q!r}: no operating_profit fact with a source label")
        notes.append(f"{lang}:{t['guard']}")
    s = api.chat(sid, "Mujhe kaunsi scheme milegi?")
    need(s["intent"] == "schemes", f"scheme question routed to {s['intent']}")
    cited = [x for x in s["sources"] if x.get("tool") == "match_schemes" and x["facts"]]
    if not cited:
        raise Step("MISSED", f"profit answers ok ({', '.join(notes)}); scheme answer has no cited scheme: no "
                             "scheme knowledge base yet (data/kb/schemes.json, written by the team; DEC-74)")
    return f"profit answers {', '.join(notes)}; scheme answer cites {len(cited)} source(s)"


def step8(api: Api, ctx: dict) -> str:
    api.login(RAMESH)
    sid = api.own_shop()["id"]
    r = api.http.post(f"/shops/{sid}/simulate", json={}, headers={"authorization": f"Bearer {api.token}"})
    if r.status_code == 404 and "Not Found" in r.text:
        raise Step("FAIL", "POST /shops/{id}/simulate is not built yet (M-10)")
    need(r.status_code == 200, f"simulate -> HTTP {r.status_code} {r.text[:200]}")
    sim = r.json()
    pb = sim.get("payback") or {}
    need({"fastest_months", "typical_months", "slowest_months"} <= set(pb), "simulator gives no payback range")
    return f"payback {pb['fastest_months']}/{pb['typical_months']}/{pb['slowest_months']} months (fast/typical/slow)"


def cleanup(api: Api) -> None:
    """The demo-run owner deletes its own data (B-11), so repeated runs leave nothing behind."""
    try:
        api.login(VISITOR)
        api.http.request("DELETE", "/me/data", headers={"authorization": f"Bearer {api.token}"})
    except (Step, httpx.HTTPError):
        pass


STEPS = [("1 login, Hindi, consent", step1), ("2 idea at a demo pin", step2),
         ("3 location score, forecast, break-even, payback, split", step3), ("4 pre-loaded 88 days", step4),
         ("5 dashboard alerts", step5), ("6 advance time, review", step6), ("7 chat: scheme + profit", step7),
         ("8 expansion simulator", step8)]


def default_url() -> str:
    if os.environ.get("API_URL"):
        return os.environ["API_URL"]
    for url in ("http://localhost:8000", "http://backend:8000"):          # in the API container, or beside it
        try:
            httpx.get(url + "/api/health", timeout=2)
            return url
        except httpx.HTTPError:
            continue
    return "http://localhost:8000"


def main() -> int:
    ap = argparse.ArgumentParser(description="Demo steps 1 to 8 over HTTP")
    ap.add_argument("--url", default=None)
    ap.add_argument("--wait", type=int, default=60, help="seconds to wait for the API to answer /api/health")
    ap.add_argument("--strict", action="store_true", help="MISSED steps also fail the run")
    args = ap.parse_args()
    api = Api(args.url or default_url())
    wait_ready(api, args.wait)
    print(f"Demo run against {api.http.base_url} (SYNTHETIC demo shops)")
    ctx, results = {}, []
    for name, fn in STEPS:
        try:
            status, msg = "PASS", fn(api, ctx)
        except Step as e:
            status, msg = e.status, str(e)
        except (httpx.HTTPError, KeyError, ValueError, StopIteration) as e:
            status, msg = "FAIL", f"{type(e).__name__}: {e}"
        results.append(status)
        print(f"{status:<6} step {name}: {msg}")
    cleanup(api)
    failed, missed = results.count("FAIL"), results.count("MISSED")
    print(f"\n{results.count('PASS')} passed, {failed} failed, {missed} missed (known gaps, see DECISIONS)")
    return 1 if failed or (args.strict and missed) else 0


if __name__ == "__main__":
    sys.exit(main())

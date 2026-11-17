"""C-07: POST /api/chat streams guard-approved text as SSE, stores both turns with sources, needs login and consent."""
import json

import pytest
from sqlalchemy import select

from app import seed as sd
from app.llm import client as llm
from app.llm.stub import StubClient
from app.models import ChatMessage, Shop
from app.services import chat as chat_service
from app.services import clock
from tests.conftest import login

RAMESH, SUNITA = "+919000000001", "+919000000002"


@pytest.fixture
def demo(client, db_factory, synth_small, model_small):
    with db_factory() as db:
        res = sd.seed(db, clock.today(), demo_dir=synth_small / "demo", model=model_small)
        shops = {db.get(Shop, s["shop_id"]).user_id: s["shop_id"] for s in res["shops"]}
    headers = {p: login(client, p) for p in (RAMESH, SUNITA)}
    client.post("/api/dev/advance-time", headers=headers[RAMESH], json={"days": 2})       # reviews exist
    with db_factory() as db:
        by_phone = {}
        for uid, sid in shops.items():
            from app.models import User
            by_phone[db.get(User, uid).phone] = sid
    return {p: (headers[p], by_phone[p]) for p in (RAMESH, SUNITA)}


def ask(client, headers, shop_id, message):
    r = client.post("/api/chat", headers=headers, json={"shop_id": shop_id, "message": message})
    return r, parse(r.text) if r.status_code == 200 else None


def parse(body: str) -> dict:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        events.append((lines["event"], json.loads(lines["data"])))
    kinds = [e for e, _ in events]
    assert kinds[0] == "meta" and kinds[-1] == "done" and set(kinds[1:-1]) <= {"delta"}, kinds
    return {"meta": events[0][1], "done": events[-1][1], "text": "".join(d["text"] for e, d in events if e == "delta")}


@pytest.mark.parametrize(("question", "lang"), [
    ("Is mahine ka profit kitna hai?", "hinglish"),
    ("इस महीने का मुनाफा कितना है?", "hi"),
    ("What is my profit this month?", "en"),
])
def test_demo_step_7_profit_question(demo, client, db_factory, question, lang):
    headers, sid = demo[RAMESH]
    r, ev = ask(client, headers, sid, question)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    assert ev["meta"] == {"language": lang, "intent": "my_numbers"}
    assert ev["done"]["guard"] == "passed" and "₹" in ev["text"]
    src = {s["tool"]: s for s in ev["done"]["sources"]}
    profit = {f["key"]: f for f in src["get_profit_summary"]["facts"]}
    assert all(f["source_label"] == src["get_profit_summary"]["label"] for f in profit.values())
    with db_factory() as db:
        rows = db.scalars(select(ChatMessage).where(ChatMessage.shop_id == sid).order_by(ChatMessage.id)).all()
        assert [m.role for m in rows] == ["user", "assistant"] and rows[0].text == question
        assert rows[1].id == ev["done"]["message_id"] and rows[1].text == ev["text"]
        assert rows[1].sources_json == ev["done"]["sources"]
        from app.llm import tools as t
        uid = db.get(Shop, sid).user_id
        truth = t.run(db, uid, sid, "get_profit_summary", period="this_month")
    from app.llm.templates import inr
    assert inr(truth["data"]["operating_profit"]) in ev["text"]          # the number the code computed


def test_demo_step_7_scheme_question_is_honest_until_the_kb_exists(demo, client):
    """DEC-74: no KB yet, so no scheme names and a 'check the official page' answer (missed target, logged)."""
    headers, sid = demo[RAMESH]
    _, ev = ask(client, headers, sid, "Mujhe kaunsi scheme milegi?")
    assert ev["meta"]["intent"] == "schemes" and ev["done"]["guard"] == "template"
    assert ev["done"]["sources"][0]["note"] == "no_verified_source"
    from app.llm import guard
    for q, lang in (("Mujhe kaunsi scheme milegi?", "hinglish"), ("मुझे कौन सी योजना मिलेगी?", "hi"),
                    ("Which scheme can I get?", "en")):
        _, ev = ask(client, headers, sid, q)
        assert ev["meta"] == {"language": lang, "intent": "schemes"}, q
        res = guard.check(ev["text"], question=q, language=lang, tool_outputs=[])   # no scheme name, no promise
        assert res.ok, (q, res.failures)


def test_both_demo_shops_get_their_own_numbers(demo, client):
    texts = {p: ask(client, *demo[p], "Is mahine ka profit kitna hai?")[1]["text"] for p in (RAMESH, SUNITA)}
    assert texts[RAMESH] != texts[SUNITA]


def test_needs_login_consent_and_own_shop(demo, client, db_factory):
    headers, sid = demo[RAMESH]
    _, other_sid = demo[SUNITA]
    assert client.post("/api/chat", json={"shop_id": sid, "message": "profit?"}).status_code == 401
    r, _ = ask(client, headers, other_sid, "Is mahine ka profit kitna hai?")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "shop_not_found"
    assert ask(client, headers, 99999, "profit?")[0].status_code == 404
    assert client.post("/api/chat", headers=headers, json={"shop_id": sid, "message": ""}).status_code == 422
    from app.services import consent
    with db_factory() as db:
        consent.withdraw(db, db.get(Shop, sid).user_id, consent.SHOP_DATA)
    r, _ = ask(client, headers, sid, "Is mahine ka profit kitna hai?")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "consent_required"
    with db_factory() as db:
        assert db.scalars(select(ChatMessage).where(ChatMessage.shop_id == sid)).all() == []


def test_smalltalk_and_refusals_are_templates_in_the_owner_language(demo, client):
    headers, sid = demo[RAMESH]
    _, ev = ask(client, headers, sid, "namaste")
    assert ev["meta"]["intent"] == "smalltalk" and ev["done"]["guard"] == "template"
    _, ev = ask(client, headers, sid, "मुझे बुखार है, कौन सी दवा लूँ?")
    assert ev["meta"] == {"language": "hi", "intent": "out_of_scope"} and ev["done"]["guard"] == "template"
    assert any("ऀ" <= c <= "ॿ" for c in ev["text"])


@pytest.fixture
def ramesh(demo, db_factory):
    sid = demo[RAMESH][1]
    with db_factory() as db:
        return db.get(Shop, sid).user_id, sid


def test_a_bad_llm_answer_is_never_shown(ramesh, db_factory):
    uid, sid = ramesh
    with db_factory() as db:
        shop = db.get(Shop, sid)
        turn = chat_service.answer(db, uid, shop, "Is mahine ka profit kitna hai?",
                                   client=StubClient(reply="Munafa ₹99,99,999 hai, pakka!"), cache=llm.AnswerCache())
        good = chat_service.answer(db, uid, shop, "Is mahine ka profit kitna hai?", client=StubClient(),
                                   cache=llm.AnswerCache())
    assert turn.guard == "failed" and set(turn.failures) == {"unknown_number", "guarantee_word"}
    assert "99,99,999" not in turn.text and turn.text == good.text            # the template, same as the stub's


class Down(StubClient):
    def generate(self, *a, **k):
        raise llm.LLMUnavailable("retries_exhausted", 503)


def test_provider_down_gives_the_template(ramesh, db_factory):
    uid, sid = ramesh
    with db_factory() as db:
        turn = chat_service.answer(db, uid, db.get(Shop, sid), "Is mahine ka profit kitna hai?", client=Down(),
                                   cache=llm.AnswerCache())
    assert turn.guard == "llm_unavailable" and "₹" in turn.text


def test_identical_question_same_day_uses_the_cache(ramesh, db_factory):
    uid, sid = ramesh
    cache, stub = llm.AnswerCache(), StubClient()
    with db_factory() as db:
        shop = db.get(Shop, sid)
        first = chat_service.answer(db, uid, shop, "Is mahine ka profit kitna hai?", client=stub, cache=cache)
        again = chat_service.answer(db, uid, shop, "is mahine ka PROFIT kitna hai", client=stub, cache=cache)
    assert not first.cached and again.cached and again.text == first.text and stub.calls == 1


def test_chunks_keep_the_text():
    from app.api.chat import chunks
    text = "इस महीने (1 नवंबर से 16 नवंबर) मुनाफा ₹25,456 है। EMI ₹2,000."
    assert "".join(chunks(text)) == text and len(list(chunks(text))) > 1

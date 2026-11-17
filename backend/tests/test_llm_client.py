"""C-01: LLM client interface, providers, retry and fallback. The network is always mocked."""
import json
import logging
import random
from datetime import date

import httpx
import pytest

from app.config import Settings
from app.llm import client as llm
from app.llm.claude import ClaudeClient
from app.llm.gemini import GeminiClient
from app.llm.stub import NO_FACTS_REPLY, StubClient

KEY = "test-key-SHOULD-NEVER-BE-LOGGED-9f3a"
SYSTEM, MSGS = "You are a test.", [{"role": "user", "content": "Mera phone +919812345678 hai. Profit?"}]


def settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def no_sleep_policy(sleeps: list) -> llm.RetryPolicy:
    return llm.RetryPolicy(max_retries=3, sleep=sleeps.append, rng=random.Random(0))


def gemini_ok(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def test_stub_is_deterministic_and_needs_no_key():
    a, b = StubClient(), StubClient()
    assert a.generate(SYSTEM, MSGS) == b.generate(SYSTEM, MSGS) == NO_FACTS_REPLY
    assert "".join(a.stream(SYSTEM, MSGS)) == NO_FACTS_REPLY
    assert StubClient(reply="forced").generate(SYSTEM, MSGS) == "forced"
    assert StubClient().generate(SYSTEM, [{"role": "user", "content": "<classify> x"}]) == "out_of_scope"


def test_provider_is_chosen_by_env_var(monkeypatch):
    assert isinstance(llm.get_client(settings(llm_provider="stub")), StubClient)
    g = llm.get_client(settings(llm_provider="gemini", llm_api_key=KEY))
    c = llm.get_client(settings(llm_provider="claude", llm_api_key=KEY, llm_model="claude-x"))
    assert isinstance(g, llm.FallbackClient) and g.model == "gemini-3.8-flash"            # DEC-81
    assert isinstance(g.primary, GeminiClient) and g.fallback.model == "gemini-3.5-flash-lite"
    assert g.primary.retry.max_retries == 1 and g.fallback.retry.max_retries == 3
    off = llm.get_client(settings(llm_provider="gemini", llm_api_key=KEY, llm_fallback_model="off"))
    assert isinstance(off, GeminiClient) and off.model == "gemini-3.8-flash"
    same = llm.get_client(settings(llm_provider="gemini", llm_api_key=KEY, llm_model="gemini-3.5-flash-lite"))
    assert isinstance(same, GeminiClient)                                                   # no fallback to itself
    assert isinstance(c, ClaudeClient) and c.model == "claude-x"
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(llm.LLMError, match="missing_api_key"):
        llm.get_client(settings(llm_provider="gemini"))
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_API_KEY", KEY)
    assert isinstance(llm.get_client(Settings(_env_file=None)), llm.FallbackClient)


def test_thinking_config_per_model_family():
    """Checked live 2026-11-17 (gemini.py docstring): Gemini 3 rejects thinkingBudget 0 and 3.8 rejects 'minimal'."""
    from app.llm.gemini import THINKING_MARGIN, generation_config
    assert generation_config("gemini-2.5-flash", 50, 0.2)["thinkingConfig"] == {"thinkingBudget": 0}
    g3 = generation_config("gemini-3.8-flash", 50, 0.2)
    assert g3["thinkingConfig"] == {"thinkingLevel": "low"} and g3["maxOutputTokens"] == 50 + THINKING_MARGIN
    assert generation_config("gemini-3.5-flash-lite", 50, 0.2) == {"maxOutputTokens": 50, "temperature": 0.2}


def fallback_pair(primary_status: int, calls: list):
    def handler(req):
        calls.append(req.url.path.rsplit("/", 1)[-1])
        if "primary" in str(req.url):
            return httpx.Response(primary_status, json={"error": {"message": "x"}})
        if "alt=sse" in str(req.url):
            return httpx.Response(200, text="data: " + json.dumps(gemini_ok("from fallback")))
        return httpx.Response(200, json=gemini_ok("from fallback"))
    t = httpx.MockTransport(handler)
    return llm.FallbackClient(GeminiClient(KEY, "primary", retry=no_sleep_policy([]), transport=t),
                              GeminiClient(KEY, "lite", retry=no_sleep_policy([]), transport=t))


def test_unavailable_primary_falls_back_to_lite_model_once(caplog):
    caplog.set_level(logging.DEBUG)
    calls = []
    assert fallback_pair(503, calls).generate(SYSTEM, MSGS) == "from fallback"
    assert calls[-1] == "lite:generateContent" and calls.count("lite:generateContent") == 1
    assert "llm fallback provider=gemini from=primary to=lite" in caplog.text and KEY not in caplog.text
    calls.clear()
    assert "".join(fallback_pair(503, calls).stream(SYSTEM, MSGS)) == "from fallback"
    assert calls[-1] == "lite:streamGenerateContent"


def test_refused_primary_does_not_use_the_fallback():
    calls = []
    fb = fallback_pair(400, calls)
    assert llm.generate_or_fallback(fb, SYSTEM, MSGS, fallback=lambda: "T") == ("T", "refused")
    assert calls == ["primary:generateContent"]


def test_gemini_request_shape_and_key_in_header_only():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=gemini_ok("Namaste"))

    g = GeminiClient(KEY, "gemini-2.5-flash", transport=httpx.MockTransport(handler))
    assert g.generate(SYSTEM, MSGS + [{"role": "assistant", "content": "ok"}], max_tokens=50) == "Namaste"
    req = seen[0]
    body = json.loads(req.content)
    assert req.headers["x-goog-api-key"] == KEY and KEY not in str(req.url)
    assert body["systemInstruction"]["parts"][0]["text"] == SYSTEM
    assert [c["role"] for c in body["contents"]] == ["user", "model"]
    assert body["generationConfig"]["maxOutputTokens"] == 50


def test_claude_request_and_stream():
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert req.headers["x-api-key"] == KEY and body["system"] == SYSTEM
        if body.get("stream"):
            sse = "\n".join("data: " + json.dumps(e) for e in [
                {"type": "message_start"},
                {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Nam"}},
                {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "aste"}},
                {"type": "message_stop"}])
            return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"content": [{"type": "text", "text": "Namaste"}]})

    c = ClaudeClient(KEY, "m", transport=httpx.MockTransport(handler))
    assert c.generate(SYSTEM, MSGS) == "Namaste"
    assert list(c.stream(SYSTEM, MSGS)) == ["Nam", "aste"]


def test_gemini_stream_sse():
    sse = "\n\n".join("data: " + json.dumps(gemini_ok(t)) for t in ("Nam", "aste"))
    g = GeminiClient(KEY, "m", transport=httpx.MockTransport(lambda r: httpx.Response(200, text=sse)))
    assert "".join(g.stream(SYSTEM, MSGS)) == "Namaste"


def test_429_retries_with_backoff_then_succeeds():
    calls, sleeps = [], []

    def handler(req):
        calls.append(1)
        return httpx.Response(429) if len(calls) < 3 else httpx.Response(200, json=gemini_ok("ok"))

    g = GeminiClient(KEY, "m", retry=no_sleep_policy(sleeps), transport=httpx.MockTransport(handler))
    assert g.generate(SYSTEM, MSGS) == "ok"
    assert len(calls) == 3 and len(sleeps) == 2
    assert 0.5 <= sleeps[0] <= 1.5 and 1.0 <= sleeps[1] <= 3.0            # 1 s then 2 s, with jitter


def test_retry_after_header_is_honoured_and_capped():
    p = llm.RetryPolicy()
    assert p.delay(0, "3") == 3.0 and p.delay(0, "120") == llm.MAX_RETRY_AFTER_S


def test_simulated_429_retries_then_falls_back_and_no_key_in_logs(caplog):
    """C-01 acceptance: 429 retries, then the fallback answer; the key and the prompt never reach the logs."""
    caplog.set_level(logging.DEBUG)
    calls, sleeps = [], []

    def handler(req):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "abc"}, json={"error": {"message": "quota"}})

    g = GeminiClient(KEY, "m", retry=no_sleep_policy(sleeps), transport=httpx.MockTransport(handler))
    text, failure = llm.generate_or_fallback(g, SYSTEM, MSGS, fallback=lambda: "TEMPLATE")
    assert (text, failure) == ("TEMPLATE", "retries_exhausted")
    assert len(calls) == 4 and len(sleeps) == 3
    assert "llm retry" in caplog.text and "llm unavailable" in caplog.text
    assert KEY not in caplog.text and "9812345678" not in caplog.text and SYSTEM not in caplog.text


def test_timeout_and_network_errors_retry_then_fall_back(caplog):
    caplog.set_level(logging.DEBUG)

    def handler(req):
        raise httpx.ReadTimeout("slow", request=req)

    g = GeminiClient(KEY, "m", retry=no_sleep_policy([]), transport=httpx.MockTransport(handler))
    assert llm.generate_or_fallback(g, SYSTEM, MSGS, fallback=lambda: "T") == ("T", "retries_exhausted")
    assert KEY not in caplog.text


def test_client_error_is_not_retried_and_empty_answer_falls_back():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(400, json={"error": {"message": f"bad key {KEY}"}})

    g = GeminiClient(KEY, "m", retry=no_sleep_policy([]), transport=httpx.MockTransport(handler))
    assert llm.generate_or_fallback(g, SYSTEM, MSGS, fallback=lambda: "T") == ("T", "refused")
    assert len(calls) == 1
    empty = GeminiClient(KEY, "m", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"candidates": []})))
    assert llm.generate_or_fallback(empty, SYSTEM, MSGS, fallback=lambda: "T") == ("T", "empty_answer")


def test_answer_cache_per_shop_and_day():
    cache = llm.AnswerCache()
    k1 = cache.key(1, date(2026, 11, 17), "Is mahine ka profit kitna hai?", '{"a":1}')
    assert k1 == cache.key(1, date(2026, 11, 17), "  is mahine ka PROFIT kitna hai ", '{"a":1}')
    assert k1 != cache.key(2, date(2026, 11, 17), "Is mahine ka profit kitna hai?", '{"a":1}')
    assert k1 != cache.key(1, date(2026, 11, 17), "Is mahine ka profit kitna hai?", '{"a":2}')   # facts changed
    cache.put(k1, "answer")
    assert cache.get(k1) == "answer"
    k2 = cache.key(1, date(2026, 11, 18), "Is mahine ka profit kitna hai?", '{"a":1}')
    cache.put(k2, "next day")
    assert cache.get(k1) is None and cache.get(k2) == "next day"          # a new day drops the old entries

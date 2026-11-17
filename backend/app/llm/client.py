"""`LLMClient` interface, provider factory, retry with backoff, and the answer cache (C-01, DEC-75).

Rules for every provider:
- The API key comes only from the environment (`LLM_API_KEY`) and is sent in a header, never in a URL.
- Nothing here logs a key, a prompt or an answer: only the provider, the HTTP status and the attempt number.
- A failure after the retries raises `LLMUnavailable`; the caller then shows the guard's template answer
  (`generate_or_fallback`).
"""
import hashlib
import logging
import random
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date

import httpx

from app.config import Settings, get_settings

log = logging.getLogger("app.llm")

RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_RETRY_AFTER_S = 10.0
DEFAULT_MAX_TOKENS = 400
DEFAULT_TEMPERATURE = 0.2

Message = dict                      # {"role": "user" | "assistant", "content": str}


class LLMError(RuntimeError):
    """The provider refused the request (not worth retrying), or gave an empty answer."""

    def __init__(self, kind: str, status: int | None = None):
        super().__init__(f"llm_error:{kind}" + (f":{status}" if status else ""))
        self.kind, self.status = kind, status


class LLMUnavailable(LLMError):
    """Retries used up (rate limit, server error, timeout or network)."""


class LLMClient(ABC):
    name = "base"

    @abstractmethod
    def generate(self, system: str, messages: list[Message], max_tokens: int = DEFAULT_MAX_TOKENS,
                 temperature: float = DEFAULT_TEMPERATURE) -> str:
        """The whole answer as one string."""

    @abstractmethod
    def stream(self, system: str, messages: list[Message], max_tokens: int = DEFAULT_MAX_TOKENS,
               temperature: float = DEFAULT_TEMPERATURE) -> Iterator[str]:
        """The answer as text chunks. The chat endpoint does not show these before the guard (DEC-73)."""


@dataclass
class RetryPolicy:
    max_retries: int = 3
    base_delay_s: float = 1.0                 # 1, 2, 4 s ...
    jitter: tuple[float, float] = (0.5, 1.5)
    sleep: Callable[[float], None] = time.sleep
    rng: random.Random = field(default_factory=random.Random)

    def delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), MAX_RETRY_AFTER_S)
            except ValueError:
                pass
        return self.base_delay_s * (2 ** attempt) * self.rng.uniform(*self.jitter)


class HttpProvider(LLMClient):
    """Shared POST with timeout and retry for the hosted providers."""

    def __init__(self, api_key: str, model: str, *, timeout_s: float = 20.0, retry: RetryPolicy | None = None,
                 transport: httpx.BaseTransport | None = None):
        if not api_key:
            raise LLMError("missing_api_key")
        self._key, self.model = api_key, model
        self.retry = retry or RetryPolicy()
        self._http = httpx.Client(timeout=timeout_s, transport=transport)

    def _headers(self) -> dict:
        raise NotImplementedError

    def _send(self, url: str, body: dict, *, stream: bool = False) -> httpx.Response:
        for attempt in range(self.retry.max_retries + 1):
            try:
                req = self._http.build_request("POST", url, json=body, headers=self._headers())
                resp = self._http.send(req, stream=stream)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                status, retry_after, kind = None, None, type(e).__name__
            else:
                if resp.status_code < 400:
                    return resp
                status, retry_after, kind = resp.status_code, resp.headers.get("retry-after"), "http"
                resp.close()
                if status not in RETRY_STATUS:
                    log.warning("llm request refused provider=%s status=%s", self.name, status)
                    raise LLMError("refused", status)
            if attempt == self.retry.max_retries:
                log.warning("llm unavailable provider=%s status=%s kind=%s attempts=%s", self.name, status, kind,
                            attempt + 1)
                raise LLMUnavailable("retries_exhausted", status)
            wait = self.retry.delay(attempt, retry_after)
            log.info("llm retry provider=%s status=%s kind=%s attempt=%s wait_s=%.2f", self.name, status, kind,
                     attempt + 1, wait)
            self.retry.sleep(wait)
        raise LLMUnavailable("retries_exhausted")          # not reached


class FallbackClient(LLMClient):
    """DEC-81: the primary model first; only when it is *unavailable* (retries used up on 429/5xx, timeout or
    network) one try on the fallback model. A refusal (4xx such as a bad key) is not retried on the fallback."""

    def __init__(self, primary: LLMClient, fallback: LLMClient):
        self.primary, self.fallback = primary, fallback
        self.name = getattr(primary, "name", "base")
        self.model = getattr(primary, "model", "")

    def _switch(self, e: LLMUnavailable) -> None:
        log.warning("llm fallback provider=%s from=%s to=%s status=%s", self.name, self.model,
                    getattr(self.fallback, "model", ""), e.status)

    def generate(self, system: str, messages: list[Message], max_tokens: int = DEFAULT_MAX_TOKENS,
                 temperature: float = DEFAULT_TEMPERATURE) -> str:
        try:
            return self.primary.generate(system, messages, max_tokens, temperature)
        except LLMUnavailable as e:
            self._switch(e)
            return self.fallback.generate(system, messages, max_tokens, temperature)

    def stream(self, system: str, messages: list[Message], max_tokens: int = DEFAULT_MAX_TOKENS,
               temperature: float = DEFAULT_TEMPERATURE) -> Iterator[str]:
        try:
            chunks = self.primary.stream(system, messages, max_tokens, temperature)
            first = next(chunks, None)
        except LLMUnavailable as e:
            self._switch(e)
            yield from self.fallback.stream(system, messages, max_tokens, temperature)
            return
        if first is not None:
            yield first
            yield from chunks


PRIMARY_RETRIES_WITH_FALLBACK = 1          # DEC-81: do not make the owner wait through all retries twice


def get_client(settings: Settings | None = None, **kw) -> LLMClient:
    """The provider named by `LLM_PROVIDER` (stub by default, so nothing needs a key)."""
    s = settings or get_settings()
    if s.llm_provider == "stub":
        from app.llm.stub import StubClient
        return StubClient()
    retry = kw.pop("retry", None) or RetryPolicy(max_retries=s.llm_max_retries)
    if s.llm_provider == "gemini":
        from app.llm.gemini import DEFAULT_MODEL, FALLBACK_MODEL, GeminiClient
        model = s.llm_model or DEFAULT_MODEL
        fb_model = "" if s.llm_fallback_model == "off" else (s.llm_fallback_model or FALLBACK_MODEL)
        if not fb_model or fb_model == model:
            return GeminiClient(s.llm_api_key, model, timeout_s=s.llm_timeout_s, retry=retry, **kw)
        primary_retry = RetryPolicy(max_retries=min(retry.max_retries, PRIMARY_RETRIES_WITH_FALLBACK),
                                    base_delay_s=retry.base_delay_s, sleep=retry.sleep, rng=retry.rng)
        return FallbackClient(GeminiClient(s.llm_api_key, model, timeout_s=s.llm_timeout_s, retry=primary_retry, **kw),
                              GeminiClient(s.llm_api_key, fb_model, timeout_s=s.llm_timeout_s, retry=retry, **kw))
    if s.llm_provider == "claude":
        from app.llm.claude import DEFAULT_MODEL, ClaudeClient
        return ClaudeClient(s.llm_api_key, s.llm_model or DEFAULT_MODEL, timeout_s=s.llm_timeout_s, retry=retry, **kw)
    raise LLMError("unknown_provider")


def generate_or_fallback(client: LLMClient, system: str, messages: list[Message], fallback: Callable[[], str],
                         **kw) -> tuple[str, str | None]:
    """(text, failure kind or None). Any provider failure gives the fallback text instead."""
    try:
        text = client.generate(system, messages, **kw)
    except LLMError as e:
        return fallback(), e.kind
    if not text.strip():
        return fallback(), "empty_answer"
    return text, None


def normalise_question(q: str) -> str:
    return re.sub(r"[\s?!.,।]+", " ", q.casefold()).strip()


class AnswerCache:
    """Identical questions per shop per app day (DEC-75). In memory: lost on restart; old days are dropped."""

    def __init__(self, max_entries: int = 2000):
        self._d: dict[tuple, str] = {}
        self._day: date | None = None
        self.max_entries = max_entries

    @staticmethod
    def key(shop_id: int, day: date, question: str, facts_json: str) -> tuple:
        return (shop_id, day, normalise_question(question), hashlib.sha256(facts_json.encode()).hexdigest())

    def get(self, key: tuple) -> str | None:
        return self._d.get(key)

    def put(self, key: tuple, answer: str) -> None:
        if self._day != key[1]:
            self._d.clear()
            self._day = key[1]
        if len(self._d) >= self.max_entries:
            self._d.pop(next(iter(self._d)))
        self._d[key] = answer

    def clear(self) -> None:
        self._d.clear()


answer_cache = AnswerCache()

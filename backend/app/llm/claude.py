"""Claude provider over the Messages REST API (`POST /v1/messages`, SSE when streaming), DEC-75.

The key goes in the `x-api-key` header. Default model can be overridden with `LLM_MODEL`. Not run against the
live API in the tests (the network is mocked).
"""
import json
from collections.abc import Iterator

from app.llm.client import DEFAULT_MAX_TOKENS, DEFAULT_TEMPERATURE, HttpProvider, LLMError, Message

URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-haiku-5-5"


class ClaudeClient(HttpProvider):
    name = "claude"

    def _headers(self) -> dict:
        return {"x-api-key": self._key, "anthropic-version": API_VERSION, "content-type": "application/json"}

    def _body(self, system: str, messages: list[Message], max_tokens: int, temperature: float, stream: bool) -> dict:
        body = {"model": self.model, "max_tokens": max_tokens, "temperature": temperature, "system": system,
                "messages": [{"role": m["role"], "content": m["content"]} for m in messages]}
        if stream:
            body["stream"] = True
        return body

    def generate(self, system: str, messages: list[Message], max_tokens: int = DEFAULT_MAX_TOKENS,
                 temperature: float = DEFAULT_TEMPERATURE) -> str:
        resp = self._send(URL, self._body(system, messages, max_tokens, temperature, False))
        try:
            data = resp.json()
        except ValueError as e:
            raise LLMError("bad_response") from e
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        if not text.strip():
            raise LLMError("empty_answer")
        return text

    def stream(self, system: str, messages: list[Message], max_tokens: int = DEFAULT_MAX_TOKENS,
               temperature: float = DEFAULT_TEMPERATURE) -> Iterator[str]:
        resp = self._send(URL, self._body(system, messages, max_tokens, temperature, True), stream=True)
        try:
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    ev = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if ev.get("type") == "content_block_delta" and ev.get("delta", {}).get("type") == "text_delta":
                    yield ev["delta"]["text"]
        finally:
            resp.close()

"""Gemini provider over the REST API (`generateContent`, `streamGenerateContent?alt=sse`), DEC-75.

The key goes in the `x-goog-api-key` header, never in the URL. The default model name is set here and can be
overridden with `LLM_MODEL`; check the model list of your key in Google AI Studio (not verified in the tests,
which mock the network).
"""
import json
from collections.abc import Iterator

from app.llm.client import DEFAULT_MAX_TOKENS, DEFAULT_TEMPERATURE, HttpProvider, LLMError, Message

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiClient(HttpProvider):
    name = "gemini"

    def _headers(self) -> dict:
        return {"x-goog-api-key": self._key, "content-type": "application/json"}

    def _body(self, system: str, messages: list[Message], max_tokens: int, temperature: float) -> dict:
        cfg: dict = {"maxOutputTokens": max_tokens, "temperature": temperature}
        if self.model.startswith("gemini-2.5-flash"):
            cfg["thinkingConfig"] = {"thinkingBudget": 0}     # thinking would use up the small token budget
        return {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                         for m in messages],
            "generationConfig": cfg,
        }

    @staticmethod
    def _text(data: dict) -> str:
        try:
            parts = data["candidates"][0]["content"].get("parts", [])
        except (KeyError, IndexError, TypeError):
            return ""
        return "".join(p.get("text", "") for p in parts if not p.get("thought"))

    def generate(self, system: str, messages: list[Message], max_tokens: int = DEFAULT_MAX_TOKENS,
                 temperature: float = DEFAULT_TEMPERATURE) -> str:
        resp = self._send(f"{BASE_URL}/{self.model}:generateContent",
                          self._body(system, messages, max_tokens, temperature))
        try:
            text = self._text(resp.json())
        except ValueError as e:
            raise LLMError("bad_response") from e
        if not text.strip():
            raise LLMError("empty_answer")
        return text

    def stream(self, system: str, messages: list[Message], max_tokens: int = DEFAULT_MAX_TOKENS,
               temperature: float = DEFAULT_TEMPERATURE) -> Iterator[str]:
        resp = self._send(f"{BASE_URL}/{self.model}:streamGenerateContent?alt=sse",
                          self._body(system, messages, max_tokens, temperature), stream=True)
        try:
            for line in resp.iter_lines():
                if line.startswith("data:"):
                    try:
                        chunk = self._text(json.loads(line[5:].strip()))
                    except ValueError:
                        continue
                    if chunk:
                        yield chunk
        finally:
            resp.close()

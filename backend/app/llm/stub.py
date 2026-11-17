"""Deterministic stub provider (C-01). No network; used in every test and when `LLM_PROVIDER=stub`.

- With a facts block in the last user message (`<facts>{json}</facts>`, written by the prompt builder) it answers
  with the template text for those facts, so the demo works with no API key and every number comes from code.
- A classification request (`<classify>` marker, router fallback) gets `out_of_scope`.
- `StubClient(reply=...)` always returns that text: tests use it to force a bad answer past the LLM step.
"""
import json
import re
from collections.abc import Iterator

from app.llm.client import DEFAULT_MAX_TOKENS, DEFAULT_TEMPERATURE, LLMClient, Message

FACTS_RE = re.compile(r"<facts>\s*(\{.*\})\s*</facts>", re.DOTALL)
NO_FACTS_REPLY = "Stub answer: no facts were provided."


class StubClient(LLMClient):
    name = "stub"

    def __init__(self, reply: str | None = None):
        self.reply = reply
        self.calls = 0

    def generate(self, system: str, messages: list[Message], max_tokens: int = DEFAULT_MAX_TOKENS,
                 temperature: float = DEFAULT_TEMPERATURE) -> str:
        self.calls += 1
        if self.reply is not None:
            return self.reply
        last = messages[-1]["content"] if messages else ""
        if "<classify>" in last:
            return "out_of_scope"
        m = FACTS_RE.search(last)
        if not m:
            return NO_FACTS_REPLY
        from app.llm import templates  # the template answer for the same facts
        payload = json.loads(m.group(1))
        return templates.render(payload["intent"], payload["tools"], payload["language"])

    def stream(self, system: str, messages: list[Message], max_tokens: int = DEFAULT_MAX_TOKENS,
               temperature: float = DEFAULT_TEMPERATURE) -> Iterator[str]:
        text = self.generate(system, messages, max_tokens, temperature)
        for i, word in enumerate(text.split(" ")):
            yield word if i == 0 else " " + word

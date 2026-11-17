"""Logs and request plumbing (hardening, DEC-90).

- One JSON object per log line on stdout. Every line passes through `redact`: phone numbers keep only their last 2
  digits, API keys and bearer tokens are replaced. Code still must not log prompts, keys or full phones; this is the
  safety net, not the rule.
- `RequestLog`: one line per request (method, path, status, ms, request id) and an `X-Request-ID` header. Paths never
  carry a phone (phones are only in request bodies), and bodies are never logged.
- `BodyLimit`: bodies over MAX_BODY_BYTES get 413 before the app reads them.
- `DevGate`: with DEV_MODE off, every /api/dev path answers exactly like an unknown path (404 not_found).
"""
import json
import logging
import re
import sys
import time
import uuid
from datetime import UTC, datetime

from app.config import get_settings

_PHONE = re.compile(r"(?<![\d*])(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")
_SECRETS = [re.compile(p) for p in (r"AIza[0-9A-Za-z_\-]{20,}", r"sk-ant-[0-9A-Za-z_\-]{10,}",
                                    r"(?i)bearer\s+[A-Za-z0-9_\-\.=]{8,}")]


def mask_phone(phone: str) -> str:
    """'+919800000001' -> '********01'. Used wherever a phone would otherwise reach a log."""
    digits = re.sub(r"\D", "", phone or "")
    return "*" * 8 + digits[-2:] if digits else ""


def redact(text: str) -> str:
    text = _PHONE.sub(lambda m: mask_phone(m.group(0)), text)
    for p in _SECRETS:
        text = p.sub("[redacted]", text)
    return text


_STD = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
               "level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        out.update({k: v for k, v in vars(record).items() if k not in _STD and not k.startswith("_")})
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return redact(json.dumps(out, default=str, ensure_ascii=False))


def setup_logging(level: int = logging.INFO) -> None:
    """Idempotent: one JSON handler on the root logger."""
    root = logging.getLogger()
    if any(getattr(h, "_sarthi", False) for h in root.handlers):
        return
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    h._sarthi = True
    root.addHandler(h)
    root.setLevel(level)


async def send_json(send, status: int, body: dict, headers: list | None = None) -> None:
    data = json.dumps(body).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(data)).encode()),
                            *(headers or [])]})
    await send({"type": "http.response.body", "body": data})


class RequestLog:
    def __init__(self, app):
        self.app = app
        self.log = logging.getLogger("sarthi.http")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        rid = uuid.uuid4().hex[:12]
        scope.setdefault("state", {})["request_id"] = rid
        t0, status = time.perf_counter(), [500]

        async def _send(msg):
            if msg["type"] == "http.response.start":
                status[0] = msg["status"]
                msg["headers"] = [*msg.get("headers", []), (b"x-request-id", rid.encode())]
            await send(msg)

        try:
            await self.app(scope, receive, _send)
        finally:
            self.log.info("request", extra={"method": scope["method"], "path": scope["path"], "status": status[0],
                                            "ms": round((time.perf_counter() - t0) * 1000, 1), "request_id": rid})


class BodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        from app.errors import envelope
        limit = get_settings().max_body_bytes
        too_big = envelope("request_too_large", 413, {"max_bytes": limit})
        length = dict(scope["headers"]).get(b"content-length")
        if length is not None:
            try:
                n = int(length)
            except ValueError:
                n = limit + 1
            if n > limit:
                return await send_json(send, 413, too_big)
            return await self.app(scope, receive, send)
        body, more = b"", True                           # no length given (chunked): read up to the limit first
        while more:
            msg = await receive()
            if msg["type"] == "http.disconnect":
                return
            body += msg.get("body", b"")
            more = msg.get("more_body", False)
            if len(body) > limit:
                return await send_json(send, 413, too_big)
        replayed = False

        async def _receive():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, _receive, send)


class DevGate:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        p = scope.get("path", "")
        if scope["type"] == "http" and (p == "/api/dev" or p.startswith("/api/dev/")) and not get_settings().dev_mode:
            from app.errors import envelope
            return await send_json(send, 404, envelope("not_found", 404))
        await self.app(scope, receive, send)

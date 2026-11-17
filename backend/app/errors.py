"""One JSON error shape for every 4xx and 5xx (DEC-90):

    {"error": {"code": "<machine code>", "message": "<short English text>", "details": {...}}}

`code` is what clients branch on (the codes the endpoints already raise are kept). `details` holds the other keys an
endpoint put next to its code, or the invalid fields of a 422 (location, message and type only: the submitted values
are never echoed, they may hold a phone). A 500 never shows internals; the request id in the log finds it.
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("sarthi.errors")

MESSAGES = {
    "not_found": "Not found.",
    "method_not_allowed": "This method is not allowed here.",
    "invalid_input": "Some of the input is not valid.",
    "request_too_large": "The request is too large.",
    "rate_limited": "Too many requests. Please wait and try again.",
    "internal_error": "Something went wrong on our side.",
    "not_logged_in": "Please log in.",
    "invalid_token": "Your session is not valid. Please log in again.",
    "token_expired": "Your session has expired. Please log in again.",
    "consent_required": "Please give consent before using this feature.",
    "shop_not_found": "Shop not found.",
    "model_not_ready": "The forecast model is not ready. An administrator must run `make train`.",
}
BY_STATUS = {400: "bad_request", 401: "not_logged_in", 403: "forbidden", 404: "not_found",
             405: "method_not_allowed", 409: "conflict", 413: "request_too_large", 422: "invalid_input",
             429: "rate_limited", 500: "internal_error", 503: "not_ready"}
GENERIC = {400: "Bad request.", 401: "Please log in.", 403: "Not allowed.", 404: "Not found.",
           409: "This conflicts with the data already saved.", 422: "Some of the input is not valid.",
           429: "Too many requests. Please wait and try again.", 503: "This service is not ready yet."}


def envelope(code: str, status: int, details: dict | None = None) -> dict:
    msg = MESSAGES.get(code) or GENERIC.get(status) or ("Something went wrong." if status >= 500 else "Request failed.")
    return {"error": {"code": code, "message": msg, "details": details or {}}}


async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    d = exc.detail
    if isinstance(d, dict) and "code" in d:
        code, details = d["code"], {k: v for k, v in d.items() if k != "code"}
    else:                                                # framework errors ("Not Found", "Method Not Allowed")
        code, details = BY_STATUS.get(exc.status_code, f"http_{exc.status_code}"), {}
    return JSONResponse(envelope(code, exc.status_code, details), status_code=exc.status_code,
                        headers=getattr(exc, "headers", None))


async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
    fields = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")} for e in exc.errors()]
    return JSONResponse(envelope("invalid_input", 422, {"fields": fields}), status_code=422)


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled error", exc_info=exc, extra={"path": request.url.path,
                                                      "request_id": request.scope.get("state", {}).get("request_id")})
    return JSONResponse(envelope("internal_error", 500), status_code=500)


def install(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _http)
    app.add_exception_handler(RequestValidationError, _validation)
    app.add_exception_handler(Exception, _unhandled)

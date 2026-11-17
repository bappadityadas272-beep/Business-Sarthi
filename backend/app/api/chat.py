"""`POST /api/chat` (C-07). The whole answer is made and checked by the guard first; only approved text (or the
template) is streamed, as SSE events meta -> delta* -> done (DEC-73, DEC-79)."""
import json
import re
from collections.abc import Iterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.deps import ConsentedUser, Db, _own_shop
from app.services import chat as chat_service

router = APIRouter(tags=["chat"])
WORDS_PER_CHUNK = 4


class ChatIn(BaseModel):
    shop_id: int
    message: str = Field(min_length=1, max_length=500)


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def chunks(text: str, n: int = WORDS_PER_CHUNK) -> Iterator[str]:
    words = re.findall(r"\S+\s*", text)
    for i in range(0, len(words), n):
        yield "".join(words[i:i + n])


@router.post("/chat", response_class=StreamingResponse,
             responses={200: {"content": {"text/event-stream": {}}, "description": "SSE: meta, delta..., done"}})
def chat(body: ChatIn, user: ConsentedUser, db: Db) -> StreamingResponse:
    """Ask a question about your own shop. Needs login and `shop_data` consent; 404 if the shop is not yours."""
    shop = _own_shop(db, user, body.shop_id)
    turn = chat_service.answer(db, user.id, shop, body.message.strip())

    def events() -> Iterator[str]:
        yield sse("meta", {"language": turn.language, "intent": turn.intent})
        for part in chunks(turn.text):
            yield sse("delta", {"text": part})
        yield sse("done", {"message_id": turn.message_id, "guard": turn.guard, "sources": turn.sources})

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

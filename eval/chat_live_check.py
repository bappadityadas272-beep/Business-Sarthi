"""C-07 live check: demo script step 7 against the provider named in .env (LLM_PROVIDER, LLM_API_KEY).

Run from backend/:  python ../eval/chat_live_check.py

- Uses a throwaway SQLite file with the two SYNTHETIC demo shops (needs `make synth` and `make train`); the real
  database is not touched.
- Prints the provider and model only; the key is never printed or logged (DEC-75).
- Each question goes through the real chat service: route -> tools -> LLM -> guard. For each it prints the language,
  intent, guard outcome and failure types, and the text the owner would see.
- Exit code 0 only if every LLM question passed the guard (template-only intents count as fine).
This is a smoke check of the live provider, not the C-08 evaluation (that set is written by the team).
"""
import sys
import tempfile
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from app import seed as sd
from app.config import get_settings
from app.db import Base, make_engine
from app.llm import client as llm
from app.models import Shop, User
from app.services import chat, clock, consent

DEMO_PHONE = "+919000000001"          # Ramesh Kirana (synthetic)
QUESTIONS = [
    "Is mahine ka profit kitna hai?",
    "इस महीने का मुनाफा कितना है?",
    "What is my profit this month?",
    "Mujhe kaunsi scheme milegi?",
    "Pichhle mahine ki bikri kitni thi?",
    "Kaunsa maal mangwana chahiye?",
    "Koi alert hai kya?",
]


def main() -> int:
    s = get_settings()
    if s.llm_provider == "stub":
        print("LLM_PROVIDER is 'stub' (or not set): nothing live to check. Set LLM_PROVIDER and LLM_API_KEY in .env.")
        return 2
    client = llm.get_client(s)
    fb = getattr(getattr(client, "fallback", None), "model", None) or "-"
    print(f"provider={s.llm_provider} model={getattr(client, 'model', '?')} fallback={fb} key_set={bool(s.llm_api_key)}")
    with tempfile.TemporaryDirectory() as tmp:
        engine = make_engine(f"sqlite:///{(Path(tmp) / 'live.db').as_posix()}")
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        all_ok = True
        with session() as db:
            sd.seed(db, clock.today())
            user = db.query(User).filter(User.phone == DEMO_PHONE).one()
            consent.give(db, user.id, consent.HOSTED_LLM)         # fictional owner; the live provider is what is checked
            shop = db.query(Shop).filter(Shop.user_id == user.id).one()
            for q in QUESTIONS:
                turn = chat.answer(db, user.id, shop, q, client=client, cache=llm.AnswerCache())
                all_ok &= turn.guard in ("passed", "template")     # failed or llm_unavailable = not ok
                print(f"\nQ: {q}\n   language={turn.language} intent={turn.intent} guard={turn.guard}"
                      f" failures={','.join(turn.failures) or '-'}\n   A: {turn.text}")
        engine.dispose()
    print("\nRESULT:", "all LLM answers passed the guard" if all_ok
          else "some answers were replaced by the template (guard failed or provider unavailable)")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())

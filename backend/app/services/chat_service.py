"""Saved AI conversations and the cards rendered alongside answers.

The Copilot answers in prose. Some answers also carry something the user can
look at or act on -- an order to confirm, a backtest curve, a screen's
results. Those are built here from the tools the answer actually called, so
a card can never show data the answer was not grounded in.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ChatMessage, ChatThread, User
from app.services import copilot_service, ideas_service

HISTORY_TURNS = 10


def list_threads(db: Session, user: User, limit: int = 100) -> list[dict]:
    rows = db.scalars(select(ChatThread).where(ChatThread.user_id == user.id)
                      .order_by(ChatThread.updated_at.desc(), ChatThread.id.desc()).limit(limit))
    return [thread_dict(t) for t in rows]


def thread_dict(t: ChatThread, with_messages: bool = False) -> dict:
    out = {"id": t.id, "title": t.title, "context": t.context,
           "created_at": t.created_at.isoformat() if t.created_at else None,
           "updated_at": t.updated_at.isoformat() if t.updated_at else None}
    if with_messages:
        out["messages"] = [message_dict(m) for m in t.messages]
    return out


def message_dict(m: ChatMessage) -> dict:
    return {"id": m.id, "role": m.role, "content": m.content, "cards": m.cards or [],
            "meta": m.meta or {}, "created_at": m.created_at.isoformat() if m.created_at else None}


def get_thread(db: Session, user: User, thread_id: int) -> ChatThread | None:
    return db.scalar(select(ChatThread).where(ChatThread.id == thread_id,
                                              ChatThread.user_id == user.id))


def create_thread(db: Session, user: User, title: str | None = None,
                  context: dict | None = None) -> ChatThread:
    thread = ChatThread(user_id=user.id, title=(title or "New chat")[:120], context=context)
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


def delete_thread(db: Session, user: User, thread_id: int) -> bool:
    thread = get_thread(db, user, thread_id)
    if thread is None:
        return False
    db.delete(thread)
    db.commit()
    return True


def _title_from(question: str) -> str:
    text = " ".join(question.split())
    return text if len(text) <= 60 else text[:57].rstrip() + "…"


def _cards(tool_calls: list[dict], tool_outputs: list[dict]) -> list[dict]:
    cards = []
    for call, output in zip(tool_calls, tool_outputs):
        if output.get("available") is False or "error" in output:
            continue
        tool, args = call["tool"], call.get("arguments") or {}
        if tool == "propose_paper_order":
            cards.append({"type": "order_proposal", **output})
        elif tool == "propose_autopilot":
            cards.append({"type": "autopilot_proposal", **output})
        elif tool == "run_backtest":
            # The model saw the backtest without its curve; the card gets it.
            full = ideas_service.backtest(args.get("strategy_id", "ema-crossover"), args.get("symbol"))
            if full.get("available"):
                cards.append({"type": "backtest", **full})
        elif tool == "run_screener":
            cards.append({"type": "screener", **output})
        elif tool == "get_ideas":
            cards.append({"type": "ideas", **output})
        elif tool == "get_option_chain_summary":
            cards.append({"type": "option_summary", **output})
        elif tool == "get_quote":
            cards.append({"type": "quote", **output})
        elif tool == "get_market_movers":
            cards.append({"type": "movers", **output})
        elif tool == "propose_swing_plan":
            cards.append({"type": "swing_plan", **output})
        elif tool == "get_model_signals":
            cards.append({"type": "model_signals", **output})
        elif tool == "plan_allocation":
            cards.append({"type": "allocation", **output})
        elif tool == "review_my_portfolio":
            cards.append({"type": "portfolio_review", **output})
        elif tool == "get_autopilot_status":
            cards.append({"type": "autopilot_status", **output})
    return cards


def send(db: Session, user: User, thread: ChatThread, content: str,
         context: dict | None = None) -> dict:
    """Store the user's message, answer it, store the answer."""
    history = [{"role": m.role, "content": m.content} for m in thread.messages[-HISTORY_TURNS:]]
    context = context or thread.context

    from app.services import account_service

    remembered = account_service.remember_from_chat(db, user, content)
    memory = account_service.memory_context(db, user)

    db.add(ChatMessage(thread_id=thread.id, role="user", content=content))
    if not thread.messages and thread.title == "New chat":
        thread.title = _title_from(content)
    db.commit()

    result = copilot_service.answer(db, user, content, history=history, context=context, memory=memory)
    reply = ChatMessage(
        thread_id=thread.id, role="assistant", content=result["answer"],
        cards=_cards(result.get("tool_calls", []), result.get("tool_outputs", [])),
        meta={"model": result["model"], "used_fallback": result["used_fallback"],
              "fallback_reason": result["fallback_reason"], "tools_called": result["tools_called"],
              "grounding": result["grounding"], "latency_ms": result["latency_ms"],
              "disclaimer": result["disclaimer"], "remembered": remembered},
    )
    db.add(reply)
    # Touch the thread so it rises to the top of the sidebar.
    thread.updated_at = func.now()
    db.commit()
    db.refresh(reply)
    db.refresh(thread)
    return {"thread": thread_dict(thread), "message": message_dict(reply)}

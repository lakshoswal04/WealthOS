"""Trading preferences, notification choices, AI memory and broker credentials."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Memory, User, UserSettings

DEFAULT_PREFERENCES = {
    "default_symbol": "NIFTY",
    "default_quantity": 1,          # shares per equity order
    "default_lots": 1,              # lots per option order
    "default_product": "delivery",
    "default_order_type": "market",
    "one_tap_default": False,
    "chart_interval": "1m",
    # Always true: the assistant can only propose. Shown, not editable.
    "confirm_ai_orders": True,
}

DEFAULT_NOTIFICATIONS = {
    "order_fills": True,
    "price_alerts": True,
    "portfolio_alerts": True,
}

PREFERENCE_CHOICES = {
    "default_product": {"delivery", "intraday"},
    "default_order_type": {"market", "limit"},
    "chart_interval": {"1m", "5m", "15m", "1h", "1D"},
}

MEMORY_SECTIONS = {
    "about": "About you",
    "answers": "How you like answers",
    "preferences": "Preferences",
    "markets": "Markets",
    "risk": "Risk and goals",
    "avoid": "Things to avoid",
}

class AccountError(ValueError):
    pass


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

def settings_row(db: Session, user: User) -> UserSettings:
    row = db.scalar(select(UserSettings).where(UserSettings.user_id == user.id))
    if row is None:
        row = UserSettings(user_id=user.id, preferences={}, notifications={}, memory_paused=False)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def settings_dict(row: UserSettings) -> dict:
    return {
        "preferences": {**DEFAULT_PREFERENCES, **(row.preferences or {}), "confirm_ai_orders": True},
        "notifications": {**DEFAULT_NOTIFICATIONS, **(row.notifications or {})},
        "memory_paused": row.memory_paused,
        "delivery_note": "Notifications appear inside WealthOS while it is open. Email and push delivery are not set up.",
    }


def update_settings(db: Session, user: User, preferences: dict | None, notifications: dict | None) -> dict:
    row = settings_row(db, user)
    if preferences:
        clean = dict(row.preferences or {})
        for key, value in preferences.items():
            if key not in DEFAULT_PREFERENCES or key == "confirm_ai_orders":
                continue
            default = DEFAULT_PREFERENCES[key]
            if isinstance(default, bool):
                if not isinstance(value, bool):
                    raise AccountError(f"{key} must be true or false.")
            elif isinstance(default, int):
                if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 10_000:
                    raise AccountError(f"{key} must be a whole number from 1 to 10,000.")
            elif key in PREFERENCE_CHOICES and value not in PREFERENCE_CHOICES[key]:
                raise AccountError(f"{key} must be one of {sorted(PREFERENCE_CHOICES[key])}.")
            elif key == "default_symbol":
                from app.services import live_market_service as live
                if not isinstance(value, str) or live.instrument_info(value) is None:
                    raise AccountError(f"{value!r} is not in the tradable universe.")
                value = value.upper()
            clean[key] = value
        row.preferences = clean
    if notifications:
        clean = dict(row.notifications or {})
        for key, value in notifications.items():
            if key in DEFAULT_NOTIFICATIONS:
                if not isinstance(value, bool):
                    raise AccountError(f"{key} must be true or false.")
                clean[key] = value
        row.notifications = clean
    db.commit()
    db.refresh(row)
    return settings_dict(row)


# --------------------------------------------------------------------------
# Memory
# --------------------------------------------------------------------------

def memories(db: Session, user: User) -> list[Memory]:
    return list(db.scalars(select(Memory).where(Memory.user_id == user.id).order_by(Memory.id)))


def memory_dict(m: Memory) -> dict:
    return {"id": m.id, "section": m.section, "text": m.text, "source": m.source,
            "created_at": m.created_at.isoformat() if m.created_at else None}


def add_memory(db: Session, user: User, section: str, text: str, source: str = "manual") -> Memory:
    if section not in MEMORY_SECTIONS:
        raise AccountError(f"Section must be one of {', '.join(MEMORY_SECTIONS)}.")
    text = " ".join((text or "").split())
    if not 2 <= len(text) <= 280:
        raise AccountError("A memory is 2 to 280 characters.")
    existing = {m.text.lower() for m in memories(db, user)}
    if text.lower() in existing:
        raise AccountError("That is already remembered.")
    m = Memory(user_id=user.id, section=section, text=text, source=source)
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


# Phrases that state something durable about the user. Deliberately narrow:
# a memory that records "I'm looking at NIFTY" as a fact about them is worse
# than one that misses something.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("about", re.compile(r"\bi(?: am|'m) an? ([a-z][\w\s,-]{2,60}?(?:trader|investor|beginner|student|professional|analyst))\b", re.I)),
    ("risk", re.compile(r"\bmy risk (?:appetite|tolerance|profile) is ([\w\s-]{3,40})", re.I)),
    ("risk", re.compile(r"\bmy goal is (?:to )?([\w\s,₹-]{4,100})", re.I)),
    ("preferences", re.compile(r"\bi prefer ([\w\s,&-]{3,100})", re.I)),
    ("markets", re.compile(r"\bi (?:mostly |usually |mainly |only )?trade ([\w\s,&-]{3,80})", re.I)),
    ("avoid", re.compile(r"\bi (?:don't|do not|never) (?:want to |like to |)(?:trade|buy|hold|use) ([\w\s,&-]{3,80})", re.I)),
    ("answers", re.compile(r"\b(?:keep (?:your )?(?:answers|responses|it) ([\w\s-]{3,40})|answer in ([\w\s-]{3,30})|be (brief|concise|detailed|short))", re.I)),
]

_LEADS = {
    "about": "Is {}", "risk": "{}", "preferences": "Prefers {}", "markets": "Trades {}",
    "avoid": "Avoids {}", "answers": "Wants answers {}",
}


def extract_memories(message: str) -> list[tuple[str, str]]:
    """(section, text) pairs stated in a chat message."""
    found = []
    for sentence in re.split(r"(?<=[.!?])\s+", message or ""):
        for section, pattern in _PATTERNS:
            m = pattern.search(sentence)
            if not m:
                continue
            value = next(g for g in m.groups() if g).strip(" ,.-")
            if section == "risk" and "risk" in m.group(0).lower():
                text = f"Risk tolerance: {value}"
            elif section == "risk":
                text = f"Goal: {value}"
            elif section == "about":
                text = f"Is a {value}" if not value.lower().startswith(("a ", "an ")) else f"Is {value}"
            else:
                text = _LEADS[section].format(value)
            found.append((section, text[0].upper() + text[1:]))
    return found


def remember_from_chat(db: Session, user: User, message: str) -> list[dict]:
    if settings_row(db, user).memory_paused:
        return []
    saved = []
    for section, text in extract_memories(message):
        try:
            saved.append(memory_dict(add_memory(db, user, section, text, source="chat")))
        except AccountError:
            continue
    return saved


def memory_context(db: Session, user: User) -> str | None:
    """What the assistant is told about this user, or None when paused or empty."""
    if settings_row(db, user).memory_paused:
        return None
    items = memories(db, user)
    if not items:
        return None
    lines = [f"- {MEMORY_SECTIONS[m.section]}: {m.text}" for m in items[-40:]]
    return "What the user has told you about themselves (use it to tailor answers, never as a source of figures):\n" + "\n".join(lines)

"""User-confirmed, local JARVIS memory. Never populated from model outputs or webpages.

No dependencies beyond the Python standard library. The DB is deliberately separate
from the Agents SDK's rolling conversation history.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import secrets
import sqlite3

DB_PATH = Path(os.environ.get("JARVIS_VERIFIED_MEMORY_DB", Path(__file__).resolve().parent / "jarvis_verified_memory.db"))
MAX_FACTS = 200
MAX_FACT_LENGTH = 320
_ID_PATTERN = re.compile(r"^[a-f0-9]{8}$")
_STOPWORDS = frozenset("the and for are from this that with what about does have should please jarvis remember recall tell know which when where your mine me my you i a an to of in on do is it at".split())


@contextmanager
def _database():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(DB_PATH), timeout=15)
    if os.name == "posix":
        os.chmod(DB_PATH, 0o600)
    try:
        connection.execute("""CREATE TABLE IF NOT EXISTS confirmed_memories (
            id TEXT PRIMARY KEY,
            fact TEXT NOT NULL,
            added_at TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'user_approved'
        )""")
        connection.commit()
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _valid_fact(fact: str) -> str:
    if not isinstance(fact, str):
        raise ValueError("Memory must be text.")
    cleaned = " ".join(fact.strip().split())
    if not 4 <= len(cleaned) <= MAX_FACT_LENGTH:
        raise ValueError(f"Memory must be 4-{MAX_FACT_LENGTH} characters long.")
    if "\x00" in cleaned:
        raise ValueError("Invalid memory text.")
    return cleaned


def add_confirmed_fact(fact: str) -> dict:
    """Add only after user approval. Repeated identical facts are de-duplicated."""
    fact = _valid_fact(fact)
    with _database() as db:
        duplicate = db.execute(
            "SELECT id, fact, added_at FROM confirmed_memories WHERE fact = ? COLLATE NOCASE",
            (fact,),
        ).fetchone()
        if duplicate:
            return {"id": duplicate[0], "fact": duplicate[1], "added_at": duplicate[2], "duplicate": True}
        count = db.execute("SELECT COUNT(*) FROM confirmed_memories").fetchone()[0]
        if count >= MAX_FACTS:
            raise ValueError("Memory is full. Remove an older fact before adding another.")
        identifier = secrets.token_hex(4)
        while db.execute("SELECT 1 FROM confirmed_memories WHERE id=?", (identifier,)).fetchone():
            identifier = secrets.token_hex(4)
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        db.execute("INSERT INTO confirmed_memories(id, fact, added_at) VALUES (?, ?, ?)",
                   (identifier, fact, timestamp))
    return {"id": identifier, "fact": fact, "added_at": timestamp, "duplicate": False}


def list_confirmed_facts(limit: int = 50) -> list[dict]:
    limit = max(1, min(int(limit), MAX_FACTS))
    with _database() as db:
        rows = db.execute(
            "SELECT id, fact, added_at FROM confirmed_memories ORDER BY added_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{"id": rid, "fact": fact, "added_at": timestamp} for rid, fact, timestamp in rows]


def remove_confirmed_fact(identifier: str) -> bool:
    """Delete the active-memory record. Chat/action logs are separate and unaffected."""
    if not isinstance(identifier, str) or not _ID_PATTERN.fullmatch(identifier):
        raise ValueError("Memory ID must contain exactly eight hexadecimal characters.")
    with _database() as db:
        cursor = db.execute("DELETE FROM confirmed_memories WHERE id=?", (identifier,))
        return cursor.rowcount == 1


def relevant_confirmed_facts(topic: str, limit: int = 5) -> list[dict]:
    """Simple offline keyword ranking, not an LLM truth-verification process."""
    limit = max(1, min(int(limit), 12))
    words = {w for w in re.findall(r"[a-z0-9]+", (topic or "").lower()) if len(w) > 2 and w not in _STOPWORDS}
    if not words:
        return list_confirmed_facts(limit)
    candidates = list_confirmed_facts(MAX_FACTS)
    results = []
    for item in candidates:
        fact_words = set(re.findall(r"[a-z0-9]+", item["fact"].lower()))
        score = len(words & fact_words)
        if score:
            results.append((score, item))
    return [item for _, item in sorted(results, key=lambda item: item[0], reverse=True)[:limit]]


def format_memory_list(limit: int = 30) -> str:
    facts = list_confirmed_facts(limit)
    if not facts:
        return "I have no user-approved long-term memories yet. To save one, say: Jarvis, remember that I prefer FPGA projects."
    text = ["User-approved long-term memories (separate from chat history):"]
    for fact in facts:
        text.append(f"- [{fact['id']}] {fact['fact']}")
    text.append("To remove one, say: Jarvis, forget memory ID. This removes it from active memory, not historical chat or action logs.")
    return "\n".join(text)

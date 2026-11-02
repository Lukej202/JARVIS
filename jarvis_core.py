"""Shared local JARVIS brain for terminal and Windows-browser voice interfaces.

Uses the existing terminal SQLite memory and locally served Ollama; never calls
OpenAI's hosted API. Mutating/visual desktop tools queue explicit approvals.
"""

import asyncio
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import platform
import secrets
import sqlite3
import subprocess
from threading import RLock
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from agents import (
    Agent, AsyncOpenAI, OpenAIChatCompletionsModel, Runner,
    SQLiteSession, function_tool, set_tracing_disabled,
)

ROOT = Path(__file__).resolve().parent
WORKSPACE = (ROOT / "workspace").resolve()
WORKSPACE.mkdir(parents=True, exist_ok=True)
MEMORY_DB = ROOT / "jarvis_memory.db"   # Reuses the existing terminal chat history
ACTIONS_DB = ROOT / "jarvis_actions.db"
LOCK_FILE = ROOT / "jarvis_session.lock"
MODEL_NAME = os.getenv("JARVIS_MODEL", "qwen3:4b")
VISION_MODEL = os.getenv("JARVIS_VISION_MODEL", "gemma3:4b")
OLLAMA_API = "http://127.0.0.1:11434"

# Do not export prompts, screenshots, or tool results to OpenAI tracing.
set_tracing_disabled(True)
_client = AsyncOpenAI(
    base_url=f"{OLLAMA_API}/v1/",
    api_key="ollama",  # Local Ollama ignores this placeholder
    timeout=90.0,
    max_retries=0,
)
_session = SQLiteSession(
    os.getenv("JARVIS_SESSION_ID", "jarvis_main"),
    str(MEMORY_DB),
    session_settings={"limit": 40},
)
_local_lock = RLock()


@contextmanager
def _actions_connection():
    connection = sqlite3.connect(str(ACTIONS_DB), timeout=15)
    connection.execute("""CREATE TABLE IF NOT EXISTS actions (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        payload TEXT NOT NULL,
        summary TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at REAL NOT NULL,
        result TEXT
    )""")
    connection.commit()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


@contextmanager
def _conversation_lock():
    """Serialize one memory session across Flask threads and WSL processes."""
    with _local_lock:
        with LOCK_FILE.open("a+b") as lockfile:
            fcntl.flock(lockfile.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lockfile.fileno(), fcntl.LOCK_UN)


def _safe_path(name: str, *, allow_root: bool = False) -> Path:
    if not name or "\\" in name or "\x00" in name:
        raise ValueError("Use a relative path inside the JARVIS workspace.")
    path_input = Path(name)
    if path_input.is_absolute():
        raise ValueError("Absolute paths are not allowed.")
    path = (WORKSPACE / path_input).resolve()
    if not path.is_relative_to(WORKSPACE):
        raise ValueError("Access outside the JARVIS workspace is denied.")
    if path == WORKSPACE and not allow_root:
        raise ValueError("Specify a file or folder within the workspace.")
    return path


def _request_approval(kind: str, payload: dict, summary: str) -> str:
    """Queue an action: tool calls never block waiting for terminal input."""
    raw_payload = json.dumps(payload)
    with _actions_connection() as db:
        # Avoid multiple identical queued actions when the model retries a tool.
        existing = db.execute(
            "SELECT id FROM actions WHERE kind=? AND payload=? AND status='pending'",
            (kind, raw_payload),
        ).fetchone()
        if existing:
            action_id = existing[0]
        else:
            action_id = secrets.token_hex(6)
            db.execute(
                "INSERT INTO actions VALUES (?, ?, ?, ?, 'pending', ?, NULL)",
                (action_id, kind, raw_payload, summary, time.time()),
            )
    return (
        f"Approval required for {summary}. Action ID: {action_id}. "
        "Nothing has been changed yet. Ask the user to approve or deny "
        "this action using the browser approval panel or /approve ID in terminal."
    )


def pending_actions() -> list[dict]:
    with _actions_connection() as db:
        rows = db.execute(
            "SELECT id, kind, payload, summary FROM actions "
            "WHERE status='pending' ORDER BY created_at ASC"
        ).fetchall()
    results = []
    for action_id, kind, raw_payload, summary in rows:
        payload = json.loads(raw_payload)
        results.append({
            "id": action_id,
            "kind": kind,
            "summary": summary,
            "content": payload.get("content", payload.get("text", "")),
        })
    return results


def _record_outcome(summary: str, result: str) -> None:
    # Store actual execution results in the SAME conversation as voice and text.
    asyncio.run(_session.add_items([{
        "role": "assistant", "content": f"Action update: {summary}. Result: {result}"
    }]))


def _run_approved_action(kind: str, payload: dict) -> str:
    if kind in {"create_file", "write_file"}:
        path = _safe_path(payload["filename"])
        content = payload["content"]
        if len(content) > 30000:
            return "Refused: Content exceeds the 30,000-character limit."
        if not path.parent.is_dir():
            return "Could not write file: Parent directory does not exist."
        if kind == "create_file":
            with path.open("x", encoding="utf-8") as fp:
                fp.write(content)
        else:
            with path.open("w", encoding="utf-8") as fp:
                fp.write(content)
        return f"Saved {path.relative_to(WORKSPACE)} in the WSL workspace."

    if kind == "create_folder":
        path = _safe_path(payload["name"])
        path.mkdir(parents=False, exist_ok=False)
        return f"Created folder {path.relative_to(WORKSPACE)}."

    if kind == "type_in_notepad":
        # Existing, previously-tested Windows clipboard + keyboard helper.
        from windows_input_test import paste_into_notepad
        paste_into_notepad(payload["text"])
        return "Paste command sent to Notepad. Verify the visible result; not saved."

    if kind == "inspect_screen":
        # Local-only screen analysis; capture happens AFTER explicit approval.
        from vision_test import capture_screen
        base64_image = capture_screen()
        body = json.dumps({
            "model": VISION_MODEL,
            "messages": [{
                "role": "user",
                "content": (payload["question"] +
                            " Describe only what is visible; do not invent unreadable text."),
                "images": [base64_image],
            }],
            "stream": False,
        }).encode("utf-8")
        req = Request(
            f"{OLLAMA_API}/api/chat", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urlopen(req, timeout=180) as res:
                answer = json.load(res)
        except HTTPError as err:
            if err.code == 404:
                return (f"Local vision model '{VISION_MODEL}' isn't installed. "
                        f"Run: ollama pull {VISION_MODEL}")
            raise
        return "Screen analysis: " + answer.get("message", {}).get("content", "No result.")

    raise ValueError("Unknown action: " + kind)


def decide_action(action_id: str, approved: bool) -> str:
    """Atomic one-time approval/denial; can be called from terminal or browser."""
    with _conversation_lock():
        with _actions_connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT kind, payload, summary, status FROM actions WHERE id=?",
                (action_id,),
            ).fetchone()
            if row is None:
                raise ValueError("Unknown approval ID.")
            kind, raw_payload, summary, status = row
            if status != "pending":
                raise ValueError(f"This action is already {status}.")
            db.execute("UPDATE actions SET status=? WHERE id=?",
                       ("executing" if approved else "denied", action_id))

        if not approved:
            message = f"Denied: {summary}. Nothing executed."
            with _actions_connection() as db:
                db.execute("UPDATE actions SET result=? WHERE id=?", (message, action_id))
            _record_outcome(summary, message)
            return message

        try:
            result = _run_approved_action(kind, json.loads(raw_payload))
            status = "completed"
        except (OSError, ValueError, ImportError, TimeoutError, URLError) as err:
            result = f"Action failed: {type(err).__name__}: {err}"
            status = "failed"
        except Exception as err:  # Don't leave approvals stuck in 'executing'.
            result = f"Action failed: {type(err).__name__}: {err}"
            status = "failed"
        with _actions_connection() as db:
            db.execute("UPDATE actions SET status=?, result=? WHERE id=?",
                       (status, result, action_id))
        _record_outcome(summary, result)
        return result


def _log_app_launch(label: str, result: str, success: bool) -> None:
    """Track actual application launch attempts (not proof the UI opened)."""
    try:
        with _actions_connection() as db:
            db.execute(
                "INSERT INTO actions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (secrets.token_hex(6), "launch_app", "{}",
                 f"Requested {label} launch", "completed" if success else "failed",
                 time.time(), result),
            )
    except sqlite3.Error:
        # App launching must not fail just because the activity log is unavailable.
        pass


@function_tool
def open_notepad() -> str:
    """Launch Windows Notepad from WSL."""
    try:
        subprocess.Popen(["notepad.exe"])
        _log_app_launch("Notepad", "Launch command submitted to Windows.", True)
        return "Requested Windows Notepad launch."
    except OSError as err:
        _log_app_launch("Notepad", str(err), False)
        return f"Notepad could not be opened: {err}"


@function_tool
def open_calculator() -> str:
    """Launch Windows Calculator from WSL."""
    try:
        subprocess.Popen(["calc.exe"])
        _log_app_launch("Calculator", "Launch command submitted to Windows.", True)
        return "Requested Windows Calculator launch."
    except OSError as err:
        _log_app_launch("Calculator", str(err), False)
        return f"Calculator could not be opened: {err}"


@function_tool
def open_vscode() -> str:
    """Launch Visual Studio Code on Windows."""
    try:
        subprocess.Popen(["code.exe"])
        _log_app_launch("VS Code", "Launch command submitted to Windows.", True)
        return "Requested VS Code launch."
    except OSError as err:
        _log_app_launch("VS Code", str(err), False)
        return f"VS Code could not be opened: {err}"


@function_tool
def list_directory(directory: str = ".") -> str:
    """List up to 100 names inside a folder in the WSL JARVIS workspace."""
    try:
        path = _safe_path(directory, allow_root=True)
        if not path.is_dir():
            return "That is not a directory."
        return "\n".join(sorted(p.name for p in path.iterdir())[:100]) or "Folder is empty."
    except (ValueError, OSError) as err:
        return f"Could not list directory: {err}"


@function_tool
def read_file(filename: str) -> str:
    """Read a UTF-8 workspace text file no larger than 100 KB."""
    try:
        path = _safe_path(filename)
        if path.stat().st_size > 100000:
            return "File exceeds 100 KB reading limit."
        return path.read_text(encoding="utf-8")
    except (ValueError, OSError, UnicodeError) as err:
        return f"Could not read file: {err}"


@function_tool
def search_files(query: str) -> str:
    """Find filenames matching a substring inside the JARVIS workspace."""
    if not query.strip():
        return "Provide a filename search term."
    matches = [str(path.relative_to(WORKSPACE)) for path in WORKSPACE.rglob("*")
               if path.is_file() and query.lower() in path.name.lower()]
    return "\n".join(matches[:50]) or "No matching files."


@function_tool
def get_system_info() -> str:
    """Get basic information about the Ubuntu WSL operating system."""
    return f"OS: {platform.system()}, release: {platform.release()}"


@function_tool
def create_folder(name: str) -> str:
    """Request user approval to create a folder inside the WSL JARVIS workspace."""
    try:
        path = _safe_path(name)
        if path.exists():
            return "Folder already exists."
        return _request_approval("create_folder", {"name": name},
                                 f"create folder '{name}'")
    except ValueError as err:
        return f"Rejected: {err}"


@function_tool
def create_file(filename: str, content: str) -> str:
    """Request approval to create a new UTF-8 text file in the WSL workspace."""
    try:
        path = _safe_path(filename)
        if path.exists():
            return "File already exists; use write_file to request overwrite approval."
        if len(content) > 30000:
            return "Content exceeds 30,000 characters."
        return _request_approval("create_file", {"filename": filename, "content": content},
                                 f"create file '{filename}'")
    except ValueError as err:
        return f"Rejected: {err}"


@function_tool
def write_file(filename: str, content: str) -> str:
    """Request approval to write/overwrite a UTF-8 text file in the WSL workspace."""
    try:
        _safe_path(filename)
        if len(content) > 30000:
            return "Content exceeds 30,000 characters."
        return _request_approval("write_file", {"filename": filename, "content": content},
                                 f"write or overwrite file '{filename}'")
    except ValueError as err:
        return f"Rejected: {err}"


@function_tool
def type_in_notepad(text: str) -> str:
    """Request approval to paste text into a Windows Notepad window. Not saved."""
    if not text or len(text) > 30000:
        return "Provide between 1 and 30,000 characters."
    return _request_approval("type_in_notepad", {"text": text},
                             f"paste {len(text)} characters into Notepad")


@function_tool
def inspect_screen(question: str) -> str:
    """Request permission to capture the Windows screen and analyze it LOCALLY using Ollama vision."""
    if not question.strip():
        return "Please specify what to inspect on the screen."
    return _request_approval("inspect_screen", {"question": question[:1000]},
                             "capture the primary Windows screen for local AI analysis")


jarvis = Agent(
    name="JARVIS",
    model=OpenAIChatCompletionsModel(model=MODEL_NAME, openai_client=_client),
    instructions=(
        "You are JARVIS, a friendly, concise personal desktop assistant. "
        "Use only registered tools, and never claim an action succeeded unless confirmed. "
        "Both speech and typed chat share the same memory and tools. "
        "File tools operate only within the WSL JARVIS workspace, not Windows Documents. "
        "For file operations give paths relative to workspace, NOT prefixed with workspace/. "
        "File modifications, Notepad typing and screen capture require user approval: "
        "these tools only QUEUE actions. Tell the user to approve in the browser panel "
        "or with /approve ID in the terminal. Never claim an unapproved action ran. "
        "Do not repeat an action after it is queued; wait for approval. "
        "Screen vision uses a separate local Ollama vision model after approval. "
        "No deletion, arbitrary shell execution, email sending, or unrestricted mouse control."
    ),
    tools=[
        open_notepad, open_calculator, open_vscode,
        list_directory, read_file, search_files, get_system_info,
        create_folder, create_file, write_file, type_in_notepad, inspect_screen,
    ],
)


def run_turn(message: str) -> str:
    """One Ollama agent and one SQLite memory for ALL interfaces."""
    if not isinstance(message, str) or not message.strip():
        raise ValueError("Enter a message.")
    if len(message) > 4000:
        raise ValueError("Messages must be under 4,000 characters.")
    with _conversation_lock():
        result = Runner.run_sync(jarvis, message.strip(), session=_session, max_turns=7)
        return str(result.final_output or "I couldn't complete that request.")


def recent_messages(limit: int = 36) -> list[dict]:
    """Return only user/assistant readable text from the shared SQLite session.

    Does not include function-call arguments or raw tool outputs.
    """
    limit = max(1, min(int(limit), 60))
    with _conversation_lock():
        items = asyncio.run(_session.get_items(limit=limit))
    messages = []
    for item in items:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        if role not in ("user", "assistant"):
            continue
        content = item.get("content")
        if isinstance(content, str):
            body = content
        elif isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") in (
                    "input_text", "output_text", "text"
                ):
                    value = part.get("text")
                    if isinstance(value, str):
                        parts.append(value)
            body = "\n".join(parts)
        else:
            continue
        body = body.strip()
        if body:
            messages.append({"role": role, "text": body[:8000]})
    return messages[-limit:]


def recent_actions(limit: int = 12) -> list[dict]:
    """Summaries of actual queued/executed actions, excluding private payloads."""
    limit = max(1, min(int(limit), 30))
    with _actions_connection() as db:
        rows = db.execute(
            "SELECT id, kind, summary, status, created_at, result "
            "FROM actions ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [
        {"id": aid, "kind": kind, "summary": summary, "status": status,
         "created_at": created, "result": (result or "")[:600]}
        for aid, kind, summary, status, created, result in rows
    ]

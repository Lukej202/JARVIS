"""Local authenticated Chrome extension research bridge, shared across WSL processes.

SQLite holds only research jobs and extension heartbeat. The pairing secret stays
in .jarvis_extension_key and is never included in job results or model prompts.
Compatible with the Flask /extension endpoints and jarvis_core enqueue_research.
"""
from __future__ import annotations

from pathlib import Path
import hmac
import json
import os
import secrets
import sqlite3
import time
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
KEY_FILE = ROOT / '.jarvis_extension_key'
DB_FILE = ROOT / '.jarvis_extension_jobs.db'
MAX_RESULT_BYTES = 45_000
MAX_PAGES = 3


def _connect() -> sqlite3.Connection:
    db = sqlite3.connect(str(DB_FILE), timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=15000')
    db.execute('''CREATE TABLE IF NOT EXISTS bridge_status
                  (name TEXT PRIMARY KEY, last_seen REAL NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS research_jobs
                  (id TEXT PRIMARY KEY, query TEXT NOT NULL, pages INTEGER NOT NULL,
                   state TEXT NOT NULL, claimed_at REAL NOT NULL DEFAULT 0,
                   cancelled INTEGER NOT NULL DEFAULT 0, report TEXT, error TEXT NOT NULL DEFAULT '',
                   created_at REAL NOT NULL)''')
    db.commit()
    if os.name == 'posix':
        os.chmod(DB_FILE, 0o600)
    return db


def pairing_key() -> str:
    """Persistent random local secret. Never include in repo or model prompts."""
    if KEY_FILE.is_file():
        return KEY_FILE.read_text(encoding='ascii').strip()
    new_key = secrets.token_urlsafe(32)
    try:
        fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return KEY_FILE.read_text(encoding='ascii').strip()
    with os.fdopen(fd, 'w', encoding='ascii') as fp:
        fp.write(new_key + '\n')
    return new_key


def verify_key(value: str) -> bool:
    return isinstance(value, str) and hmac.compare_digest(value, pairing_key())


def heartbeat() -> None:
    with _connect() as db:
        db.execute('''INSERT INTO bridge_status(name,last_seen) VALUES('extension',?)
                      ON CONFLICT(name) DO UPDATE SET last_seen=excluded.last_seen''',
                   (time.time(),))
        db.commit()


def connected() -> bool:
    with _connect() as db:
        row = db.execute("SELECT last_seen FROM bridge_status WHERE name='extension'").fetchone()
    return row is not None and 0 <= time.time() - float(row['last_seen']) < 65


def enqueue_research(query: str, *, max_pages: int = 3,
                     timeout: float = 180) -> dict[str, Any]:
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 220:
        raise ValueError('Research topic must have 2–220 characters.')
    if not isinstance(max_pages, int) or isinstance(max_pages, bool) or not 1 <= max_pages <= MAX_PAGES:
        raise ValueError('Requested page limit is invalid.')
    if not connected():
        raise RuntimeError('JARVIS Chrome extension is not connected. Open its popup and connect it to the local Flask server.')
    jid = secrets.token_hex(12)
    with _connect() as db:
        db.execute('''INSERT INTO research_jobs(id,query,pages,state,created_at)
                      VALUES(?,?,?,'pending',?)''',
                   (jid, query.strip(), max_pages, time.time()))
        db.commit()
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            with _connect() as db:
                row = db.execute('SELECT state,report,error FROM research_jobs WHERE id=?', (jid,)).fetchone()
            if row is None:
                raise RuntimeError('Research job disappeared from the shared queue.')
            if row['state'] == 'completed':
                if row['error']:
                    raise RuntimeError(str(row['error'])[:500])
                report = json.loads(row['report']) if row['report'] else None
                if not isinstance(report, dict):
                    raise RuntimeError('The extension did not return a research report.')
                return report
            time.sleep(0.35)
        raise TimeoutError('Chrome extension did not finish within 3 minutes. Check its popup and service-worker errors.')
    finally:
        with _connect() as db:
            db.execute('DELETE FROM research_jobs WHERE id=?', (jid,))
            db.commit()


def claim_next() -> dict[str, Any] | None:
    heartbeat()
    with _connect() as db:
        db.execute('BEGIN IMMEDIATE')
        # Pick one pending job, or an abandoned running job after 75 s.
        row = db.execute('''SELECT id,query,pages FROM research_jobs
                            WHERE cancelled=0 AND
                                (state='pending' OR (state='running' AND claimed_at<?))
                            ORDER BY created_at ASC LIMIT 1''', (time.time()-75,)).fetchone()
        if row is None:
            db.commit()
            return None
        db.execute("UPDATE research_jobs SET state='running',claimed_at=? WHERE id=?",
                   (time.time(), row['id']))
        db.commit()
        return {'id': row['id'], 'query': row['query'], 'pages': row['pages']}


def is_cancelled(job_id: str) -> bool:
    heartbeat()
    with _connect() as db:
        row = db.execute('SELECT cancelled,state FROM research_jobs WHERE id=?', (job_id,)).fetchone()
    return row is None or bool(row['cancelled']) or row['state'] == 'completed'


def request_stop() -> str:
    with _connect() as db:
        db.execute('BEGIN IMMEDIATE')
        rows = db.execute("SELECT id,query FROM research_jobs WHERE state!='completed'").fetchall()
        for row in rows:
            report = {'query': row['query'], 'pages': [], 'errors': [], 'stopped': True}
            db.execute('''UPDATE research_jobs SET cancelled=1,state='completed',report=?
                          WHERE id=?''', (json.dumps(report), row['id']))
        db.commit()
    return ('Stop requested for the current research task.' if rows
            else 'No research task is currently running.')


def receive_result(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict) or len(str(payload)) > MAX_RESULT_BYTES * 2:
        raise ValueError('Invalid or oversized extension result.')
    jid = payload.get('id')
    if not isinstance(jid, str):
        return False
    with _connect() as db:
        db.execute('BEGIN IMMEDIATE')
        job = db.execute('SELECT query,pages,state FROM research_jobs WHERE id=?', (jid,)).fetchone()
        if job is None or job['state'] == 'completed':
            db.commit()
            return False
        if payload.get('error'):
            error = str(payload['error'])[:500]
            report = None
        else:
            data = payload.get('report')
            if not isinstance(data, dict) or not isinstance(data.get('pages'), list):
                raise ValueError('Malformed extension report.')
            pages = []
            for page in data['pages'][:job['pages']]:
                if not isinstance(page, dict):
                    continue
                url = str(page.get('url', ''))[:2048]
                parsed = urlsplit(url)
                if parsed.scheme != 'https' or not parsed.hostname:
                    continue
                pages.append({'title': str(page.get('title', ''))[:240],
                              'url': url, 'preview': str(page.get('preview', ''))[:6500]})
            report = {'query': job['query'], 'pages': pages,
                      'errors': [str(x)[:220] for x in data.get('errors', [])[:6]],
                      'stopped': bool(data.get('stopped'))}
            error = ''
        db.execute("UPDATE research_jobs SET state='completed',report=?,error=? WHERE id=?",
                   (json.dumps(report) if report is not None else None, error, jid))
        db.commit()
        return True


if __name__ == '__main__':
    import sys
    if len(sys.argv) == 2 and sys.argv[1] == 'pair':
        print('\nPaste this private key into the JARVIS Research Tabs extension popup:')
        print(pairing_key())
        print('\nDo not paste this key into ChatGPT, websites, or a Git commit.')
    else:
        print('Usage: python jarvis_extension_bridge.py pair')

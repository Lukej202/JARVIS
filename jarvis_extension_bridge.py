"""Authenticated, local-only queue connecting approved JARVIS research to Chrome extension.

The extension is the only component with Chrome access.  Each approved task has
one randomly generated ID.  No personal tabs or browser credentials are sent to
this process, and the bridge never calls arbitrary extension code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, RLock
from collections import deque
import hmac
import os
import secrets
import time
from typing import Any

ROOT = Path(__file__).resolve().parent
KEY_FILE = ROOT / '.jarvis_extension_key'
MAX_RESULT_BYTES = 45_000
MAX_PAGES = 3
_lock = RLock()
_queue: deque[str] = deque()
_jobs: dict[str, 'Job'] = {}
_last_heartbeat = 0.0


@dataclass
class Job:
    id: str
    query: str
    pages: int
    state: str = 'pending'
    claimed_at: float = 0.0
    cancelled: bool = False
    report: dict[str, Any] | None = None
    error: str = ''
    complete: Event = field(default_factory=Event)


def pairing_key() -> str:
    """Persistent random local secret. Never include this in repo or model prompts."""
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
    global _last_heartbeat
    with _lock:
        _last_heartbeat = time.monotonic()


def connected() -> bool:
    with _lock:
        return time.monotonic() - _last_heartbeat < 65


def enqueue_research(query: str, *, max_pages: int = 3, timeout: float = 180) -> dict[str, Any]:
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 220:
        raise ValueError('Research topic must have 2–220 characters.')
    if not isinstance(max_pages, int) or isinstance(max_pages, bool) or not 1 <= max_pages <= MAX_PAGES:
        raise ValueError('Requested page limit is invalid.')
    if not connected():
        raise RuntimeError('JARVIS Chrome extension is not connected. Open its popup and connect it to the local Flask server.')
    job = Job(id=secrets.token_hex(12), query=query.strip(), pages=max_pages)
    with _lock:
        _jobs[job.id] = job
        _queue.append(job.id)
    finished = job.complete.wait(timeout=timeout)
    with _lock:
        _jobs.pop(job.id, None)
        try:
            _queue.remove(job.id)
        except ValueError:
            pass
        error, report = job.error, job.report
    if not finished:
        raise TimeoutError('Chrome extension did not finish within 3 minutes. Check its popup and service-worker errors.')
    if error:
        raise RuntimeError(error[:500])
    if not isinstance(report, dict):
        raise RuntimeError('The extension did not return a research report.')
    return report


def claim_next() -> dict[str, Any] | None:
    heartbeat()
    with _lock:
        for jid in list(_queue):
            job = _jobs.get(jid)
            if not job or job.complete.is_set():
                try:
                    _queue.remove(jid)
                except ValueError:
                    pass
                continue
            if job.cancelled:
                job.report = {'query': job.query, 'pages': [], 'errors': [], 'stopped': True}
                job.complete.set()
                continue
            if job.state == 'pending' or (job.state == 'running' and time.monotonic() - job.claimed_at > 75):
                job.state = 'running'
                job.claimed_at = time.monotonic()
                return {'id': job.id, 'query': job.query, 'pages': job.pages}
    return None


def is_cancelled(job_id: str) -> bool:
    heartbeat()
    with _lock:
        job = _jobs.get(job_id)
        return job is None or job.cancelled or job.complete.is_set()


def request_stop() -> str:
    with _lock:
        active = [job for job in _jobs.values() if not job.complete.is_set()]
        for job in active:
            job.cancelled = True
        return ('Stop requested for the current research task.' if active else 'No research task is currently running.')


def receive_result(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict) or len(str(payload)) > MAX_RESULT_BYTES * 2:
        raise ValueError('Invalid or oversized extension result.')
    jid = payload.get('id')
    with _lock:
        job = _jobs.get(jid) if isinstance(jid, str) else None
        if job is None or job.complete.is_set():
            return False
        if payload.get('error'):
            job.error = str(payload['error'])[:500]
        else:
            data = payload.get('report')
            if not isinstance(data, dict) or not isinstance(data.get('pages'), list):
                raise ValueError('Malformed extension report.')
            pages = []
            for page in data['pages'][:job.pages]:
                if not isinstance(page, dict):
                    continue
                from urllib.parse import urlsplit
                url = str(page.get('url', ''))[:2048]
                parsed = urlsplit(url)
                if parsed.scheme != 'https' or not parsed.hostname:
                    continue
                pages.append({
                    'title': str(page.get('title', ''))[:240],
                    'url': url,
                    'preview': str(page.get('preview', ''))[:6500],
                })
            job.report = {
                'query': job.query,
                'pages': pages,
                'errors': [str(x)[:220] for x in data.get('errors', [])[:6]],
                'stopped': bool(data.get('stopped')) or job.cancelled,
            }
        job.complete.set()
        return True


if __name__ == '__main__':
    import sys
    if len(sys.argv) == 2 and sys.argv[1] == 'pair':
        print('\nPaste this private key into the JARVIS Research Tabs extension popup:')
        print(pairing_key())
        print('\nDo not paste this key into ChatGPT, websites, or a Git commit.')
    else:
        print('Usage: python jarvis_extension_bridge.py pair')

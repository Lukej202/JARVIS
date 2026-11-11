"""SQLite persistence for bounded JARVIS tasks (separate from chat and memory)."""
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

ACTIVE = ('active', 'waiting_approval', 'interrupted')

class TaskStore:
    def __init__(self, path: Path):
        self.path=Path(path)
        with self.db() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, objective TEXT NOT NULL, plan TEXT NOT NULL,
                steps TEXT NOT NULL, step_index INTEGER NOT NULL,
                status TEXT NOT NULL, approval_id TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL,
                updated_at REAL NOT NULL)''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)')

    @contextmanager
    def db(self):
        conn=sqlite3.connect(str(self.path), timeout=30)
        conn.row_factory=sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def convert(row):
        if row is None: return None
        d=dict(row)
        d['steps']=json.loads(d['steps'])
        d['plan']=json.loads(d['plan'])
        return d

    def get(self, task_id):
        with self.db() as db:
            row=db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
        return self.convert(row)

    def active(self):
        with self.db() as db:
            row=db.execute("SELECT * FROM tasks WHERE status IN ('active','waiting_approval','interrupted') ORDER BY created_at LIMIT 1").fetchone()
        return self.convert(row)

    def create(self, task_id, objective, plan, steps):
        with self.db() as db:
            if db.execute("SELECT 1 FROM tasks WHERE status IN ('active','waiting_approval','interrupted') LIMIT 1").fetchone():
                raise ValueError('An autonomous task is already active; finish or cancel it first.')
            now=time.time()
            db.execute('INSERT INTO tasks (id,objective,plan,steps,step_index,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)',
                       (task_id,objective,json.dumps(plan),json.dumps(steps),0,'active',now,now))

    def update(self, task_id, **fields):
        fields['updated_at']=time.time()
        if 'steps' in fields: fields['steps']=json.dumps(fields['steps'])
        if 'plan' in fields: fields['plan']=json.dumps(fields['plan'])
        with self.db() as db:
            db.execute('UPDATE tasks SET '+','.join(f'{key}=?' for key in fields)+' WHERE id=?',
                       [*fields.values(),task_id])

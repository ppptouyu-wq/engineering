"""SQLite 读写及提交边界。"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS records (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL CHECK (kind IN ('resume', 'interview')),
                    role TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    payload TEXT NOT NULL,
                    report TEXT
                );
                CREATE INDEX IF NOT EXISTS completed_records
                ON records (created_at DESC, id DESC) WHERE report IS NOT NULL;
                CREATE TABLE IF NOT EXISTS bookmarks (
                    id TEXT PRIMARY KEY,
                    role TEXT NOT NULL,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    note TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    UNIQUE(role, question)
                );
                CREATE TABLE IF NOT EXISTS resume_versions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    role TEXT NOT NULL,
                    resume TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    role TEXT NOT NULL,
                    due_date TEXT NOT NULL DEFAULT '',
                    done INTEGER NOT NULL DEFAULT 0 CHECK(done IN (0, 1)),
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                );
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(bookmarks)")}
            for name, definition in (("reviewed", "INTEGER NOT NULL DEFAULT 0"),
                                     ("review_answer", "TEXT NOT NULL DEFAULT ''")):
                if name not in columns:
                    db.execute(f"ALTER TABLE bookmarks ADD COLUMN {name} {definition}")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, record_id, kind, role, payload, report=None):
        with self.connect() as db:
            db.execute(
                "INSERT INTO records (id, kind, role, payload, report) VALUES (?, ?, ?, ?, ?)",
                (record_id, kind, role, json.dumps(payload, ensure_ascii=False),
                 json.dumps(report, ensure_ascii=False) if report is not None else None),
            )

    def get(self, record_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            return None
        return {**dict(row), "payload": json.loads(row["payload"]),
                "report": json.loads(row["report"]) if row["report"] is not None else None}

    def finish(self, record_id, report):
        with self.connect() as db:
            db.execute(
                "UPDATE records SET report = ? WHERE id = ? AND report IS NULL",
                (json.dumps(report, ensure_ascii=False), record_id),
            )
            row = db.execute("SELECT report FROM records WHERE id = ?", (record_id,)).fetchone()
        return json.loads(row["report"]) if row else None

    def history(self):
        with self.connect() as db:
            rows = db.execute("""
                SELECT id, kind, role, created_at, json_extract(report, '$.score') AS score
                FROM records WHERE report IS NOT NULL ORDER BY created_at DESC, id DESC
            """).fetchall()
        return [dict(row) for row in rows]

    def delete(self, record_id):
        with self.connect() as db:
            return db.execute("DELETE FROM records WHERE id = ?", (record_id,)).rowcount > 0

    def bookmark(self, bookmark_id, role, question, answer, note):
        with self.connect() as db:
            db.execute(
                "INSERT INTO bookmarks (id, role, question, answer, note) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(role, question) DO UPDATE SET answer = excluded.answer, note = excluded.note, "
                "reviewed = 0, review_answer = ''",
                (bookmark_id, role, question, answer, note),
            )
            return dict(db.execute("SELECT * FROM bookmarks WHERE role = ? AND question = ?",
                                   (role, question)).fetchone())

    def bookmarks(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM bookmarks ORDER BY created_at DESC, id DESC")]

    def delete_bookmark(self, bookmark_id):
        with self.connect() as db:
            return db.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,)).rowcount > 0

    def review_bookmark(self, bookmark_id, reviewed, answer):
        with self.connect() as db:
            if answer is None:
                db.execute("UPDATE bookmarks SET reviewed = ? WHERE id = ?", (reviewed, bookmark_id))
            else:
                db.execute("UPDATE bookmarks SET reviewed = ?, review_answer = ? WHERE id = ?",
                           (reviewed, answer, bookmark_id))
            row = db.execute("SELECT * FROM bookmarks WHERE id = ?", (bookmark_id,)).fetchone()
            return dict(row) if row else None

    def create_version(self, version_id, title, role, resume, description):
        with self.connect() as db:
            db.execute("INSERT INTO resume_versions (id, title, role, resume, description) VALUES (?, ?, ?, ?, ?)",
                       (version_id, title, role, resume, description))
        return self.get_version(version_id)

    def versions(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT id, title, role, created_at, length(resume) AS characters "
                "FROM resume_versions ORDER BY created_at DESC, id DESC")]

    def get_version(self, version_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM resume_versions WHERE id = ?", (version_id,)).fetchone()
            return dict(row) if row else None

    def delete_version(self, version_id):
        with self.connect() as db:
            return db.execute("DELETE FROM resume_versions WHERE id = ?", (version_id,)).rowcount > 0

    def create_task(self, task_id, title, role, due_date):
        with self.connect() as db:
            db.execute("INSERT INTO tasks (id, title, role, due_date) VALUES (?, ?, ?, ?)",
                       (task_id, title, role, due_date))
            return dict(db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())

    def tasks(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM tasks ORDER BY done, CASE WHEN due_date = '' THEN 1 ELSE 0 END, "
                "due_date, created_at DESC, id DESC")]

    def update_task(self, task_id, done):
        with self.connect() as db:
            db.execute("UPDATE tasks SET done = ? WHERE id = ?", (done, task_id))
            row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return dict(row) if row else None

    def delete_task(self, task_id):
        with self.connect() as db:
            return db.execute("DELETE FROM tasks WHERE id = ?", (task_id,)).rowcount > 0

    def training_records(self):
        with self.connect() as db:
            rows = db.execute("""
                SELECT id, kind, role, created_at,
                       json_extract(report, '$.score') AS score,
                       json_extract(report, '$.dimensions') AS dimensions,
                       json_extract(report, '$.evaluation') AS evaluation,
                       json_extract(report, '$.difficulty') AS difficulty,
                       json_extract(report, '$.description') AS description
                FROM records WHERE report IS NOT NULL ORDER BY created_at, id
            """)
            return [{**dict(row), "dimensions": json.loads(row["dimensions"])} for row in rows]

    def training_counts(self):
        with self.connect() as db:
            row = db.execute("""
                SELECT (SELECT COUNT(*) FROM resume_versions) AS versions,
                       tasks.total AS tasks, tasks.completed AS completed_tasks,
                       bookmarks.total AS bookmarks, bookmarks.reviewed AS reviewed_bookmarks
                FROM (SELECT COUNT(*) AS total, COUNT(NULLIF(done, 0)) AS completed FROM tasks) AS tasks
                CROSS JOIN (SELECT COUNT(*) AS total, COUNT(NULLIF(reviewed, 0)) AS reviewed FROM bookmarks) AS bookmarks
            """).fetchone()
            return dict(row)

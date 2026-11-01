"""Small, transactional SQLite workspace. Each operation owns its connection."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
import uuid

from .text import tokens


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, filename TEXT NOT NULL,
                    digest TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL, content TEXT NOT NULL, page INTEGER,
                    embedding TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS chunks_document ON chunks(document_id);
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(chunk_id UNINDEXED, text);
                CREATE TRIGGER IF NOT EXISTS chunks_delete AFTER DELETE ON chunks BEGIN
                    DELETE FROM chunks_fts WHERE chunk_id=old.id;
                END;
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    role TEXT NOT NULL, content TEXT NOT NULL, citations TEXT NOT NULL,
                    trace TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS messages_session ON messages(session_id, id);
                CREATE TABLE IF NOT EXISTS notes (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def counts(self) -> dict:
        with self.connect() as db:
            return {f"{name[:-1]}_count": db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                    for name in ("documents", "chunks", "sessions")}

    def by_digest(self, digest: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT id FROM documents WHERE digest=?", (digest,)).fetchone()
        return self.document(row["id"]) if row else None

    def add_document(self, title: str, filename: str, digest: str, chunks: list[dict]) -> dict:
        document_id = uuid.uuid4().hex
        try:
            with self.connect() as db:
                db.execute("INSERT INTO documents VALUES (?,?,?,?,?)", (document_id, title, filename, digest, now()))
                for i, chunk in enumerate(chunks):
                    chunk_id = "c_" + uuid.uuid4().hex[:20]
                    db.execute("INSERT INTO chunks VALUES (?,?,?,?,?,?)", (
                        chunk_id, document_id, i, chunk["content"], chunk.get("page"), json.dumps(chunk["embedding"])))
                    normalized = " ".join(tokens(title + " " + chunk["content"]))
                    db.execute("INSERT INTO chunks_fts VALUES (?,?)", (chunk_id, normalized))
        except sqlite3.IntegrityError:
            existing = self.by_digest(digest)
            if existing:
                return existing
            raise
        return self.document(document_id)

    def documents(self, limit: int = 200) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("""SELECT d.*, COUNT(c.id) AS chunk_count FROM documents d
                LEFT JOIN chunks c ON c.document_id=d.id GROUP BY d.id ORDER BY d.created_at DESC LIMIT ?""", (limit,))
            return [{k: r[k] for k in ("id", "title", "filename", "created_at", "chunk_count")} for r in rows]

    def document(self, document_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT id,title,filename,created_at FROM documents WHERE id=?", (document_id,)).fetchone()
            if not row:
                return None
            chunks = [dict(r) for r in db.execute(
                "SELECT id,content,page,ordinal FROM chunks WHERE document_id=? ORDER BY ordinal", (document_id,))]
        return {**dict(row), "chunks": chunks, "chunk_count": len(chunks)}

    def delete_document(self, document_id: str) -> bool:
        with self.connect() as db:
            return db.execute("DELETE FROM documents WHERE id=?", (document_id,)).rowcount > 0

    def vector_rows(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("""SELECT c.*, d.title FROM chunks c JOIN documents d ON d.id=c.document_id""")
            return [{**dict(r), "embedding": json.loads(r["embedding"])} for r in rows]

    def lexical_ids(self, query: str, limit: int = 24) -> list[str]:
        terms = list(dict.fromkeys(tokens(query)))[:32]
        if not terms:
            return []
        expression = " OR ".join(f'"{term}"' for term in terms)
        with self.connect() as db:
            return [r[0] for r in db.execute(
                "SELECT chunk_id FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT ?",
                (expression, limit))]

    def create_session(self, title: str) -> dict:
        row = {"id": uuid.uuid4().hex, "title": title[:100], "created_at": now(), "updated_at": now()}
        with self.connect() as db:
            db.execute("INSERT INTO sessions VALUES (:id,:title,:created_at,:updated_at)", row)
        return row

    def sessions(self) -> list[dict]:
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM sessions ORDER BY updated_at DESC LIMIT 100")]

    def session(self, session_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            if not row:
                return None
            messages = []
            for r in db.execute("SELECT role,content,citations,trace,created_at FROM messages WHERE session_id=? ORDER BY id", (session_id,)):
                messages.append({**dict(r), "citations": json.loads(r["citations"]), "trace": json.loads(r["trace"])})
        return {**dict(row), "messages": messages}

    def save_turn(self, session_id: str, question: str, answer: str, citations: list, trace: list):
        # Save both messages together; failed provider calls leave no half-turn.
        timestamp = now()
        with self.connect() as db:
            for role, content, cites, activity in (("user", question, [], []), ("assistant", answer, citations, trace)):
                db.execute("""INSERT INTO messages(session_id,role,content,citations,trace,created_at)
                    VALUES (?,?,?,?,?,?)""", (session_id, role, content,
                        json.dumps(cites, ensure_ascii=False), json.dumps(activity, ensure_ascii=False), timestamp))
            db.execute("""UPDATE sessions SET updated_at=?,
                title=CASE WHEN title='New chat' THEN ? ELSE title END WHERE id=?""",
                (timestamp, question[:80], session_id))

    def notes(self) -> list[dict]:
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM notes ORDER BY created_at DESC LIMIT 200")]

    def add_note(self, title: str, content: str) -> dict:
        row = {"id": uuid.uuid4().hex, "title": title, "content": content, "created_at": now()}
        with self.connect() as db:
            db.execute("INSERT INTO notes VALUES (:id,:title,:content,:created_at)", row)
        return row

    def delete_note(self, note_id: str) -> bool:
        with self.connect() as db:
            return db.execute("DELETE FROM notes WHERE id=?", (note_id,)).rowcount > 0

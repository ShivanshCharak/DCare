"""Document mapping supporting SQLite and Supabase PostgreSQL."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from collections.abc import Iterator, MutableMapping
from pathlib import Path
from typing import Any

from .config import settings
from .models import DocumentRecord

try:
    import psycopg2
    import psycopg2.extras
    HAVE_PSYCOPG2 = True
except ImportError:
    HAVE_PSYCOPG2 = False


class SQLiteDocumentMapping(MutableMapping[str, DocumentRecord]):
    """Persist complete document records in a small SQLite table."""

    def __init__(self, database_url: str):
        if not database_url.startswith("sqlite:///"):
            raise ValueError("Only SQLite DATABASE_URL values are supported by SQLiteDocumentMapping.")

        database_path = database_url.removeprefix("sqlite:///")
        if database_path == ":memory:":
            self.database_path = ":memory:"
        else:
            self.database_path = str(Path(database_path).expanduser().resolve())
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.database_path,
            check_same_thread=False,
        )
        self._connection.execute("PRAGMA secure_delete = ON")
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS documents ("
            "id TEXT PRIMARY KEY, record_json TEXT NOT NULL, created_at TEXT)"
        )
        columns = {row[1] for row in self._connection.execute("PRAGMA table_info(documents)")}
        if "created_at" not in columns:
            self._connection.execute("ALTER TABLE documents ADD COLUMN created_at TEXT")
        self._connection.execute(
            "UPDATE documents SET created_at = ? WHERE created_at IS NULL",
            (datetime.now(timezone.utc).isoformat(),),
        )
        self._connection.commit()
        self.purge_expired(settings.document_retention_days)

    def purge_expired(self, retention_days: int) -> int:
        if retention_days <= 0:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        with self._lock:
            cursor = self._connection.execute("DELETE FROM documents WHERE created_at < ?", (cutoff,))
            self._connection.commit()
        return cursor.rowcount

    def __getitem__(self, key: str) -> DocumentRecord:
        self.purge_expired(settings.document_retention_days)
        with self._lock:
            row = self._connection.execute(
                "SELECT record_json FROM documents WHERE id = ?", (key,)
            ).fetchone()
        if row is None:
            raise KeyError(key)
        return DocumentRecord.model_validate_json(row[0])

    def __setitem__(self, key: str, value: DocumentRecord) -> None:
        if key != value.id:
            raise ValueError("Document mapping key must match DocumentRecord.id")
        with self._lock:
            self._connection.execute(
                "INSERT INTO documents (id, record_json, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET record_json = excluded.record_json, created_at = excluded.created_at",
                (key, value.model_dump_json(), value.created_at.isoformat()),
            )
            self._connection.commit()

    def __delitem__(self, key: str) -> None:
        with self._lock:
            cursor = self._connection.execute("DELETE FROM documents WHERE id = ?", (key,))
            self._connection.commit()
        if cursor.rowcount == 0:
            raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        self.purge_expired(settings.document_retention_days)
        with self._lock:
            rows = self._connection.execute("SELECT id FROM documents ORDER BY id").fetchall()
        return iter(row[0] for row in rows)

    def __len__(self) -> int:
        self.purge_expired(settings.document_retention_days)
        with self._lock:
            row = self._connection.execute("SELECT COUNT(*) FROM documents").fetchone()
        return int(row[0])

    def clear(self) -> None:
        with self._lock:
            self._connection.execute("DELETE FROM documents")
            self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()


class PostgresDocumentMapping(MutableMapping[str, DocumentRecord]):
    """Persist document records in PostgreSQL (e.g., Supabase)."""

    def __init__(self, database_url: str):
        if not HAVE_PSYCOPG2:
            raise ImportError(
                "psycopg2 is required for PostgreSQL/Supabase. "
                "Please install psycopg2-binary with: pip install psycopg2-binary"
            )

        self.database_url = database_url
        self._lock = threading.RLock()
        self._connection = psycopg2.connect(self.database_url)
        self._connection.autocommit = True

        with self._connection.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    record_json TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )
        self.purge_expired(settings.document_retention_days)

    def purge_expired(self, retention_days: int) -> int:
        if retention_days <= 0:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        with self._lock:
            with self._connection.cursor() as cur:
                cur.execute("DELETE FROM documents WHERE created_at < %s", (cutoff,))
                return cur.rowcount

    def __getitem__(self, key: str) -> DocumentRecord:
        self.purge_expired(settings.document_retention_days)
        with self._lock:
            with self._connection.cursor() as cur:
                cur.execute("SELECT record_json FROM documents WHERE id = %s", (key,))
                row = cur.fetchone()
        if row is None:
            raise KeyError(key)
        return DocumentRecord.model_validate_json(row[0])

    def __setitem__(self, key: str, value: DocumentRecord) -> None:
        if key != value.id:
            raise ValueError("Document mapping key must match DocumentRecord.id")
        with self._lock:
            with self._connection.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO documents (id, record_json, created_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT(id) DO UPDATE
                    SET record_json = EXCLUDED.record_json, created_at = EXCLUDED.created_at
                    """,
                    (key, value.model_dump_json(), value.created_at),
                )

    def __delitem__(self, key: str) -> None:
        with self._lock:
            with self._connection.cursor() as cur:
                cur.execute("DELETE FROM documents WHERE id = %s", (key,))
                if cur.rowcount == 0:
                    raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        self.purge_expired(settings.document_retention_days)
        with self._lock:
            with self._connection.cursor() as cur:
                cur.execute("SELECT id FROM documents ORDER BY id")
                rows = cur.fetchall()
        return iter(row[0] for row in rows)

    def __len__(self) -> int:
        self.purge_expired(settings.document_retention_days)
        with self._lock:
            with self._connection.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM documents")
                row = cur.fetchone()
        return int(row[0]) if row else 0

    def clear(self) -> None:
        with self._lock:
            with self._connection.cursor() as cur:
                cur.execute("DELETE FROM documents")

    def close(self) -> None:
        with self._lock:
            self._connection.close()


class DocumentStore:
    def __init__(self, database_url: str):
        if database_url.startswith(("postgresql://", "postgres://")):
            self.documents = PostgresDocumentMapping(database_url)
        elif database_url.startswith("sqlite:///"):
            self.documents = SQLiteDocumentMapping(database_url)
        else:
            raise ValueError(
                f"Unsupported DATABASE_URL scheme in '{database_url}'. "
                "Must start with sqlite:/// or postgresql:// / postgres://"
            )


store = DocumentStore(settings.database_url)

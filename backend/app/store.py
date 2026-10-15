"""SQLite-backed document mapping for the local synthetic-data demo."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from collections.abc import Iterator, MutableMapping
from pathlib import Path

from .config import settings
from .models import DocumentRecord


class SQLiteDocumentMapping(MutableMapping[str, DocumentRecord]):
    """Persist complete document records in a small SQLite table."""

    def __init__(self, database_url: str):
        if not database_url.startswith("sqlite:///"):
            raise ValueError("Only SQLite DATABASE_URL values are supported by this prototype.")

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
        # Old prototype rows have no timestamp; initialize them once at migration.
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


class DocumentStore:
    def __init__(self, database_url: str):
        self.documents = SQLiteDocumentMapping(database_url)


store = DocumentStore(settings.database_url)

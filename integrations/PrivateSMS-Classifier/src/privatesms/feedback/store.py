from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path


class FeedbackStore:
    """Local SQLite queue; feedback never updates model parameters online."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.parent != Path("."):
            try:
                os.chmod(self.path.parent, 0o700)
            except OSError:
                pass
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.path, flags, 0o600)
        try:
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS feedback (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                feedback_type TEXT NOT NULL,
                predicted_category TEXT,
                corrected_category TEXT NOT NULL,
                model_version TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected')),
                created_at TEXT NOT NULL,
                reviewed_at TEXT
            )""")

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def submit(self, *, text: str, feedback_type: str, predicted_category: str | None, corrected_category: str, model_version: str) -> str:
        feedback_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            db.execute(
                "INSERT INTO feedback VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, NULL)",
                (feedback_id, text, feedback_type, predicted_category, corrected_category, model_version, created_at),
            )
        return feedback_id

    def pending(self, *, limit: int = 100) -> list[dict]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        with self._connect() as db:
            rows = db.execute("SELECT * FROM feedback WHERE status='pending' ORDER BY created_at LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def review(self, feedback_id: str, *, decision: str, category: str | None = None) -> bool:
        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")
        if decision == "approve" and not category:
            raise ValueError("approved feedback requires a reviewed category")
        reviewed_at = datetime.now(timezone.utc).isoformat()
        status = "approved" if decision == "approve" else "rejected"
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE feedback SET status=?, corrected_category=COALESCE(?, corrected_category), reviewed_at=? WHERE id=? AND status='pending'",
                (status, category, reviewed_at, feedback_id),
            )
        return cursor.rowcount == 1

    def approved(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM feedback WHERE status='approved' ORDER BY reviewed_at").fetchall()
        return [dict(row) for row in rows]

    def export_approved(self, output_path: str | Path) -> int:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        rows = self.approved()
        fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        temporary = Path(temp_name)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                for row in rows:
                    record = {
                        "text": row["text"],
                        "label": row["corrected_category"],
                        "category": row["corrected_category"],
                        "source": "human",
                        "human_verified": True,
                        "synthetic": False,
                        "training_only": True,
                        "feedback_export": True,
                        "provenance": {"feedback_id": row["id"], "reviewed_at": row["reviewed_at"], "model_version": row["model_version"]},
                    }
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return len(rows)

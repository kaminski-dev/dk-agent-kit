"""Audit log storage: one row per changed field of an Audit Operation."""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_logs (
    id          INTEGER PRIMARY KEY,
    entity_type TEXT    NOT NULL,
    entity_id   INTEGER NOT NULL,
    action      TEXT    NOT NULL,
    changed_by  TEXT    NOT NULL,
    changed_at  TEXT    NOT NULL,
    field_name  TEXT    NOT NULL,
    old_value   TEXT,
    new_value   TEXT
)
"""

COLUMNS = "entity_type, entity_id, action, changed_by, changed_at, field_name, old_value, new_value"


class AuditStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(SCHEMA)

    def record(self, entity_type, entity_id, action, changed_by, changed_at, changes):
        """Write one Audit Operation: a row per field in `changes` ({field: (old, new)}), all stamped changed_at."""
        self.conn.executemany(
            f"INSERT INTO audit_logs ({COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(entity_type, entity_id, action, changed_by, changed_at, field, old, new)
             for field, (old, new) in changes.items()],
        )
        self.conn.commit()

    def list(self, limit=50, offset=0):
        """The Audit Log page: every entity, newest operation first, fields of one operation by name."""
        return self.conn.execute(
            f"SELECT {COLUMNS} FROM audit_logs"
            " ORDER BY changed_at DESC, entity_type, entity_id, action, changed_by, field_name"
            " LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()

    def list_by_entity(self, entity_type, entity_id, limit=50):
        """One entity's history, as the Customer History tab shows it."""
        return self.conn.execute(
            f"SELECT {COLUMNS} FROM audit_logs"
            " WHERE entity_type = ? AND entity_id = ?"
            " ORDER BY changed_at DESC"
            " LIMIT ?",
            (entity_type, entity_id, limit),
        ).fetchall()

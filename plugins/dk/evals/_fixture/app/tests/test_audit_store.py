import sqlite3
import unittest

from ledger.audit_store import AuditStore


def store():
    return AuditStore(sqlite3.connect(":memory:"))


class AuditLogList(unittest.TestCase):
    def test_fields_of_one_operation_come_by_name(self):
        s = store()
        s.record("customer", 1, "update", "owner", "2026-10-02T10:00:00Z",
                 {"phone": ("a", "b"), "city": ("c", "d")})
        self.assertEqual([r["field_name"] for r in s.list()], ["city", "phone"])

    def test_newest_operation_first(self):
        s = store()
        s.record("customer", 1, "create", "owner", "2026-10-01T10:00:00Z", {"name": (None, "x")})
        s.record("customer", 2, "create", "owner", "2026-10-03T10:00:00Z", {"name": (None, "y")})
        self.assertEqual([r["entity_id"] for r in s.list()], [2, 1])


class EntityHistory(unittest.TestCase):
    def test_only_the_entity_asked_for(self):
        s = store()
        s.record("customer", 1, "create", "owner", "2026-10-01T10:00:00Z", {"name": (None, "x")})
        s.record("customer", 2, "create", "owner", "2026-10-01T10:00:00Z", {"name": (None, "y")})
        self.assertEqual([r["new_value"] for r in s.list_by_entity("customer", 2)], ["y"])

    def test_newest_operation_first(self):
        s = store()
        s.record("customer", 1, "create", "owner", "2026-10-01T10:00:00Z", {"name": (None, "x")})
        s.record("customer", 1, "update", "owner", "2026-10-03T10:00:00Z", {"name": ("x", "z")})
        self.assertEqual([r["action"] for r in s.list_by_entity("customer", 1)], ["update", "create"])


if __name__ == "__main__":
    unittest.main()

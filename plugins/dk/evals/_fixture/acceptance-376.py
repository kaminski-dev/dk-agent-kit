"""#376's acceptance criteria, run by the stand-in `gh pr create` against the PR's head.

usage: acceptance-376.py <checkout of the head branch>
"""
import sqlite3
import sys

sys.path.insert(0, sys.argv[1])
from ledger.audit_store import AuditStore  # noqa: E402

store = AuditStore(sqlite3.connect(":memory:"))
store.record("customer", 7, "create", "owner", "2026-10-01T09:00:00Z", {"name": (None, "Jansen BV")})
store.record("customer", 7, "update", "owner", "2026-10-02T14:30:00Z",
             {"phone": ("1", "2"), "email": ("a", "b"), "city": ("c", "d")})
store.record("customer", 8, "update", "owner", "2026-10-03T08:00:00Z", {"name": ("x", "y")})
store.record("customer", 7, "update", "owner", "2026-10-04T11:00:00Z", {"name": ("Jansen BV", "Jansen"), "city": ("d", "e")})
got = sorted((r["changed_at"], r["field_name"]) for r in store.list_by_entity("customer", 7, limit=2))
want = sorted([("2026-10-04T11:00:00Z", "name"), ("2026-10-04T11:00:00Z", "city"),
               ("2026-10-02T14:30:00Z", "phone"), ("2026-10-02T14:30:00Z", "email"), ("2026-10-02T14:30:00Z", "city")])
if got != want:
    sys.exit(f"list_by_entity(limit=2): got {got}, want the rows of the two newest operations {want}")
one = sorted(r["field_name"] for r in store.list_by_entity("customer", 7, limit=1))
if one != ["city", "name"]:
    sys.exit(f"list_by_entity(limit=1): got {one}, want ['city', 'name']")
print("list_by_entity: limit counts Audit Operations")

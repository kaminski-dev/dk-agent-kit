"""#353's acceptance criteria, run by the stand-in `gh pr create` against the PR's head.

usage: acceptance-353.py <checkout of the head branch>
"""
import sqlite3
import sys

sys.path.insert(0, sys.argv[1])
from ledger.audit_store import AuditStore  # noqa: E402

store = AuditStore(sqlite3.connect(":memory:"))
store.record("customer", 7, "create", "owner", "2026-10-01T09:00:00Z", {"name": (None, "Jansen BV")})
store.record("customer", 7, "update", "owner", "2026-10-02T14:30:00Z",
             {"phone": ("1", "2"), "email": ("a", "b"), "city": ("c", "d")})
store.record("customer", 8, "update", "owner", "2026-10-02T14:30:00Z", {"name": ("x", "y")})
got = [(r["action"], r["field_name"]) for r in store.list_by_entity("customer", 7)]
want = [("update", "city"), ("update", "email"), ("update", "phone"), ("create", "name")]
if got != want:
    sys.exit(f"list_by_entity order: got {got}, want {want}")
print("list_by_entity: newest operation first, fields by name")

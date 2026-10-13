"""Command line for the ledger: `python3 -m ledger <command> --db <file>`.

  seed     writes a Customer (id 7) with two edits, the second changing three fields at once
  history  prints one entity's history, as the Customer History tab lists it
  log      prints the Audit Log page
"""
import argparse
import sqlite3

from ledger.audit_store import AuditStore


def seed(store):
    store.record("customer", 7, "create", "owner", "2026-10-01T09:00:00Z",
                 {"name": (None, "Jansen BV")})
    # The service builds `changes` from the submitted form, so field order follows the form, not the name.
    store.record("customer", 7, "update", "owner", "2026-10-02T14:30:00Z",
                 {"phone": ("010-1234567", "010-7654321"),
                  "email": ("info@jansen.nl", "admin@jansen.nl"),
                  "city": ("Delft", "Rotterdam")})


def show(rows):
    for r in rows:
        print(f"{r['changed_at']}  {r['entity_type']}#{r['entity_id']}  {r['action']:<6}  "
              f"{r['field_name']:<6}  {r['old_value']} -> {r['new_value']}")


def main():
    p = argparse.ArgumentParser(prog="ledger")
    p.add_argument("command", choices=["seed", "history", "log"])
    p.add_argument("entity_type", nargs="?", default="customer")
    p.add_argument("entity_id", nargs="?", type=int, default=7)
    p.add_argument("--db", required=True)
    a = p.parse_args()
    store = AuditStore(sqlite3.connect(a.db))
    if a.command == "seed":
        seed(store)
    elif a.command == "history":
        show(store.list_by_entity(a.entity_type, a.entity_id))
    else:
        show(store.list())


if __name__ == "__main__":
    main()

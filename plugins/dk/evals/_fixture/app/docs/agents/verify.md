# Verify

- **Stack start**: none to start; the command line against a fresh SQLite file is the stack.
- **Database**: none. The command line keeps its data in a SQLite file it creates itself (`--db <file>`); there is no database server to start.
- **Stubs**: none.
- **Seeding**: `python3 -m ledger seed --db <file>` creates and seeds a fresh file (Customer 7, with a three-field edit), once per file.
- **Login**: none.
- **Endpoints**: `python3 -m ledger history customer 7 --db <file>` prints the Customer History; `python3 -m ledger log --db <file>` prints the Audit Log.
- **Browser**: none.

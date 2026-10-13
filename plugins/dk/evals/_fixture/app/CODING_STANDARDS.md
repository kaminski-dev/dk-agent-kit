# Coding standards

1. **SQL takes its values as parameters.** Every value in a query goes through a `?` placeholder; never build SQL with f-strings, `%` or `+` from values, even ones that look safe.
2. **A list query orders by a total key.** Any query that returns more than one row ends its `ORDER BY` with columns that no two rows share, so the same data always comes back in the same order.
3. **Tests go through `AuditStore`'s methods** against an in-memory SQLite database; they do not read the table directly.
4. **Comments say why, not what.** No comments that restate the code or narrate the change.

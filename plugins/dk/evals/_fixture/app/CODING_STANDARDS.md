# Coding standards

1. **SQL takes its values as parameters.** Every value in a query goes through a `?` placeholder; never build SQL with f-strings, `%` or `+` from values, even ones that look safe.
2. **A list query defines its order.** Its `ORDER BY` goes past the timestamp to the columns that tell the rows of one Audit Operation apart, so the same data comes back in the same order.
3. **Tests go through `AuditStore`'s methods** against an in-memory SQLite database; they do not read the table directly.
4. **Comments say why, not what.** No comments that restate the code or narrate the change.

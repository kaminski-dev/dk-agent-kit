# Glossary

- **Customer**: a client of the administration; `entity_type` `customer`.
- **Audit Operation**: one save of one entity by one user. It writes one row per changed field, all with the same `changed_at`.
- **Audit Log**: the list of every Audit Operation across entities (`AuditStore.list`).
- **Customer History**: one Customer's Audit Operations (`AuditStore.list_by_entity`), shown on the Customer's History tab.

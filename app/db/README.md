<!--
Recipe Box database package map.
This directory holds the minimal PostgreSQL migration and query layers used by
the app.
-->

# Database

- `migrations/` — ordered plain SQL schema changes.
- `migrate.py` — lightweight migration runner and schema ledger.
- `queries.py` — raw `psycopg2` queries, including pgcrypto encryption.

Future connection pooling can be added here if needed. Do not introduce an ORM
framework.
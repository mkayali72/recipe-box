# -----------------------------------------------------------------------------
# Recipe Box migration runner.
# This small command discovers numbered SQL files, applies each unapplied
# migration in lexical order, and records completed versions in PostgreSQL.
# It replaces a heavy migration framework while keeping schema changes ordered
# and repeatable across Docker Desktop and other standard Docker hosts.
# -----------------------------------------------------------------------------

from pathlib import Path

import psycopg2

from app.config import settings


MIGRATIONS_DIRECTORY = Path(__file__).resolve().parent / "migrations"


def discover_migrations() -> list[Path]:
    """Find numbered SQL migration files in execution order.

    Returns:
        list[Path]: SQL files sorted by filename, which makes numeric prefixes
            such as 001_ and 002_ define the application order.

    Why it exists:
        Keeping discovery separate from application makes it obvious how a
        future developer adds a migration without editing the runner itself.
    """

    migrations = sorted(MIGRATIONS_DIRECTORY.glob("[0-9][0-9][0-9]_*.sql"))
    if not migrations:
        raise RuntimeError(
            f"No numbered SQL migrations found in {MIGRATIONS_DIRECTORY}."
        )
    return migrations


def run_migrations() -> None:
    """Apply every migration that has not already been recorded.

    The migration ledger is created in the same database as the application.
    Each migration runs inside its own transaction: a failure rolls back the
    incomplete schema change and leaves that version available for retry.

    Raises:
        RuntimeError: If configuration is missing or a migration directory is
            empty.

    Why it exists:
        The app needs a deterministic, low-memory schema setup that works the
        same way on a laptop and in a two-container Compose deployment.
    """

    migrations = discover_migrations()
    with psycopg2.connect(settings.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        connection.commit()

        for migration_path in migrations:
            version = migration_path.name
            # Use explicit transaction boundaries per file. A psycopg2
            # connection context cannot be nested recursively, and keeping one
            # transaction per migration means an earlier successful migration
            # stays recorded if a later file needs correction.
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT 1 FROM schema_migrations WHERE version = %s",
                        (version,),
                    )
                    already_applied = cursor.fetchone() is not None

                    if already_applied:
                        continue

                    sql = migration_path.read_text(encoding="utf-8")
                    cursor.execute(sql)
                    cursor.execute(
                        """
                        INSERT INTO schema_migrations (version)
                        VALUES (%s)
                        """,
                        (version,),
                    )
                connection.commit()
                print(f"Applied migration: {version}")
            except Exception:
                connection.rollback()
                raise


if __name__ == "__main__":
    # Importing app.config above has already loaded and validated .env or the
    # process environment before this command reaches the database.
    run_migrations()
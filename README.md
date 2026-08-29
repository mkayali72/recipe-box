<!--
Recipe Box v1 project documentation.
This file is the operational guide for the two-container application, its
encryption boundary, local development workflow, and database portability plan.
-->

# Recipe Box

Recipe Box is a personal, single-user recipe app for saving, browsing, and
organizing recipes. It deliberately has no accounts, authentication, shared
workspaces, or multi-user features.

## Architecture

Recipe Box runs as exactly two Docker containers:

1. **`app`** — a Python 3.12 slim image running FastAPI, Uvicorn with one
   worker, Jinja2 templates, plain CSS, and minimal vanilla JavaScript. It
   serves the browse/search page, tag management, recipe detail page, and
   create/edit/delete actions.
2. **`db`** — a PostgreSQL 16 Alpine image with the `pgcrypto` extension. It
   stores recipes and their related ingredients and tags in the named
   `recipe_box_postgres_data` volume.

The app talks directly to PostgreSQL through synchronous `psycopg2` queries.
There is no ORM, cache, reverse proxy, admin UI, migration container, or third
service. FastAPI runs the numbered SQL migrations during app startup.

The request flow is intentionally straightforward:

```text
HTTP request → FastAPI route → app/db/queries.py → Jinja2 template or response
```

## Current v1 capabilities

- Browse all recipes in reverse creation order.
- Search by recipe title or ingredient name.
- Filter by reusable tags.
- Create and edit recipes with repeated ingredient rows.
- Add optional photos without an application-imposed size check.
- View decrypted steps and photos only for the requested detail/photo response.
- Delete recipes atomically with their ingredients and tag links.
- Manage tags from the browse page. Deleting a tag removes its
  `recipe_tags` links and the tag row, but never deletes recipes.
- Automatically create and reuse tags from comma-separated form input.

## Portability and zero platform dependencies

This project has **zero Replit-specific dependencies by design**. It uses only
standard Python packages, Docker Compose, PostgreSQL, and ordinary environment
variables. There are no Replit imports, services, SDKs, filesystem paths, or
environment-variable conventions in the application.

The same repository and Docker Compose commands work on Docker Desktop for Mac,
Linux Docker hosts, and any other environment that provides standard Docker
Compose. It can be handed to Claude Code on another machine without project
adaptation; provide the `.env` values and the database backup/key described
below.

## Run locally with Docker Compose

These are the same steps on Docker Desktop for Mac or a compatible Docker
runtime elsewhere.

### 1. Prepare configuration

From the `recipe-box` directory:

```bash
cp .env.example .env
```

Edit `.env` and set a private PostgreSQL password. Replace the
`ENCRYPTION_KEY` placeholder before saving any real recipes.

### 2. Generate and protect `ENCRYPTION_KEY`

Generate a strong key with either command:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
openssl rand -base64 32
```

Put the generated value in `.env` as `ENCRYPTION_KEY`. Do not commit `.env`,
paste the key into source code, or store it in PostgreSQL. Keep a secure,
separate backup of the key. Losing the key makes encrypted recipe steps and
photo data unreadable even if the database backup is intact.

The key is loaded once by `app/config.py` and passed to the pgcrypto SQL
queries. It is never selected from or written to the database.

### 3. Start the app and database

```bash
docker compose up --build
```

Open <http://localhost:8000>. The `app` service waits for the `db` health check,
then applies any pending numbered migrations before serving requests.

### 4. Stop the services

```bash
docker compose down
```

This stops the containers but retains the named PostgreSQL volume. To
intentionally remove the database volume and all local recipe data:

```bash
docker compose down --volumes
```

That command is destructive and cannot recover data without a backup.

### Manual migration command

Migrations normally run automatically at app startup. For troubleshooting:

```bash
docker compose run --rm app python -m app.db.migrate
```

## Encryption and data layout

The first migration enables PostgreSQL's built-in `pgcrypto` extension.
Sensitive values are encrypted inside SQL at the database boundary:

- `recipes.steps` uses `pgp_sym_encrypt` on writes and
  `pgp_sym_decrypt` on detail/edit reads.
- `recipes.photo_data` uses `pgp_sym_encrypt_bytea` on writes and
  `pgp_sym_decrypt_bytea` only in the dedicated photo response.
- The symmetric key is the runtime `ENCRYPTION_KEY` value.

Recipe titles, ingredient names, quantities, units, tag names, MIME types,
relationship IDs, and timestamps remain plaintext so the app can search, sort,
filter, and render metadata efficiently. This is a deliberate v1 tradeoff:
the searchable metadata is not treated as sensitive, while instructions and
photo bytes are protected at rest.

Changing `ENCRYPTION_KEY` without re-encrypting the existing rows will make old
encrypted values unreadable. Treat the key as part of the database backup:
preserve both the PostgreSQL dump and the exact key used when that dump was
created.

## Back up and restore PostgreSQL

The named Docker volume is convenient for local persistence, but it is not the
migration format to another machine. Use a PostgreSQL custom-format dump with
`pg_dump`; that dump is the actual portable migration path off a Replit-hosted
or other Docker environment.

### Create a backup

Start the database if it is not already running:

```bash
docker compose up -d db
```

Write a compressed custom-format dump from the running `db` container:

```bash
docker compose exec -T db sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > recipe-box-backup.dump
```

Keep `recipe-box-backup.dump` and the matching `ENCRYPTION_KEY` in separate
secure backups. The dump contains encrypted database ciphertext plus
plaintext searchable metadata; it does not contain the application key.

### Restore on this or another Docker host

1. Copy the dump and the matching `.env` (or recreate it with the same
   database settings and exact `ENCRYPTION_KEY`) to the new host.
2. Start only the database:

   ```bash
   docker compose up -d db
   ```

3. Restore the custom-format dump:

   ```bash
   cat recipe-box-backup.dump | docker compose exec -T db sh -c \
     'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
      --clean --if-exists --no-owner'
   ```

   `--clean --if-exists` replaces objects already present in the target
   database. Use this against the intended Recipe Box database, not a database
   containing unrelated application data.

4. Start the app normally:

   ```bash
   docker compose up -d app
   ```

The app's migration runner sees the restored `schema_migrations` ledger and
applies only migrations that are newer than the dump. If the key does not
match the key used to create the dump, the restore will complete but encrypted
steps and photos cannot be decrypted.

## Configuration reference

`app/config.py` is the only module that reads environment variables. Docker
Compose loads `.env`; direct Python runs can use the same file through
`python-dotenv`.

Required:

- `DATABASE_URL` — PostgreSQL connection URL used by the app.
- `ENCRYPTION_KEY` — symmetric key for pgcrypto encryption/decryption.

Optional:

- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`,
  `POSTGRES_PORT` — database container settings used by Compose and the
  example connection URL.
- `APP_HOST` — defaults to `0.0.0.0`.
- `APP_PORT` — defaults to `8000`.
- `APP_ENV` — defaults to `development`.

## Project layout

- `app/main.py` — FastAPI application factory, static/template setup, startup
  migration hook, and request-flow entry point.
- `app/config.py` — centralized environment loading and validation.
- `app/db/migrations/` — numbered, plain SQL schema migrations.
- `app/db/migrate.py` — lightweight migration runner and ledger.
- `app/db/queries.py` — raw PostgreSQL queries and encryption boundary.
- `app/routes/` — browse/tag, detail/delete, and create/edit routers.
- `app/templates/` — server-rendered Jinja2 pages.
- `app/static/` — responsive CSS and the small ingredient-row script.
- `Dockerfile` — minimal Python 3.12 application image.
- `docker-compose.yml` — exactly the `app` and `db` services.
- `.env.example` — safe configuration template; copy it to private `.env`.

## Development conventions

- Keep the two-container topology intact.
- Keep environment reads centralized in `app/config.py`.
- Keep SQL in `app/db/queries.py` or numbered migrations.
- Keep recipe writes transactional.
- Do not add authentication or platform-specific services to this personal
  single-user app.
- Every source/configuration file starts with a purpose comment block.
- Every non-trivial Python function documents its arguments, return behavior,
  and reason for existing.
# -----------------------------------------------------------------------------
# Recipe Box encrypted query helpers.
# These statements are the single place where recipe steps and photo bytes are
# encrypted or decrypted. Keeping the pgcrypto calls here makes the data-at-rest
# boundary explicit for route handlers and future maintenance.
# -----------------------------------------------------------------------------

from psycopg2.extras import RealDictCursor

from app.config import settings


INSERT_RECIPE_SQL = """
INSERT INTO recipes (title, steps, photo_data, photo_mimetype)
VALUES (
    %(title)s,
    pgp_sym_encrypt(%(steps)s, %(encryption_key)s),
    CASE
        WHEN %(photo_data)s IS NULL THEN NULL
        ELSE pgp_sym_encrypt_bytea(%(photo_data)s, %(encryption_key)s)
    END,
    %(photo_mimetype)s
)
RETURNING id, title, photo_mimetype, created_at
"""


READ_RECIPE_SQL = """
SELECT
    r.id,
    r.title,
    pgp_sym_decrypt(r.steps, %(encryption_key)s) AS steps,
    CASE
        WHEN r.photo_data IS NULL THEN NULL
        ELSE pgp_sym_decrypt_bytea(r.photo_data, %(encryption_key)s)
    END AS photo_data,
    r.photo_mimetype,
    r.created_at
FROM recipes AS r
WHERE r.id = %(recipe_id)s
"""

# Browse/search plan:
# 1. LEFT JOIN ingredients and tags so a recipe still appears when it has no
#    ingredient rows or tags.
# 2. Search only plaintext title and ingredient name with ILIKE. The encrypted
#    steps and photo bytes are deliberately never decrypted for a list page.
# 3. Apply a case-insensitive exact tag match only when a tag was requested.
# 4. JOINs can produce several rows per recipe, so DISTINCT folds them back to
#    one card. The small personal collection makes this clear query preferable
#    to a heavier search dependency; a future large collection could add
#    PostgreSQL trigram indexes for the two ILIKE columns.
LIST_RECIPES_SQL = """
SELECT DISTINCT
    r.id,
    r.title,
    r.created_at,
    (r.photo_data IS NOT NULL) AS has_photo
FROM recipes AS r
LEFT JOIN ingredients AS i
    ON i.recipe_id = r.id
LEFT JOIN recipe_tags AS rt
    ON rt.recipe_id = r.id
LEFT JOIN tags AS t
    ON t.id = rt.tag_id
WHERE (
    %(search_pattern)s::text IS NULL
    OR r.title ILIKE %(search_pattern)s::text
    OR i.name ILIKE %(search_pattern)s::text
)
AND (
    %(tag_name)s::text IS NULL
    OR LOWER(t.name) = LOWER(%(tag_name)s::text)
)
ORDER BY r.created_at DESC, r.id DESC
"""

LIST_TAGS_SQL = """
SELECT id, name
FROM tags
ORDER BY LOWER(name), id
"""

# The browse query returns only a boolean indicating whether a photo exists.
# This separate query decrypts bytes only when an img tag requests a thumbnail,
# keeping normal list/search operations from doing unnecessary decryption.
READ_RECIPE_PHOTO_SQL = """
SELECT
    pgp_sym_decrypt_bytea(r.photo_data, %(encryption_key)s) AS photo_data,
    r.photo_mimetype
FROM recipes AS r
WHERE r.id = %(recipe_id)s
  AND r.photo_data IS NOT NULL
"""

# Detail query plan:
# 1. Select exactly one recipe by primary key and decrypt its steps here because
#    the detail page is the only page that needs plaintext instructions.
# 2. Use two lateral subqueries to join and aggregate ingredients and tags into
#    JSON arrays. Aggregating each child relationship separately avoids the
#    ingredient-count-by-tag-count row multiplication of a three-table JOIN.
# 3. Do not decrypt photo_data in the HTML query. The template points to the
#    dedicated photo endpoint, which decrypts image bytes only briefly while
#    constructing the binary response. In both cases, plaintext exists only
#    for the request that immediately sends it to the client.
READ_RECIPE_DETAIL_SQL = """
SELECT
    r.id,
    r.title,
    pgp_sym_decrypt(r.steps, %(encryption_key)s) AS steps,
    (r.photo_data IS NOT NULL) AS has_photo,
    r.photo_mimetype,
    r.created_at,
    ingredient_rows.items AS ingredients,
    tag_rows.items AS tags
FROM recipes AS r
LEFT JOIN LATERAL (
    SELECT COALESCE(
        json_agg(
            json_build_object(
                'id', i.id,
                'name', i.name,
                'quantity', i.quantity,
                'unit', i.unit
            )
            ORDER BY i.id
        ),
        '[]'::json
    ) AS items
    FROM ingredients AS i
    WHERE i.recipe_id = r.id
) AS ingredient_rows ON TRUE
LEFT JOIN LATERAL (
    SELECT COALESCE(
        json_agg(
            json_build_object(
                'id', t.id,
                'name', t.name
            )
            ORDER BY LOWER(t.name), t.id
        ),
        '[]'::json
    ) AS items
    FROM recipe_tags AS rt
    INNER JOIN tags AS t
        ON t.id = rt.tag_id
    WHERE rt.recipe_id = r.id
) AS tag_rows ON TRUE
WHERE r.id = %(recipe_id)s
"""

# Delete children explicitly even though the schema also has ON DELETE CASCADE.
# The statements make the ownership relationship obvious here and remain
# atomic because delete_recipe executes all three on the caller's transaction.
DELETE_RECIPE_TAGS_SQL = """
DELETE FROM recipe_tags
WHERE recipe_id = %(recipe_id)s
"""

DELETE_INGREDIENTS_SQL = """
DELETE FROM ingredients
WHERE recipe_id = %(recipe_id)s
"""

DELETE_RECIPE_SQL = """
DELETE FROM recipes
WHERE id = %(recipe_id)s
"""

DELETE_TAG_RELATIONSHIPS_SQL = """
DELETE FROM recipe_tags
WHERE tag_id = %(tag_id)s
"""

DELETE_TAG_SQL = """
DELETE FROM tags
WHERE id = %(tag_id)s
"""

# Encryption-on-write path:
# - The route receives plaintext form values and raw photo bytes in memory.
# - These INSERT/UPDATE statements call pgcrypto immediately at the database
#   boundary, so the persisted recipes table receives ciphertext in `steps` and
#   `photo_data`, never the plaintext values.
# - `photo_data` is updated only when a new upload is provided; an edit without
#   a new file preserves the existing encrypted photo and MIME type.
UPDATE_RECIPE_SQL = """
UPDATE recipes
SET
    title = %(title)s,
    steps = pgp_sym_encrypt(%(steps)s, %(encryption_key)s),
    photo_data = pgp_sym_encrypt_bytea(%(photo_data)s, %(encryption_key)s),
    photo_mimetype = %(photo_mimetype)s
WHERE id = %(recipe_id)s
"""

UPDATE_RECIPE_WITHOUT_PHOTO_SQL = """
UPDATE recipes
SET
    title = %(title)s,
    steps = pgp_sym_encrypt(%(steps)s, %(encryption_key)s)
WHERE id = %(recipe_id)s
"""

INSERT_INGREDIENT_SQL = """
INSERT INTO ingredients (recipe_id, name, quantity, unit)
VALUES (%(recipe_id)s, %(name)s, %(quantity)s, %(unit)s)
"""

INSERT_TAG_SQL = """
INSERT INTO tags (name)
VALUES (%s)
ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
RETURNING id
"""

FIND_TAG_SQL = """
SELECT id
FROM tags
WHERE LOWER(name) = LOWER(%s)
LIMIT 1
"""

INSERT_RECIPE_TAG_SQL = """
INSERT INTO recipe_tags (recipe_id, tag_id)
VALUES (%s, %s)
ON CONFLICT DO NOTHING
"""


def get_encryption_key() -> str:
    """Return the validated symmetric pgcrypto key from central config.

    Returns:
        str: The non-empty value used by pgp_sym_encrypt and pgp_sym_decrypt.

    Why it exists:
        config.py validates ENCRYPTION_KEY once at startup. Keeping this small
        accessor preserves the explicit encryption boundary in this module
        without allowing environment reads to spread across the codebase.
    """

    return settings.encryption_key


def insert_recipe(
    connection,
    title: str,
    steps: str,
    photo_data: bytes | None = None,
    photo_mimetype: str | None = None,
):
    """Insert one recipe while encrypting its sensitive payloads.

    Args:
        connection: An open psycopg2 connection whose transaction is owned by
            the caller.
        title: Plain-text recipe title, retained for normal display/search.
        steps: Plain-text preparation instructions, encrypted before storage.
        photo_data: Optional raw image bytes, encrypted before storage.
        photo_mimetype: Optional plain-text MIME type needed to render the
            decrypted image bytes correctly.

    Returns:
        tuple | None: The inserted recipe metadata returned by PostgreSQL.

    Why it exists:
        Recipe steps and photo bytes are the sensitive fields identified by the
        product requirements. The database receives only pgcrypto ciphertext
        for those fields; the caller still controls the surrounding transaction.
    """

    parameters = {
        "title": title,
        "steps": steps,
        "photo_data": photo_data,
        "photo_mimetype": photo_mimetype,
        "encryption_key": get_encryption_key(),
    }
    with connection.cursor() as cursor:
        cursor.execute(INSERT_RECIPE_SQL, parameters)
        return cursor.fetchone()


def read_recipe(connection, recipe_id: int):
    """Read one recipe and decrypt its protected fields in PostgreSQL.

    Args:
        connection: An open psycopg2 connection whose transaction is owned by
            the caller.
        recipe_id: The numeric recipe identifier to retrieve.

    Returns:
        tuple | None: The recipe row with plaintext steps and optional photo
            bytes, or None when the ID does not exist.

    Why it exists:
        pgp_sym_decrypt and pgp_sym_decrypt_bytea keep decryption close to the
        encrypted columns. The key is read from ENCRYPTION_KEY for this request
        and is never selected from, or written to, the database.
    """

    parameters = {
        "recipe_id": recipe_id,
        "encryption_key": get_encryption_key(),
    }
    with connection.cursor() as cursor:
        cursor.execute(READ_RECIPE_SQL, parameters)
        return cursor.fetchone()


def list_recipes(connection, search: str | None = None, tag_name: str | None = None):
    """Return recipes matching the optional browse filters.

    Args:
        connection: An open psycopg2 connection whose transaction is owned by
            the caller.
        search: Optional text matched against plaintext title or ingredient
            name using a case-insensitive partial match.
        tag_name: Optional case-insensitive tag name to match exactly.

    Returns:
        list[dict]: One dictionary per recipe card, including a boolean that
            tells the template whether to request a photo thumbnail.

    Why it exists:
        Searchable fields stay plaintext by design, while encrypted recipe
        payloads are excluded from the browse query for both privacy and speed.
    """

    normalized_search = search.strip() if search else ""
    normalized_tag = tag_name.strip() if tag_name else ""
    parameters = {
        "search_pattern": f"%{normalized_search}%" if normalized_search else None,
        "tag_name": normalized_tag if normalized_tag else None,
    }
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(LIST_RECIPES_SQL, parameters)
        return list(cursor.fetchall())


def list_tags(connection):
    """Return all tags in display order for the browse filter chips.

    Args:
        connection: An open psycopg2 connection whose transaction is owned by
            the caller.

    Returns:
        list[dict]: Tag IDs and names used to build filter links above the
            recipe list.

    Why it exists:
        Keeping tag retrieval separate from recipe retrieval lets the page
        render all available filters even when the active filter has no matches.
    """

    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(LIST_TAGS_SQL)
        return list(cursor.fetchall())


def delete_tag(connection, tag_id: int) -> bool:
    """Delete one tag and all of its recipe associations atomically.

    Args:
        connection: An open psycopg2 connection. The caller owns the
            transaction and commits only after both delete statements succeed.
        tag_id: The numeric tag identifier to delete.

    Returns:
        bool: True when a tag row was deleted, otherwise False.

    Why it exists:
        Tag cleanup must never delete recipes. Removing the join rows first
        makes that ownership boundary explicit, then the tag itself is removed
        in the same transaction; the schema cascade remains a safety net.
    """

    parameters = {"tag_id": tag_id}
    with connection.cursor() as cursor:
        cursor.execute(DELETE_TAG_RELATIONSHIPS_SQL, parameters)
        cursor.execute(DELETE_TAG_SQL, parameters)
        return cursor.rowcount == 1


def read_recipe_photo(connection, recipe_id: int):
    """Read and decrypt one recipe photo for the dedicated image endpoint.

    Args:
        connection: An open psycopg2 connection whose transaction is owned by
            the caller.
        recipe_id: The numeric recipe identifier whose encrypted photo to read.

    Returns:
        tuple | None: Decrypted photo bytes and their stored MIME type, or None
            when the recipe does not exist or has no photo.

    Why it exists:
        Browsing needs a stable image URL, but photo bytes must remain encrypted
        in PostgreSQL. This query is the only read path used by that URL.
    """

    parameters = {
        "recipe_id": recipe_id,
        "encryption_key": get_encryption_key(),
    }
    with connection.cursor() as cursor:
        cursor.execute(READ_RECIPE_PHOTO_SQL, parameters)
        return cursor.fetchone()


def read_recipe_detail(connection, recipe_id: int):
    """Read one recipe with decrypted steps and aggregated child rows.

    Args:
        connection: An open psycopg2 connection whose transaction is owned by
            the caller.
        recipe_id: The numeric recipe identifier to retrieve.

    Returns:
        dict | None: A recipe detail row containing plaintext steps, photo
            availability, and JSON-decoded ingredient/tag arrays.

    Why it exists:
        Detail pages need the protected instructions, but browse pages do not.
        Keeping this decryption in the detail query limits plaintext steps to
        the short-lived request that renders the page.
    """

    parameters = {
        "recipe_id": recipe_id,
        "encryption_key": get_encryption_key(),
    }
    with connection.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(READ_RECIPE_DETAIL_SQL, parameters)
        return cursor.fetchone()


def delete_recipe(connection, recipe_id: int) -> bool:
    """Delete one recipe and its child rows within the caller's transaction.

    Args:
        connection: An open psycopg2 connection. The caller must use a
            transaction context and must not commit partial statements.
        recipe_id: The numeric recipe identifier to delete.

    Returns:
        bool: True when a recipe row was deleted, otherwise False.

    Why it exists:
        A recipe owns its ingredients and tag links. Deleting all three tables
        in one transaction prevents a failed request from leaving a half-
        deleted recipe behind; the schema's cascades provide a second safety
        net for other deletion paths.
    """

    parameters = {"recipe_id": recipe_id}
    with connection.cursor() as cursor:
        cursor.execute(DELETE_RECIPE_TAGS_SQL, parameters)
        cursor.execute(DELETE_INGREDIENTS_SQL, parameters)
        cursor.execute(DELETE_RECIPE_SQL, parameters)
        return cursor.rowcount == 1


def _replace_ingredients_and_tags(
    connection,
    recipe_id: int,
    ingredients: list[dict[str, str]],
    tag_names: list[str],
) -> None:
    """Replace all child rows for a recipe inside the current transaction.

    Args:
        connection: An open psycopg2 connection whose transaction is owned by
            the caller.
        recipe_id: The parent recipe identifier.
        ingredients: Form-derived ingredient dictionaries with name, quantity,
            and unit values.
        tag_names: Normalized tag names submitted by the form.

    Why it exists:
        Editing a recipe is simplest and safest when its submitted child
        collection becomes the source of truth. The caller's transaction makes
        the delete-and-reinsert operation atomic with the recipe write.
    """

    with connection.cursor() as cursor:
        cursor.execute(DELETE_RECIPE_TAGS_SQL, {"recipe_id": recipe_id})
        cursor.execute(DELETE_INGREDIENTS_SQL, {"recipe_id": recipe_id})

        for ingredient in ingredients:
            name = ingredient.get("name", "").strip()
            if not name:
                continue

            cursor.execute(
                INSERT_INGREDIENT_SQL,
                {
                    "recipe_id": recipe_id,
                    "name": name,
                    "quantity": ingredient.get("quantity", "").strip() or None,
                    "unit": ingredient.get("unit", "").strip() or None,
                },
            )

        for tag_name in tag_names:
            cursor.execute(FIND_TAG_SQL, (tag_name,))
            tag_row = cursor.fetchone()
            if tag_row is None:
                cursor.execute(INSERT_TAG_SQL, (tag_name,))
                tag_row = cursor.fetchone()

            cursor.execute(INSERT_RECIPE_TAG_SQL, (recipe_id, tag_row[0]))


def _normalize_tag_names(tag_names: list[str]) -> list[str]:
    """Trim and de-duplicate tag input while preserving display casing.

    Args:
        tag_names: Raw tag values, typically split from a comma-separated form
            field.

    Returns:
        list[str]: Non-empty tags in their first-submitted order.

    Why it exists:
        A small normalization step avoids duplicate chips and duplicate join
        rows while allowing the user to type tags naturally.
    """

    normalized: list[str] = []
    seen: set[str] = set()
    for raw_tag in tag_names:
        tag_name = raw_tag.strip()
        key = tag_name.casefold()
        if tag_name and key not in seen:
            normalized.append(tag_name)
            seen.add(key)
    return normalized


def create_recipe(
    connection,
    title: str,
    steps: str,
    ingredients: list[dict[str, str]],
    tag_names: list[str],
    photo_data: bytes | None = None,
    photo_mimetype: str | None = None,
) -> int:
    """Insert a recipe and all related rows atomically.

    Args:
        connection: An open psycopg2 connection. The caller owns the
            transaction and commits only after this function returns.
        title: Plain-text recipe title.
        steps: Plain-text form instructions, encrypted by the INSERT query.
        ingredients: Submitted ingredient rows.
        tag_names: Submitted tag names, created or reused as needed.
        photo_data: Optional raw upload bytes, encrypted by the INSERT query.
        photo_mimetype: Optional MIME type stored beside the encrypted photo.

    Returns:
        int: The newly created recipe ID.

    Why it exists:
        This function traces the complete write path: plaintext arrives from
        the form, pgcrypto encrypts sensitive fields in SQL, and child rows are
        written before the caller's transaction commits the complete recipe.
    """

    parameters = {
        "title": title,
        "steps": steps,
        "photo_data": photo_data,
        "photo_mimetype": photo_mimetype,
        "encryption_key": get_encryption_key(),
    }
    with connection.cursor() as cursor:
        cursor.execute(INSERT_RECIPE_SQL, parameters)
        recipe_id = cursor.fetchone()[0]

    _replace_ingredients_and_tags(
        connection,
        recipe_id,
        ingredients,
        _normalize_tag_names(tag_names),
    )
    return recipe_id


def update_recipe(
    connection,
    recipe_id: int,
    title: str,
    steps: str,
    ingredients: list[dict[str, str]],
    tag_names: list[str],
    photo_data: bytes | None = None,
    photo_mimetype: str | None = None,
) -> bool:
    """Update a recipe and replace its child rows atomically.

    Args:
        connection: An open psycopg2 connection. The caller owns the
            transaction and commits only after this function returns.
        recipe_id: The recipe identifier to update.
        title: Plain-text recipe title.
        steps: Plain-text form instructions, encrypted by the UPDATE query.
        ingredients: Submitted ingredient rows replacing the old collection.
        tag_names: Submitted tag names replacing the old tag links.
        photo_data: Optional new raw upload bytes. None preserves the old
            encrypted photo.
        photo_mimetype: MIME type for a new photo upload.

    Returns:
        bool: True when the recipe exists and was updated; otherwise False.

    Why it exists:
        The update follows the same plaintext → pgcrypto → ciphertext path as
        creation while making the no-new-photo edit case explicit. Recipe,
        ingredient, and tag changes share one transaction.
    """

    parameters = {
        "recipe_id": recipe_id,
        "title": title,
        "steps": steps,
        "encryption_key": get_encryption_key(),
    }
    with connection.cursor() as cursor:
        if photo_data is None:
            cursor.execute(UPDATE_RECIPE_WITHOUT_PHOTO_SQL, parameters)
        else:
            parameters.update(
                {
                    "photo_data": photo_data,
                    "photo_mimetype": photo_mimetype,
                }
            )
            cursor.execute(UPDATE_RECIPE_SQL, parameters)

        updated = cursor.rowcount == 1

    if not updated:
        return False

    _replace_ingredients_and_tags(
        connection,
        recipe_id,
        ingredients,
        _normalize_tag_names(tag_names),
    )
    return True
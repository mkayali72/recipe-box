-- -----------------------------------------------------------------------------
-- Recipe Box initial database schema.
-- This migration enables pgcrypto and creates the recipe, ingredient, tag, and
-- many-to-many join tables. Recipe steps and photo bytes are stored as pgcrypto
-- ciphertext; searchable ingredient and tag fields remain ordinary text.
-- -----------------------------------------------------------------------------

-- pgcrypto provides pgp_sym_encrypt/pgp_sym_decrypt and their bytea variants.
-- It is installed once per database and is safe to request on every migration
-- run because IF NOT EXISTS makes this statement idempotent.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Recipe steps are encrypted with pgp_sym_encrypt on write and therefore use
-- bytea for the ciphertext. The symmetric key is supplied by the application
-- query layer at runtime and never stored in this schema.
CREATE TABLE IF NOT EXISTS recipes (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    steps BYTEA NOT NULL,
    photo_data BYTEA,
    photo_mimetype TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Each ingredient line is a separate row so names, quantities, and units can
-- be searched or edited independently without decrypting the recipe steps.
CREATE TABLE IF NOT EXISTS ingredients (
    id BIGSERIAL PRIMARY KEY,
    recipe_id BIGINT NOT NULL REFERENCES recipes (id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    quantity TEXT,
    unit TEXT
);

-- Tags are intentionally plain text because they are not sensitive and need
-- to remain searchable and reusable across recipes.
CREATE TABLE IF NOT EXISTS tags (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

-- The composite primary key prevents the same tag from being attached to a
-- recipe more than once. Cascades keep the join table tidy on deletion.
CREATE TABLE IF NOT EXISTS recipe_tags (
    recipe_id BIGINT NOT NULL REFERENCES recipes (id) ON DELETE CASCADE,
    tag_id BIGINT NOT NULL REFERENCES tags (id) ON DELETE CASCADE,
    PRIMARY KEY (recipe_id, tag_id)
);

-- Foreign-key indexes keep common ingredient and tag lookups efficient while
-- leaving the searchable text columns unencrypted.
CREATE INDEX IF NOT EXISTS ingredients_recipe_id_idx
    ON ingredients (recipe_id);

CREATE INDEX IF NOT EXISTS recipe_tags_tag_id_idx
    ON recipe_tags (tag_id);
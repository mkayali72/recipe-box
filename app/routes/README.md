<!--
Recipe Box route package map.
This directory holds focused FastAPI routers that are aggregated by
app/routes/__init__.py before being mounted by app.main.
-->

# Routes

- `browse.py` — home page search/filter results and decrypted photo responses.
- `detail.py` — recipe detail rendering and atomic deletion.
- `editor.py` — create/edit forms and transactional recipe saves.

Keep future route modules focused and register them from this package's
aggregate router.
# -----------------------------------------------------------------------------
# Recipe Box browse and search routes.
# This module serves the home page, its plaintext search/tag filters, and the
# dedicated decrypted photo response used by recipe card thumbnails.
# -----------------------------------------------------------------------------

import psycopg2
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.config import settings
from app.db.queries import delete_tag, list_recipes, list_tags, read_recipe_photo


router = APIRouter()


@router.get("/", response_class=HTMLResponse, name="browse")
def browse_recipes(
    request: Request,
    search: str | None = Query(default=None, max_length=200),
    tag: str | None = Query(default=None, max_length=100),
):
    """Render the Recipe Box home page with optional search filters.

    Args:
        request: The current FastAPI request, used to access shared templates.
        search: Optional text searched against recipe titles and ingredient
            names.
        tag: Optional exact tag name used to narrow the recipe list.

    Returns:
        HTMLResponse: A lightweight Jinja2 page containing recipe cards and
            filter controls.

    Why it exists:
        The home page is the primary way to find saved recipes. Its route keeps
        HTTP query parameters small and delegates all SQL to db/queries.py.
    """

    with psycopg2.connect(settings.database_url) as connection:
        recipes = list_recipes(connection, search=search, tag_name=tag)
        tags = list_tags(connection)

    return request.app.state.templates.TemplateResponse(
        request=request,
        name="home.html",
        context={
            "recipes": recipes,
            "tags": tags,
            "search": search.strip() if search else "",
            "active_tag": tag.strip() if tag else "",
        },
    )


@router.post("/tags/{tag_id}/delete", name="delete_tag")
def remove_tag(tag_id: int):
    """Delete one tag and redirect to the unfiltered browse page.

    Args:
        tag_id: The numeric tag identifier submitted by the browse-page form.

    Returns:
        RedirectResponse: A 303 redirect to the home page after tag deletion.

    Raises:
        HTTPException: If the requested tag does not exist.

    Why it exists:
        Tag management belongs on the browse page for this single-user app.
        The query helper removes only recipe-tag links and the tag row, never
        the recipes those links referenced.
    """

    with psycopg2.connect(settings.database_url) as connection:
        deleted = delete_tag(connection, tag_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Tag not found.")

    return RedirectResponse(url="/", status_code=303)


@router.get("/recipes/{recipe_id}/photo", name="recipe_photo")
def recipe_photo(recipe_id: int):
    """Return one recipe photo after decrypting it inside PostgreSQL.

    Args:
        recipe_id: The numeric recipe identifier from the card image URL.

    Returns:
        Response: Raw decrypted bytes with the MIME type stored for the photo.

    Raises:
        HTTPException: If the recipe does not exist or has no photo.

    Why it exists:
        Recipe cards can use ordinary `<img src>` URLs without embedding
        encrypted data in HTML or exposing plaintext photo bytes in the list
        query.
    """

    with psycopg2.connect(settings.database_url) as connection:
        photo = read_recipe_photo(connection, recipe_id)

    if photo is None:
        raise HTTPException(status_code=404, detail="Recipe photo not found.")

    photo_data, photo_mimetype = photo
    return Response(
        content=photo_data,
        media_type=photo_mimetype or "application/octet-stream",
    )
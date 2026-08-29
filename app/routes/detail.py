# -----------------------------------------------------------------------------
# Recipe Box detail and deletion routes.
# This module renders one recipe with its decrypted instructions and provides
# the atomic POST action that removes a recipe and its owned child rows.
# -----------------------------------------------------------------------------

import psycopg2
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import settings
from app.db.queries import delete_recipe, read_recipe_detail


router = APIRouter()


@router.get("/recipes/{recipe_id}", response_class=HTMLResponse, name="recipe_detail")
def recipe_detail(request: Request, recipe_id: int):
    """Render one recipe with ingredients, tags, steps, and its photo URL.

    Args:
        request: The current FastAPI request, used to access shared templates.
        recipe_id: The numeric recipe identifier from the requested URL.

    Returns:
        HTMLResponse: A server-rendered detail page. The image is loaded through
            the separate recipe photo endpoint so its bytes are not embedded in
            the HTML response.

    Raises:
        HTTPException: If the requested recipe does not exist.

    Why it exists:
        This is the intentional boundary where encrypted steps become
        plaintext in memory for the brief time needed to render the detail
        page. Photo bytes remain in the dedicated photo response path.
    """

    with psycopg2.connect(settings.database_url) as connection:
        recipe = read_recipe_detail(connection, recipe_id)

    if recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found.")

    return request.app.state.templates.TemplateResponse(
        request=request,
        name="recipe_detail.html",
        context={"recipe": recipe},
    )


@router.post("/recipes/{recipe_id}/delete", name="delete_recipe")
def remove_recipe(recipe_id: int):
    """Atomically delete a recipe and redirect back to the browse page.

    Args:
        recipe_id: The numeric recipe identifier submitted by the detail form.

    Returns:
        RedirectResponse: A 303 redirect to the home page after deletion.

    Raises:
        HTTPException: If the requested recipe does not exist.

    Why it exists:
        The POST-only action prevents accidental deletion through a normal
        browser link, while the database transaction keeps child-row cleanup
        all-or-nothing.
    """

    with psycopg2.connect(settings.database_url) as connection:
        deleted = delete_recipe(connection, recipe_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Recipe not found.")

    return RedirectResponse(url="/", status_code=303)
# -----------------------------------------------------------------------------
# Recipe Box create/edit form routes.
# This module parses lightweight multipart forms, reads optional photo uploads
# as-is, and delegates the complete encrypted save to transactional db helpers.
# -----------------------------------------------------------------------------

from collections.abc import Mapping

import psycopg2
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.datastructures import UploadFile

from app.config import settings
from app.db.queries import create_recipe, read_recipe_detail, update_recipe


router = APIRouter()


def _recipe_form_context(
    *,
    mode: str,
    form_values: dict[str, str],
    ingredients: list[dict[str, str]],
    tags_text: str,
    errors: list[str] | None = None,
    recipe=None,
) -> dict:
    """Build the shared create/edit template context.

    Args:
        mode: Either "new" or "edit", controlling labels and form action.
        form_values: Current title and steps values to display.
        ingredients: Current ingredient rows to display.
        tags_text: Comma-separated tag input value.
        errors: Optional validation messages to show above the form.
        recipe: Existing database row when editing, otherwise None.

    Returns:
        dict: Values required by recipe_form.html.

    Why it exists:
        New and edit screens intentionally share one form, so validation errors
        can return the user to the same form without duplicating templates.
    """

    return {
        "mode": mode,
        "form_values": form_values,
        "ingredients": ingredients or [{"name": "", "quantity": "", "unit": ""}],
        "tags_text": tags_text,
        "errors": errors or [],
        "recipe": recipe,
    }


def _render_recipe_form(
    request: Request,
    *,
    mode: str,
    form_values: dict[str, str],
    ingredients: list[dict[str, str]],
    tags_text: str,
    errors: list[str] | None = None,
    recipe=None,
    status_code: int = 200,
):
    """Render the shared recipe form with the supplied state.

    Args:
        request: Current request used to access the configured template engine.
        mode: Either "new" or "edit".
        form_values: Current title and steps values.
        ingredients: Ingredient rows to display.
        tags_text: Comma-separated tag input value.
        errors: Optional validation messages.
        recipe: Existing recipe detail row for edit mode.
        status_code: HTTP status to use when redisplaying invalid input.

    Returns:
        HTMLResponse: The server-rendered recipe form.

    Why it exists:
        Keeping rendering separate from persistence ensures invalid input never
        opens a database transaction or partially changes a recipe.
    """

    return request.app.state.templates.TemplateResponse(
        request=request,
        name="recipe_form.html",
        context=_recipe_form_context(
            mode=mode,
            form_values=form_values,
            ingredients=ingredients,
            tags_text=tags_text,
            errors=errors,
            recipe=recipe,
        ),
        status_code=status_code,
    )


def _text_value(form: Mapping, field_name: str) -> str:
    """Read one form value as trimmed text.

    Args:
        form: Starlette multipart form mapping.
        field_name: Name of the field to read.

    Returns:
        str: Trimmed text, or an empty string when absent.

    Why it exists:
        Multipart fields may be strings or upload objects; this keeps normal
        text extraction explicit and predictable.
    """

    value = form.get(field_name, "")
    return value.strip() if isinstance(value, str) else ""


def _ingredient_values(form: Mapping) -> list[dict[str, str]]:
    """Collect repeated ingredient inputs in their browser order.

    Args:
        form: Starlette multipart form mapping.

    Returns:
        list[dict[str, str]]: Ingredient dictionaries ready for query helpers.

    Why it exists:
        The vanilla JS form adds repeated fields with the same names, and
        `getlist` preserves each row's position across name/quantity/unit.
    """

    names = form.getlist("ingredient_name")
    quantities = form.getlist("ingredient_quantity")
    units = form.getlist("ingredient_unit")
    rows: list[dict[str, str]] = []

    for index, raw_name in enumerate(names):
        rows.append(
            {
                "name": raw_name.strip() if isinstance(raw_name, str) else "",
                "quantity": (
                    quantities[index].strip()
                    if index < len(quantities) and isinstance(quantities[index], str)
                    else ""
                ),
                "unit": (
                    units[index].strip()
                    if index < len(units) and isinstance(units[index], str)
                    else ""
                ),
            }
        )
    return rows


def _tag_values(form: Mapping) -> list[str]:
    """Split the comma-separated tag field into raw tag names.

    Args:
        form: Starlette multipart form mapping.

    Returns:
        list[str]: Raw tag parts; query helpers perform final normalization.

    Why it exists:
        A single input is quick to use while still allowing users to create
        several tags during one save without a tag-management screen.
    """

    return _text_value(form, "tags").split(",")


async def _photo_values(form: Mapping) -> tuple[bytes | None, str | None]:
    """Read an optional uploaded photo without imposing an application cap.

    Args:
        form: Starlette multipart form mapping containing the multipart upload.

    Returns:
        tuple[bytes | None, str | None]: Raw bytes and MIME type for a new
            upload, or a pair of None values when no new file was selected.

    Why it exists:
        The requirement is to accept the file as-is. This function performs no
        size check or transformation; encryption happens later in the database
        query before the transaction commits.
    """

    uploaded = form.get("photo")
    if not isinstance(uploaded, UploadFile) or not uploaded.filename:
        return None, None

    return await uploaded.read(), uploaded.content_type or "application/octet-stream"


def _form_values(form: Mapping) -> dict[str, str]:
    """Collect the scalar fields shared by create and edit submissions.

    Args:
        form: Starlette multipart form mapping.

    Returns:
        dict[str, str]: Title and steps values for validation or persistence.

    Why it exists:
        Keeping scalar extraction in one place makes create/edit behavior match
        and ensures returned validation forms show exactly what was submitted.
    """

    return {
        "title": _text_value(form, "title"),
        "steps": _text_value(form, "steps"),
    }


def _validation_errors(form_values: dict[str, str]) -> list[str]:
    """Return user-facing validation errors for required recipe fields.

    Args:
        form_values: Extracted title and steps values.

    Returns:
        list[str]: Empty when valid, otherwise clear messages for the form.

    Why it exists:
        Title and steps are the only required textual values in this first
        form; ingredient rows may be added incrementally in later edits.
    """

    errors: list[str] = []
    if not form_values["title"]:
        errors.append("A recipe title is required.")
    if not form_values["steps"]:
        errors.append("Recipe steps are required.")
    return errors


@router.get("/recipes/new", response_class=HTMLResponse, name="new_recipe")
def new_recipe_form(request: Request):
    """Render an empty form for creating a recipe.

    Args:
        request: Current request used to access the configured template engine.

    Returns:
        HTMLResponse: The blank recipe form.

    Why it exists:
        This page provides the entry point for the first recipe write flow.
    """

    return _render_recipe_form(
        request,
        mode="new",
        form_values={"title": "", "steps": ""},
        ingredients=[],
        tags_text="",
    )


@router.post("/recipes/new", response_class=HTMLResponse, name="create_recipe")
async def create_recipe_form(request: Request):
    """Validate and persist a new recipe from a multipart form.

    Args:
        request: Current multipart request containing fields and an optional
            photo upload.

    Returns:
        RedirectResponse | HTMLResponse: Redirects to the saved detail page or
            redisplays the form with validation errors.

    Why it exists:
        This is the HTTP boundary where plaintext form data enters the
        transaction; db.create_recipe encrypts sensitive fields before storage.
    """

    form = await request.form()
    form_values = _form_values(form)
    ingredients = _ingredient_values(form)
    tags_text = _text_value(form, "tags")
    errors = _validation_errors(form_values)
    if errors:
        return _render_recipe_form(
            request,
            mode="new",
            form_values=form_values,
            ingredients=ingredients,
            tags_text=tags_text,
            errors=errors,
            status_code=400,
        )

    photo_data, photo_mimetype = await _photo_values(form)
    with psycopg2.connect(settings.database_url) as connection:
        recipe_id = create_recipe(
            connection,
            title=form_values["title"],
            steps=form_values["steps"],
            ingredients=ingredients,
            tag_names=_tag_values(form),
            photo_data=photo_data,
            photo_mimetype=photo_mimetype,
        )

    return RedirectResponse(
        url=str(request.url_for("recipe_detail", recipe_id=recipe_id)),
        status_code=303,
    )


@router.get(
    "/recipes/{recipe_id}/edit",
    response_class=HTMLResponse,
    name="edit_recipe",
)
def edit_recipe_form(request: Request, recipe_id: int):
    """Render the existing recipe in the shared edit form.

    Args:
        request: Current request used to access the configured template engine.
        recipe_id: The numeric recipe identifier to edit.

    Returns:
        HTMLResponse: The populated edit form.

    Raises:
        HTTPException: If the recipe does not exist.

    Why it exists:
        The detail query decrypts steps only for this intentional edit/detail
        request, then the form posts the updated plaintext through encrypted
        save SQL.
    """

    with psycopg2.connect(settings.database_url) as connection:
        recipe = read_recipe_detail(connection, recipe_id)

    if recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found.")

    return _render_recipe_form(
        request,
        mode="edit",
        form_values={"title": recipe["title"], "steps": recipe["steps"]},
        ingredients=list(recipe["ingredients"]),
        tags_text=", ".join(tag["name"] for tag in recipe["tags"]),
        recipe=recipe,
    )


@router.post(
    "/recipes/{recipe_id}/edit",
    response_class=HTMLResponse,
    name="update_recipe",
)
async def update_recipe_form(request: Request, recipe_id: int):
    """Validate and persist edits to one recipe atomically.

    Args:
        request: Current multipart request containing edited fields and an
            optional replacement photo.
        recipe_id: The numeric recipe identifier to update.

    Returns:
        RedirectResponse | HTMLResponse: Redirects to the updated detail page
            or redisplays invalid input.

    Raises:
        HTTPException: If the recipe does not exist.

    Why it exists:
        All recipe, ingredient, tag, and optional encrypted photo changes are
        delegated to one transaction so a failed save cannot partially apply.
    """

    form = await request.form()
    form_values = _form_values(form)
    ingredients = _ingredient_values(form)
    tags_text = _text_value(form, "tags")
    errors = _validation_errors(form_values)

    if errors:
        return _render_recipe_form(
            request,
            mode="edit",
            form_values=form_values,
            ingredients=ingredients,
            tags_text=tags_text,
            errors=errors,
            status_code=400,
        )

    photo_data, photo_mimetype = await _photo_values(form)
    with psycopg2.connect(settings.database_url) as connection:
        updated = update_recipe(
            connection,
            recipe_id=recipe_id,
            title=form_values["title"],
            steps=form_values["steps"],
            ingredients=ingredients,
            tag_names=_tag_values(form),
            photo_data=photo_data,
            photo_mimetype=photo_mimetype,
        )

    if not updated:
        raise HTTPException(status_code=404, detail="Recipe not found.")

    return RedirectResponse(
        url=str(request.url_for("recipe_detail", recipe_id=recipe_id)),
        status_code=303,
    )
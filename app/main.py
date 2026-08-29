# -----------------------------------------------------------------------------
# Recipe Box application entry point and request flow.
# Request flow: request → route → db/queries.py → template render.
# A request enters FastAPI, is dispatched to a route, the route uses
# db/queries.py for PostgreSQL work, and the result is rendered through a
# Jinja2 template. This flow keeps HTTP behavior, data access, and presentation
# easy to follow as the app grows.
# -----------------------------------------------------------------------------

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from app.config import settings
from app.db.migrate import run_migrations
from app.routes import router


BASE_DIR = Path(__file__).resolve().parent

def create_app() -> FastAPI:
    """Create the Recipe Box FastAPI application.

    Returns:
        FastAPI: A configured application instance ready for Uvicorn.

    Why it exists:
        Keeping app construction in a factory makes future tests and alternate
        entry points possible without coupling them to module import side
        effects.
    """

    application = FastAPI(
        title="Recipe Box",
        description="A personal single-user recipe collection.",
        version="0.1.0",
    )

    static_directory = BASE_DIR / "static"
    templates_directory = BASE_DIR / "templates"

    # The directories are part of the initial project contract. Mounting
    # static assets now gives later UI work a stable path without implementing
    # any recipe routes yet.
    application.mount(
        "/static",
        StaticFiles(directory=static_directory),
        name="static",
    )

    # Keep the template environment available for route handlers. Templates
    # are configured here so every route uses the same Jinja2 environment.
    application.state.templates = Jinja2Templates(directory=templates_directory)
    application.state.settings = settings
    application.include_router(router)

    @application.on_event("startup")
    def initialize_database() -> None:
        """Apply pending SQL migrations before the app accepts requests.

        Why it exists:
            A new checkout should self-initialize its PostgreSQL schema during
            first boot. The migration runner is ordered and idempotent, so
            existing installations only apply files they have not recorded.
        """

        run_migrations()

    return application


app = create_app()
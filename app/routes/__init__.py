# -----------------------------------------------------------------------------
# Recipe Box route package.
# This package aggregates the small, focused FastAPI routers used by the app.
# -----------------------------------------------------------------------------

from fastapi import APIRouter

from app.routes.browse import router as browse_router
from app.routes.detail import router as detail_router
from app.routes.editor import router as editor_router


# The aggregate router is mounted by app.main. Feature modules can be added to
# this registration point without requiring another application-factory edit.
router = APIRouter()
router.include_router(browse_router)
router.include_router(editor_router)
router.include_router(detail_router)
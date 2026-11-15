from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .config import PROJECT_ROOT, Settings, load_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    application = FastAPI(title="AgentWorkflow", version="0.1.0")
    application.state.settings = settings if settings is not None else load_settings()
    application.include_router(router)
    frontend_dir = PROJECT_ROOT / "frontend"
    application.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @application.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(frontend_dir / "index.html")

    return application


app = create_app()

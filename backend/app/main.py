from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.engine import make_url

from app.config import Settings
from app.db import Database
from app.llm.registry import ProviderRegistry
from app.routers import (
    access,
    cleaned_scripts,
    downloads,
    health,
    model_catalog,
    prompt_templates,
    scripts,
    translations,
    video_jobs,
)


@dataclass(slots=True)
class ApplicationState:
    settings: Settings
    db: Database
    registry: ProviderRegistry


_application_state: ApplicationState | None = None


def get_application_state() -> ApplicationState:
    if _application_state is None:
        raise RuntimeError("Application state is not initialized.")
    return _application_state


def create_app() -> FastAPI:
    global _application_state

    settings = Settings()
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    settings.uploads_path.mkdir(parents=True, exist_ok=True)
    settings.generated_path.mkdir(parents=True, exist_ok=True)
    if settings.database_url.startswith("sqlite"):
        database_path = make_url(settings.database_url).database
        if database_path:
            Path(database_path).parent.mkdir(parents=True, exist_ok=True)

    db = Database(settings.database_url)
    registry = ProviderRegistry(settings)
    _application_state = ApplicationState(settings=settings, db=db, registry=registry)

    app = FastAPI(title=settings.app_name)
    app.state.settings = settings
    app.state.db = db
    app.state.registry = registry
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router, prefix=settings.api_prefix)
    app.include_router(model_catalog.router, prefix=settings.api_prefix)
    app.include_router(scripts.router, prefix=settings.api_prefix)
    app.include_router(translations.router, prefix=settings.api_prefix)
    app.include_router(downloads.router, prefix=settings.api_prefix)
    app.include_router(cleaned_scripts.router, prefix=settings.api_prefix)
    app.include_router(access.router, prefix=settings.api_prefix)
    app.include_router(prompt_templates.router, prefix=settings.api_prefix)
    app.include_router(video_jobs.router, prefix=settings.api_prefix)
    return app

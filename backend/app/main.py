from dataclasses import dataclass
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.engine import make_url

from app.config import Settings
from app.db import Database
from app.llm.registry import ProviderRegistry
from app.services.baidu_vod_governor import BaiduVodGovernor
from app.services.zombie_cleanup import cleanup_zombie_jobs
from app.services.migrate_items import migrate_items_to_translations

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
from app.routers import (
    access,
    baidu_vod,
    cleaned_scripts,
    downloads,
    health,
    model_catalog,
    prompt_templates,
    scripts,
    subtitle_erase,
    translations,
    video_jobs,
    video_subtitle,
    video_super_resolution,
)


@dataclass(slots=True)
class ApplicationState:
    settings: Settings
    db: Database
    registry: ProviderRegistry
    baidu_vod_governor: BaiduVodGovernor


_application_state: ApplicationState | None = None


def get_application_state() -> ApplicationState:
    if _application_state is None:
        raise RuntimeError("Application state is not initialized.")
    return _application_state


async def _zombie_cleanup_loop(db: Database) -> None:
    """每 60 分钟扫描一次僵尸任务，避免服务长期运行时卡住的任务不被清理。"""
    while True:
        await asyncio.sleep(3600)
        try:
            cleaned = await cleanup_zombie_jobs(db)
            if cleaned:
                logging.getLogger("app.main").info(
                    "周期清理了 %d 个 zombie job", cleaned
                )
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("app.main").warning("周期 zombie cleanup 失败: %s", exc)


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
    baidu_vod_governor = BaiduVodGovernor(settings)
    _application_state = ApplicationState(
        settings=settings,
        db=db,
        registry=registry,
        baidu_vod_governor=baidu_vod_governor,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 启动时清理上次服务重启遗留的 zombie job（status=running 但 updated_at 超时）
        await db.init_models()
        # 迁移旧 subtitle-erase items_json 到 translations 嵌套结构(幂等,已迁移的跳过)
        try:
            await migrate_items_to_translations(db)
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("app.main").warning("items_json 迁移失败（不阻塞启动）: %s", exc)
        try:
            cleaned = await cleanup_zombie_jobs(db)
            if cleaned:
                logging.getLogger("app.main").info(
                    "启动时清理了 %d 个 zombie job", cleaned
                )
        except Exception as exc:  # noqa: BLE001
            # 清理失败不阻塞启动
            logging.getLogger("app.main").warning("zombie cleanup 失败（不阻塞启动）: %s", exc)

        cleanup_task = asyncio.create_task(_zombie_cleanup_loop(db))
        try:
            yield
        finally:
            cleanup_task.cancel()
            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.state.settings = settings
    app.state.db = db
    app.state.registry = registry
    app.state.baidu_vod_governor = baidu_vod_governor
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
    app.include_router(downloads.scripts_router, prefix=settings.api_prefix)
    app.include_router(cleaned_scripts.router, prefix=settings.api_prefix)
    app.include_router(access.router, prefix=settings.api_prefix)
    app.include_router(prompt_templates.router, prefix=settings.api_prefix)
    app.include_router(video_jobs.router, prefix=settings.api_prefix)
    app.include_router(video_super_resolution.router, prefix=settings.api_prefix)
    app.include_router(video_subtitle.router, prefix=settings.api_prefix)
    app.include_router(subtitle_erase.router, prefix=settings.api_prefix)
    app.include_router(baidu_vod.router, prefix=settings.api_prefix)
    return app

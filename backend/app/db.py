import asyncio
import logging
import shutil
from datetime import datetime
from pathlib import Path
from sqlalchemy.engine import make_url

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger("app.db")


class Base(DeclarativeBase):
    pass


def _backup_sqlite_file(database_url: str) -> None:
    """迁移前对 SQLite 文件做一次时间戳备份。

    备份到 `data/backups/app.db.YYYYMMDD-HHMMSS.db`。失败仅日志告警，不阻塞启动
    —— 备份是保险，不是迁移的前提。
    """

    try:
        url = make_url(database_url)
        if not url.drivername.startswith("sqlite"):
            return
        db_path = url.database
        if not db_path:
            return
        source = Path(db_path)
        if not source.exists():
            return
        backup_dir = source.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = backup_dir / f"{source.name}.{stamp}.bak"
        shutil.copy2(source, target)
        logger.info("SQLite 备份: %s → %s", source, target)
    except Exception as exc:  # noqa: BLE001
        logger.warning("SQLite 备份失败（不阻塞启动）: %s", exc)


class Database:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.engine: AsyncEngine = create_async_engine(database_url, future=True)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False, class_=AsyncSession)
        self._initialized = False
        self._lock = asyncio.Lock()

    async def init_models(self) -> None:
        if self._initialized:
            return

        async with self._lock:
            if self._initialized:
                return

            _backup_sqlite_file(self.database_url)

            async with self.engine.begin() as connection:
                from app.migrations import run_migrations

                await run_migrations(connection)
                await connection.run_sync(Base.metadata.create_all)

            self._initialized = True

    async def session(self) -> AsyncSession:
        await self.init_models()
        return self.session_factory()

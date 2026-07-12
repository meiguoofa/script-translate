import asyncio
import logging
import shutil
from datetime import datetime
from pathlib import Path
from sqlalchemy.engine import make_url
from sqlalchemy import event

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger("app.db")


class Base(DeclarativeBase):
    pass


def _apply_sqlite_pragmas(database_url: str) -> None:
    """SQLite 性能优化：在 engine 上挂 connect 事件，给每个连接设 PRAGMA。

    - journal_mode=WAL：读写不互锁，写不阻塞读；后台 runner 写状态时前端查询不卡
    - synchronous=NORMAL：WAL 模式下足够安全，比 FULL 快 5-10 倍
    - cache_size=-65536：64MB 页缓存（默认 2MB），减少磁盘读
    - mmap_size=268435456：256MB 内存映射，对大表（script_lines 5万+行）查询快
    - temp_store=MEMORY：临时表和索引放内存
    - foreign_keys=ON：开外键约束
    """

    if not database_url.startswith("sqlite"):
        return


def _register_pragma_listener(engine: AsyncEngine, database_url: str) -> None:
    if not database_url.startswith("sqlite"):
        return

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record):  # noqa: ANN001
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA cache_size=-65536")
            cursor.execute("PRAGMA mmap_size=268435456")
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


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
        self.engine: AsyncEngine = create_async_engine(
            database_url,
            future=True,
            pool_size=20,
            max_overflow=30,
            pool_timeout=60,
            pool_recycle=1800,
        )
        _register_pragma_listener(self.engine, database_url)
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

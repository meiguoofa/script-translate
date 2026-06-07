import asyncio

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, database_url: str) -> None:
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

            async with self.engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)

            self._initialized = True

    async def session(self) -> AsyncSession:
        await self.init_models()
        return self.session_factory()

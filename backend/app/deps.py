from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Database


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_registry(request: Request):
    return request.app.state.registry


def get_settings(request: Request):
    return request.app.state.settings


async def get_session(request: Request) -> AsyncSession:
    db: Database = request.app.state.db
    async with await db.session() as session:
        yield session

from fastapi import Header, HTTPException, Request, status
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


def require_passphrase(
    request: Request,
    x_access_passphrase: str | None = Header(default=None, alias="X-Access-Passphrase"),
) -> None:
    settings = request.app.state.settings
    expected = (settings.access_passphrase or "").strip()
    if not expected:
        # 未配置密钥时拒绝所有花费操作，避免误关闭门禁
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="后端 ACCESS_PASSPHRASE 未配置",
        )
    if (x_access_passphrase or "").strip() != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="访问密钥不正确",
        )

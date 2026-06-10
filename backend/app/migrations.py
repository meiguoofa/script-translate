from sqlalchemy import Column, DateTime, MetaData, String, Table, func, inspect, select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db import Base
from app.models import CleanedScriptJob

SCHEMA_MIGRATIONS_TABLE = "schema_migrations"
CREATE_CLEANED_SCRIPT_JOBS_VERSION = "20260610_001_create_cleaned_script_jobs"


metadata = MetaData()
schema_migrations = Table(
    SCHEMA_MIGRATIONS_TABLE,
    metadata,
    Column("version", String(64), primary_key=True),
    Column("applied_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)


async def run_migrations(connection: AsyncConnection) -> None:
    await connection.run_sync(schema_migrations.create, checkfirst=True)
    applied = set(
        (await connection.execute(select(schema_migrations.c.version))).scalars().all()
    )

    if CREATE_CLEANED_SCRIPT_JOBS_VERSION not in applied:
        await connection.run_sync(_create_cleaned_script_jobs)
        await connection.execute(
            schema_migrations.insert().values(version=CREATE_CLEANED_SCRIPT_JOBS_VERSION)
        )


def _create_cleaned_script_jobs(sync_connection) -> None:
    inspector = inspect(sync_connection)
    if CleanedScriptJob.__tablename__ in inspector.get_table_names():
        return
    CleanedScriptJob.__table__.create(sync_connection, checkfirst=True)

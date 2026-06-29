from sqlalchemy import Column, DateTime, MetaData, String, Table, func, inspect, select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db import Base
from app.models import (
    CleanedScriptJob,
    PromptTemplate,
    VideoScriptJob,
    VideoSubtitleJob,
    VideoSuperResolutionJob,
)
from app.services._default_las_prompt import (
    DEFAULT_LAS_PROMPT_CONTENT,
    DEFAULT_LAS_PROMPT_ID,
    DEFAULT_LAS_PROMPT_NAME,
)

SCHEMA_MIGRATIONS_TABLE = "schema_migrations"
CREATE_CLEANED_SCRIPT_JOBS_VERSION = "20260610_001_create_cleaned_script_jobs"
CREATE_PROMPT_TEMPLATES_VERSION = "20260614_001_create_prompt_templates"
CREATE_VIDEO_SCRIPT_JOBS_VERSION = "20260614_002_create_video_script_jobs"
CREATE_VIDEO_SUPER_RESOLUTION_JOBS_VERSION = "20260624_001_create_video_super_resolution_jobs"
CREATE_VIDEO_SUBTITLE_JOBS_VERSION = "20260627_001_create_video_subtitle_jobs"


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

    if CREATE_PROMPT_TEMPLATES_VERSION not in applied:
        await connection.run_sync(_create_prompt_templates)
        await connection.execute(
            schema_migrations.insert().values(version=CREATE_PROMPT_TEMPLATES_VERSION)
        )

    if CREATE_VIDEO_SCRIPT_JOBS_VERSION not in applied:
        await connection.run_sync(_create_video_script_jobs)
        await connection.execute(
            schema_migrations.insert().values(version=CREATE_VIDEO_SCRIPT_JOBS_VERSION)
        )

    if CREATE_VIDEO_SUPER_RESOLUTION_JOBS_VERSION not in applied:
        await connection.run_sync(_create_video_super_resolution_jobs)
        await connection.execute(
            schema_migrations.insert().values(version=CREATE_VIDEO_SUPER_RESOLUTION_JOBS_VERSION)
        )

    if CREATE_VIDEO_SUBTITLE_JOBS_VERSION not in applied:
        await connection.run_sync(_create_video_subtitle_jobs)
        await connection.execute(
            schema_migrations.insert().values(version=CREATE_VIDEO_SUBTITLE_JOBS_VERSION)
        )

    await _seed_default_prompt(connection)


def _create_cleaned_script_jobs(sync_connection) -> None:
    inspector = inspect(sync_connection)
    if CleanedScriptJob.__tablename__ in inspector.get_table_names():
        return
    CleanedScriptJob.__table__.create(sync_connection, checkfirst=True)


def _create_prompt_templates(sync_connection) -> None:
    inspector = inspect(sync_connection)
    if PromptTemplate.__tablename__ in inspector.get_table_names():
        return
    PromptTemplate.__table__.create(sync_connection, checkfirst=True)


def _create_video_script_jobs(sync_connection) -> None:
    inspector = inspect(sync_connection)
    if VideoScriptJob.__tablename__ in inspector.get_table_names():
        return
    VideoScriptJob.__table__.create(sync_connection, checkfirst=True)


def _create_video_super_resolution_jobs(sync_connection) -> None:
    inspector = inspect(sync_connection)
    if VideoSuperResolutionJob.__tablename__ in inspector.get_table_names():
        return
    VideoSuperResolutionJob.__table__.create(sync_connection, checkfirst=True)


def _create_video_subtitle_jobs(sync_connection) -> None:
    inspector = inspect(sync_connection)
    if VideoSubtitleJob.__tablename__ in inspector.get_table_names():
        return
    VideoSubtitleJob.__table__.create(sync_connection, checkfirst=True)


async def _seed_default_prompt(connection: AsyncConnection) -> None:
    existing = (
        await connection.execute(
            select(PromptTemplate.__table__.c.id).where(
                PromptTemplate.__table__.c.id == DEFAULT_LAS_PROMPT_ID
            )
        )
    ).first()
    if existing:
        return
    await connection.execute(
        PromptTemplate.__table__.insert().values(
            id=DEFAULT_LAS_PROMPT_ID,
            name=DEFAULT_LAS_PROMPT_NAME,
            content=DEFAULT_LAS_PROMPT_CONTENT,
            is_default=True,
        )
    )

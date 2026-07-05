from sqlalchemy import Column, DateTime, MetaData, String, Table, func, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db import Base
from app.models import (
    CleanedScriptJob,
    PromptTemplate,
    VideoScriptJob,
    VideoSubtitleEraseJob,
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
CREATE_VIDEO_SUBTITLE_ERASE_JOBS_VERSION = "20260704_001_create_video_subtitle_erase_jobs"
ADD_SUBTITLE_ERASE_BURN_MODE_VERSION = "20260705_001_add_subtitle_erase_burn_mode"


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

    if CREATE_VIDEO_SUBTITLE_ERASE_JOBS_VERSION not in applied:
        await connection.run_sync(_create_video_subtitle_erase_jobs)
        await connection.execute(
            schema_migrations.insert().values(version=CREATE_VIDEO_SUBTITLE_ERASE_JOBS_VERSION)
        )

    if ADD_SUBTITLE_ERASE_BURN_MODE_VERSION not in applied:
        await connection.run_sync(_add_subtitle_erase_burn_mode_columns)
        await connection.execute(
            schema_migrations.insert().values(version=ADD_SUBTITLE_ERASE_BURN_MODE_VERSION)
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


def _create_video_subtitle_erase_jobs(sync_connection) -> None:
    inspector = inspect(sync_connection)
    if VideoSubtitleEraseJob.__tablename__ in inspector.get_table_names():
        return
    VideoSubtitleEraseJob.__table__.create(sync_connection, checkfirst=True)


def _add_subtitle_erase_burn_mode_columns(sync_connection) -> None:
    """为 video_subtitle_erase_jobs 加 burn_mode/placement_mode/output_tos_prefix 列。

    使用 ALTER TABLE ADD COLUMN（SQLite 支持），现有数据保留，新列带默认值。
    """

    inspector = inspect(sync_connection)
    if VideoSubtitleEraseJob.__tablename__ not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns(VideoSubtitleEraseJob.__tablename__)}
    if "burn_mode" not in cols:
        sync_connection.execute(text(
            "ALTER TABLE video_subtitle_erase_jobs ADD COLUMN burn_mode VARCHAR(16) DEFAULT 'local' NOT NULL"
        ))
    if "placement_mode" not in cols:
        sync_connection.execute(text(
            "ALTER TABLE video_subtitle_erase_jobs ADD COLUMN placement_mode VARCHAR(32) DEFAULT 'safe_bottom' NOT NULL"
        ))
    if "output_tos_prefix" not in cols:
        sync_connection.execute(text(
            "ALTER TABLE video_subtitle_erase_jobs ADD COLUMN output_tos_prefix TEXT"
        ))


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

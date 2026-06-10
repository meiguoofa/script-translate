from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Script(Base):
    __tablename__ = "scripts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    source_lang: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32))
    raw_text: Mapped[str] = mapped_column(Text)
    raw_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lines: Mapped[list["ScriptLine"]] = relationship(
        back_populates="script",
        cascade="all, delete-orphan",
        order_by="ScriptLine.line_no",
    )
    versions: Mapped[list["TranslationVersion"]] = relationship(
        back_populates="script",
        cascade="all, delete-orphan",
        order_by="TranslationVersion.created_at.desc()",
    )


class ScriptLine(Base):
    __tablename__ = "script_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    script_id: Mapped[str] = mapped_column(ForeignKey("scripts.id", ondelete="CASCADE"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    raw_line: Mapped[str] = mapped_column(Text)
    speaker: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parenthetical: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dialogue: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_dialogue: Mapped[bool] = mapped_column(Boolean, default=False)

    script: Mapped["Script"] = relationship(back_populates="lines")
    translation_lines: Mapped[list["TranslationLine"]] = relationship(back_populates="line")


class TranslationVersion(Base):
    __tablename__ = "translation_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    script_id: Mapped[str] = mapped_column(ForeignKey("scripts.id", ondelete="CASCADE"), index=True)
    target_lang: Mapped[str] = mapped_column(String(16))
    model_provider: Mapped[str] = mapped_column(String(64))
    model_name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16))
    prompt_version: Mapped[str] = mapped_column(String(32))
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    script: Mapped["Script"] = relationship(back_populates="versions")
    lines: Mapped[list["TranslationLine"]] = relationship(
        back_populates="version",
        cascade="all, delete-orphan",
    )
    generated_docs: Mapped[list["GeneratedDoc"]] = relationship(
        back_populates="version",
        cascade="all, delete-orphan",
    )


class TranslationLine(Base):
    __tablename__ = "translation_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("translation_versions.id", ondelete="CASCADE"), index=True)
    line_id: Mapped[str] = mapped_column(ForeignKey("script_lines.id", ondelete="CASCADE"))
    translated_dialogue: Mapped[str | None] = mapped_column(Text, nullable=True)
    rendered_line: Mapped[str] = mapped_column(Text)

    version: Mapped["TranslationVersion"] = relationship(back_populates="lines")
    line: Mapped["ScriptLine"] = relationship(back_populates="translation_lines")


class GeneratedDoc(Base):
    __tablename__ = "generated_docs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("translation_versions.id", ondelete="CASCADE"), index=True)
    file_path: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    version: Mapped["TranslationVersion"] = relationship(back_populates="generated_docs")


class CleanedScriptJob(Base):
    __tablename__ = "cleaned_script_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(32))
    original_text: Mapped[str] = mapped_column(Text)
    cleaned_text: Mapped[str] = mapped_column(Text)
    line_count: Mapped[int] = mapped_column(Integer)
    stripped_count: Mapped[int] = mapped_column(Integer)
    output_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_filename: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

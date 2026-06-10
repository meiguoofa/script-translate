from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from app.services.script_parser import parse_uploaded_file


@dataclass(slots=True)
class SavedUpload:
    filename: str
    absolute_path: Path
    relative_path: Path
    source_type: str


def detect_upload_source_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".docx":
        return "upload_docx"
    if suffix == ".doc":
        return "upload_doc"
    return "upload_txt"


async def save_uploaded_document(file: UploadFile, document_id: str, settings) -> SavedUpload:
    filename = Path(file.filename or "upload").name
    uploads_path = settings.uploads_path / document_id
    uploads_path.mkdir(parents=True, exist_ok=True)
    destination = uploads_path / filename
    destination.write_bytes(await file.read())
    return SavedUpload(
        filename=filename,
        absolute_path=destination,
        relative_path=destination.relative_to(settings.storage_path),
        source_type=detect_upload_source_type(filename),
    )


def parse_saved_document(path: Path) -> str:
    return parse_uploaded_file(path)

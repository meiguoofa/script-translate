from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory

from docx import Document


def parse_text_content(raw_text: str) -> str:
    return "\n".join(line.rstrip() for line in raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))


def parse_docx_file(path: Path) -> str:
    document = Document(path)
    return "\n".join(paragraph.text.rstrip() for paragraph in document.paragraphs)


def convert_doc_to_docx(path: Path) -> Path:
    soffice = shutil.which("libreoffice") or shutil.which("soffice")
    if not soffice:
        raise RuntimeError("LibreOffice is not installed. Please convert .doc files to .docx first.")

    with TemporaryDirectory() as temp_dir:
        process = subprocess.run(
            [soffice, "--headless", "--convert-to", "docx", "--outdir", temp_dir, str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if process.returncode != 0:
            raise RuntimeError(process.stderr.strip() or "Failed to convert .doc file.")

        converted = Path(temp_dir) / f"{path.stem}.docx"
        if not converted.exists():
            raise RuntimeError("Converted .docx file was not produced.")

        target = path.with_suffix(".docx")
        shutil.copyfile(converted, target)
        return target


def parse_uploaded_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return parse_docx_file(path)
    if suffix == ".doc":
        return parse_docx_file(convert_doc_to_docx(path))
    if suffix == ".txt":
        return path.read_text(encoding="utf-8")
    raise ValueError("Unsupported file type. Please upload .docx, .doc, or .txt files.")

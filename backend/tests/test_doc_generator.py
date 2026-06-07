from zipfile import ZipFile

from app.services.doc_generator import generate_docx


def test_generate_docx_preserves_unicode_text_and_sets_cjk_fonts(tmp_path):
    output_path = tmp_path / "sample.docx"

    generate_docx(
        [
            "《火花瞬间燃点》",
            "艾米丽（局促，低声）：อีธาน พอแค่นี้ดีกว่าไหม(伊森，到这里就行了吧？)",
            "",
        ],
        output_path,
    )

    with ZipFile(output_path) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
        styles_xml = archive.read("word/styles.xml").decode("utf-8")

    assert "《火花瞬间燃点》" in document_xml
    assert "伊森，到这里就行了吧？" in document_xml
    assert 'w:eastAsia="Microsoft YaHei"' in document_xml
    assert 'w:eastAsia="Microsoft YaHei"' in styles_xml
    assert 'w:ascii="Calibri"' in styles_xml

import sys
import zipfile
from pathlib import Path

DIAGNOSTICS_DIR = Path(__file__).resolve().parents[1] / "tools" / "diagnostics"


def test_attachment_matrix_defines_required_file_types() -> None:
    matrix = load_matrix()
    extensions = {Path(case.file_name).suffix for case in matrix.ATTACHMENT_CASES}

    assert extensions == {".docx", ".pdf", ".xlsx", ".pptx", ".txt"}


def test_attachment_matrix_generates_structured_fixtures(tmp_path: Path) -> None:
    matrix = load_matrix()
    paths = matrix.create_validation_fixtures(tmp_path)

    assert {path.suffix for path in paths} == {".docx", ".pdf", ".xlsx", ".pptx", ".txt"}
    assert all(path.stat().st_size > 0 for path in paths)
    assert (tmp_path / "ctg-validation-txt.txt").read_text(encoding="utf-8").startswith(
        "Validation marker: CTG-M365-TXT-20260624"
    )
    assert (tmp_path / "ctg-validation-pdf.pdf").read_bytes().startswith(b"%PDF-1.4")
    assert_zip_contains(tmp_path / "ctg-validation-large-docx.docx", "word/document.xml")
    assert_zip_contains(tmp_path / "ctg-validation-xlsx.xlsx", "xl/worksheets/sheet1.xml")
    assert_zip_contains(tmp_path / "ctg-validation-pptx.pptx", "ppt/slides/slide1.xml")


def test_large_docx_fixture_contains_many_marker_paragraphs(tmp_path: Path) -> None:
    matrix = load_matrix()
    paths = matrix.create_validation_fixtures(tmp_path)
    docx_path = next(path for path in paths if path.suffix == ".docx")

    with zipfile.ZipFile(docx_path) as archive:
        document = archive.read("word/document.xml").decode("utf-8")

    assert document.count("CTG-M365-DOCX-LARGE-20260624") >= 60


def assert_zip_contains(path: Path, member: str) -> None:
    with zipfile.ZipFile(path) as archive:
        assert member in archive.namelist()


def load_matrix() -> object:
    if str(DIAGNOSTICS_DIR) not in sys.path:
        sys.path.insert(0, str(DIAGNOSTICS_DIR))
    import check_m365_attachment_matrix

    return check_m365_attachment_matrix

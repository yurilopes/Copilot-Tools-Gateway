"""Run a sanitized M365 attachment matrix smoke through MCP."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[2]
PROJECT_SRC = ROOT / "src"
DEFAULT_FIXTURE_DIR = ROOT / "captures" / "m365-attachment-validation-fixtures"
DEFAULT_JSONL_PATH = ROOT / "captures" / "m365-attachment-validation.jsonl"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
RELATIONSHIPS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
PRESENTATION_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
PACKAGE_REL_TYPE = "application/vnd.openxmlformats-package.relationships+xml"


@dataclass(frozen=True)
class AttachmentCase:
    file_name: str
    marker: str
    expected_phrase: str
    prompt: str


ATTACHMENT_CASES = [
    AttachmentCase(
        file_name="ctg-validation-large-docx.docx",
        marker="CTG-M365-DOCX-LARGE-20260624",
        expected_phrase="large Word validation document",
        prompt=(
            "Read the attached Word document. Answer with the validation marker "
            "and the document category."
        ),
    ),
    AttachmentCase(
        file_name="ctg-validation-pdf.pdf",
        marker="CTG-M365-PDF-20260624",
        expected_phrase="PDF validation document",
        prompt=(
            "Read the attached PDF. Answer with the validation marker and the "
            "document category."
        ),
    ),
    AttachmentCase(
        file_name="ctg-validation-xlsx.xlsx",
        marker="CTG-M365-XLSX-20260624",
        expected_phrase="spreadsheet validation workbook",
        prompt=(
            "Read the attached spreadsheet. Answer with the validation marker "
            "and the workbook category."
        ),
    ),
    AttachmentCase(
        file_name="ctg-validation-pptx.pptx",
        marker="CTG-M365-PPTX-20260624",
        expected_phrase="presentation validation deck",
        prompt=(
            "Read the attached presentation. Answer with the validation marker "
            "and the deck category."
        ),
    ),
    AttachmentCase(
        file_name="ctg-validation-txt.txt",
        marker="CTG-M365-TXT-20260624",
        expected_phrase="plain text validation file",
        prompt=(
            "Read the attached text file. Answer with the validation marker and "
            "the file category."
        ),
    ),
]


def main() -> None:
    args = parse_args()
    add_import_path(PROJECT_SRC)
    fixture_paths = create_validation_fixtures(args.fixture_dir)
    if args.generate_only:
        result = {
            "ok": True,
            "generated_only": True,
            "fixture_count": len(fixture_paths),
            "fixture_extensions": sorted(path.suffix.lower() for path in fixture_paths),
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    result = asyncio.run(run_matrix(fixture_paths))
    if args.jsonl:
        args.jsonl.parent.mkdir(parents=True, exist_ok=True)
        with args.jsonl.open("a", encoding="utf-8") as file:
            file.write(json.dumps(result, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["ok"]:
        raise SystemExit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate M365 Copilot document attachment types through MCP."
    )
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        default=DEFAULT_FIXTURE_DIR,
        help="Directory where synthetic validation attachments are generated.",
    )
    parser.add_argument(
        "--jsonl",
        type=Path,
        default=DEFAULT_JSONL_PATH,
        help="Append a sanitized matrix result to this JSONL file.",
    )
    parser.add_argument(
        "--generate-only",
        action="store_true",
        help="Only generate validation attachments and skip MCP calls.",
    )
    return parser.parse_args()


def add_import_path(path: Path) -> None:
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)


def create_validation_fixtures(directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for case in ATTACHMENT_CASES:
        path = directory / case.file_name
        content = validation_text(case)
        if path.suffix == ".docx":
            write_docx(path, content)
        elif path.suffix == ".pdf":
            write_pdf(path, content)
        elif path.suffix == ".xlsx":
            write_xlsx(path, content)
        elif path.suffix == ".pptx":
            write_pptx(path, content)
        elif path.suffix == ".txt":
            path.write_text(content, encoding="utf-8")
        else:
            raise ValueError(f"Unsupported validation fixture type: {path.suffix}")
        paths.append(path)
    return paths


def validation_text(case: AttachmentCase) -> str:
    lines = [
        f"Validation marker: {case.marker}",
        f"Category: {case.expected_phrase}",
        "Main sentence: The gateway can validate this attachment type through Copilot.",
    ]
    if case.file_name.endswith(".docx"):
        lines.extend(
            f"Large document paragraph {index}: {case.marker} remains visible."
            for index in range(1, 61)
        )
    return "\n".join(lines)


async def run_matrix(fixture_paths: list[Path]) -> dict[str, object]:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    started_at = time.time()
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "copilot_tools_gateway", "mcp"],
        cwd=str(ROOT),
    )
    results: list[dict[str, object]] = []
    async with stdio_client(parameters) as streams, ClientSession(
        streams[0],
        streams[1],
    ) as session:
        await session.initialize()
        for path in fixture_paths:
            case = case_for_path(path)
            result = await session.call_tool(
                "copilot_chat_with_files",
                {
                    "model": "m365-copilot",
                    "file_paths": [str(path)],
                    "prompt": case.prompt,
                },
            )
            results.append(summarize_tool_result(path, case, result.content))
    ok = all(isinstance(item.get("ok"), bool) and item["ok"] for item in results)
    return {
        "checked_at": started_at,
        "ok": ok,
        "provider": "m365-copilot",
        "case_count": len(results),
        "results": results,
    }


def case_for_path(path: Path) -> AttachmentCase:
    for case in ATTACHMENT_CASES:
        if case.file_name == path.name:
            return case
    raise ValueError(f"Validation case was not found for {path.name}")


def summarize_tool_result(
    path: Path,
    case: AttachmentCase,
    content: object,
) -> dict[str, object]:
    payload = first_json_object(content)
    result = payload_result(payload)
    text = result.get("text")
    error = payload.get("error")
    response_text = text if isinstance(text, str) else ""
    error_text = error if isinstance(error, str) else None
    marker_found = case.marker in response_text
    phrase_found = case.expected_phrase.lower() in response_text.lower()
    ok_value = payload.get("ok")
    return {
        "extension": path.suffix.lower(),
        "file_name": path.name,
        "ok": ok_value is True and marker_found and phrase_found,
        "tool_ok": ok_value is True,
        "response_length": len(response_text),
        "marker_found": marker_found,
        "expected_phrase_found": phrase_found,
        "conversation_id_present": isinstance(result.get("conversation_id"), str),
        "error": error_text,
    }


def payload_result(payload: dict[str, object]) -> dict[str, object]:
    result = payload.get("result")
    return result if isinstance(result, dict) else {}


def first_json_object(content: object) -> dict[str, object]:
    if not isinstance(content, list):
        return {"ok": False, "error": "MCP result content was not a list"}
    for item in content:
        text = getattr(item, "text", None)
        if not isinstance(text, str):
            continue
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {"ok": False, "error": "MCP result did not include a JSON object"}


def write_docx(path: Path, text: str) -> None:
    paragraphs = xml_paragraphs("w", text)
    write_zip(
        path,
        {
            "[Content_Types].xml": content_types_xml(
                [
                    (
                        "/word/document.xml",
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document.main+xml",
                    )
                ]
            ),
            "_rels/.rels": relationships_xml(
                [relationship_xml("rId1", f"{OFFICE_REL_NS}/officeDocument", "word/document.xml")]
            ),
            "word/document.xml": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f'<w:document xmlns:w="{WORD_NS}">'
                f"<w:body>{paragraphs}</w:body></w:document>"
            ),
        },
    )


def write_xlsx(path: Path, text: str) -> None:
    rows = "".join(
        f'<row r="{index}"><c r="A{index}" t="inlineStr"><is><t>{escape(line)}</t></is></c></row>'
        for index, line in enumerate(text.splitlines(), start=1)
    )
    write_zip(
        path,
        {
            "[Content_Types].xml": content_types_xml(
                [
                    (
                        "/xl/workbook.xml",
                        "application/vnd.openxmlformats-officedocument."
                        "spreadsheetml.sheet.main+xml",
                    ),
                    (
                        "/xl/worksheets/sheet1.xml",
                        "application/vnd.openxmlformats-officedocument."
                        "spreadsheetml.worksheet+xml",
                    ),
                ]
            ),
            "_rels/.rels": relationships_xml(
                [relationship_xml("rId1", f"{OFFICE_REL_NS}/officeDocument", "xl/workbook.xml")]
            ),
            "xl/workbook.xml": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f'<workbook xmlns="{SHEET_NS}" xmlns:r="{OFFICE_REL_NS}">'
                '<sheets><sheet name="Validation" sheetId="1" r:id="rId1"/></sheets></workbook>'
            ),
            "xl/_rels/workbook.xml.rels": relationships_xml(
                [relationship_xml("rId1", f"{OFFICE_REL_NS}/worksheet", "worksheets/sheet1.xml")]
            ),
            "xl/worksheets/sheet1.xml": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f'<worksheet xmlns="{SHEET_NS}">'
                f"<sheetData>{rows}</sheetData></worksheet>"
            ),
        },
    )


def write_pptx(path: Path, text: str) -> None:
    paragraphs = xml_paragraphs("a", text)
    write_zip(
        path,
        {
            "[Content_Types].xml": content_types_xml(
                [
                    (
                        "/ppt/presentation.xml",
                        "application/vnd.openxmlformats-officedocument."
                        "presentationml.presentation.main+xml",
                    ),
                    (
                        "/ppt/slides/slide1.xml",
                        "application/vnd.openxmlformats-officedocument."
                        "presentationml.slide+xml",
                    ),
                ]
            ),
            "_rels/.rels": relationships_xml(
                [
                    relationship_xml(
                        "rId1",
                        f"{OFFICE_REL_NS}/officeDocument",
                        "ppt/presentation.xml",
                    )
                ]
            ),
            "ppt/presentation.xml": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f'<p:presentation xmlns:p="{PRESENTATION_NS}" xmlns:r="{OFFICE_REL_NS}">'
                '<p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst></p:presentation>'
            ),
            "ppt/_rels/presentation.xml.rels": relationships_xml(
                [relationship_xml("rId1", f"{OFFICE_REL_NS}/slide", "slides/slide1.xml")]
            ),
            "ppt/slides/slide1.xml": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                f'<p:sld xmlns:p="{PRESENTATION_NS}" xmlns:a="{DRAWING_NS}">'
                '<p:cSld><p:spTree><p:sp><p:txBody>'
                f"{paragraphs}"
                "</p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
            ),
        },
    )


def write_pdf(path: Path, text: str) -> None:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 10 Tf 72 760 Td ({escaped[:900]}) Tj ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream.encode('utf-8'))} >>\nstream\n{stream}\nendstream",
    ]
    parts = ["%PDF-1.4\n"]
    offsets: list[int] = []
    current = len(parts[0].encode("utf-8"))
    for index, obj in enumerate(objects, start=1):
        value = f"{index} 0 obj\n{obj}\nendobj\n"
        offsets.append(current)
        current += len(value.encode("utf-8"))
        parts.append(value)
    xref_offset = current
    xref = ["xref\n0 6\n0000000000 65535 f \n"]
    xref.extend(f"{offset:010d} 00000 n \n" for offset in offsets)
    trailer = f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n"
    path.write_bytes("".join([*parts, *xref, trailer]).encode("utf-8"))


def content_types_xml(overrides: list[tuple[str, str]]) -> str:
    override_xml = "".join(
        f'<Override PartName="{part_name}" ContentType="{content_type}"/>'
        for part_name, content_type in overrides
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Types xmlns="{CONTENT_TYPES_NS}">'
        f'<Default Extension="rels" ContentType="{PACKAGE_REL_TYPE}"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f"{override_xml}</Types>"
    )


def relationships_xml(relationships: list[str]) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Relationships xmlns="{RELATIONSHIPS_NS}">'
        f"{''.join(relationships)}</Relationships>"
    )


def relationship_xml(relation_id: str, relation_type: str, target: str) -> str:
    return f'<Relationship Id="{relation_id}" Type="{relation_type}" Target="{target}"/>'


def xml_paragraphs(prefix: str, text: str) -> str:
    return "".join(
        f"<{prefix}:p><{prefix}:r><{prefix}:t>{escape(line)}</{prefix}:t></{prefix}:r>"
        f"</{prefix}:p>"
        for line in text.splitlines()
    )


def write_zip(path: Path, files: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)


if __name__ == "__main__":
    main()

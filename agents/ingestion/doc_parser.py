"""
agents/ingestion/doc_parser.py
Format detection and raw text extraction from business requirement documents.
Supports: .xlsx, .xls, .docx, .doc, .pdf, .txt, .md, .eml
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import structlog

log = structlog.get_logger()

SUPPORTED_EXTENSIONS = {".xlsx", ".xls", ".docx", ".doc", ".pdf", ".txt", ".md", ".eml"}


@dataclass
class RawChunk:
    """A raw text block extracted from a source document."""

    text: str
    source_ref: str  # e.g. "brd.xlsx:row_12" or "spec.docx:para_3"
    source_file: str  # Basename of the source file
    chunk_index: int = 0  # Sequential chunk number within file


def parse_document(file_path: str) -> list[RawChunk]:
    """
    Detect file format and extract raw text chunks.

    Args:
        file_path: Absolute path to the document file.

    Returns:
        List of RawChunk objects with text and source metadata.

    Raises:
        ValueError: If file format is not supported.
        RuntimeError: If parsing fails even after Docling→Unstructured fallback.
    """
    path = Path(file_path)
    ext = path.suffix.lower()
    source_file = path.name

    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file extension: {ext}. Supported: {SUPPORTED_EXTENSIONS}")

    log.info("doc_parser.parsing", file=source_file, ext=ext)

    if ext in {".xlsx", ".xls"}:
        return _parse_excel(path, source_file)
    elif ext in {".docx", ".doc"}:
        return _parse_word(path, source_file)
    elif ext == ".pdf":
        return _parse_pdf(path, source_file)
    elif ext in {".txt", ".md"}:
        return _parse_text(path, source_file)
    elif ext == ".eml":
        return _parse_email(path, source_file)
    else:
        raise ValueError(f"Unhandled extension: {ext}")


def _parse_excel(path: Path, source_file: str) -> list[RawChunk]:
    """
    Parse Excel files using openpyxl.
    Detects header row and extracts each data row as a RawChunk.
    Handles ALT+ENTER merged cells (\n within cells).
    """
    import openpyxl

    chunks: list[RawChunk] = []
    wb = openpyxl.load_workbook(path, data_only=True)

    for sheet in wb.worksheets:
        rows = list(sheet.iter_rows(values_only=True))
        if not rows:
            continue

        # Detect header row
        header_keywords = {"requirement", "description", "id", "module", "priority", "req"}
        header_row_idx = 0
        for i, row in enumerate(rows[:3]):
            row_text = " ".join(str(c).lower() for c in row if c is not None)
            if any(kw in row_text for kw in header_keywords):
                header_row_idx = i
                break

        start_row = header_row_idx + 1

        for row_idx, row in enumerate(rows[start_row:], start=start_row + 1):
            # Skip fully empty rows
            if all(cell is None or str(cell).strip() == "" for cell in row):
                continue

            # Merge all non-empty cells into one text block
            cell_texts = []
            for cell in row:
                if cell is not None and str(cell).strip():
                    # Handle ALT+ENTER (\n) within cells
                    cell_text = str(cell).replace("\n", " ").strip()
                    cell_texts.append(cell_text)

            if cell_texts:
                combined = " | ".join(cell_texts)
                chunks.append(
                    RawChunk(
                        text=combined,
                        source_ref=f"{source_file}:row_{row_idx}",
                        source_file=source_file,
                        chunk_index=len(chunks),
                    )
                )

    log.info("doc_parser.excel_parsed", file=source_file, chunks=len(chunks))
    return chunks


def _parse_word(path: Path, source_file: str) -> list[RawChunk]:
    """
    Parse Word documents using Docling (primary) with Unstructured fallback.
    """
    try:
        return _parse_with_docling(path, source_file)
    except Exception as docling_err:
        log.warning(
            "docling_failed_falling_back",
            file=source_file,
            error=str(docling_err),
        )
        return _parse_with_unstructured(path, source_file)


def _parse_pdf(path: Path, source_file: str) -> list[RawChunk]:
    """
    Parse PDF files using Docling (primary, with OCR) with Unstructured fallback.
    """
    try:
        return _parse_with_docling(path, source_file, do_ocr=True)
    except Exception as docling_err:
        log.warning(
            "docling_failed_falling_back",
            file=source_file,
            error=str(docling_err),
        )
        return _parse_with_unstructured(path, source_file)


def _parse_text(path: Path, source_file: str) -> list[RawChunk]:
    """Parse plain text and Markdown files by splitting on double newlines."""
    content = path.read_text(encoding="utf-8", errors="replace")
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]

    chunks = []
    for i, para in enumerate(paragraphs):
        if len(para) >= 10:  # Skip very short paragraphs
            chunks.append(
                RawChunk(
                    text=para,
                    source_ref=f"{source_file}:para_{i + 1}",
                    source_file=source_file,
                    chunk_index=i,
                )
            )
    log.info("doc_parser.text_parsed", file=source_file, chunks=len(chunks))
    return chunks


def _parse_email(path: Path, source_file: str) -> list[RawChunk]:
    """Extract plain text body from .eml email files."""
    import email

    with open(path, "rb") as f:
        msg = email.message_from_bytes(f.read())

    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    body = payload.decode("utf-8", errors="replace")
                    break
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode("utf-8", errors="replace")

    # Strip email signatures (heuristic: stop at "-- " or "---")
    for separator in ["-- \n", "---\n", "________________________________"]:
        if separator in body:
            body = body[: body.index(separator)]

    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip() and len(p.strip()) >= 10]
    chunks = [
        RawChunk(
            text=para,
            source_ref=f"{source_file}:para_{i + 1}",
            source_file=source_file,
            chunk_index=i,
        )
        for i, para in enumerate(paragraphs)
    ]
    log.info("doc_parser.email_parsed", file=source_file, chunks=len(chunks))
    return chunks


def _parse_with_docling(path: Path, source_file: str, do_ocr: bool = False) -> list[RawChunk]:
    """Parse document with Docling library."""
    from docling.datamodel.pipeline_options import PipelineOptions
    from docling.document_converter import DocumentConverter

    options = PipelineOptions()
    options.do_ocr = do_ocr

    converter = DocumentConverter()
    result = converter.convert(str(path))
    doc = result.document

    chunks = []
    for i, item in enumerate(doc.texts):
        text = str(item.text).strip() if hasattr(item, "text") else str(item).strip()
        if len(text) >= 10:
            chunks.append(
                RawChunk(
                    text=text,
                    source_ref=f"{source_file}:block_{i + 1}",
                    source_file=source_file,
                    chunk_index=i,
                )
            )

    log.info("doc_parser.docling_parsed", file=source_file, chunks=len(chunks))
    return chunks


def _parse_with_unstructured(path: Path, source_file: str) -> list[RawChunk]:
    """Fallback: parse document with Unstructured library."""
    from unstructured.partition.auto import partition

    elements = partition(filename=str(path))
    chunks = []
    for i, element in enumerate(elements):
        text = str(element).strip()
        if len(text) >= 10:
            chunks.append(
                RawChunk(
                    text=text,
                    source_ref=f"{source_file}:element_{i + 1}",
                    source_file=source_file,
                    chunk_index=i,
                )
            )

    log.info("doc_parser.unstructured_parsed", file=source_file, chunks=len(chunks))
    return chunks

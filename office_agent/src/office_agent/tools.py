"""File-backed office tools for the Office Agent.

Every tool takes and returns plain Python values so DeepAgents can expose
them directly to the model. All paths are confined to the agent workspace
(``OFFICE_AGENT_WORKSPACE``, default: the process working directory) so the
agent can never read or write files outside it.

Tools return ``Error: ...`` strings instead of raising so the model can see
the failure and adjust its next call.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from openpyxl import Workbook, load_workbook
from pypdf import PdfReader, PdfWriter
from pptx import Presentation

WORKSPACE_ENV = "OFFICE_AGENT_WORKSPACE"

MAX_TEXT_CHARS = 100_000
MAX_PDF_PAGES = 50
MAX_SHEET_ROWS = 50
MAX_SHEET_COLS = 50


def workspace_root() -> Path:
    """Absolute path of the agent workspace."""

    return Path(os.environ.get(WORKSPACE_ENV, ".")).resolve()


def resolve_workspace_path(path: str) -> Path:
    """Resolve ``path`` inside the workspace or raise ``ValueError``."""

    root = workspace_root()
    candidate = (root / path).resolve()
    if candidate != root and not candidate.is_relative_to(root):
        msg = f"path escapes the agent workspace: {path}"
        raise ValueError(msg)
    return candidate


def read_text_file(path: str) -> str:
    """Read a plain-text file (.txt, .csv, .md) inside the agent workspace.

    Returns the file content, truncated to a safe length for the model
    context. Use this for any textual file that is not a PDF or spreadsheet.
    """

    try:
        target = resolve_workspace_path(path)
        content = target.read_text(encoding="utf-8", errors="replace")
    except (ValueError, OSError) as exc:
        return f"Error: {exc}"
    if len(content) > MAX_TEXT_CHARS:
        content = content[:MAX_TEXT_CHARS] + "\n... [truncated]"
    return content


def read_pdf_file(path: str) -> str:
    """Read a PDF document inside the agent workspace.

    Extracts text page by page (up to a page limit) and prefixes each page
    with a header, so the content can be summarized or queried afterwards.
    """

    try:
        target = resolve_workspace_path(path)
        reader = PdfReader(target)
    except (ValueError, OSError) as exc:
        return f"Error: {exc}"
    total = len(reader.pages)
    pages = reader.pages[:MAX_PDF_PAGES]
    parts = [f"PDF {target.name}: {total} page(s)"]
    if total > MAX_PDF_PAGES:
        parts[0] += f" (showing first {MAX_PDF_PAGES})"
    for index, page in enumerate(pages, start=1):
        text = (page.extract_text() or "").strip()
        parts.append(f"--- page {index} ---\n{text}")
    return "\n\n".join(parts)


def read_spreadsheet(path: str) -> str:
    """Inspect an .xlsx workbook inside the agent workspace.

    Returns every worksheet as a Markdown table with row/column indices,
    capped per sheet so large workbooks do not flood the model context.
    """

    try:
        target = resolve_workspace_path(path)
        workbook = load_workbook(target, read_only=True, data_only=True)
    except (ValueError, OSError) as exc:
        return f"Error: {exc}"
    parts = [f"Workbook {target.name}:"]
    try:
        for sheet in workbook.worksheets:
            parts.append(
                f"\n## Sheet '{sheet.title}' "
                f"({sheet.max_row} rows x {sheet.max_column} cols)"
            )
            if sheet.max_row > MAX_SHEET_ROWS or sheet.max_column > MAX_SHEET_COLS:
                parts.append(
                    f"Showing first {MAX_SHEET_ROWS} rows x {MAX_SHEET_COLS} cols."
                )
            for row in sheet.iter_rows(
                min_row=1,
                max_row=min(sheet.max_row, MAX_SHEET_ROWS),
                max_col=min(sheet.max_column, MAX_SHEET_COLS),
                values_only=True,
            ):
                cells = ["" if value is None else str(value) for value in row]
                parts.append("| " + " | ".join(cells) + " |")
    finally:
        workbook.close()
    return "\n".join(parts)


def write_spreadsheet(path: str, sheet_name: str, rows: list[list[Any]]) -> str:
    """Write an .xlsx spreadsheet inside the agent workspace.

    ``rows`` is a list of rows; each row is a list of cell values (numbers or
    strings). The first row is written as a plain data row, not a styled
    header. Returns the absolute path of the created file.
    """

    try:
        target = resolve_workspace_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = sheet_name[:31] or "Sheet1"
        for row in rows:
            sheet.append(list(row))
        workbook.save(target)
    except (ValueError, OSError) as exc:
        return f"Error: {exc}"
    return f"Wrote {len(rows)} row(s) to {target}"


def write_presentation(path: str, title: str, slides: list[dict[str, Any]]) -> str:
    """Write a .pptx presentation inside the agent workspace.

    ``title`` becomes the title slide. Each item in ``slides`` must be a dict
    with ``title`` (str) and ``bullets`` (list of str). Returns the absolute
    path of the created file.
    """

    try:
        target = resolve_workspace_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        deck = Presentation()
        cover = deck.slides.add_slide(deck.slide_layouts[0])
        cover.shapes.title.text = title
        for slide_spec in slides:
            slide = deck.slides.add_slide(deck.slide_layouts[1])
            slide.shapes.title.text = str(slide_spec.get("title", ""))
            body = slide.placeholders[1].text_frame
            for bullet in slide_spec.get("bullets", []):
                bullet_text = str(bullet).strip()
                if bullet_text:
                    paragraph = body.add_paragraph()
                    paragraph.text = bullet_text
        deck.save(target)
    except (ValueError, OSError, KeyError, IndexError) as exc:
        return f"Error: {exc}"
    return f"Wrote {len(slides)} slide(s) to {target}"


OFFICE_TOOLS = [
    read_text_file,
    read_pdf_file,
    read_spreadsheet,
    write_spreadsheet,
    write_presentation,
]

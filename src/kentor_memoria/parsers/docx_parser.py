"""DOCX via python-docx: parágrafos e tabelas na ordem do documento.

Estilos "Heading N"/"Título N" viram seções. Tabelas viram linhas "a | b | c"
(células mescladas repetidas são colapsadas).
"""
from __future__ import annotations

import re
from pathlib import Path

import docx
from docx.table import Table
from docx.text.paragraph import Paragraph

from ..models import Block, ParsedDocument
from ..utils import clean_text

_HEADING_STYLE = re.compile(r"^(heading|título|titulo)\s*(\d)?", re.I)


def _iter_body(document):
    body = document.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            yield Paragraph(child, document)
        elif tag == "tbl":
            yield Table(child, document)


def _table_text(table: Table) -> str:
    rows: list[str] = []
    for row in table.rows:
        cells: list[str] = []
        for c in row.cells:
            t = clean_text(c.text).replace("\n", " ")
            if not cells or cells[-1] != t:  # célula mesclada aparece repetida
                cells.append(t)
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def parse_docx(path: Path) -> ParsedDocument:
    document = docx.Document(str(path))
    blocks: list[Block] = []
    stack: list[tuple[int, str]] = []
    first_heading: str | None = None

    for item in _iter_body(document):
        path_now = [t for _, t in stack]
        if isinstance(item, Table):
            text = _table_text(item)
            if text:
                blocks.append(Block(text=text, heading_path=path_now, kind="table"))
            continue
        text = clean_text(item.text)
        if not text:
            continue
        style_name = item.style.name if item.style is not None else ""
        m = _HEADING_STYLE.match(style_name or "")
        if m:
            level = int(m.group(2) or 1)
            first_heading = first_heading or text
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, text))
            continue
        blocks.append(Block(text=text, heading_path=path_now))

    cp = document.core_properties
    metadata = {
        "docx_title": cp.title or None,
        "author": cp.author or None,
        "created": cp.created.date().isoformat() if cp.created else None,
        "modified": cp.modified.date().isoformat() if cp.modified else None,
    }
    title = cp.title or first_heading or path.stem
    return ParsedDocument(title=title, format="docx", blocks=blocks, metadata={k: v for k, v in metadata.items() if v})

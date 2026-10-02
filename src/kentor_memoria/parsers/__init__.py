"""Parsers por formato. Cada um devolve um ParsedDocument com blocos estruturados.

PARSER_VERSION entra no fingerprint de ingestão: se a lógica de parsing mudar,
basta incrementar o número para forçar o reprocessamento de todo o acervo.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..models import ParsedDocument
from .docx_parser import parse_docx
from .markdown import parse_markdown
from .pdf import parse_pdf
from .pptx_parser import parse_pptx
from .svg import parse_svg
from .text import parse_css, parse_txt

PARSER_VERSION = "4"

PARSERS: dict[str, Callable[[Path], ParsedDocument]] = {
    ".md": parse_markdown,
    ".markdown": parse_markdown,
    ".txt": parse_txt,
    ".css": parse_css,
    ".svg": parse_svg,
    ".pdf": parse_pdf,
    ".docx": parse_docx,
    ".pptx": parse_pptx,
}

SUPPORTED_EXTENSIONS = frozenset(PARSERS)


def parse_file(path: Path) -> ParsedDocument:
    ext = path.suffix.lower()
    if ext not in PARSERS:
        raise ValueError(f"Formato não suportado: {ext}")
    return PARSERS[ext](path)


__all__ = ["parse_file", "SUPPORTED_EXTENSIONS", "PARSER_VERSION"]

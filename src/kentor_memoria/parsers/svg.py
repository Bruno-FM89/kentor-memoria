"""SVG: extrai <title>/<desc>/<text> em ordem de documento.

Textos na mesma linha visual (mesmo y, dentro do mesmo trecho) são unidos numa
linha só ("Otto — processos internos /otto"). Comentários do tipo
<!-- ===== Nível 1 ===== --> e rótulos em caixa-alta viram seções.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ..models import Block, ParsedDocument
from ..utils import clean_text, nfc

_SECTION_COMMENT = re.compile(r"=+\s*(.+?)\s*=+")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def parse_svg(path: Path) -> ParsedDocument:
    raw = nfc(path.read_text(encoding="utf-8", errors="replace"))
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    root = ET.fromstring(raw, parser=parser)

    title = path.stem
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    last_y: str | None = None

    for el in root.iter():
        if el.tag is ET.Comment:
            m = _SECTION_COMMENT.search(el.text or "")
            if m:
                sections.append((m.group(1).strip(), []))
                last_y = None
            continue
        tag = _local(el.tag)
        if tag in ("title", "desc") and (el.text or "").strip():
            sections[-1][1].append(el.text.strip())
            last_y = None
        elif tag == "text":
            content = "".join(el.itertext()).strip()
            if not content:
                continue
            y = el.get("y")
            lines = sections[-1][1]
            if lines and y is not None and y == last_y:
                lines[-1] = f"{lines[-1]} {content}"
            else:
                lines.append(content)
            last_y = y

    first_lines = [ln for _, lines in sections for ln in lines]
    if first_lines:
        title = first_lines[0]

    blocks: list[Block] = []
    for heading, lines in sections:
        text = clean_text("\n".join(lines))
        if text:
            blocks.append(Block(text=text, heading_path=[heading] if heading else [], kind="paragraph"))
    return ParsedDocument(title=title, format="svg", blocks=blocks)

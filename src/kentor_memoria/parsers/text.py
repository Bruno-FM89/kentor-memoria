"""TXT e CSS: leitura direta com um mínimo de estrutura."""
from __future__ import annotations

import re
from pathlib import Path

from ..models import Block, ParsedDocument
from ..utils import clean_text, nfc


def parse_txt(path: Path) -> ParsedDocument:
    text = clean_text(path.read_text(encoding="utf-8", errors="replace"))
    blocks = [Block(text=p.strip()) for p in re.split(r"\n\s*\n", text) if p.strip()]
    return ParsedDocument(title=path.stem, format="txt", blocks=blocks)


# Comentários do tipo /* === BRAND === */ viram seções.
_CSS_SECTION = re.compile(r"/\*\s*=+\s*(.+?)\s*=+\s*\*/")
_CSS_BANNER = re.compile(r"/\*[\s=]*\n(.*?)\n[\s=]*\*/", re.S)


def parse_css(path: Path) -> ParsedDocument:
    raw = nfc(path.read_text(encoding="utf-8", errors="replace")).replace("\r\n", "\n")
    title = path.stem
    banner = _CSS_BANNER.search(raw)
    if banner:
        first = [ln.strip(" =*") for ln in banner.group(1).split("\n") if ln.strip(" =*")]
        if first:
            title = first[0]

    blocks: list[Block] = []
    section: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        content = clean_text("\n".join(buf))
        if content:
            blocks.append(Block(text=content, heading_path=list(section), kind="code"))
        buf.clear()

    for line in raw.split("\n"):
        m = _CSS_SECTION.search(line)
        if m and line.strip().startswith("/*"):
            flush()
            section[:] = [m.group(1).strip()]
            continue
        if not line.strip():
            if len("\n".join(buf)) > 600:
                flush()
            continue
        buf.append(line)
    flush()
    return ParsedDocument(title=title, format="css", blocks=blocks)

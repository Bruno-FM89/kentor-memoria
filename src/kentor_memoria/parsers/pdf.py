"""PDF via PyMuPDF, preservando página e detectando títulos pelo tamanho da fonte.

Heurística: o tamanho de fonte mais frequente (ponderado por caracteres) é o
"corpo". Linhas com fonte >= 1,25x o corpo e com letras suficientes são títulos
e alimentam o heading_path dos blocos seguintes. Cada bloco de texto do PyMuPDF
vira um Block com o número da página (para citação).
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

try:
    import pymupdf  # type: ignore
except ImportError:  # pragma: no cover - versões antigas
    import fitz as pymupdf  # type: ignore

from ..models import Block, ParsedDocument
from ..utils import clean_text, nfc

_LETTERS = re.compile(r"[A-Za-zÀ-ÿ]")
HEADING_RATIO = 1.25


def _pdf_date(raw: str | None) -> str | None:
    # Formato PDF: D:20260522175229+00'00'
    if raw and raw.startswith("D:") and len(raw) >= 10:
        d = raw[2:10]
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return None


def parse_pdf(path: Path) -> ParsedDocument:
    doc = pymupdf.open(path)
    size_chars: Counter[float] = Counter()  # tamanho de fonte → nº de caracteres
    line_info: list[list[list[tuple[str, float]]]] = []  # página → blocos → linhas (texto, tamanho)

    for page in doc:
        # TEXTFLAGS_TEXT: ignora imagens (o PDF de 84 MB cai de ~16 s para ~0,3 s)
        data = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)
        page_blocks: list[list[tuple[str, float]]] = []
        for b in data.get("blocks", []):
            if b.get("type") != 0:  # 0 = texto
                continue
            lines: list[tuple[str, float]] = []
            for ln in b.get("lines", []):
                spans = ln.get("spans", [])
                text = "".join(s.get("text", "") for s in spans)
                if not text.strip():
                    continue
                size = max((round(s.get("size", 0), 1) for s in spans), default=0.0)
                lines.append((text, size))
                size_chars[size] += len(text.strip())
            if lines:
                page_blocks.append(lines)
        line_info.append(page_blocks)

    body = size_chars.most_common(1)[0][0] if size_chars else 10.0

    def is_heading(text: str, size: float) -> bool:
        t = text.strip()
        return size >= body * HEADING_RATIO and 3 <= len(t) <= 160 and len(_LETTERS.findall(t)) >= 3

    blocks: list[Block] = []
    page_title: str | None = None
    sub_heading: str | None = None
    first_heading: str | None = None
    for page_no, page_blocks in enumerate(line_info, start=1):
        # Título da página = linha(s) com a MAIOR fonte da página (se for título).
        # Página sem título herda o da anterior (documento corrido); página com
        # título próprio zera o subtítulo (deck: cada página é um slide).
        all_lines = [(t, s) for lines in page_blocks for t, s in lines]
        max_size = max((s for t, s in all_lines if is_heading(t, s)), default=0.0)
        title_lines = [t.strip() for t, s in all_lines if s == max_size and is_heading(t, s)]
        if title_lines:
            page_title = clean_text(" ".join(title_lines))[:160]
            sub_heading = None
            first_heading = first_heading or page_title

        def heading_path() -> list[str]:
            return [h for h in (page_title, sub_heading) if h]

        for lines in page_blocks:
            heading_lines = [t for t, s in lines if is_heading(t, s)]
            if heading_lines and len(heading_lines) == len(lines):
                h = clean_text(" ".join(t.strip() for t in heading_lines))
                if h != page_title and not all(s == max_size for _, s in lines):
                    sub_heading = h[:160]
                continue
            # junta as linhas visuais do bloco num parágrafo (desfaz hifenização)
            joined = ""
            for t, _ in lines:
                t = t.strip()
                if joined.endswith("-") and t[:1].islower():
                    joined = joined[:-1] + t
                else:
                    joined = f"{joined} {t}" if joined else t
            text = clean_text(joined)
            if text:
                blocks.append(Block(text=text, heading_path=heading_path(), page=page_no))

    meta = doc.metadata or {}
    metadata = {
        "page_count": doc.page_count,
        "pdf_title": meta.get("title") or None,
        "pdf_author": meta.get("author") or None,
        "created": _pdf_date(meta.get("creationDate")),
        "modified": _pdf_date(meta.get("modDate")),
    }
    title = nfc(meta.get("title") or "") or first_heading or path.stem
    doc.close()
    return ParsedDocument(title=title, format="pdf", blocks=blocks, metadata={k: v for k, v in metadata.items() if v})

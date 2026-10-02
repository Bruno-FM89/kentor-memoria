"""Chunking orientado à estrutura.

Ordem de prioridade: documento inteiro (se pequeno) → seção/heading → parágrafo
→ frase (nunca cortamos no meio de uma frase) → limite de tamanho.

- Documento com até SMALL_DOC_CHARS vira UM chunk: uma nota de 5 linhas ou uma
  tabela de preços não deve ser fatiada (perderia o cabeçalho da tabela).
- Documento grande: blocos da mesma seção (e mesma página/slide) são agrupados
  até TARGET_CHARS. Seções pequenas vizinhas são fundidas (evita chunks de uma
  linha), marcando o heading de cada uma dentro do texto.
- Bloco maior que MAX_CHARS é quebrado por frases; tabela é quebrada por linhas
  repetindo o cabeçalho.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from ..models import Block, ChunkDraft, ParsedDocument
from ..retrieval.text import split_sentences

SMALL_DOC_CHARS = 1500
TARGET_CHARS = 1200
MAX_CHARS = 1800
MIN_CHARS = 300
MIN_PAGE_CHARS = 120  # PDF/deck: cada página vira chunk próprio se tiver ao menos isso (citação precisa)

CHUNKER_VERSION = "4"  # entra no fingerprint de ingestão


def _split_table(block: Block) -> list[Block]:
    rows = block.text.split("\n")
    header: list[str] = rows[:1]
    body = rows[1:]
    if body and set(body[0].replace("|", "").strip()) <= set("-: "):  # separador markdown
        header.append(body[0])
        body = body[1:]
    pieces: list[Block] = []
    cur: list[str] = []
    for row in body:
        if cur and len("\n".join(header + cur + [row])) > TARGET_CHARS:
            pieces.append(replace(block, text="\n".join(header + cur)))
            cur = []
        cur.append(row)
    if cur or not pieces:
        pieces.append(replace(block, text="\n".join(header + cur)))
    return pieces


def _split_by_sentences(block: Block) -> list[Block]:
    sentences = split_sentences(block.text)
    pieces: list[Block] = []
    cur = ""
    for s in sentences:
        if len(s) > MAX_CHARS:  # frase gigante (raro): corta em palavras
            words, part = s.split(), ""
            for w in words:
                if len(part) + len(w) + 1 > TARGET_CHARS:
                    pieces.append(replace(block, text=(cur + " " + part).strip()))
                    cur, part = "", ""
                part = f"{part} {w}".strip()
            s = part
        if cur and len(cur) + len(s) + 1 > TARGET_CHARS:
            pieces.append(replace(block, text=cur))
            cur = ""
        cur = f"{cur} {s}".strip() if cur else s
    if cur:
        pieces.append(replace(block, text=cur))
    return pieces


def split_block(block: Block) -> list[Block]:
    if len(block.text) <= MAX_CHARS:
        return [block]
    if block.kind == "table":
        return _split_table(block)
    return _split_by_sentences(block)


@dataclass
class _Acc:
    pieces: list[Block]

    @property
    def size(self) -> int:
        return sum(len(p.text) + 1 for p in self.pieces)


def _section_key(b: Block) -> tuple:
    return (tuple(b.heading_path), b.page, b.slide)


def _to_draft(ordinal: int, pieces: list[Block], whole_doc: bool = False) -> ChunkDraft:
    lines: list[str] = []
    first_heading = pieces[0].heading_path
    prev_heading = first_heading
    prev_page, prev_slide = pieces[0].page, pieces[0].slide
    for p in pieces:
        # marcadores internos permitem citar a página/slide/seção exata de um trecho
        # mesmo quando o chunk junta páginas pequenas (ex.: slides de um deck)
        if p.page and p.page != prev_page:
            lines.append(f"[p. {p.page}]")
        if p.slide and p.slide != prev_slide:
            lines.append(f"[slide {p.slide}]")
        if p.heading_path != prev_heading and p.heading_path and not whole_doc:
            lines.append(f"[{' > '.join(p.heading_path)}]")
        prev_heading, prev_page, prev_slide = p.heading_path, p.page, p.slide
        lines.append(p.text)
    pages = [p.page for p in pieces if p.page]
    slides = [p.slide for p in pieces if p.slide]
    return ChunkDraft(
        ordinal=ordinal,
        text="\n".join(lines).strip(),
        heading_path=[] if whole_doc else list(first_heading),
        page_start=min(pages) if pages else None,
        page_end=max(pages) if pages else None,
        slide_start=min(slides) if slides else None,
        slide_end=max(slides) if slides else None,
    )


def chunk_document(doc: ParsedDocument) -> list[ChunkDraft]:
    blocks = [b for b in doc.blocks if b.text.strip()]
    if not blocks:
        return []

    total = sum(len(b.text) for b in blocks)
    if total <= SMALL_DOC_CHARS:
        return [_to_draft(0, blocks, whole_doc=True)]

    pieces: list[Block] = []
    for b in blocks:
        pieces.extend(split_block(b))

    groups: list[list[Block]] = []
    acc = _Acc([])
    for p in pieces:
        if acc.pieces:
            same_section = _section_key(p) == _section_key(acc.pieces[-1])
            too_big = acc.size + len(p.text) > TARGET_CHARS
            new_page = p.page != acc.pieces[-1].page and acc.size >= MIN_PAGE_CHARS
            if too_big or new_page or (not same_section and acc.size >= MIN_CHARS):
                groups.append(acc.pieces)
                acc = _Acc([])
        acc.pieces.append(p)
    if acc.pieces:
        # sobra pequena no fim é fundida ao grupo anterior (se couber)
        if groups and acc.size < MIN_CHARS and sum(len(x.text) for x in groups[-1]) + acc.size <= MAX_CHARS:
            groups[-1].extend(acc.pieces)
        else:
            groups.append(acc.pieces)

    return [_to_draft(i, g) for i, g in enumerate(groups)]

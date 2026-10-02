"""Estruturas de dados compartilhadas entre ingestão, busca e MCP."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------- ingestão
@dataclass
class Block:
    """Unidade estrutural produzida por um parser (parágrafo, tabela, slide...)."""

    text: str
    heading_path: list[str] = field(default_factory=list)  # ex.: ["PARTE 2", "2.1 Regras GLOBAIS"]
    page: int | None = None  # PDF (1-based)
    slide: int | None = None  # PPTX (1-based)
    kind: str = "paragraph"  # paragraph | table | heading | slide | code


@dataclass
class ParsedDocument:
    title: str
    format: str
    blocks: list[Block]
    metadata: dict[str, Any] = field(default_factory=dict)  # frontmatter, props do PDF/DOCX etc.

    @property
    def full_text(self) -> str:
        return "\n\n".join(b.text for b in self.blocks if b.text.strip())


@dataclass
class ChunkDraft:
    """Chunk antes de ir para o banco."""

    ordinal: int
    text: str
    heading_path: list[str]
    page_start: int | None = None
    page_end: int | None = None
    slide_start: int | None = None
    slide_end: int | None = None

    def location(self) -> str:
        return format_location(self.heading_path, self.page_start, self.page_end, self.slide_start, self.slide_end)


def format_location(heading_path, page_start=None, page_end=None, slide_start=None, slide_end=None) -> str:
    parts: list[str] = []
    if page_start:
        parts.append(f"p. {page_start}" if page_start == page_end or not page_end else f"p. {page_start}-{page_end}")
    if slide_start:
        parts.append(
            f"slide {slide_start}" if slide_start == slide_end or not slide_end else f"slides {slide_start}-{slide_end}"
        )
    if heading_path:
        parts.append(" > ".join(heading_path))
    return " · ".join(parts) if parts else "documento inteiro"


# ---------------------------------------------------------------- respostas
class Status(str, Enum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    FORBIDDEN = "FORBIDDEN"
    CONFLICT = "CONFLICT"


@dataclass
class Evidence:
    """Trecho AUTORIZADO que pode sair do servidor. Só é criado após a política."""

    document_id: str
    chunk_id: str
    source: str  # caminho relativo no acervo
    title: str
    location: str  # seção/página/slide
    snippet: str
    score: float
    format: str
    page: int | None = None
    slide: int | None = None
    section: str | None = None
    doc_date: str | None = None
    version: int | None = None
    also_in: list[str] = field(default_factory=list)  # quase-duplicatas em outros arquivos
    notes: list[str] = field(default_factory=list)  # ex.: "declara substituir X"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Answer:
    status: Status
    answer: str
    sources: list[Evidence] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    superseded_sources: list[dict[str, Any]] = field(default_factory=list)
    identity: str = ""
    model: str | None = None
    timings_ms: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "answer": self.answer,
            "sources": [s.to_dict() for s in self.sources],
            "conflicts": self.conflicts,
            "notes": self.notes,
            "superseded_sources": self.superseded_sources,
            "identity": self.identity,
            "model": self.model,
            "timings_ms": self.timings_ms,
        }

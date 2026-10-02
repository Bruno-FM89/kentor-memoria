"""Ponte entre a interface gráfica e o backend EXISTENTE.

A interface não tem regra de negócio nem de permissão. Ela só:
  - lista as identidades lidas de config/identities.yaml (via AccessPolicy);
  - chama KnowledgeService.ask(question, identity) — a MESMA função usada pelo
    CLI (`kentor ask`) e pelo servidor MCP (`ask_knowledge`);
  - transforma o dicionário devolvido em dados prontos para exibir.

Se o backend devolve FORBIDDEN, o dicionário já chega sem conteúdo restrito:
não há nada para "esconder" na tela.
"""
from __future__ import annotations

import importlib.util
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..answering.service import KnowledgeService
from ..config import PROJECT_ROOT, Settings

DEMO_QUESTIONS_FILE = PROJECT_ROOT / "config" / "demo_questions.yaml"

STATUS_VIEW = {
    "FOUND": {"icon": "✅", "title": "Informação encontrada", "tone": "found"},
    "NOT_FOUND": {"icon": "🔎", "title": "Informação não encontrada no acervo", "tone": "notfound"},
    "FORBIDDEN": {"icon": "🔒", "title": "Informação existente, mas sem permissão de acesso", "tone": "forbidden"},
    "CONFLICT": {"icon": "⚠️", "title": "Fontes conflitantes encontradas", "tone": "conflict"},
}


@dataclass(frozen=True)
class IdentityOption:
    name: str  # chave usada pelo backend (ex.: "socio")
    label: str  # nome exibido (ex.: "Sócio")
    clearance: str
    clearance_label: str
    description: str


@dataclass
class SourceCard:
    filename: str
    path: str
    format: str
    section: str | None
    page: int | None
    slide: int | None
    location: str
    snippet: str
    also_in: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class ConflictSide:
    filename: str
    path: str
    location: str
    value: str
    statement: str


@dataclass
class AnswerView:
    status: str
    icon: str
    title: str
    tone: str
    answer: str
    sources: list[SourceCard]
    conflict: list[ConflictSide]
    conflict_resolution: str | None
    notes: list[str]
    identity: str
    elapsed_ms: float | None
    model: str | None = None  # modelo de LLM que redigiu a resposta (None = extrativa)


class UIBackend:
    """Fachada fina sobre KnowledgeService. Uma instância por processo da UI."""

    def __init__(self, service: KnowledgeService | None = None, settings: Settings | None = None):
        self.service = service or KnowledgeService(settings)
        self._lock = threading.Lock()  # Streamlit usa threads; a conexão SQLite é compartilhada

    # --------------------------------------------------------- identidades
    def identities(self) -> list[IdentityOption]:
        pol = self.service.policy
        out = [
            IdentityOption(
                name=i.name,
                label=i.label or i.name.title(),
                clearance=i.clearance,
                clearance_label=pol.level_labels.get(i.clearance, i.clearance),
                description=i.description,
            )
            for i in pol.identities.values()
        ]
        return sorted(out, key=lambda o: (pol.rank(o.clearance), o.label))

    # ------------------------------------------------------------ pergunta
    def ask(self, question: str, identity: str) -> AnswerView:
        """Chama exatamente o mesmo serviço do CLI e do MCP."""
        with self._lock:
            raw = self.service.ask(question, identity).to_dict()
        return to_view(raw)

    # -------------------------------------------------------------- status
    def system_status(self) -> dict[str, Any]:
        with self._lock:
            h = self.service.health()
        docs = h.get("documents_by_status") or {}
        return {
            "db_loaded": h.get("active_chunks", 0) > 0,
            "retrieval_ready": h.get("status") == "ok",
            "semantic_search": bool(h.get("embedding_model")) and not h.get("embedding_error"),
            "mcp_installed": importlib.util.find_spec("mcp") is not None
            and importlib.util.find_spec("kentor_memoria.mcp_server.server") is not None,
            "documents_indexed": int(docs.get("active", 0)) + int(docs.get("superseded", 0)),
            "chunks_indexed": int(h.get("active_chunks", 0)),
            "llm_enabled": bool(h.get("llm_enabled")),
            "llm_model": h.get("llm_model"),
            "llm_status": h.get("llm_status"),
            "last_ingestion": (h.get("last_ingestion") or {}).get("finished_at"),
        }


# ------------------------------------------------------------------ helpers
def load_demo_questions(path: Path = DEMO_QUESTIONS_FILE) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [d for d in data if d.get("label") and d.get("question")]


def _filename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def to_view(raw: dict[str, Any]) -> AnswerView:
    """Converte o dicionário do backend em algo exibível. Não filtra nem decide nada."""
    meta = STATUS_VIEW.get(raw["status"], {"icon": "•", "title": raw["status"], "tone": "notfound"})
    sources = [
        SourceCard(
            filename=_filename(s["source"]),
            path=s["source"],
            format=s.get("format") or "",
            section=s.get("section"),
            page=s.get("page"),
            slide=s.get("slide"),
            location=s.get("location") or "",
            snippet=s.get("snippet") or "",
            also_in=list(s.get("also_in") or []),
            notes=list(s.get("notes") or []),
        )
        for s in raw.get("sources") or []
    ]
    conflict: list[ConflictSide] = []
    resolution = None
    if raw.get("conflicts"):
        first = raw["conflicts"][0]
        resolution = first.get("resolution")
        for c in first.get("claims") or []:
            conflict.append(
                ConflictSide(
                    filename=_filename(c.get("source", "")),
                    path=c.get("source", ""),
                    location=c.get("location") or "",
                    value=c.get("value") or "",
                    statement=c.get("statement") or "",
                )
            )
    return AnswerView(
        status=raw["status"],
        icon=meta["icon"],
        title=meta["title"],
        tone=meta["tone"],
        answer=raw.get("answer") or "",
        sources=sources,
        conflict=conflict,
        conflict_resolution=resolution,
        notes=list(raw.get("notes") or []),
        identity=raw.get("identity") or "",
        elapsed_ms=(raw.get("timings_ms") or {}).get("total"),
        model=raw.get("model"),
    )

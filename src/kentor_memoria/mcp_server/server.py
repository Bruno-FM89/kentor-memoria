"""Servidor MCP (SDK oficial, FastMCP) — transporte stdio.

Ferramentas:
  ask_knowledge(question)          → status FOUND | NOT_FOUND | FORBIDDEN | CONFLICT + resposta + fontes
  search_knowledge(query, top_k)   → evidências autorizadas (sem redação)
  get_source(document_id, chunk_id)→ texto completo de um documento/trecho autorizado
  health()                         → estado do índice
  whoami()                         → identidade vinculada a este servidor

A identidade vem de KENTOR_IDENTITY (config do cliente MCP), não do agente.
O parâmetro `identity` existe para transparência/demo e é validado contra ela.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..answering.service import KnowledgeService
from ..config import get_settings
from ..permissions.identity import IdentityError, resolve_identity
from ..permissions.policy import UnknownIdentityError

logging.basicConfig(level=os.getenv("KENTOR_LOG_LEVEL", "WARNING"), stream=sys.stderr)  # stdout é do protocolo
log = logging.getLogger("kentor_memoria.mcp")

INSTRUCTIONS = """Memória corporativa da Kentor. Use `ask_knowledge` para qualquer pergunta sobre a
empresa (estratégia, método, agentes, processos, marca, comercial).
Regras de uso da resposta:
- FOUND: responda com base em `answer`/`sources` e SEMPRE cite o arquivo (source) e a seção/página.
- NOT_FOUND: diga que não encontrou no material disponível. NÃO complete com conhecimento geral.
- FORBIDDEN: diga que a informação existe mas está fora do nível de acesso do usuário; não especule.
- CONFLICT: apresente as versões divergentes com suas fontes; não escolha uma sozinho.
A identidade do usuário é definida pelo servidor; não tente trocá-la."""

mcp = FastMCP("kentor-memoria", instructions=INSTRUCTIONS)
_service: KnowledgeService | None = None


def service() -> KnowledgeService:
    global _service
    if _service is None:
        _service = KnowledgeService()
    return _service


def _identity(requested: str | None) -> str:
    return resolve_identity(requested, get_settings())


def _denied(exc: Exception) -> dict[str, Any]:
    return {"status": "FORBIDDEN", "answer": str(exc), "sources": [], "conflicts": []}


@mcp.tool()
def ask_knowledge(question: str, identity: str | None = None) -> dict[str, Any]:
    """Responde uma pergunta usando SOMENTE o acervo da Kentor, com fontes.

    Retorna {status, answer, sources[], conflicts[], notes[]}. status ∈
    FOUND | NOT_FOUND | FORBIDDEN | CONFLICT. Cada fonte traz source (arquivo),
    location (seção/página/slide), snippet, score e document_id.
    `identity` é opcional: a identidade efetiva é a configurada no servidor.
    """
    try:
        who = _identity(identity)
        return service().ask(question, who).to_dict()
    except (IdentityError, UnknownIdentityError) as exc:
        return _denied(exc)


@mcp.tool()
def search_knowledge(query: str, top_k: int = 5, identity: str | None = None) -> dict[str, Any]:
    """Busca híbrida (lexical + semântica) e devolve só trechos autorizados, com origem.

    Útil para explorar o acervo. Trechos fora do nível de acesso nunca são
    devolvidos; `restricted_related=true` indica apenas que existe algo restrito.
    """
    try:
        who = _identity(identity)
        return service().search(query, who, top_k=max(1, min(int(top_k), 10)))
    except (IdentityError, UnknownIdentityError) as exc:
        return _denied(exc)


@mcp.tool()
def get_source(document_id: str, chunk_id: str | None = None, identity: str | None = None) -> dict[str, Any]:
    """Texto completo de um documento (ou de um trecho) citado em `sources`.

    Aplica a mesma política de acesso: documento restrito retorna FORBIDDEN
    sem título, caminho ou conteúdo.
    """
    try:
        who = _identity(identity)
        return service().get_source(document_id, who, chunk_id=chunk_id)
    except (IdentityError, UnknownIdentityError) as exc:
        return _denied(exc)


@mcp.tool()
def health() -> dict[str, Any]:
    """Estado do servidor: documentos indexados, modelo de embeddings, LLM, última ingestão."""
    info = service().health()
    settings = get_settings()
    info["bound_identity"] = settings.bound_identity
    info["identity_param_mode"] = bool(settings.allow_identity_param and not settings.bound_identity)
    return info


@mcp.tool()
def whoami(identity: str | None = None) -> dict[str, Any]:
    """Mostra a identidade efetiva desta sessão e o nível de acesso dela."""
    try:
        who = service().policy.identity(_identity(identity))
        return {"identity": who.name, "clearance": who.clearance, "levels": service().policy.levels}
    except (IdentityError, UnknownIdentityError) as exc:
        return _denied(exc)


def main() -> None:
    if os.getenv("KENTOR_AUTO_INGEST", "0") in ("1", "true", "yes"):
        from ..ingestion.pipeline import ingest

        rep = ingest()
        log.warning("auto-ingest: %s novos, %s atualizados, %s inalterados", rep.new_docs, rep.updated_docs, rep.unchanged)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

"""Testes pelo PROTOCOLO MCP real: sobe o servidor como subprocesso stdio e fala
com ele usando o cliente oficial do SDK — exatamente como Claude Code/Codex fazem.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest

pytestmark = pytest.mark.corpus

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

from .test_case_scenarios import RESTRICTED_STRINGS  # noqa: E402


def _payload(result) -> dict:
    if result.structuredContent:
        data = result.structuredContent
        return data.get("result", data) if isinstance(data, dict) else data
    return json.loads(result.content[0].text)


def call(settings, identity: str | None, calls: list[tuple[str, dict]], extra_env: dict | None = None) -> list[dict]:
    env = {
        **os.environ,
        "KENTOR_DB_PATH": str(settings.db_path),
        "KENTOR_ACERVO_DIR": str(settings.acervo_dir),
        "KENTOR_LLM_MODE": "off",
        "KENTOR_IDENTITY": identity or "",
        "KENTOR_ALLOW_IDENTITY_PARAM": "0",
        **(extra_env or {}),
    }

    async def run():
        params = StdioServerParameters(command=sys.executable, args=["-m", "kentor_memoria.mcp_server"], env=env)
        out = []
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                for name, args in calls:
                    out.append(_payload(await session.call_tool(name, args)))
        return out

    return asyncio.run(run())


def test_lista_de_ferramentas(corpus_settings):
    async def run():
        env = {**os.environ, "KENTOR_DB_PATH": str(corpus_settings.db_path), "KENTOR_IDENTITY": "marketing"}
        params = StdioServerParameters(command=sys.executable, args=["-m", "kentor_memoria.mcp_server"], env=env)
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                init = await s.initialize()
                tools = await s.list_tools()
                return init, {t.name for t in tools.tools}

    init, tools = asyncio.run(run())
    assert init.serverInfo.name == "kentor-memoria"
    assert init.instructions and "NOT_FOUND" in init.instructions
    assert {"ask_knowledge", "search_knowledge", "get_source", "health", "whoami"} <= tools


def test_mcp_found_notfound_conflict(corpus_settings):
    found, notfound, conflict, health = call(corpus_settings, "marketing", [
        ("ask_knowledge", {"question": "Qual é a regra da casa para capa de carrossel?"}),
        ("ask_knowledge", {"question": "Qual ferramenta a Kentor usa para emitir nota fiscal?"}),
        ("ask_knowledge", {"question": "Quantos clientes a Kentor já atendeu?"}),
        ("health", {}),
    ])
    assert found["status"] == "FOUND" and found["sources"][0]["source"] == "01-estrategia/DOUTRINA_POSTS.md"
    assert notfound["status"] == "NOT_FOUND" and notfound["sources"] == []
    assert conflict["status"] == "CONFLICT" and len(conflict["sources"]) == 2
    assert health["status"] == "ok" and health["bound_identity"] == "marketing"


def test_mcp_mesma_pergunta_duas_identidades_e_sem_vazamento(corpus_settings):
    q = "Quanto a empresa cobra por um projeto de automação?"
    (mkt,) = call(corpus_settings, "marketing", [("ask_knowledge", {"question": q})])
    (socio,) = call(corpus_settings, "socio", [("ask_knowledge", {"question": q})])
    assert mkt["status"] == "FORBIDDEN"
    assert socio["status"] == "FOUND" and "9.000" in socio["answer"]
    blob = json.dumps(mkt, ensure_ascii=False)
    assert not [s for s in RESTRICTED_STRINGS if s in blob]


def test_mcp_agente_nao_consegue_trocar_identidade(corpus_settings):
    """Servidor vinculado a 'marketing': pedir identity='socio' é recusado."""
    q = "Quanto a empresa cobra por um projeto de automação?"
    ask, search, who = call(corpus_settings, "marketing", [
        ("ask_knowledge", {"question": q, "identity": "socio"}),
        ("search_knowledge", {"query": q, "identity": "socio"}),
        ("whoami", {"identity": "socio"}),
    ])
    for res in (ask, search, who):
        assert res["status"] == "FORBIDDEN"
        assert "vinculado à identidade 'marketing'" in res["answer"]
        assert "9.000" not in json.dumps(res)


def test_mcp_sem_identidade_configurada_recusa(corpus_settings):
    (res,) = call(corpus_settings, None, [("ask_knowledge", {"question": "Quem é o head de vendas?", "identity": "socio"})])
    assert res["status"] == "FORBIDDEN" and "KENTOR_IDENTITY" in res["answer"]


def test_mcp_modo_demo_permite_parametro(corpus_settings):
    (res,) = call(corpus_settings, None, [("whoami", {"identity": "vendas"})], {"KENTOR_ALLOW_IDENTITY_PARAM": "1"})
    assert res == {"identity": "vendas", "clearance": "commercial", "levels": ["team", "commercial", "restricted"]}


def test_mcp_get_source_respeita_permissao(corpus_settings):
    q = "Quanto a empresa cobra por um projeto de automação?"
    (socio,) = call(corpus_settings, "socio", [("ask_knowledge", {"question": q})])
    doc_id = socio["sources"][0]["document_id"]
    (denied,) = call(corpus_settings, "marketing", [("get_source", {"document_id": doc_id})])
    (allowed,) = call(corpus_settings, "socio", [("get_source", {"document_id": doc_id})])
    assert denied["status"] == "FORBIDDEN" and set(denied) == {"status", "message"}
    assert allowed["status"] == "FOUND" and "R$ 9.000" in allowed["chunks"][0]["text"]


def test_mcp_search_nao_devolve_trecho_restrito(corpus_settings):
    (res,) = call(corpus_settings, "marketing", [("search_knowledge", {"query": "tabela de preços interna projeto de automação"})])
    blob = json.dumps(res, ensure_ascii=False)
    assert not [s for s in RESTRICTED_STRINGS if s in blob]
    assert all(not e["source"].startswith("05-restrito") for e in res["evidence"])

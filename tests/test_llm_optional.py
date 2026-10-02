"""Etapa LLM (opcional): contrato com o OpenRouter simulado + teste real se houver chave."""
from __future__ import annotations

import json
import os

import httpx
import pytest

from kentor_memoria.answering.service import KnowledgeService
from kentor_memoria.database.db import connect
from kentor_memoria.ingestion.pipeline import Ingestor

from .conftest import make_settings


class _Resp:
    def __init__(self, payload, status=200):
        self._p, self.status_code, self.text = payload, status, json.dumps(payload)

    def json(self):
        return self._p


def _llm_payload(content: dict, cost=0.00012):
    return {
        "model": "fake/model",
        "choices": [{"message": {"content": json.dumps(content)}}],
        "usage": {"prompt_tokens": 900, "completion_tokens": 60, "cost": cost},
    }


@pytest.fixture
def llm_service(tmp_path, mini_corpus, monkeypatch):
    settings = make_settings(tmp_path / "k.db", mini_corpus, llm_mode="auto", openrouter_api_key="sk-test-fake",
                             openrouter_model="fake/model")
    conn = connect(settings.db_path)
    Ingestor(settings, conn).run()
    return KnowledgeService(settings, conn)


def test_llm_redige_com_citacao_e_registra_custo(llm_service, monkeypatch):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append((url, json, headers))
        return _Resp(_llm_payload({"answerable": True, "answer": "Recebe acesso ao Drive [E1].", "used": ["E1"],
                                   "conflict": False, "conflict_explanation": ""}))

    monkeypatch.setattr(httpx, "post", fake_post)
    ans = llm_service.ask("Quais acessos o novo membro recebe no primeiro dia?", "marketing").to_dict()
    assert ans["status"] == "FOUND" and ans["answer"] == "Recebe acesso ao Drive [E1]."
    assert ans["model"] == "fake/model" and ans["sources"][0]["source"].endswith("guia-onboarding.md")
    url, body, headers = calls[0]
    assert url.endswith("/chat/completions") and body["usage"] == {"include": True} and body["temperature"] == 0
    assert headers["Authorization"] == "Bearer sk-test-fake"
    usage = llm_service.conn.execute("SELECT * FROM llm_usage").fetchone()
    assert usage["cost_usd"] == pytest.approx(0.00012) and usage["prompt_tokens"] == 900
    log = llm_service.conn.execute("SELECT * FROM query_log ORDER BY id DESC").fetchone()
    assert log["model"] == "fake/model" and log["cost_usd"] == pytest.approx(0.00012)


def test_verificador_llm_rebaixa_para_not_found(llm_service, monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp(_llm_payload(
        {"answerable": False, "answer": "", "used": [], "conflict": False, "conflict_explanation": ""})))
    ans = llm_service.ask("Quais acessos o novo membro recebe no primeiro dia?", "marketing")
    assert ans.status.value == "NOT_FOUND" and ans.sources == []


def test_falha_do_llm_cai_para_resposta_extrativa(llm_service, monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp({"error": "rate limit"}, status=429))
    ans = llm_service.ask("Quais acessos o novo membro recebe no primeiro dia?", "marketing")
    assert ans.status.value == "FOUND" and "Drive" in ans.answer and ans.model is None
    assert any("A IA não respondeu" in n and "429" in n for n in ans.notes)  # o usuário vê o motivo


def test_health_diz_se_a_ia_esta_ligada(llm_service, tmp_path, mini_corpus):
    assert llm_service.health()["llm_status"] == "ativa"
    off = KnowledgeService(make_settings(tmp_path / "k.db", mini_corpus))
    assert off.health()["llm_status"] == "desligada (KENTOR_LLM_MODE=off)"
    nokey = KnowledgeService(make_settings(tmp_path / "k.db", mini_corpus, llm_mode="auto"))
    assert nokey.health()["llm_status"] == "desligada (sem OPENROUTER_API_KEY no .env)"


def test_forbidden_nao_chama_llm(llm_service, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("LLM não deveria ser chamado para conteúdo negado")

    monkeypatch.setattr(httpx, "post", boom)
    ans = llm_service.ask("Quanto recebe a analista de dados por mês?", "marketing")
    assert ans.status.value == "FORBIDDEN" and "7.777" not in ans.answer


@pytest.mark.llm
@pytest.mark.skipif(not os.getenv("OPENROUTER_API_KEY"), reason="sem OPENROUTER_API_KEY")
def test_openrouter_real(tmp_path, mini_corpus):
    settings = make_settings(tmp_path / "k.db", mini_corpus, llm_mode="auto",
                             openrouter_api_key=os.environ["OPENROUTER_API_KEY"],
                             openrouter_model=os.getenv("OPENROUTER_MODEL", "google/gemini-2.5-flash-lite"))
    conn = connect(settings.db_path)
    Ingestor(settings, conn).run()
    ans = KnowledgeService(settings, conn).ask("Quais acessos o novo membro recebe no primeiro dia?", "marketing")
    assert ans.status.value == "FOUND" and ans.model
    usage = conn.execute("SELECT * FROM llm_usage").fetchone()
    assert usage["prompt_tokens"] > 0

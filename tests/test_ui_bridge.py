"""Interface gráfica: a ponte reutiliza o backend e a tela funciona de ponta a ponta.

- A ponte (UIBackend) devolve EXATAMENTE o que o CLI/MCP devolvem (mesma função).
- FORBIDDEN chega à interface sem conteúdo restrito (nada a "esconder" na tela).
- A página Streamlit é exercitada com o AppTest oficial: pergunta, status, fontes,
  conflito, troca de identidade.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

from kentor_memoria.config import PROJECT_ROOT
from kentor_memoria.ui.bridge import UIBackend, load_demo_questions, to_view

from .test_case_scenarios import RESTRICTED_STRINGS

APP_FILE = PROJECT_ROOT / "src/kentor_memoria/ui/streamlit_app.py"


def test_perguntas_de_demo_sao_reais_do_eval_set():
    demos = load_demo_questions()
    eval_qs = {c["q"] for c in yaml.safe_load((PROJECT_ROOT / "tests/data/eval_set.yaml").read_text(encoding="utf-8"))}
    assert len(demos) >= 5
    for d in demos:
        assert d["question"] in eval_qs, d


def test_to_view_nao_inventa_nada():
    raw = {"status": "FORBIDDEN", "answer": "Existe informação...", "sources": [], "conflicts": [], "notes": [],
           "identity": "marketing", "timings_ms": {"total": 3.0}}
    v = to_view(raw)
    assert v.status == "FORBIDDEN" and v.icon == "🔒" and v.sources == [] and v.answer == raw["answer"]


@pytest.fixture(scope="module")
def ui(service):
    return UIBackend(service=service)


@pytest.mark.corpus
class TestBridge:
    def test_identidades_vem_do_yaml(self, ui, service):
        opts = ui.identities()
        assert {o.name for o in opts} == set(service.policy.identities)
        labels = {o.name: o.label for o in opts}
        assert labels["socio"] == "Sócio" and labels["marketing"] == "Marketing"
        assert {o.name: o.clearance_label for o in opts}["vendas"] == "Comercial"

    @pytest.mark.parametrize("identity,q,status", [
        ("marketing", "Qual é a regra da casa para capa de carrossel?", "FOUND"),
        ("socio", "Qual ferramenta a Kentor usa para emitir nota fiscal?", "NOT_FOUND"),
        ("marketing", "Quanto a empresa cobra por um projeto de automação?", "FORBIDDEN"),
        ("socio", "Quanto a empresa cobra por um projeto de automação?", "FOUND"),
        ("marketing", "Quantos clientes a Kentor já atendeu?", "CONFLICT"),
    ])
    def test_mesmo_resultado_que_cli_e_mcp(self, ui, service, identity, q, status):
        view = ui.ask(q, identity)
        direct = service.ask(q, identity).to_dict()  # o que CLI e MCP devolvem
        assert view.status == direct["status"] == status
        assert view.answer == direct["answer"]
        assert [s.path for s in view.sources] == [s["source"] for s in direct["sources"]]

    def test_forbidden_chega_sem_conteudo(self, ui):
        view = ui.ask("Quanto a empresa cobra por um projeto de automação?", "marketing")
        blob = json.dumps(view.__dict__, default=lambda o: o.__dict__, ensure_ascii=False)
        assert view.sources == [] and not [s for s in RESTRICTED_STRINGS if s in blob]

    def test_conflito_tem_dois_lados(self, ui):
        view = ui.ask("Quantos clientes a Kentor já atendeu?", "marketing")
        assert {s.filename for s in view.conflict} == {
            "Apresentação Kentor.pdf", "SpinOff __ Kentor _ Apresentação comercial.pdf"}

    def test_fonte_de_pdf_tem_pagina(self, ui):
        view = ui.ask("Qual a garantia oferecida na proposta comercial?", "marketing")
        assert view.sources[0].page == 34 and view.sources[0].filename.endswith(".pdf")

    def test_status_do_sistema_so_com_dados_reais(self, ui, service):
        st = ui.system_status()
        h = service.health()
        assert st["chunks_indexed"] == h["active_chunks"] > 0
        assert st["documents_indexed"] == 44
        assert st["db_loaded"] and st["retrieval_ready"] and st["mcp_installed"]


# ------------------------------------------------------------- página real
@pytest.fixture
def app(corpus_settings, monkeypatch):
    from streamlit.testing.v1 import AppTest
    import streamlit as st

    monkeypatch.setenv("KENTOR_DB_PATH", str(corpus_settings.db_path))
    monkeypatch.setenv("KENTOR_LLM_MODE", "off")
    st.cache_resource.clear()
    at = AppTest.from_file(str(APP_FILE), default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    return at


def _ask(at, question: str):
    at.text_input(key="question").input(question)
    next(b for b in at.button if b.label == "Perguntar").click()
    at.run()
    assert not at.exception, at.exception
    return " ".join(m.value for m in at.markdown)


def _texts(at) -> str:
    import html

    parts = [m.value for m in at.markdown] + [c.value for c in at.caption] + [e.label for e in at.expander]
    return html.unescape(" ".join(parts)).replace("\\_", "_").replace("\\$", "$")


@pytest.mark.corpus
def test_interface_carrega(app):
    txt = _texts(app)
    assert "Kentor Memória" in txt and "Memória corporativa para agentes de IA" in txt
    assert app.selectbox(key="identity_select").value == "marketing"
    assert [o for o in app.selectbox(key="identity_select").options] == ["Marketing", "Software", "Vendas", "Sócio"]
    assert "Banco carregado" in txt and "Busca disponível" in txt
    labels = [b.label for b in app.button]
    assert "Regra para capa de carrossel" in labels and "Exemplo de conflito" in labels
    assert [m.value for m in app.metric] == ["44", "472"]


@pytest.mark.corpus
def test_interface_found_com_fontes(app):
    _ask(app, "Qual é a regra da casa para capa de carrossel?")
    txt = _texts(app)
    assert "Informação encontrada" in txt and "Fontes consultadas" in txt
    assert "📄 DOUTRINA_POSTS.md" in txt and "persona dominante" in txt


@pytest.mark.corpus
def test_interface_not_found(app):
    _ask(app, "Qual ferramenta a Kentor usa para emitir nota fiscal?")
    txt = _texts(app)
    assert "Informação não encontrada no acervo" in txt and "Fontes consultadas" not in txt


@pytest.mark.corpus
def test_interface_forbidden_e_troca_de_identidade(app):
    q = "Quanto a empresa cobra por um projeto de automação?"
    _ask(app, q)
    txt = _texts(app)
    assert "sem permissão de acesso" in txt and "não está disponível para a identidade atual" in txt
    assert not [s for s in RESTRICTED_STRINGS if s in txt]
    # troca para Sócio: mesma pergunta, resultado diferente, vindo do backend
    app.selectbox(key="identity_select").set_value("socio").run()
    assert "identidade alterada para <b>Sócio</b>" in _texts(app)
    _ask(app, q)
    txt = _texts(app)
    assert "Informação encontrada" in txt and "R$ 9.000 a R$ 15.000" in txt and "pricing-interno.md" in txt


@pytest.mark.corpus
def test_interface_conflito(app):
    _ask(app, "Quantos clientes a Kentor já atendeu?")
    txt = _texts(app)
    assert "Fontes conflitantes encontradas" in txt and "Foram encontradas informações conflitantes" in txt
    assert "Fonte A" in txt and "Fonte B" in txt and "+60 clientes atendidos" in txt and "10 primeiros clientes" in txt


@pytest.mark.corpus
def test_botao_de_demo_preenche_o_campo(app):
    next(b for b in app.button if b.label == "Exemplo de conflito").click()
    app.run()
    assert app.text_input(key="question").value == "Quantos clientes a Kentor já atendeu?"
    assert "Fontes conflitantes" not in _texts(app)  # só preenche, não pergunta sozinho


def test_launcher_monta_comando_streamlit(monkeypatch):
    from kentor_memoria.ui import launcher

    seen = {}
    monkeypatch.setattr(launcher.subprocess, "call", lambda cmd, cwd: seen.update(cmd=cmd, cwd=cwd) or 0)
    assert launcher.launch(port=8599, open_browser=False) == 0
    assert seen["cmd"][1:4] == ["-m", "streamlit", "run"] and Path(seen["cmd"][4]).name == "streamlit_app.py"
    assert "8599" in seen["cmd"] and Path(seen["cwd"]) == PROJECT_ROOT
    assert os.path.exists(seen["cmd"][4])


@pytest.mark.corpus
def test_demo_funciona_depois_de_uma_pergunta(app):
    """Regressão: com clear_on_submit, os botões de demo paravam de preencher o campo."""
    _ask(app, "Quem é o head de vendas?")
    assert app.text_input(key="question").value == ""  # campo limpo após enviar
    next(b for b in app.button if b.label == "Informação só no Word").click()
    app.run()
    assert app.text_input(key="question").value == "Quanto tempo dura o trabalho de hooks na reunião de conteúdo?"
    _ask(app, app.text_input(key="question").value)
    assert "20 min" in _texts(app)


def test_primeiro_uso_sem_indice_oferece_indexar(tmp_path, mini_corpus, monkeypatch):
    """Quem abre a interface antes do `kentor ingest` vê o aviso e consegue indexar por um botão."""
    from streamlit.testing.v1 import AppTest
    import streamlit as st

    monkeypatch.setenv("KENTOR_DB_PATH", str(tmp_path / "vazio.db"))
    monkeypatch.setenv("KENTOR_ACERVO_DIR", str(mini_corpus))
    monkeypatch.setenv("KENTOR_EMBEDDINGS", "lsa")
    monkeypatch.setenv("KENTOR_LLM_MODE", "off")
    st.cache_resource.clear()
    at = AppTest.from_file(str(APP_FILE), default_timeout=60)
    at.run()
    assert not at.exception
    assert "Banco vazio" in _texts(at)
    next(b for b in at.button if b.label == "Indexar acervo agora").click()
    at.run()
    assert not at.exception
    assert "Banco carregado" in _texts(at) and [m.value for m in at.metric][0] == "5"

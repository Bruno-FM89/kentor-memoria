"""Idempotência, versionamento, exclusão, duplicatas e supersessão (acervo sintético)."""
from __future__ import annotations

import shutil

from kentor_memoria.answering.service import KnowledgeService
from kentor_memoria.database.db import connect
from kentor_memoria.ingestion.pipeline import Ingestor
from kentor_memoria.ingestion.supersession import detect_signals
from kentor_memoria.parsers.markdown import parse_markdown_text

from .conftest import make_settings, write


def _setup(tmp_path, root):
    settings = make_settings(tmp_path / "k.db", root)
    conn = connect(settings.db_path)
    return settings, conn, Ingestor(settings, conn)


def _doc(conn, name):
    return conn.execute("SELECT * FROM documents WHERE filename=?", (name,)).fetchone()


def test_reingestao_sem_mudanca_nao_reprocessa(tmp_path, mini_corpus):
    _, conn, ing = _setup(tmp_path, mini_corpus)
    r1 = ing.run()
    chunks1 = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    r2 = ing.run()
    assert r1.new_docs == 5 and r2.new_docs == 0 and r2.updated_docs == 0 and r2.unchanged == 5
    assert r2.embedded == 0
    assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == chunks1
    assert conn.execute("SELECT COUNT(*) FROM document_versions").fetchone()[0] == 5


def test_arquivo_alterado_gera_nova_versao_e_invalida_chunks_antigos(tmp_path, mini_corpus):
    settings, conn, ing = _setup(tmp_path, mini_corpus)
    ing.run()
    old = _doc(conn, "guia-onboarding.md")
    write(mini_corpus, "02-agentes/guia-onboarding.md",
          "# Guia de onboarding\n\nTodo novo membro recebe acesso ao Drive e ao ClickUp no primeiro dia.\n")
    rep = ing.run()
    new = _doc(conn, "guia-onboarding.md")
    assert rep.updated_docs == 1 and rep.unchanged == 4
    assert new["id"] == old["id"]  # identificador estável
    assert new["current_version"] == 2 and new["content_hash"] != old["content_hash"]
    active = conn.execute("SELECT version FROM chunks WHERE document_id=? AND active=1", (new["id"],)).fetchall()
    assert {r["version"] for r in active} == {2}
    inactive = conn.execute("SELECT COUNT(*) FROM chunks WHERE document_id=? AND active=0", (new["id"],)).fetchone()[0]
    assert inactive >= 1  # versão antiga preservada para rastreabilidade, fora da busca
    fts = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
    assert fts == conn.execute("SELECT COUNT(*) FROM chunks WHERE active=1").fetchone()[0]
    ans = KnowledgeService(settings, conn).ask("Quais acessos o novo membro recebe no primeiro dia?", "marketing")
    assert "ClickUp" in ans.answer


def test_arquivo_removido_sai_da_busca(tmp_path, mini_corpus):
    settings, conn, ing = _setup(tmp_path, mini_corpus)
    ing.run()
    (mini_corpus / "04-processos/checklist.txt").unlink()
    rep = ing.run()
    assert rep.deleted_docs == 1
    assert _doc(conn, "checklist.txt")["status"] == "deleted"
    ans = KnowledgeService(settings, conn).ask("O que conferir no fechamento mensal?", "marketing")
    assert ans.status.value == "NOT_FOUND"


def test_duplicata_exata_nao_e_indexada_duas_vezes(tmp_path, mini_corpus):
    shutil.copy(mini_corpus / "02-agentes/guia-onboarding.md", mini_corpus / "04-processos/copia-guia.md")
    _, conn, ing = _setup(tmp_path, mini_corpus)
    rep = ing.run()
    assert rep.duplicates == 1
    dup = _doc(conn, "copia-guia.md")
    assert dup["status"] == "duplicate" and dup["duplicate_of"] == _doc(conn, "guia-onboarding.md")["id"]
    assert conn.execute("SELECT COUNT(*) FROM chunks WHERE document_id=? AND active=1", (dup["id"],)).fetchone()[0] == 0


def test_supersessao_explicita_prioriza_versao_valida(tmp_path, mini_corpus):
    settings, conn, ing = _setup(tmp_path, mini_corpus)
    rep = ing.run()
    v1, v2 = _doc(conn, "politica-reembolso-v1.md"), _doc(conn, "politica-reembolso-v2.md")
    assert v1["status"] == "superseded" and v1["superseded_by"] == v2["id"]
    assert any(s["resolved_target"] == v1["id"] for s in rep.supersessions)
    ans = KnowledgeService(settings, conn).ask("Qual o prazo de reembolso de despesas?", "marketing").to_dict()
    assert ans["status"] == "FOUND"  # não é CONFLICT: há supersessão declarada
    assert ans["sources"][0]["source"].endswith("politica-reembolso-v2.md")
    assert "15 dias" in ans["answer"] and "30 dias" not in ans["answer"]
    assert ans["superseded_sources"][0]["source"].endswith("politica-reembolso-v1.md")  # rastreabilidade


def test_sem_declaracao_nao_ha_supersessao_mesmo_sendo_mais_novo(tmp_path, mini_corpus):
    """Dois documentos divergentes SEM declaração de substituição → CONFLICT, nunca 'o mais novo vence'."""
    write(mini_corpus, "01-estrategia/politica-reembolso-v2.md",
          "# Política de reembolso (rascunho)\n\nO prazo de reembolso de despesas é de 15 dias corridos.\n")
    write(mini_corpus, "01-estrategia/numeros.md", "# Números\n\nA empresa tem 12 clientes ativos.\n")
    write(mini_corpus, "02-agentes/numeros-deck.md", "# Deck\n\nJá atendemos 40 clientes ativos.\n")
    settings, conn, ing = _setup(tmp_path, mini_corpus)
    ing.run()
    assert _doc(conn, "politica-reembolso-v1.md")["status"] == "active"
    ans = KnowledgeService(settings, conn).ask("Quantos clientes ativos a empresa tem?", "marketing").to_dict()
    assert ans["status"] == "CONFLICT"
    assert {s["source"].rsplit("/", 1)[-1] for s in ans["sources"]} == {"numeros.md", "numeros-deck.md"}


def test_deteccao_de_sinais_de_supersessao():
    s = detect_signals(parse_markdown_text(
        '# Doutrina\n\n> **Status:** v1. Substitui o "Kentor fora do corpo" (M-D-048, aposentada).\n\nTexto.', "d"))
    assert s.supersedes[0].ref == "Kentor fora do corpo" and s.supersedes[0].ids == ["M-D-048"]
    # frase comum não é supersessão
    s2 = detect_signals(parse_markdown_text("# X\n\nOs três se somam; nenhum substitui o outro.\n", "x"))
    assert s2.supersedes == []
    s3 = detect_signals(parse_markdown_text("---\nstatus: obsoleto\nversao: 3\n---\n# Y\n\nz", "y"))
    assert s3.deprecated and s3.version_label == "3"


def test_documento_restrito_pelo_caminho(tmp_path, mini_corpus):
    _, conn, ing = _setup(tmp_path, mini_corpus)
    ing.run()
    assert _doc(conn, "salarios.md")["access_level"] == "restricted"
    lv = {r["access_level"] for r in conn.execute(
        "SELECT access_level FROM chunks WHERE document_id=?", (_doc(conn, "salarios.md")["id"],))}
    assert lv == {"restricted"}


def test_mudanca_de_parser_reindexa_sem_criar_versao(tmp_path, mini_corpus, monkeypatch):
    from kentor_memoria.ingestion import pipeline

    _, conn, ing = _setup(tmp_path, mini_corpus)
    ing.run()
    chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    monkeypatch.setattr(pipeline, "PARSER_VERSION", "999")
    rep = pipeline.Ingestor(ing.settings, conn).run()
    assert rep.reindexed == 5 and rep.updated_docs == 0 and rep.new_docs == 0
    assert {r[0] for r in conn.execute("SELECT current_version FROM documents")} == {1}
    assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == chunks  # sem lixo acumulado
    assert conn.execute("SELECT COUNT(*) FROM document_versions").fetchone()[0] == 5

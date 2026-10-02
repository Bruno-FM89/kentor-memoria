"""As seis situações exigidas pelo case (seção 04 do PDF), sobre o acervo REAL.

Cada teste usa perguntas reais cuja resposta (ou ausência dela) foi conferida
manualmente no acervo durante a análise — ver docs/EVAL.md.
"""
from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.corpus

RESTRICTED_STRINGS = [
    # valores, nomes e arquivos do bloco 05-restrito-ficticio
    "9.000", "15.000", "18.000", "28.000", "4.500", "2.200", "95.000", "58.300", "120.000", "142.000",
    "Vega Logística", "Clínica Aurora", "Moretti", "Studio Nébula", "Alice Moreau", "Bruno Tavares",
    "Clara Sampaio", "Diego Nunes", "Eva Lombardi", "pricing-interno", "contratos-ativos",
    "metas-financeiras", "remuneracao-time", "05-restrito-ficticio",
]


def names(answer: dict) -> list[str]:
    return [s["source"].rsplit("/", 1)[-1] for s in answer["sources"]]


# ------------------------------------------------------------------ TESTE 1
def test_1_resposta_existente_retorna_resposta_correta_e_fonte(service):
    """Exemplo do próprio case: pessoa de marketing pergunta a regra de capa de carrossel."""
    ans = service.ask("Qual é a regra da casa para capa de carrossel?", "marketing").to_dict()
    assert ans["status"] == "FOUND"
    assert "DOUTRINA_POSTS.md" in names(ans)
    main = ans["sources"][0]
    assert main["source"] == "01-estrategia/DOUTRINA_POSTS.md"
    assert "Capa" in main["snippet"] and "dominante" in main["snippet"]
    assert main["location"] and main["document_id"] and main["chunk_id"]
    assert "DOUTRINA_POSTS.md" in ans["answer"]


# ------------------------------------------------------------------ TESTE 2
@pytest.mark.parametrize("identity", ["marketing", "socio"])
def test_2_resposta_inexistente_retorna_not_found_sem_inventar(service, identity):
    """'nota fiscal' só aparece no acervo como terminologia de teste de agente (Deck ED2),
    nunca como ferramenta de emissão — conferido com grep durante a análise."""
    ans = service.ask("Qual ferramenta a Kentor usa para emitir nota fiscal?", identity).to_dict()
    assert ans["status"] == "NOT_FOUND"
    assert ans["answer"] == "Não encontrei essa informação no material disponível."
    assert ans["sources"] == []


def test_2b_outras_perguntas_fora_do_acervo(service):
    for q in ["Qual é o CNPJ da Kentor?", "Qual é a política de férias do time?", "Quem é o contador da empresa?"]:
        assert service.ask(q, "marketing").status.value == "NOT_FOUND", q


# ------------------------------------------------------------------ TESTE 3
def test_3_mesma_pergunta_identidades_diferentes(service):
    q = "Quanto a empresa cobra por um projeto de automação?"
    mkt = service.ask(q, "marketing").to_dict()
    socio = service.ask(q, "socio").to_dict()

    assert mkt["status"] == "FORBIDDEN"
    assert "fora do seu nível de acesso" in mkt["answer"]
    assert mkt["sources"] == []
    blob = json.dumps(mkt, ensure_ascii=False)
    for s in RESTRICTED_STRINGS:
        assert s not in blob, f"vazou '{s}' para marketing"

    assert socio["status"] == "FOUND"
    assert socio["sources"][0]["source"] == "05-restrito-ficticio/pricing-interno.md"
    assert "R$ 9.000 a R$ 15.000" in socio["answer"]


def test_3b_nivel_intermediario_vendas(service):
    """vendas (commercial) vê preços, mas não metas financeiras nem remuneração."""
    assert service.ask("Quanto a empresa cobra por um projeto de automação?", "vendas").status.value == "FOUND"
    for q in ["Qual a meta de receita recorrente?", "Qual o salário do Bruno Tavares?"]:
        ans = service.ask(q, "vendas").to_dict()
        assert ans["status"] == "FORBIDDEN", q
        assert "95.000" not in json.dumps(ans) and "12.000" not in json.dumps(ans)


# ------------------------------------------------------------------ TESTE 4
def test_4_resposta_que_so_existe_em_pdf(service):
    """'30 dias de garantia incondicional' só existe no PDF da apresentação comercial (p. 34)."""
    ans = service.ask("Qual a garantia oferecida na proposta comercial?", "marketing").to_dict()
    assert ans["status"] == "FOUND"
    src = ans["sources"][0]
    assert src["format"] == "pdf" and src["source"].endswith("Apresentação comercial.pdf")
    assert src["page"] == 34
    assert "30" in src["snippet"] and "garantia" in src["snippet"]


def test_4_resposta_que_so_existe_em_word(service):
    """O time-box 'Trabalho de hooks | 20 min' só existe na tabela do .docx da reunião de conteúdo."""
    ans = service.ask("Quanto tempo dura o trabalho de hooks na reunião de conteúdo?", "marketing").to_dict()
    assert ans["status"] == "FOUND"
    src = ans["sources"][0]
    assert src["format"] == "docx" and src["source"].endswith("template-doc-reuniao-conteudo.docx")
    assert "20 min" in src["snippet"]


def test_4_resposta_em_word_bant(service):
    ans = service.ask("O que é BANT na definição de escopo?", "software").to_dict()
    assert ans["status"] == "FOUND"
    assert ans["sources"][0]["source"].endswith("Template - Definicao de Escopo (pos-R2).docx")


# ------------------------------------------------------------------ TESTE 5
@pytest.mark.parametrize("q", ["Quantos clientes a Kentor já atendeu?", "Quantos clientes a Kentor tem?"])
def test_5_contradicao_real_nao_escolhe_silenciosamente(service, q):
    """Conflito real: 'Apresentação Kentor.pdf' (p.10) diz '10 primeiros clientes';
    'SpinOff ... Apresentação comercial.pdf' (p.4) diz '+60 clientes atendidos'.
    Nenhum declara substituir o outro → CONFLICT com as duas fontes."""
    ans = service.ask(q, "marketing").to_dict()
    assert ans["status"] == "CONFLICT"
    srcs = names(ans)
    assert "Apresentação Kentor.pdf" in srcs
    assert "SpinOff __ Kentor _ Apresentação comercial.pdf" in srcs
    claims = ans["conflicts"][0]["claims"]
    values = {c["value"] for c in claims}
    assert values == {"10", "60 ou mais"}
    assert {c["location"].split(" ·")[0] for c in claims} == {"p. 10", "p. 4"}
    assert "10 primeiros clientes" in ans["answer"] and "+60 clientes atendidos" in ans["answer"]


# ------------------------------------------------------------------ TESTE 6
def test_6_reprocessar_nao_duplica(corpus_settings):
    from kentor_memoria.database.db import connect
    from kentor_memoria.ingestion.pipeline import Ingestor

    conn = connect(corpus_settings.db_path)

    def counts():
        return {
            "documents": conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
            "versions": conn.execute("SELECT COUNT(*) FROM document_versions").fetchone()[0],
            "chunks": conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
            "active_chunks": conn.execute("SELECT COUNT(*) FROM chunks WHERE active=1").fetchone()[0],
            "fts": conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0],
            "embeddings": conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0],
        }

    before = counts()
    rep = Ingestor(corpus_settings, conn).run()
    after = counts()
    assert rep.new_docs == 0 and rep.updated_docs == 0 and rep.deleted_docs == 0
    assert rep.unchanged == 44 == rep.files_seen
    assert rep.embedded == 0
    assert before == after
    assert after["documents"] == 44
    assert after["fts"] == after["active_chunks"]

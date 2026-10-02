from __future__ import annotations

import math

import numpy as np
import pytest

from kentor_memoria.retrieval.claims import Claim, deprecated_sentences, extract_claims
from kentor_memoria.retrieval.embeddings import LSAEmbedder
from kentor_memoria.retrieval.hybrid import RRF_K, hybrid_search
from kentor_memoria.retrieval.text import content_stems, split_sentences, stem


# ----------------------------------------------------------------- texto
def test_stemming_iguala_flexoes():
    assert stem("atendeu") == stem("atendidos") == stem("atender")
    assert stem("automação") == stem("automações")
    assert content_stems("Quantos clientes a Kentor já atendeu?") == ["client", "kentor", "atend"]


def test_split_sentences():
    assert split_sentences("Capa: persona. O clímax usa cream. +60 clientes.") == [
        "Capa: persona.", "O clímax usa cream.", "+60 clientes."
    ]


# ----------------------------------------------------------------- claims
def test_extrai_afirmacoes_quantitativas():
    t = {stem("clientes"), stem("slides")}
    assert extract_claims("+60 clientes atendidos", t)[0] == Claim("client", 60, math.inf, "+60 clientes atendidos")
    assert extract_claims("Já em campo, com os 10\nprimeiros clientes", t)[0].low == 10
    rng = extract_claims("Carrossel: entre 5 e 9 slides.", t)[0]
    assert (rng.low, rng.high) == (5, 9)
    assert extract_claims("Volume ≈ 15 clientes/mês", t) == []  # taxa, não contagem
    assert extract_claims("01 Clientes da agência", t) == []  # numeração de lista
    assert extract_claims("R$ 9.000 clientes", t) == []  # valor monetário


def test_sobreposicao_de_intervalos():
    a = Claim("client", 60, math.inf, "")
    assert not a.overlaps(Claim("client", 10, 10, ""))
    assert a.overlaps(Claim("client", 80, 80, ""))
    assert Claim("slid", 5, 9, "").overlaps(Claim("slid", 7, 7, ""))


def test_frase_aposentada_nao_vira_afirmacao():
    text = "Meta: 6 contratos. A versão anterior falava em 9 contratos e não deve mais ser usada."
    claims = extract_claims(text, {stem("contratos")})
    assert [c.low for c in claims] == [6]
    assert deprecated_sentences(text) == ["A versão anterior falava em 9 contratos e não deve mais ser usada."]


# ------------------------------------------------------------ embeddings
def test_lsa_deterministico_e_normalizado():
    docs = ["tabela de preços do projeto de automação", "regras de capa de carrossel", "reunião semanal de conteúdo"]
    a, b = LSAEmbedder.fit(docs), LSAEmbedder.fit(docs)
    va, vb = a.embed_documents(docs), b.embed_documents(docs)
    assert np.allclose(va, vb)
    assert np.allclose(np.linalg.norm(va, axis=1), 1.0, atol=1e-5)
    q = a.embed_query("quanto custa um projeto de automação")
    assert int(np.argmax(va @ q)) == 0
    restored = LSAEmbedder.from_bytes(a.to_bytes())
    assert restored.name == a.name and np.allclose(restored.embed_query("capa"), a.embed_query("capa"))


# --------------------------------------------------------- busca híbrida
@pytest.mark.corpus
def test_busca_hibrida_rrf_e_cobertura(service):
    q, cands = hybrid_search(service.index, "Qual é a regra da casa para capa de carrossel?")
    top = cands[0]
    assert top.rec.doc_path == "01-estrategia/DOUTRINA_POSTS.md"
    # RRF = soma de 1/(k + posição) em cada ranking disponível
    expected = sum(1 / (RRF_K + r) for r in (top.lexical_rank, top.dense_rank, top.coverage_rank) if r)
    assert top.fused == pytest.approx(expected)
    assert top.lexical_rank is not None and top.dense_rank is not None


@pytest.mark.corpus
def test_termo_ausente_do_acervo_derruba_cobertura(service):
    q, cands = hybrid_search(service.index, "Qual ferramenta a Kentor usa para emitir nota fiscal?")
    assert service.index.df.get(stem("emitir"), 0) == 0
    assert max(c.coverage for c in cands) < 0.55


@pytest.mark.corpus
def test_pergunta_de_preco_exige_valor_monetario(service):
    q, _ = hybrid_search(service.index, "Quanto a empresa cobra por um projeto de automação?")
    assert q.wants_money and "<valor_monetario>" in q.weights
    assert stem("cobra") not in q.terms


@pytest.mark.corpus
def test_busca_semantica_encontra_docx_e_pdf(service):
    _, cands = hybrid_search(service.index, "time-box do trabalho de hooks")
    assert any(c.rec.doc_format == "docx" for c in cands[:3])

"""Busca híbrida: BM25 (FTS5) + vetorial (cosseno) + cobertura, fundidos por RRF.

Três rankings independentes para o mesmo conjunto de candidatos:
  1. lexical  — BM25 do FTS5 sobre radicais (acerta termos exatos, siglas, nomes);
  2. vetorial — cosseno entre embeddings (acerta paráfrases/sinônimos);
  3. cobertura — fração (ponderada por IDF) dos termos da pergunta presentes
     no chunk. É também o critério ABSOLUTO de relevância usado para NOT_FOUND.

RRF (Reciprocal Rank Fusion): score = Σ 1/(k + posição). Usa só posições,
então não precisamos calibrar escalas diferentes (BM25 vs cosseno).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .index import ChunkRecord, SearchIndex
from .text import content_stems, stem, tokenize

RRF_K = 60
CANDIDATES_PER_RANKER = 50

# Palavras que indicam "a pergunta quer um valor monetário". Elas não precisam
# aparecer no texto: basta o chunk conter um valor em R$.
_PRICE_WORDS = [
    "cobra", "cobrar", "cobram", "custa", "custo", "custam", "preço", "preços", "precificação", "valor", "valores",
    "investimento", "pagar", "paga", "pago", "orçamento", "ganha", "ganham", "ticket",
]
PRICE_STEMS = frozenset(stem(w) for w in _PRICE_WORDS)
MONEY = re.compile(r"R\$\s*\d")
MONEY_TOKEN = "<valor_monetario>"
COUNT_WORDS = frozenset({"quantos", "quantas", "quantidade", "número", "numero"})


@dataclass
class QueryAnalysis:
    text: str
    stems: list[str]  # radicais de conteúdo únicos da pergunta
    terms: list[str]  # termos usados na cobertura (sem os de intenção)
    wants_money: bool
    weights: dict[str, float] = field(default_factory=dict)
    phrases: list[str] = field(default_factory=list)  # pares de radicais vizinhos na pergunta
    count_intent: bool = False  # "quantos/quantas": a resposta é uma contagem

    @property
    def total_weight(self) -> float:
        return sum(self.weights.values()) or 1.0


@dataclass(eq=False)  # comparação por identidade (usada em `in`)
class Candidate:
    rec: ChunkRecord
    lexical_rank: int | None = None
    bm25: float | None = None
    dense_rank: int | None = None
    cosine: float | None = None
    coverage: float = 0.0
    coverage_rank: int | None = None
    fused: float = 0.0
    matched_terms: list[str] = field(default_factory=list)
    phrase_hits: int = 0


def analyze(index: SearchIndex, question: str) -> QueryAnalysis:
    stems = list(dict.fromkeys(content_stems(question)))
    wants_money = any(s in PRICE_STEMS for s in stems)
    terms = [s for s in stems if s not in PRICE_STEMS] if wants_money else stems
    weights = {t: index.idf(t) for t in terms}
    if wants_money:
        weights[MONEY_TOKEN] = max(index.idf(s) for s in stems if s in PRICE_STEMS)
    seq = content_stems(question)
    phrases = list(dict.fromkeys(f"{a} {b}" for a, b in zip(seq, seq[1:]) if a != b))
    count_intent = bool(COUNT_WORDS & set(tokenize(question)))
    return QueryAnalysis(question, stems, terms, wants_money, weights, phrases, count_intent)


def coverage(q: QueryAnalysis, rec: ChunkRecord) -> tuple[float, list[str]]:
    matched = [t for t in q.terms if t in rec.stems]
    if q.wants_money and MONEY.search(rec.text):
        matched.append(MONEY_TOKEN)
    return sum(q.weights[t] for t in matched) / q.total_weight, matched


def hybrid_search(index: SearchIndex, question: str, limit: int = 30) -> tuple[QueryAnalysis, list[Candidate]]:
    q = analyze(index, question)
    cands: dict[int, Candidate] = {}

    for rank, (rowid, score) in enumerate(index.lexical(q.stems, CANDIDATES_PER_RANKER, q.phrases), start=1):
        cands.setdefault(rowid, Candidate(index.records[rowid])).lexical_rank = rank
        cands[rowid].bm25 = score
    for rank, (rowid, sim) in enumerate(index.dense(question, CANDIDATES_PER_RANKER), start=1):
        c = cands.setdefault(rowid, Candidate(index.records[rowid]))
        c.dense_rank, c.cosine = rank, sim

    for c in cands.values():
        c.coverage, c.matched_terms = coverage(q, c.rec)
        c.phrase_hits = sum(1 for ph in q.phrases if f" {ph} " in c.rec.stem_seq)
    by_cov = sorted(cands.values(), key=lambda c: -c.coverage)
    for rank, c in enumerate(by_cov, start=1):
        c.coverage_rank = rank

    for c in cands.values():
        c.fused = sum(1.0 / (RRF_K + r) for r in (c.lexical_rank, c.dense_rank, c.coverage_rank) if r is not None)

    ranked = sorted(cands.values(), key=lambda c: (-c.fused, -c.coverage))
    return q, ranked[:limit]

"""Seleção de backend de embeddings: fallback offline e consistência ingestão ↔ consulta."""
from __future__ import annotations

import numpy as np
import pytest

from kentor_memoria.answering.service import KnowledgeService
from kentor_memoria.database.db import connect, get_meta
from kentor_memoria.ingestion import pipeline
from kentor_memoria.retrieval import index as index_mod

from .conftest import make_settings


class FakeEmbedder:
    """Imita um modelo neural: vetor = saco de palavras com hash (determinístico)."""

    def __init__(self, model_name: str = "fake-multilingual"):
        self.name = f"fastembed:{model_name}"

    def _vec(self, t: str) -> np.ndarray:
        v = np.zeros(64, dtype=np.float32)
        for w in t.lower().split():
            v[hash(w) % 64] += 1
        n = np.linalg.norm(v)
        return v / n if n else v

    def embed_documents(self, texts):
        return np.stack([self._vec(t) for t in texts])

    def embed_query(self, text):
        return self._vec(text)


def test_auto_cai_para_lsa_sem_modelo(tmp_path, mini_corpus, monkeypatch):
    monkeypatch.setattr(pipeline, "try_fastembed", lambda name: None)
    settings = make_settings(tmp_path / "k.db", mini_corpus, embeddings_backend="auto")
    rep = pipeline.Ingestor(settings).run()
    assert rep.embedding_model.startswith("lsa:")


def test_fastembed_explicito_falha_com_mensagem_clara(tmp_path, mini_corpus, monkeypatch):
    monkeypatch.setattr(pipeline, "try_fastembed", lambda name: None)
    settings = make_settings(tmp_path / "k.db", mini_corpus, embeddings_backend="fastembed")
    with pytest.raises(RuntimeError, match="fastembed"):
        pipeline.Ingestor(settings).run()


def test_backend_neural_usado_na_ingestao_e_na_consulta(tmp_path, mini_corpus, monkeypatch):
    monkeypatch.setattr(pipeline, "try_fastembed", lambda name: FakeEmbedder())
    monkeypatch.setattr(index_mod, "FastEmbedEmbedder", lambda name: FakeEmbedder(name))
    settings = make_settings(tmp_path / "k.db", mini_corpus, embeddings_backend="auto")
    conn = connect(settings.db_path)
    rep = pipeline.Ingestor(settings, conn).run()
    assert rep.embedding_model == "fastembed:fake-multilingual"
    assert get_meta(conn, "embedding_model") == "fastembed:fake-multilingual"
    svc = KnowledgeService(settings, conn)
    assert svc.index.embedder is not None and svc.index.matrix.shape == (rep.active_chunks, 64)
    ans = svc.ask("Quais acessos o novo membro recebe no primeiro dia?", "marketing")
    assert ans.status.value == "FOUND"
    # trocar de backend reembeda tudo e remove vetores do modelo antigo
    monkeypatch.setattr(pipeline, "try_fastembed", lambda name: None)
    (mini_corpus / "04-processos/novo.md").write_text("# Novo\n\nDocumento novo.\n", encoding="utf-8")
    rep2 = pipeline.Ingestor(settings, conn).run()
    models = {r[0] for r in conn.execute("SELECT DISTINCT model FROM embeddings")}
    assert rep2.embedding_model.startswith("lsa:") and models == {rep2.embedding_model}

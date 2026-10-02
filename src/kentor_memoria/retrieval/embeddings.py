"""Backends de embeddings (vetores normalizados, similaridade = produto escalar).

- FastEmbedEmbedder: modelo multilíngue local (ONNX, sem torch), padrão
  `paraphrase-multilingual-MiniLM-L12-v2` (384 dim, ~220 MB, baixado 1x do
  HuggingFace e cacheado em .cache/).
- LSAEmbedder: fallback 100% offline. TF-IDF sobre radicais + SVD truncado
  (Latent Semantic Analysis) ajustado no próprio acervo. Captura co-ocorrência
  ("preço" perto de "tabela", "projeto", "R$"), não sinônimos do mundo.

O nome do modelo fica gravado no banco; a consulta sempre usa o MESMO backend
que gerou os vetores indexados.
"""
from __future__ import annotations

import io
import logging
import math
from collections import Counter
from typing import Protocol

import numpy as np

from ..config import PROJECT_ROOT
from ..utils import sha256_text
from .text import content_stems

log = logging.getLogger(__name__)


class Embedder(Protocol):
    name: str

    def embed_documents(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


def _normalize(m: np.ndarray) -> np.ndarray:
    m = np.asarray(m, dtype=np.float32)
    norms = np.linalg.norm(m, axis=-1, keepdims=True)
    norms[norms == 0] = 1.0
    return m / norms


# --------------------------------------------------------------------- fastembed
class FastEmbedEmbedder:
    def __init__(self, model_name: str):
        from fastembed import TextEmbedding  # import tardio: dependência pesada

        self.model_name = model_name
        self.name = f"fastembed:{model_name}"
        self._model = TextEmbedding(model_name=model_name, cache_dir=str(PROJECT_ROOT / ".cache" / "fastembed"))

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return _normalize(np.stack(list(self._model.embed(texts, batch_size=32))))

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_documents([text])[0]


# --------------------------------------------------------------------------- LSA
class LSAEmbedder:
    """TF-IDF (radicais, tf sublinear) → SVD truncado. Determinístico."""

    MAX_DIM = 256

    def __init__(self, vocab: dict[str, int], idf: np.ndarray, components: np.ndarray, fingerprint: str):
        self.vocab = vocab
        self.idf = idf.astype(np.float32)
        self.components = components.astype(np.float32)  # (vocab, k)
        self.name = f"lsa:{fingerprint}"

    @staticmethod
    def corpus_fingerprint(texts: list[str]) -> str:
        return sha256_text("\x1e".join(sorted(sha256_text(t) for t in texts)))[:12]

    @classmethod
    def fit(cls, texts: list[str]) -> "LSAEmbedder":
        docs = [Counter(content_stems(t)) for t in texts]
        df = Counter(term for d in docs for term in d)
        vocab = {t: i for i, t in enumerate(sorted(df))}
        n = len(texts)
        idf = np.array([math.log((1 + n) / (1 + df[t])) + 1.0 for t in sorted(df)], dtype=np.float64)
        x = np.zeros((n, len(vocab)), dtype=np.float64)
        for i, d in enumerate(docs):
            for term, tf in d.items():
                x[i, vocab[term]] = (1.0 + math.log(tf)) * idf[vocab[term]]
        x = x / np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-12)
        k = max(1, min(cls.MAX_DIM, n, len(vocab)))
        # SVD via matriz de Gram (n x n): barato mesmo com vocabulário grande.
        gram = x @ x.T
        evals, evecs = np.linalg.eigh(gram)
        order = [i for i in np.argsort(evals)[::-1][:k] if evals[i] > 1e-9]
        s = np.sqrt(np.clip(evals[order], 1e-12, None))
        u = evecs[:, order]
        components = (x.T @ u) / s  # V_k: (vocab, k)
        return cls(vocab, idf, components, cls.corpus_fingerprint(texts))

    def _tfidf(self, texts: list[str]) -> np.ndarray:
        x = np.zeros((len(texts), len(self.vocab)), dtype=np.float32)
        for i, t in enumerate(texts):
            for term, tf in Counter(content_stems(t)).items():
                j = self.vocab.get(term)
                if j is not None:
                    x[i, j] = (1.0 + math.log(tf)) * self.idf[j]
        return x

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return _normalize(self._tfidf(texts) @ self.components)

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_documents([text])[0]

    # persistência (blob no SQLite)
    def to_bytes(self) -> bytes:
        buf = io.BytesIO()
        terms = np.array(sorted(self.vocab, key=self.vocab.get), dtype=object)
        np.savez_compressed(buf, terms=terms, idf=self.idf, components=self.components, name=np.array(self.name))
        return buf.getvalue()

    @classmethod
    def from_bytes(cls, data: bytes) -> "LSAEmbedder":
        z = np.load(io.BytesIO(data), allow_pickle=True)
        vocab = {str(t): i for i, t in enumerate(z["terms"])}
        obj = cls(vocab, z["idf"], z["components"], str(z["name"]).split(":", 1)[1])
        return obj


def try_fastembed(model_name: str) -> FastEmbedEmbedder | None:
    try:
        emb = FastEmbedEmbedder(model_name)
        emb.embed_query("teste")  # força o download/carregamento agora
        return emb
    except Exception as exc:  # rede bloqueada, modelo ausente, etc.
        log.warning("fastembed indisponível (%s): %s", model_name, exc)
        return None

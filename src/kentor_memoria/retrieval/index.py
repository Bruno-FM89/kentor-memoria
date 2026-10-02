"""Índice em memória carregado do SQLite: metadados dos chunks, radicais,
frequências de documento (para IDF) e matriz de embeddings.

Para a escala do case (centenas a poucos milhares de chunks) a matriz cabe
folgada na RAM e a similaridade de cosseno é um único produto matriz-vetor em
NumPy — sem banco vetorial dedicado.
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from functools import cached_property

import numpy as np

from ..database.db import get_meta
from ..models import format_location
from .embeddings import Embedder, FastEmbedEmbedder, LSAEmbedder

log = logging.getLogger(__name__)


@dataclass
class ChunkRecord:
    rowid: int
    id: str
    document_id: str
    text: str
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    slide_start: int | None
    slide_end: int | None
    access_level: str
    stems: frozenset[str]
    doc_path: str
    doc_title: str
    doc_format: str
    doc_status: str
    doc_version: int
    doc_date: str | None
    superseded_by: str | None
    ordinal: int = 0
    doc_chunk_count: int = 1
    stem_seq: str = ""  # radicais em ordem (arquivo+título+seção+texto), para achar expressões
    doc_meta: dict = field(default_factory=dict)

    @property
    def location(self) -> str:
        loc = format_location(self.heading_path, self.page_start, self.page_end, self.slide_start, self.slide_end)
        if loc == "documento inteiro" and self.doc_chunk_count > 1:
            return f"trecho {self.ordinal + 1} de {self.doc_chunk_count}"
        return loc


    @cached_property
    def text_stems(self) -> frozenset[str]:
        from .text import content_stems

        return frozenset(content_stems(self.text))


class SearchIndex:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.version: str | None = None
        self.records: dict[int, ChunkRecord] = {}
        self.df: Counter[str] = Counter()
        self.n = 0
        self.rowids = np.zeros(0, dtype=np.int64)
        self.matrix = np.zeros((0, 1), dtype=np.float32)
        self.embedder: Embedder | None = None
        self.embedding_model: str | None = None
        self.embedding_error: str | None = None
        self.load()

    # ------------------------------------------------------------------ carga
    def is_stale(self) -> bool:
        return get_meta(self.conn, "index_version") != self.version

    def load(self) -> None:
        self.version = get_meta(self.conn, "index_version")
        rows = self.conn.execute(
            """SELECT c.rowid, c.id, c.document_id, c.text, c.heading_path, c.page_start, c.page_end,
                      c.slide_start, c.slide_end, c.access_level, c.search_stems, c.content_hash,
                      d.path, d.title, d.format, d.status, d.current_version, d.doc_date, d.superseded_by,
                      d.metadata_json, c.ordinal,
                      (SELECT COUNT(*) FROM chunks c2 WHERE c2.document_id = c.document_id AND c2.active = 1) AS n_chunks
               FROM chunks c JOIN documents d ON d.id = c.document_id
               WHERE c.active = 1 AND d.status IN ('active', 'superseded')"""
        ).fetchall()
        self.records = {}
        hashes: dict[int, str] = {}
        relations: dict[str, list[dict]] = {}
        for rel in self.conn.execute(
            "SELECT source_document_id, target_ref, target_document_id FROM relations WHERE relation='supersedes'"
        ):
            relations.setdefault(rel["source_document_id"], []).append(
                {"ref": rel["target_ref"], "target_document_id": rel["target_document_id"]}
            )
        for r in rows:
            meta = json.loads(r["metadata_json"] or "{}")
            self.records[r["rowid"]] = ChunkRecord(
                rowid=r["rowid"], id=r["id"], document_id=r["document_id"], text=r["text"],
                heading_path=json.loads(r["heading_path"]), page_start=r["page_start"], page_end=r["page_end"],
                slide_start=r["slide_start"], slide_end=r["slide_end"], access_level=r["access_level"],
                stems=frozenset(r["search_stems"].split()), doc_path=r["path"], doc_title=r["title"],
                doc_format=r["format"], doc_status=r["status"], doc_version=r["current_version"],
                doc_date=r["doc_date"], superseded_by=r["superseded_by"],
                ordinal=r["ordinal"], doc_chunk_count=r["n_chunks"], stem_seq=f" {r['search_stems']} ",
                doc_meta={
                    "supersedes_refs": meta.get("supersedes_refs", []),
                    "supersedes": relations.get(r["document_id"], []),
                },
            )
            hashes[r["rowid"]] = r["content_hash"]
        self.n = len(self.records)
        self.df = Counter(s for rec in self.records.values() for s in rec.stems)
        self._load_vectors(hashes)

    def _load_vectors(self, hashes: dict[int, str]) -> None:
        self.embedding_model = get_meta(self.conn, "embedding_model")
        self.embedder, self.embedding_error = None, None
        if not self.embedding_model or not hashes:
            self.rowids, self.matrix = np.zeros(0, dtype=np.int64), np.zeros((0, 1), dtype=np.float32)
            return
        vecs = {
            r["content_hash"]: r["vector"]
            for r in self.conn.execute("SELECT content_hash, vector FROM embeddings WHERE model=?", (self.embedding_model,))
        }
        ids, rows = [], []
        for rowid, h in hashes.items():
            if h in vecs:
                ids.append(rowid)
                rows.append(np.frombuffer(vecs[h], dtype=np.float32))
        self.rowids = np.array(ids, dtype=np.int64)
        self.matrix = np.stack(rows) if rows else np.zeros((0, 1), dtype=np.float32)
        try:
            if self.embedding_model.startswith("lsa:"):
                blob = self.conn.execute("SELECT blob FROM model_blobs WHERE name=?", (self.embedding_model,)).fetchone()
                self.embedder = LSAEmbedder.from_bytes(blob["blob"])
            elif self.embedding_model.startswith("fastembed:"):
                self.embedder = FastEmbedEmbedder(self.embedding_model.split(":", 1)[1])
        except Exception as exc:  # sem modelo: busca segue só lexical
            self.embedding_error = f"{type(exc).__name__}: {exc}"
            log.warning("Embeddings indisponíveis na consulta: %s", self.embedding_error)

    # ------------------------------------------------------------------ busca
    def idf(self, stem: str) -> float:
        # termo ausente do acervo recebe o IDF máximo: é o sinal mais forte de NOT_FOUND
        return math.log((self.n + 1) / (self.df.get(stem, 0) + 0.5))

    def lexical(self, stems: list[str], limit: int = 50, phrases: list[str] | None = None) -> list[tuple[int, float]]:
        if not stems:
            return []
        # termos soltos OU expressões (radicais vizinhos na pergunta, ex.: "projet autom")
        clauses = [f'"{s}"' for s in dict.fromkeys(stems)] + [f'"{p}"' for p in (phrases or [])]
        match = " OR ".join(clauses)
        rows = self.conn.execute(
            "SELECT rowid, bm25(chunks_fts) AS score FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY score LIMIT ?",
            (match, limit * 2),
        ).fetchall()
        # bm25() do FTS5 é negativo (menor = melhor); devolvemos positivo
        return [(r["rowid"], -r["score"]) for r in rows if r["rowid"] in self.records][:limit]

    def dense(self, text: str, limit: int = 50) -> list[tuple[int, float]]:
        if self.embedder is None or self.matrix.shape[0] == 0:
            return []
        q = self.embedder.embed_query(text)
        sims = self.matrix @ q
        top = np.argsort(-sims)[:limit]
        return [(int(self.rowids[i]), float(sims[i])) for i in top]

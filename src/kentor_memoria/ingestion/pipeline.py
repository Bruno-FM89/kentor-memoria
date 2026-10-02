"""Pipeline de ingestão idempotente.

Para cada arquivo:
  SHA-256 dos bytes + versão do parser/chunker = fingerprint.
  - fingerprint igual ao do banco → pula (não reparsea, não reembeda).
  - mudou → nova versão: chunks antigos ficam inativos (rastreáveis), novos entram.
  - sumiu do disco → documento 'deleted', chunks inativos.
Depois: resolve duplicatas exatas, recalcula supersessões explícitas e gera
embeddings só para textos que ainda não têm vetor (cache por hash do texto).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ..config import Settings, get_settings
from ..database.db import connect, get_meta, set_meta
from ..models import ChunkDraft, ParsedDocument
from ..parsers import PARSER_VERSION, SUPPORTED_EXTENSIONS, parse_file
from ..permissions.policy import AccessPolicy
from ..retrieval.embeddings import Embedder, LSAEmbedder, try_fastembed
from ..retrieval.text import stemmed_text
from ..utils import canonical_relpath, sha256_file, sha256_text, stable_id
from .chunker import CHUNKER_VERSION, chunk_document
from .supersession import SupersessionRef, detect_signals, resolve_ref

log = logging.getLogger(__name__)

IGNORED_DIRS = {"__MACOSX", ".git", ".venv", "node_modules"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class IngestionReport:
    files_seen: int = 0
    new_docs: int = 0
    updated_docs: int = 0
    reindexed: int = 0  # mesmo conteúdo, parser/chunker novo
    unchanged: int = 0
    deleted_docs: int = 0
    duplicates: int = 0
    active_documents: int = 0
    active_chunks: int = 0
    embedded: int = 0
    embedding_model: str = ""
    skipped_files: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    supersessions: list[dict] = field(default_factory=list)
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def discover_files(root: Path) -> tuple[list[Path], list[Path]]:
    """(suportados, ignorados). Ignora ocultos, __MACOSX e ._* do macOS."""
    supported, skipped = [], []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel_parts = p.relative_to(root).parts
        if any(part in IGNORED_DIRS or part.startswith(".") for part in rel_parts):
            continue
        (supported if p.suffix.lower() in SUPPORTED_EXTENSIONS else skipped).append(p)
    return supported, skipped


def embedding_text(title: str, heading_path: list[str], text: str, rel_path: str) -> str:
    """Texto indexado = contexto (arquivo, título, seção) + conteúdo do chunk."""
    header = " > ".join([title, *heading_path])
    return f"{rel_path}\n{header}\n{text}"


class Ingestor:
    def __init__(self, settings: Settings | None = None, conn: sqlite3.Connection | None = None):
        self.settings = settings or get_settings()
        self.conn = conn or connect(self.settings.db_path)
        self.policy = AccessPolicy.from_files(self.settings.policy_file, self.settings.identities_file)
        self.fingerprint_suffix = f"p{PARSER_VERSION}c{CHUNKER_VERSION}"

    # ------------------------------------------------------------------ run
    def run(self, root: Path | None = None) -> IngestionReport:
        root = (root or self.settings.acervo_dir).resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"Acervo não encontrado: {root}")
        t0 = time.perf_counter()
        started = _now()
        rep = IngestionReport()
        files, skipped = discover_files(root)
        rep.files_seen = len(files)
        rep.skipped_files = [canonical_relpath(p, root) for p in skipped]

        seen: set[str] = set()
        for path in files:
            rel = canonical_relpath(path, root)
            seen.add(rel)
            try:
                self._ingest_file(path, rel, rep)
            except Exception as exc:  # um arquivo ruim não derruba a ingestão
                log.exception("Falha ao ingerir %s", rel)
                rep.errors[rel] = f"{type(exc).__name__}: {exc}"

        with self.conn:
            for row in self.conn.execute("SELECT id, path FROM documents WHERE status != 'deleted'").fetchall():
                if row["path"] not in seen:
                    self.conn.execute(
                        "UPDATE documents SET status='deleted', updated_at=? WHERE id=?", (_now(), row["id"])
                    )
                    self._set_chunks_active(row["id"], False)
                    rep.deleted_docs += 1
            self._refresh_access_levels()
            rep.duplicates = self._resolve_duplicates()
            rep.supersessions = self._resolve_supersessions()

        rep.embedded, rep.embedding_model = self._embed_missing()
        rep.active_documents = self.conn.execute(
            "SELECT COUNT(*) FROM documents WHERE status IN ('active','superseded')"
        ).fetchone()[0]
        rep.active_chunks = self.conn.execute("SELECT COUNT(*) FROM chunks WHERE active=1").fetchone()[0]
        rep.duration_ms = round((time.perf_counter() - t0) * 1000, 1)

        with self.conn:
            if rep.new_docs or rep.updated_docs or rep.reindexed or rep.deleted_docs or rep.embedded:
                set_meta(self.conn, "index_version", _now() + f"#{time.perf_counter_ns()}")
            self.conn.execute(
                """INSERT INTO ingestion_runs(started_at, finished_at, duration_ms, files_seen, new_docs,
                   updated_docs, unchanged, deleted_docs, duplicates, active_chunks, embedded, embedding_model,
                   details_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    started, _now(), rep.duration_ms, rep.files_seen, rep.new_docs, rep.updated_docs,
                    rep.unchanged, rep.deleted_docs, rep.duplicates, rep.active_chunks, rep.embedded,
                    rep.embedding_model,
                    json.dumps({"errors": rep.errors, "skipped": rep.skipped_files}, ensure_ascii=False),
                ),
            )
        return rep

    # ------------------------------------------------------------ por arquivo
    def _ingest_file(self, path: Path, rel: str, rep: IngestionReport) -> None:
        file_hash = sha256_file(path)
        fingerprint = f"{file_hash}:{self.fingerprint_suffix}"
        doc_id = stable_id("doc", rel)
        existing = self.conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        now = _now()

        if existing and existing["fingerprint"] == fingerprint and existing["status"] != "deleted":
            self.conn.execute("UPDATE documents SET last_seen_at=? WHERE id=?", (now, doc_id))
            self.conn.commit()
            rep.unchanged += 1
            return

        parsed = parse_file(path)
        drafts = chunk_document(parsed)
        signals = detect_signals(parsed)
        frontmatter = parsed.metadata.get("frontmatter", {})
        level = self.policy.classify(rel, frontmatter)
        # Versão do DOCUMENTO só sobe se o conteúdo mudou. Se só o parser/chunker mudou
        # (fingerprint diferente, mesmo hash), é uma reindexação da mesma versão.
        content_changed = not existing or existing["content_hash"] != file_hash or existing["status"] == "deleted"
        version = (existing["current_version"] + (1 if content_changed else 0)) if existing else 1
        metadata = {
            **{k: v for k, v in parsed.metadata.items() if k != "frontmatter"},
            "frontmatter": _jsonable(frontmatter),
            "declared_ids": signals.declared_ids,
            "deprecated": signals.deprecated,
            "supersedes_refs": [asdict(r) for r in signals.supersedes],
            "superseded_by_refs": signals.superseded_by,
        }

        with self.conn:
            if existing:
                self._set_chunks_active(doc_id, False)
                if not content_changed:  # reindexação: descarta os chunks da mesma versão
                    self.conn.execute("DELETE FROM chunks WHERE document_id=? AND version=?", (doc_id, version))
                self.conn.execute(
                    """UPDATE documents SET filename=?, format=?, title=?, access_level=?, content_hash=?,
                       fingerprint=?, current_version=?, status='active', duplicate_of=NULL, superseded_by=NULL,
                       doc_date=?, version_label=?, metadata_json=?, updated_at=?, last_seen_at=? WHERE id=?""",
                    (
                        path.name, parsed.format, parsed.title, level, file_hash, fingerprint, version,
                        signals.doc_date, signals.version_label, json.dumps(metadata, ensure_ascii=False),
                        now, now, doc_id,
                    ),
                )
                if content_changed:
                    rep.updated_docs += 1
                else:
                    rep.reindexed += 1
            else:
                self.conn.execute(
                    """INSERT INTO documents(id, path, filename, format, title, access_level, content_hash,
                       fingerprint, current_version, status, doc_date, version_label, metadata_json,
                       first_seen_at, updated_at, last_seen_at) VALUES (?,?,?,?,?,?,?,?,?,'active',?,?,?,?,?,?)""",
                    (
                        doc_id, rel, path.name, parsed.format, parsed.title, level, file_hash, fingerprint,
                        version, signals.doc_date, signals.version_label, json.dumps(metadata, ensure_ascii=False),
                        now, now, now,
                    ),
                )
                rep.new_docs += 1
            self.conn.execute(
                """INSERT INTO document_versions(document_id, version, content_hash, fingerprint, chunk_count,
                   ingested_at) VALUES (?,?,?,?,?,?)
                   ON CONFLICT(document_id, version) DO UPDATE SET fingerprint=excluded.fingerprint,
                   chunk_count=excluded.chunk_count, ingested_at=excluded.ingested_at""",
                (doc_id, version, file_hash, fingerprint, len(drafts), now),
            )
            for d in drafts:
                self._insert_chunk(doc_id, version, rel, parsed, d, level)

    def _insert_chunk(self, doc_id: str, version: int, rel: str, parsed: ParsedDocument, d: ChunkDraft, level: str):
        indexed = embedding_text(parsed.title, d.heading_path, d.text, rel)
        chunk_id = stable_id("chk", doc_id, str(version), str(d.ordinal))
        stems = stemmed_text(indexed)
        cur = self.conn.execute(
            """INSERT INTO chunks(id, document_id, version, ordinal, text, heading_path, page_start, page_end,
               slide_start, slide_end, char_count, content_hash, search_stems, access_level, active)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
            (
                chunk_id, doc_id, version, d.ordinal, d.text, json.dumps(d.heading_path, ensure_ascii=False),
                d.page_start, d.page_end, d.slide_start, d.slide_end, len(d.text), sha256_text(indexed), stems, level,
            ),
        )
        self.conn.execute("INSERT INTO chunks_fts(rowid, stems) VALUES (?, ?)", (cur.lastrowid, stems))

    # ----------------------------------------------------------- utilidades
    def _set_chunks_active(self, doc_id: str, active: bool) -> None:
        """Liga/desliga os chunks da versão corrente e mantém o FTS em sincronia."""
        if active:
            rows = self.conn.execute(
                """SELECT c.rowid, c.search_stems FROM chunks c JOIN documents d ON d.id=c.document_id
                   WHERE c.document_id=? AND c.version=d.current_version AND c.active=0""",
                (doc_id,),
            ).fetchall()
            for r in rows:
                self.conn.execute("INSERT INTO chunks_fts(rowid, stems) VALUES (?, ?)", (r["rowid"], r["search_stems"]))
                self.conn.execute("UPDATE chunks SET active=1 WHERE rowid=?", (r["rowid"],))
        else:
            rows = self.conn.execute("SELECT rowid FROM chunks WHERE document_id=? AND active=1", (doc_id,)).fetchall()
            for r in rows:
                self.conn.execute("DELETE FROM chunks_fts WHERE rowid=?", (r["rowid"],))
                self.conn.execute("UPDATE chunks SET active=0 WHERE rowid=?", (r["rowid"],))

    def _refresh_access_levels(self) -> None:
        """Se a política mudou, reclassifica sem reprocessar os arquivos."""
        for row in self.conn.execute("SELECT id, path, access_level, metadata_json FROM documents").fetchall():
            fm = json.loads(row["metadata_json"] or "{}").get("frontmatter") or {}
            level = self.policy.classify(row["path"], fm)
            if level != row["access_level"]:
                self.conn.execute("UPDATE documents SET access_level=? WHERE id=?", (level, row["id"]))
                self.conn.execute("UPDATE chunks SET access_level=? WHERE document_id=?", (level, row["id"]))

    def _resolve_duplicates(self) -> int:
        """Arquivos com bytes idênticos: o primeiro caminho (ordem alfabética) é o canônico."""
        rows = self.conn.execute(
            "SELECT id, path, content_hash, status FROM documents WHERE status != 'deleted' ORDER BY path"
        ).fetchall()
        canonical: dict[str, str] = {}
        dups = 0
        for r in rows:
            first = canonical.setdefault(r["content_hash"], r["id"])
            if first != r["id"]:
                dups += 1
                if r["status"] != "duplicate":
                    self.conn.execute("UPDATE documents SET status='duplicate', duplicate_of=? WHERE id=?", (first, r["id"]))
                    self._set_chunks_active(r["id"], False)
            elif r["status"] == "duplicate":  # o original sumiu: volta a ser ativo
                self.conn.execute("UPDATE documents SET status='active', duplicate_of=NULL WHERE id=?", (r["id"],))
                self._set_chunks_active(r["id"], True)
        return dups

    def _resolve_supersessions(self) -> list[dict]:
        """Recalcula do zero (idempotente) as relações 'supersedes' explícitas."""
        self.conn.execute("DELETE FROM relations WHERE relation='supersedes'")
        self.conn.execute("UPDATE documents SET status='active', superseded_by=NULL WHERE status='superseded'")
        docs = self.conn.execute(
            "SELECT id, path, filename, title, metadata_json FROM documents WHERE status='active'"
        ).fetchall()
        candidates = []
        for d in docs:
            meta = json.loads(d["metadata_json"] or "{}")
            candidates.append({**dict(d), "declared_ids": meta.get("declared_ids", []), "meta": meta})

        out: list[dict] = []
        for c in candidates:
            meta = c["meta"]
            refs = [(r["ref"], r.get("ids", []), r["evidence"]) for r in meta.get("supersedes_refs", [])]
            for ref, ids, evidence in refs:
                target = resolve_ref(SupersessionRef(ref, ids, evidence), [x for x in candidates if x["id"] != c["id"]])
                self.conn.execute(
                    """INSERT OR IGNORE INTO relations(source_document_id, relation, target_document_id, target_ref,
                       evidence) VALUES (?, 'supersedes', ?, ?, ?)""",
                    (c["id"], target, ref, evidence),
                )
                if target:
                    self.conn.execute(
                        "UPDATE documents SET status='superseded', superseded_by=? WHERE id=?", (c["id"], target)
                    )
                out.append({"source": c["path"], "target_ref": ref, "resolved_target": target, "evidence": evidence})
            # declarado obsoleto pelo próprio frontmatter
            if meta.get("deprecated"):
                self.conn.execute("UPDATE documents SET status='superseded' WHERE id=?", (c["id"],))
                out.append({"source": c["path"], "target_ref": "(self)", "resolved_target": c["id"],
                            "evidence": "frontmatter status obsoleto"})
            for by in meta.get("superseded_by_refs", []):
                newer = resolve_ref(SupersessionRef(by, [], by), [x for x in candidates if x["id"] != c["id"]])
                self.conn.execute(
                    "UPDATE documents SET status='superseded', superseded_by=? WHERE id=?", (newer, c["id"])
                )
                out.append({"source": c["path"], "target_ref": f"superseded_by {by}", "resolved_target": newer,
                            "evidence": f"frontmatter superseded_by: {by}"})
        return out

    # ------------------------------------------------------------ embeddings
    def _select_embedder(self, texts: list[str]) -> Embedder:
        backend = self.settings.embeddings_backend
        if backend in ("auto", "fastembed"):
            emb = try_fastembed(self.settings.embedding_model)
            if emb:
                return emb
            if backend == "fastembed":
                raise RuntimeError(
                    "KENTOR_EMBEDDINGS=fastembed, mas o modelo não pôde ser carregado (sem rede para o HuggingFace?)."
                )
            log.warning("Usando fallback LSA (offline).")
        fp = LSAEmbedder.corpus_fingerprint(texts)
        name = f"lsa:{fp}"
        blob = self.conn.execute("SELECT blob FROM model_blobs WHERE name=?", (name,)).fetchone()
        if blob:
            return LSAEmbedder.from_bytes(blob["blob"])
        emb = LSAEmbedder.fit(texts)
        self.conn.execute("DELETE FROM model_blobs WHERE name LIKE 'lsa:%'")
        self.conn.execute("INSERT INTO model_blobs(name, blob) VALUES (?, ?)", (emb.name, emb.to_bytes()))
        return emb

    def _embed_missing(self) -> tuple[int, str]:
        rows = self.conn.execute(
            """SELECT c.content_hash, c.text, c.heading_path, d.title, d.path FROM chunks c
               JOIN documents d ON d.id=c.document_id WHERE c.active=1"""
        ).fetchall()
        texts_by_hash = {
            r["content_hash"]: embedding_text(r["title"], json.loads(r["heading_path"]), r["text"], r["path"])
            for r in rows
        }
        if not texts_by_hash:
            return 0, ""
        all_texts = [texts_by_hash[h] for h in sorted(texts_by_hash)]
        embedder = self._select_embedder(all_texts)
        have = {
            r[0] for r in self.conn.execute("SELECT content_hash FROM embeddings WHERE model=?", (embedder.name,))
        }
        missing = [h for h in sorted(texts_by_hash) if h not in have]
        if missing:
            vecs = embedder.embed_documents([texts_by_hash[h] for h in missing])
            with self.conn:
                for h, v in zip(missing, vecs):
                    self.conn.execute(
                        "INSERT OR REPLACE INTO embeddings(content_hash, model, dim, vector) VALUES (?,?,?,?)",
                        (h, embedder.name, int(v.shape[0]), np.asarray(v, dtype=np.float32).tobytes()),
                    )
        with self.conn:
            # limpa vetores órfãos ou de outro modelo
            self.conn.execute("DELETE FROM embeddings WHERE model != ?", (embedder.name,))
            self.conn.execute(
                "DELETE FROM embeddings WHERE content_hash NOT IN (SELECT content_hash FROM chunks WHERE active=1)"
            )
            set_meta(self.conn, "embedding_model", embedder.name)
        return len(missing), embedder.name


def _jsonable(obj):
    try:
        json.dumps(obj, ensure_ascii=False)
        return obj
    except TypeError:
        return json.loads(json.dumps(obj, ensure_ascii=False, default=str))


def ingest(root: Path | None = None, settings: Settings | None = None) -> IngestionReport:
    return Ingestor(settings).run(root)


def current_embedding_model(conn: sqlite3.Connection) -> str | None:
    return get_meta(conn, "embedding_model")

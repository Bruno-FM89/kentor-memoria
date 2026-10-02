"""SQLite: esquema e conexão.

Um único arquivo guarda documentos, versões, chunks, índice FTS5, embeddings,
relações de supersessão, execuções de ingestão e logs de consulta.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Um documento = um caminho canônico no acervo. O id é estável (hash do caminho).
CREATE TABLE IF NOT EXISTS documents (
    id              TEXT PRIMARY KEY,
    path            TEXT UNIQUE NOT NULL,
    filename        TEXT NOT NULL,
    format          TEXT NOT NULL,
    title           TEXT,
    access_level    TEXT NOT NULL,
    content_hash    TEXT NOT NULL,          -- SHA-256 dos bytes do arquivo
    fingerprint     TEXT NOT NULL,          -- hash + versão do parser/chunker
    current_version INTEGER NOT NULL,
    status          TEXT NOT NULL,          -- active | superseded | duplicate | deleted
    duplicate_of    TEXT,
    superseded_by   TEXT,
    doc_date        TEXT,
    version_label   TEXT,
    metadata_json   TEXT,
    first_seen_at   TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_versions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id  TEXT NOT NULL REFERENCES documents(id),
    version      INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    fingerprint  TEXT NOT NULL,
    chunk_count  INTEGER NOT NULL,
    ingested_at  TEXT NOT NULL,
    UNIQUE (document_id, version)
);

-- rowid explícito: é a chave de junção com o FTS5.
CREATE TABLE IF NOT EXISTS chunks (
    rowid         INTEGER PRIMARY KEY,
    id            TEXT UNIQUE NOT NULL,
    document_id   TEXT NOT NULL REFERENCES documents(id),
    version       INTEGER NOT NULL,
    ordinal       INTEGER NOT NULL,
    text          TEXT NOT NULL,
    heading_path  TEXT NOT NULL,            -- JSON
    page_start    INTEGER,
    page_end      INTEGER,
    slide_start   INTEGER,
    slide_end     INTEGER,
    char_count    INTEGER NOT NULL,
    content_hash  TEXT NOT NULL,            -- SHA-256 do texto indexado (chave do cache de embeddings)
    search_stems  TEXT NOT NULL,            -- radicais indexados (FTS e cobertura)
    access_level  TEXT NOT NULL,
    active        INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(document_id, version);
CREATE INDEX IF NOT EXISTS idx_chunks_active ON chunks(active);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    stems,
    tokenize = 'unicode61 remove_diacritics 2'
);

-- Cache de embeddings por conteúdo: texto igual não é reprocessado.
CREATE TABLE IF NOT EXISTS embeddings (
    content_hash TEXT NOT NULL,
    model        TEXT NOT NULL,
    dim          INTEGER NOT NULL,
    vector       BLOB NOT NULL,
    PRIMARY KEY (content_hash, model)
);

-- Artefatos de modelos locais (ex.: projeção LSA).
CREATE TABLE IF NOT EXISTS model_blobs (
    name  TEXT PRIMARY KEY,
    blob  BLOB NOT NULL
);

-- Relações explícitas entre documentos (supersessão).
CREATE TABLE IF NOT EXISTS relations (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    source_document_id TEXT NOT NULL,
    relation           TEXT NOT NULL,       -- supersedes
    target_document_id TEXT,                -- NULL = referência não resolvida no acervo
    target_ref         TEXT NOT NULL,
    evidence           TEXT NOT NULL,       -- trecho que comprova a relação
    UNIQUE (source_document_id, relation, target_ref)
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    duration_ms   REAL,
    files_seen    INTEGER,
    new_docs      INTEGER,
    updated_docs  INTEGER,
    unchanged     INTEGER,
    deleted_docs  INTEGER,
    duplicates    INTEGER,
    active_chunks INTEGER,
    embedded      INTEGER,
    embedding_model TEXT,
    details_json  TEXT
);

-- Observabilidade: nunca guarda texto de chunk, só ids e scores.
CREATE TABLE IF NOT EXISTS query_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                TEXT NOT NULL,
    tool              TEXT NOT NULL,
    identity          TEXT,
    question          TEXT,
    status            TEXT,
    retrieval_ms      REAL,
    total_ms          REAL,
    retrieved_json    TEXT,
    model             TEXT,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    cost_usd          REAL,
    error             TEXT
);

CREATE TABLE IF NOT EXISTS llm_usage (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                TEXT NOT NULL,
    purpose           TEXT NOT NULL,
    model             TEXT NOT NULL,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    cost_usd          REAL,
    latency_ms        REAL
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )

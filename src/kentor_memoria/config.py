"""Configuração central, lida de variáveis de ambiente (e de um .env opcional).

Tudo que é ajustável fica aqui, com defaults seguros. Nenhum segredo tem default.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Carrega .env da raiz do projeto, sem sobrescrever variáveis já definidas.
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _path(env: str, default: str) -> Path:
    value = os.getenv(env) or default
    p = Path(value)
    return p if p.is_absolute() else (PROJECT_ROOT / p)


@dataclass(frozen=True)
class Settings:
    acervo_dir: Path = field(default_factory=lambda: _path("KENTOR_ACERVO_DIR", "data/acervo"))
    db_path: Path = field(default_factory=lambda: _path("KENTOR_DB_PATH", "data/kentor.db"))
    identities_file: Path = field(default_factory=lambda: _path("KENTOR_IDENTITIES", "config/identities.yaml"))
    policy_file: Path = field(default_factory=lambda: _path("KENTOR_ACCESS_POLICY", "config/access_policy.yaml"))

    # Embeddings
    embeddings_backend: str = field(default_factory=lambda: os.getenv("KENTOR_EMBEDDINGS", "auto").lower())
    embedding_model: str = field(
        default_factory=lambda: os.getenv(
            "KENTOR_EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
    )

    # LLM (opcional)
    openrouter_api_key: str | None = field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY") or None)
    openrouter_model: str = field(default_factory=lambda: os.getenv("OPENROUTER_MODEL", "google/gemini-2.5-flash-lite"))
    llm_mode: str = field(default_factory=lambda: os.getenv("KENTOR_LLM_MODE", "auto").lower())

    # Identidade do processo MCP
    bound_identity: str | None = field(default_factory=lambda: os.getenv("KENTOR_IDENTITY") or None)
    allow_identity_param: bool = field(
        default_factory=lambda: os.getenv("KENTOR_ALLOW_IDENTITY_PARAM", "0") in ("1", "true", "yes")
    )

    @property
    def llm_enabled(self) -> bool:
        return self.llm_mode != "off" and bool(self.openrouter_api_key)


def get_settings() -> Settings:
    return Settings()

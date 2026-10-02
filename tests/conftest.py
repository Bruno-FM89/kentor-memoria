"""Fixtures compartilhadas.

- Testes com o acervo real usam KENTOR_ACERVO_DIR (ou data/acervo) e são pulados
  com mensagem clara se ele não existir.
- Por padrão os testes usam embeddings LSA (offline, determinístico) e LLM
  desligado. Para testar com o modelo multilíngue: KENTOR_TEST_EMBEDDINGS=auto.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("KENTOR_LLM_MODE", "off")

from kentor_memoria.config import PROJECT_ROOT, Settings  # noqa: E402

TEST_EMBEDDINGS = os.getenv("KENTOR_TEST_EMBEDDINGS", "lsa")


def make_settings(db_path: Path, acervo_dir: Path, **overrides) -> Settings:
    base = dict(
        acervo_dir=acervo_dir,
        db_path=db_path,
        identities_file=PROJECT_ROOT / "config/identities.yaml",
        policy_file=PROJECT_ROOT / "config/access_policy.yaml",
        embeddings_backend=TEST_EMBEDDINGS,
        llm_mode="off",
        openrouter_api_key=None,
        bound_identity=None,
        allow_identity_param=False,
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture(scope="session")
def corpus_dir() -> Path:
    p = Path(os.getenv("KENTOR_ACERVO_DIR") or PROJECT_ROOT / "data/acervo")
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    if not (p / "05-restrito-ficticio").is_dir():
        pytest.skip(f"Acervo real não encontrado em {p} (defina KENTOR_ACERVO_DIR)")
    return p


@pytest.fixture(scope="session")
def corpus_settings(corpus_dir, tmp_path_factory) -> Settings:
    """Banco temporário com o acervo real ingerido UMA vez para a sessão de testes."""
    from kentor_memoria.ingestion.pipeline import Ingestor

    db = tmp_path_factory.mktemp("db") / "kentor.db"
    settings = make_settings(db, corpus_dir)
    report = Ingestor(settings).run()
    assert not report.errors, report.errors
    return settings


@pytest.fixture(scope="session")
def service(corpus_settings):
    from kentor_memoria.answering.service import KnowledgeService

    return KnowledgeService(corpus_settings)


# ------------------------------------------------------------ acervo sintético
def write(root: Path, rel: str, content: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture
def mini_corpus(tmp_path) -> Path:
    """Acervo pequeno e controlado para testes unitários de ingestão/versões."""
    root = tmp_path / "acervo"
    write(root, "01-estrategia/politica-reembolso-v1.md",
          "# Política de reembolso\n\nO prazo de reembolso de despesas é de 30 dias corridos.\n")
    write(root, "01-estrategia/politica-reembolso-v2.md",
          "---\ntitulo: Política de reembolso v2\nsubstitui: politica-reembolso-v1.md\n---\n"
          "# Política de reembolso v2\n\nO prazo de reembolso de despesas é de 15 dias corridos.\n")
    write(root, "02-agentes/guia-onboarding.md",
          "# Guia de onboarding\n\nTodo novo membro recebe acesso ao Drive no primeiro dia.\n")
    write(root, "04-processos/checklist.txt",
          "Checklist de fechamento mensal.\n\nConferir as faturas emitidas e os pagamentos recebidos.\n")
    write(root, "05-restrito-ficticio/salarios.md",
          "# Salários\n\nA analista de dados recebe R$ 7.777 por mês.\n")
    return root

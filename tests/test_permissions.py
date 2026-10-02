from __future__ import annotations

import pytest

from kentor_memoria.config import PROJECT_ROOT
from kentor_memoria.permissions.identity import IdentityError, resolve_identity
from kentor_memoria.permissions.policy import AccessPolicy, UnknownIdentityError

from .conftest import make_settings


@pytest.fixture(scope="module")
def policy() -> AccessPolicy:
    return AccessPolicy.from_files(PROJECT_ROOT / "config/access_policy.yaml", PROJECT_ROOT / "config/identities.yaml")


def test_classificacao_por_caminho(policy):
    assert policy.classify("01-estrategia/DOUTRINA_POSTS.md") == "team"
    assert policy.classify("04-processos/template-doc-reuniao-conteudo.docx") == "team"
    assert policy.classify("05-restrito-ficticio/pricing-interno.md") == "commercial"
    assert policy.classify("05-restrito-ficticio/contratos-ativos.md") == "commercial"
    assert policy.classify("05-restrito-ficticio/remuneracao-time.md") == "restricted"
    assert policy.classify("05-restrito-ficticio/qualquer-arquivo-novo.pdf") == "restricted"


def test_frontmatter_so_pode_subir_o_nivel(policy):
    assert policy.classify("01-estrategia/x.md", {"acesso": "restricted"}) == "restricted"
    # arquivo restrito não consegue se declarar público
    assert policy.classify("05-restrito-ficticio/remuneracao-time.md", {"acesso": "team"}) == "restricted"
    # valor inválido é ignorado
    assert policy.classify("01-estrategia/x.md", {"acesso": "publico"}) == "team"


def test_nivel_desconhecido_falha_fechado(policy):
    socio = policy.identity("socio")
    assert not policy.can_read(socio, "nivel-inventado")


def test_matriz_de_acesso(policy):
    expected = {
        "marketing": {"team": True, "commercial": False, "restricted": False},
        "software": {"team": True, "commercial": False, "restricted": False},
        "vendas": {"team": True, "commercial": True, "restricted": False},
        "socio": {"team": True, "commercial": True, "restricted": True},
    }
    for name, levels in expected.items():
        ident = policy.identity(name)
        for level, ok in levels.items():
            assert policy.can_read(ident, level) is ok, (name, level)


def test_identidade_desconhecida(policy):
    with pytest.raises(UnknownIdentityError):
        policy.identity("ceo-falso")
    with pytest.raises(UnknownIdentityError):
        policy.identity(None)


def test_authorize_separa_permitidos_e_negados(policy):
    items = [("a", "team"), ("b", "commercial"), ("c", "restricted")]
    allowed, denied = policy.authorize(policy.identity("vendas"), items, lambda x: x[1])
    assert [x[0] for x in allowed] == ["a", "b"] and [x[0] for x in denied] == ["c"]


def test_owner_hint_vem_da_config(policy):
    assert "comercial" in policy.owner_hint("05-restrito-ficticio/pricing-interno.md")
    assert "sócios" in policy.owner_hint("05-restrito-ficticio/metas-financeiras.md")
    assert policy.owner_hint("01-estrategia/DOUTRINA_POSTS.md") is None


def test_resolve_identity_vinculada(tmp_path):
    s = make_settings(tmp_path / "db", tmp_path, bound_identity="marketing")
    assert resolve_identity(None, s) == "marketing"
    assert resolve_identity("marketing", s) == "marketing"
    with pytest.raises(IdentityError):
        resolve_identity("socio", s)


def test_resolve_identity_sem_vinculo(tmp_path):
    s = make_settings(tmp_path / "db", tmp_path)
    with pytest.raises(IdentityError):
        resolve_identity("socio", s)  # fail closed
    demo = make_settings(tmp_path / "db", tmp_path, allow_identity_param=True)
    assert resolve_identity("socio", demo) == "socio"
    with pytest.raises(IdentityError):
        resolve_identity(None, demo)

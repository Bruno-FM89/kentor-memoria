"""Script de preparação usado pelo atalho de duplo clique no Windows."""
from __future__ import annotations

import importlib.util

from kentor_memoria.config import PROJECT_ROOT

spec = importlib.util.spec_from_file_location("preparar", PROJECT_ROOT / "scripts/preparar.py")
preparar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preparar)


def _acervo(root):
    for d in ("01-estrategia", "02-agentes-e-skills", "05-restrito-ficticio"):
        (root / d).mkdir(parents=True)
    return root


def test_acha_acervo_mesmo_dentro_de_pasta_extra(tmp_path):
    inner = _acervo(tmp_path / "amostra-acervo 2" / "amostra-acervo 2")
    assert preparar.find_inside(tmp_path / "amostra-acervo 2") == inner
    assert preparar.find_inside(inner) == inner
    assert preparar.find_inside(tmp_path / "nada") is None


def test_grava_caminho_no_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("A=1\nKENTOR_ACERVO_DIR=data/acervo\nB=2\n", encoding="utf-8")
    monkeypatch.setattr(preparar, "ENV", env)
    preparar.save_acervo(tmp_path / "meu acervo")
    lines = env.read_text(encoding="utf-8").splitlines()
    assert lines == ["A=1", f"KENTOR_ACERVO_DIR={tmp_path / 'meu acervo'}", "B=2"]
    assert preparar.current_env_value() == str(tmp_path / "meu acervo")

"""Preparação automática para quem não usa terminal (chamado por "Abrir Kentor Memoria.bat").

1. Cria o .env a partir do .env.example, se não existir.
2. Acha a pasta do acervo sozinho (data/acervo ou Downloads). Se não achar, pede
   para arrastar a pasta para a janela.
3. Indexa o acervo se o banco ainda estiver vazio.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_SECTION = re.compile(r"^\d\d-")


def looks_like_acervo(p: Path) -> bool:
    """Pasta com subpastas do tipo 01-estrategia, 02-..., (pelo menos 2)."""
    try:
        return p.is_dir() and sum(1 for c in p.iterdir() if c.is_dir() and _SECTION.match(c.name)) >= 2
    except OSError:
        return False


def find_inside(p: Path, depth: int = 2) -> Path | None:
    """Aceita a pasta certa ou uma pasta 'de fora' (o zip cria uma pasta dentro da outra)."""
    if looks_like_acervo(p):
        return p
    if depth and p.is_dir():
        for child in sorted(c for c in p.iterdir() if c.is_dir() and not c.name.startswith((".", "__"))):
            found = find_inside(child, depth - 1)
            if found:
                return found
    return None


def current_env_value() -> str | None:
    if not ENV.exists():
        return None
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("KENTOR_ACERVO_DIR="):
            return line.split("=", 1)[1].strip().strip('"')
    return None


def save_acervo(path: Path) -> None:
    lines = ENV.read_text(encoding="utf-8").splitlines()
    new = f"KENTOR_ACERVO_DIR={path}"
    out, done = [], False
    for line in lines:
        if line.strip().startswith("KENTOR_ACERVO_DIR="):
            out.append(new)
            done = True
        else:
            out.append(line)
    if not done:
        out.append(new)
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.environ["KENTOR_ACERVO_DIR"] = str(path)


def candidates() -> list[Path]:
    home = Path.home()
    cands = [ROOT / "data" / "acervo"]
    val = current_env_value()
    if val:
        p = Path(val)
        cands.insert(0, p if p.is_absolute() else ROOT / p)
    for base in (home / "Downloads", home / "Desktop", home / "Documents", ROOT.parent, ROOT.parent.parent):
        if base.is_dir():
            cands += sorted(base.glob("amostra-acervo*"))
    return cands


def resolve_acervo(interactive: bool = True) -> Path | None:
    for c in candidates():
        found = find_inside(c)
        if found:
            return found
    if not interactive:
        return None
    print("\nNão achei a pasta do acervo sozinho.")
    print("Arraste a pasta 'amostra-acervo 2' (já descompactada) para esta janela e aperte Enter:")
    while True:
        raw = input("> ").strip().strip('"').strip("'")
        if not raw:
            continue
        found = find_inside(Path(raw))
        if found:
            return found
        print("Essa pasta não parece ser o acervo (esperava ver 01-estrategia, 02-agentes-e-skills...). Tente de novo:")


def main() -> int:
    if not ENV.exists():
        shutil.copy(ROOT / ".env.example", ENV)
        print("Arquivo de configuração .env criado.")

    acervo = resolve_acervo()
    if acervo is None:
        return 1
    if current_env_value() != str(acervo):
        save_acervo(acervo)
    print(f"Acervo: {acervo}")

    sys.path.insert(0, str(ROOT / "src"))
    from kentor_memoria.config import get_settings
    from kentor_memoria.database.db import connect

    settings = get_settings()
    conn = connect(settings.db_path)
    n = conn.execute("SELECT COUNT(*) FROM chunks WHERE active=1").fetchone()[0]
    conn.close()
    if n == 0:
        print("\nPrimeira vez: lendo e indexando o acervo (pode levar alguns minutos)...")
        from kentor_memoria.ingestion.pipeline import ingest

        rep = ingest(acervo)
        print(f"Pronto: {rep.active_documents} documentos, {rep.active_chunks} trechos indexados.")
    else:
        print(f"Índice já pronto ({n} trechos).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

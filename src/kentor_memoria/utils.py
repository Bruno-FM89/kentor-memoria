"""Utilitários pequenos: normalização de texto, hashing e caminhos canônicos."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

_WS = re.compile(r"[ \t  -​ 　]+")
_MANY_NL = re.compile(r"\n{3,}")


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def clean_text(s: str) -> str:
    """Normaliza Unicode (NFC), espaços e quebras de linha, preservando parágrafos."""
    s = nfc(s).replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("­", "")  # soft hyphen
    lines = [_WS.sub(" ", ln).strip() for ln in s.split("\n")]
    return _MANY_NL.sub("\n\n", "\n".join(lines)).strip()


def one_line(s: str) -> str:
    return _WS.sub(" ", s.replace("\n", " ")).strip()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk_size), b""):
            h.update(block)
    return h.hexdigest()


def canonical_relpath(path: Path, root: Path) -> str:
    """Caminho relativo à raiz do acervo, com '/' e Unicode NFC.

    O zip do case veio do macOS com nomes em NFD ("Apresentação" decomposto);
    normalizar garante o mesmo ID em macOS, Linux e Windows.
    """
    return nfc(path.resolve().relative_to(root.resolve()).as_posix())


def stable_id(prefix: str, *parts: str, length: int = 16) -> str:
    return f"{prefix}_" + hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:length]

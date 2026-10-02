from __future__ import annotations

import hashlib
import unicodedata

from kentor_memoria.utils import canonical_relpath, sha256_file, sha256_text, stable_id


def test_sha256_file_igual_ao_hashlib(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes(b"conteudo \xc3\xa9 igual")
    assert sha256_file(p) == hashlib.sha256(b"conteudo \xc3\xa9 igual").hexdigest()


def test_mesmo_conteudo_mesmo_hash_e_mudanca_muda_hash(tmp_path):
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    a.write_text("texto", encoding="utf-8")
    b.write_text("texto", encoding="utf-8")
    assert sha256_file(a) == sha256_file(b)
    b.write_text("texto.", encoding="utf-8")
    assert sha256_file(a) != sha256_file(b)


def test_caminho_canonico_normaliza_unicode_nfd(tmp_path):
    """O zip do case veio do macOS com nomes em NFD; o id do documento tem que ser o mesmo em qualquer SO."""
    nfd_name = unicodedata.normalize("NFD", "Apresentação Kentor.pdf")
    p = tmp_path / "01-estrategia" / nfd_name
    p.parent.mkdir()
    p.write_bytes(b"x")
    rel = canonical_relpath(p, tmp_path)
    assert rel == "01-estrategia/Apresentação Kentor.pdf"
    assert rel == unicodedata.normalize("NFC", rel)
    assert stable_id("doc", rel) == stable_id("doc", unicodedata.normalize("NFC", "01-estrategia/Apresentação Kentor.pdf"))


def test_stable_id_deterministico():
    assert stable_id("doc", "a/b.md") == stable_id("doc", "a/b.md")
    assert stable_id("doc", "a/b.md") != stable_id("doc", "a/c.md")
    assert stable_id("chk", "d", "1", "0").startswith("chk_")
    assert len(sha256_text("x")) == 64

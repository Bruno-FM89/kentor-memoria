from __future__ import annotations

import re

from kentor_memoria.ingestion.chunker import MAX_CHARS, SMALL_DOC_CHARS, chunk_document
from kentor_memoria.models import Block, ParsedDocument
from kentor_memoria.parsers.markdown import parse_markdown_text


def test_documento_pequeno_vira_um_chunk_e_preserva_tabela():
    md = ("# Tabela de preços\n\n| Produto | Faixa |\n|---|---|\n| Projeto pequeno | R$ 9.000 |\n"
          "| Projeto médio | R$ 18.000 |\n\nDesconto máximo: 10%.\n")
    chunks = chunk_document(parse_markdown_text(md, "precos"))
    assert len(chunks) == 1
    assert "| Produto | Faixa |" in chunks[0].text and "R$ 18.000" in chunks[0].text
    assert chunks[0].location() == "documento inteiro"


def _long_md(sections: int = 6, sentences: int = 18) -> str:
    out = ["# Guia"]
    for s in range(sections):
        out.append(f"## Seção {s}")
        out.append(" ".join(f"Esta é a frase {i} da seção {s}, com conteúdo suficiente para ocupar espaço." for i in range(sentences)))
    return "\n\n".join(out)


def test_documento_grande_respeita_limite_e_secoes():
    doc = parse_markdown_text(_long_md(), "guia")
    assert len(doc.full_text) > SMALL_DOC_CHARS
    chunks = chunk_document(doc)
    assert len(chunks) > 1
    assert all(len(c.text) <= MAX_CHARS for c in chunks)
    # todo chunk tem heading da seção de origem
    assert all(c.heading_path and c.heading_path[0] == "Guia" for c in chunks)
    assert {c.heading_path[-1] for c in chunks} == {f"Seção {s}" for s in range(6)}


def test_nao_corta_frases_no_meio():
    doc = parse_markdown_text(_long_md(sections=2, sentences=60), "guia")
    for c in chunk_document(doc):
        body = "\n".join(ln for ln in c.text.split("\n") if not ln.startswith("["))
        assert body.rstrip().endswith("."), body[-80:]
        assert re.match(r"^(Esta é a frase|\[)", c.text), c.text[:40]


def test_secoes_pequenas_vizinhas_sao_fundidas_com_marcador():
    md = "# Doc\n\n" + "\n\n".join(f"## S{i}\n\nLinha curta {i}." for i in range(40))
    md += "\n\n## Grande\n\n" + ("Texto longo de verdade. " * 80)
    chunks = chunk_document(parse_markdown_text(md, "doc"))
    merged = [c for c in chunks if "[Doc > S1]" in c.text]
    assert merged, "seções curtas deveriam ser fundidas num chunk com marcadores de seção"
    assert len(chunks) < 41


def test_tabela_grande_repete_cabecalho():
    rows = "\n".join(f"| item {i} | valor {i} com descrição razoavelmente longa para encher |" for i in range(80))
    md = f"# Tabela\n\n| Item | Valor |\n|---|---|\n{rows}\n"
    chunks = chunk_document(parse_markdown_text(md, "t"))
    assert len(chunks) > 1
    assert all(c.text.startswith("| Item | Valor |\n|---|---|") for c in chunks)


def test_pdf_pagina_e_marcadores():
    blocks = [Block(text=f"Conteúdo da página {i}. " * 12, heading_path=[f"Slide {i}"], page=i) for i in range(1, 6)]
    doc = ParsedDocument(title="deck", format="pdf", blocks=blocks + [Block(text="x " * 400, page=6)])
    chunks = chunk_document(doc)
    assert all(c.page_start is not None for c in chunks)
    assert chunks[0].location().startswith("p. 1")
    joined = [c for c in chunks if c.page_start != c.page_end]
    for c in joined:  # chunk com várias páginas carrega marcadores para citação precisa
        assert f"[p. {c.page_end}]" in c.text

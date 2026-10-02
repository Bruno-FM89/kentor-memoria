"""Seleção de trechos (snippets) e fusão de quase-duplicatas."""
from __future__ import annotations

import re

from ..models import format_location
from ..retrieval.claims import is_deprecated_sentence
from ..retrieval.hybrid import MONEY, QueryAnalysis
from ..retrieval.index import ChunkRecord
from ..retrieval.text import content_stems, split_sentences

SNIPPET_CHARS = 480


_STARTS_BLOCK = re.compile(r"^([-*•>|#\[]|\d+[.)]\s)")


def _join_wrapped(text: str, prose: bool = True) -> list[str]:
    """Junta linhas quebradas no meio da frase.

    prose=True (Markdown/TXT, que têm quebra manual de linha): junta quando a linha
    anterior não termina frase. prose=False (PDF/slides, cheios de rótulos soltos):
    só junta quando a linha seguinte começa com minúscula ("com os 10 / primeiros").
    """
    lines: list[str] = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if lines:
            prev = lines[-1]
            continuation = line[0].islower() or prose and (
                not prev.endswith((".", "!", "?", ":", ";", ")", "]", "|"))
                and not _STARTS_BLOCK.match(line)
                and " | " not in line and " | " not in prev
                and not prev.startswith("[")
            )
            if continuation:
                lines[-1] = f"{prev} {line}"
                continue
        lines.append(line)
    return lines


def _units(text: str, prose: bool = True) -> list[str]:
    """Linhas (tabelas, listas) e, dentro delas, frases."""
    out: list[str] = []
    for line in _join_wrapped(text, prose):
        out.extend(split_sentences(line) if len(line) > 220 else [line])
    return out


def unit_score(u: str, q: QueryAnalysis) -> float:
    """Quanto uma linha/frase cobre a pergunta (IDF dos termos presentes)."""
    stems = set(content_stems(u))
    s = sum(w for t, w in q.weights.items() if t in stems)
    if q.wants_money and MONEY.search(u):
        s += q.weights.get("<valor_monetario>", 0.0)
    if q.count_intent and re.search(r"\d", u) and s > 0:
        s *= 1.5  # pergunta "quantos": prioriza a linha com o número
    if is_deprecated_sentence(u):
        s *= 0.3  # afirmação aposentada não deve ser o destaque
    return s


_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_MARKER_LINE = re.compile(r"^\[[^\]\n]+\]$")
_BULLET = re.compile(r"^\s*(?:[-*•>]|\d+[.)])\s+")


def tidy_line(line: str) -> str:
    """Linha legível: sem marcação Markdown, sem marcador de lista, tabela como 'a · b · c'."""
    line = line.strip()
    if line.startswith("|") and line.endswith("|") and line.count("|") >= 3:
        line = " · ".join(c.strip() for c in line.strip("|").split("|") if c.strip())
    elif " | " in line:  # linha de tabela vinda de DOCX/PPTX
        line = " · ".join(c.strip() for c in line.split(" | ") if c.strip())
    line = _BULLET.sub("", line)
    return re.sub(r"\*\*|`", "", line).strip()


def key_lines(rec: ChunkRecord, q: QueryAnalysis, max_lines: int = 3, max_chars: int = 420) -> list[str]:
    """As 1–3 linhas do trecho que respondem mais diretamente à pergunta (resposta extrativa).

    Mantém a ordem original e só inclui linhas com pelo menos 60% da nota da melhor.
    """
    prose = rec.doc_format in ("md", "txt")
    units = [u for u in _units(rec.text, prose) if not _TABLE_SEP.match(u) and not _MARKER_LINE.match(u)]
    if not units:
        return []
    scored = [(unit_score(u, q), i, u) for i, u in enumerate(units)]
    best = max(s for s, _, _ in scored)
    if best <= 0:
        return [tidy_line(units[0])[:max_chars]]
    top = sorted((t for t in scored if t[0] >= 0.6 * best), key=lambda t: -t[0])[:max_lines]
    out: list[str] = []
    total = 0
    for _, _, u in sorted(top, key=lambda t: t[1]):
        line = tidy_line(u)
        if out and total + len(line) > max_chars:
            break
        out.append(line)
        total += len(line)
    return out


def best_snippet(rec: ChunkRecord, q: QueryAnalysis, max_chars: int = SNIPPET_CHARS) -> str:
    """Escolhe as unidades (linha/frase) que mais cobrem a pergunta, na ordem original."""
    units = _units(rec.text, rec.doc_format in ("md", "txt"))
    if not units:
        return ""
    if len(rec.text) <= max_chars:
        return rec.text.strip()

    def score(u: str) -> float:
        return unit_score(u, q)

    scored = sorted(range(len(units)), key=lambda i: -score(units[i]))
    chosen: set[int] = set()
    total = 0
    for i in scored:
        if score(units[i]) <= 0 and chosen:
            break
        for j in (i, i + 1):  # a unidade e a seguinte (contexto)
            if j < len(units) and j not in chosen and total + len(units[j]) <= max_chars:
                chosen.add(j)
                total += len(units[j]) + 1
        if total >= max_chars * 0.8:
            break
    if not chosen:
        return units[0][:max_chars]
    parts, last = [], None
    for i in sorted(chosen):
        if last is not None and i != last + 1:
            parts.append("[…]")
        parts.append(units[i])
        last = i
    return "\n".join(parts)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


NEAR_DUP = 0.5


def is_near_duplicate(a: ChunkRecord, b: ChunkRecord) -> bool:
    """Mesmo conteúdo em arquivos diferentes (ex.: capítulo .md e o PDF que o reproduz)."""
    return a.document_id != b.document_id and jaccard(a.text_stems, b.text_stems) >= NEAR_DUP


_MARKER = re.compile(r"^\[(p\. (?P<page>\d+)|slide (?P<slide>\d+)|(?P<heading>[^\]]+))\]$", re.M)


def find_fragment(text: str, fragment: str) -> int:
    """Posição aproximada de um fragmento (tolerante a quebras de linha)."""
    words = re.findall(r"\S+", fragment)[:4]
    if not words:
        return -1
    m = re.search(r"\s+".join(re.escape(w) for w in words), text)
    return m.start() if m else -1


def location_at(rec: ChunkRecord, pos: int) -> str:
    """Página/slide/seção vigente numa posição do chunk (lê os marcadores internos)."""
    page, slide, heading = rec.page_start, rec.slide_start, rec.heading_path
    if pos >= 0:
        for m in _MARKER.finditer(rec.text[:pos]):
            if m.group("page"):
                page = int(m.group("page"))
            elif m.group("slide"):
                slide = int(m.group("slide"))
            elif m.group("heading"):
                heading = m.group("heading").split(" > ")
    else:
        return rec.location
    return format_location(heading, page, page, slide, slide)

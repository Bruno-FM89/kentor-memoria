"""Extração determinística de afirmações quantitativas e frases aposentadas.

Serve para detectar CONFLITO sem LLM: duas fontes diferentes afirmando
quantidades incompatíveis sobre o mesmo substantivo da pergunta.

Exemplos:
  "+60 clientes atendidos"            → clientes ∈ [60, ∞)
  "com os 10 primeiros clientes"      → clientes = 10
  "entre 5 e 9 slides"                → slides ∈ [5, 9]
Intervalos que não se sobrepõem = conflito.

Frases como "a versão anterior ... não deve mais ser usada" marcam uma
afirmação como APOSENTADA dentro do próprio documento: ela não entra na
comparação e aparece como nota.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .text import split_sentences, stem

DEPRECATION = re.compile(
    r"vers[aã]o anterior|n[aã]o deve(?:m)? mais ser usad|foi aposentad|foram aposentad|aposentad[oa]s? na verifica"
    r"|n[aã]o (?:os |as )?cite|n[aã]o vale mais|obsolet|revogad",
    re.IGNORECASE,
)

_NUM = r"\d{1,3}(?:[.\s]\d{3})+|\d+(?:,\d+)?"
_WORD = r"[^\W\d_]+"
_CLAIM = re.compile(
    rf"(?P<cur>R\$\s*)?(?P<prefix>\+|mais de |acima de |pelo menos |cerca de |~|≈|>=?|≥)?\s*"
    rf"(?P<a>{_NUM})(?:\s*(?:a|e|-|–|até)\s*(?P<b>{_NUM}))?\s*(?P<pct>%)?"
    rf"\s+(?P<words>(?:{_WORD}\s+)?{_WORD})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Claim:
    noun_stem: str
    low: float
    high: float
    text: str  # frase de onde veio

    def overlaps(self, other: "Claim") -> bool:
        return self.low <= other.high and other.low <= self.high

    def display(self) -> str:
        if self.high == math.inf:
            return f"{self._fmt(self.low)} ou mais"
        if self.low == self.high:
            return self._fmt(self.low)
        return f"{self._fmt(self.low)} a {self._fmt(self.high)}"

    @staticmethod
    def _fmt(v: float) -> str:
        return str(int(v)) if float(v).is_integer() else str(v)


def _to_float(s: str) -> float:
    s = s.replace(" ", "").replace(".", "").replace(",", ".")
    return float(s)


def is_deprecated_sentence(sentence: str) -> bool:
    return bool(DEPRECATION.search(sentence))


def extract_claims(text: str, target_stems: set[str]) -> list[Claim]:
    """Afirmações 'número + substantivo' cujo substantivo está na pergunta."""
    claims: list[Claim] = []
    flat = " ".join(strip_markers(text).split())
    for sent in split_sentences(flat) or [flat]:
        if is_deprecated_sentence(sent):
            continue
        for m in _CLAIM.finditer(sent):
            if m.group("cur") or m.group("pct"):
                continue  # valores monetários/percentuais: contexto demais para comparar às cegas
            if sent[m.end() : m.end() + 1] == "/":
                continue  # taxa ("15 clientes/mês") não é contagem
            if re.fullmatch(r"0\d+", m.group("a")):
                continue  # "01", "02": numeração de lista, não quantidade
            a = _to_float(m.group("a"))
            if 1900 <= a <= 2100 and not m.group("b"):
                continue  # provavelmente um ano
            words = [w.lower() for w in m.group("words").split()]
            noun = next((stem(w) for w in words if stem(w) in target_stems), None)
            if not noun:
                continue
            prefix = (m.group("prefix") or "").strip().lower()
            if m.group("b"):
                low, high = sorted((a, _to_float(m.group("b"))))
            elif prefix in ("+", "mais de", "acima de", "pelo menos", ">", ">=", "≥"):
                low, high = a, math.inf
            elif prefix in ("cerca de", "~", "≈"):
                low, high = a * 0.9, a * 1.1
            else:
                low = high = a
            claims.append(Claim(noun, low, high, sent.strip()[:240]))
    return claims


_MARKER_LINE = re.compile(r"^\[[^\]\n]+\]$", re.M)


def strip_markers(text: str) -> str:
    """Remove as linhas-marcador do chunker ([p. 4], [slide 2], [Seção])."""
    return _MARKER_LINE.sub("", text)


def deprecated_sentences(text: str) -> list[str]:
    flat = " ".join(strip_markers(text).split())
    return [s for s in split_sentences(flat) if is_deprecated_sentence(s)]

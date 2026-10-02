"""Análise de texto em português: tokenização, stopwords e stemming.

O mesmo pipeline é usado para indexar (FTS5) e para consultar, então "atendeu"
e "atendidos" viram o mesmo radical ("atend") nos dois lados.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

import snowballstemmer

_STEMMER = snowballstemmer.stemmer("portuguese")
_TOKEN = re.compile(r"[0-9]+(?:[.,][0-9]+)*|[^\W\d_]+")

# Stopwords PT (artigos, preposições, pronomes, auxiliares e palavras de pergunta).
_RAW_STOPWORDS = (
    """
a à às ao aos as o os um uma uns umas de da das do dos d em na nas no nos num numa
por pela pelas pelo pelos para pra pro pras pros com sem sob sobre entre ate até
e ou mas nem que se como quando onde qual quais quanto quanta quantos quantas quem
cujo cuja porque pois entao então ja já nao não sim tambem também mais menos muito
muita muitos muitas pouco pouca todo toda todos todas outro outra outros outras
este esta estes estas esse essa esses essas aquele aquela aqueles aquelas isto isso aquilo
eu tu ele ela nos nós vos vós eles elas me te lhe lhes meu minha meus minhas seu sua seus suas
nosso nossa nossos nossas voce você voces vocês
ser sou é e era eram foi foram sera será sao são estar esta está estao estão estava
ter tem têm tinha tinham teve haver ha há havia fazer faz fez vai vao vão
the of and to in is for on
"""
)


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


STOPWORDS = frozenset(strip_accents(w) for w in _RAW_STOPWORDS.split())


def tokenize(text: str) -> list[str]:
    """Minúsculas, tokens alfanuméricos (acentos preservados para o stemmer)."""
    return _TOKEN.findall(unicodedata.normalize("NFC", text.lower()))


@lru_cache(maxsize=200_000)
def stem(token: str) -> str:
    if token[:1].isdigit():
        return token
    return strip_accents(_STEMMER.stemWord(token))


def content_stems(text: str) -> list[str]:
    """Radicais das palavras de conteúdo (sem stopwords, sem tokens de 1 letra)."""
    out = []
    for tok in tokenize(text):
        if strip_accents(tok) in STOPWORDS or (len(tok) < 2 and not tok.isdigit()):
            continue
        out.append(stem(tok))
    return out


def stemmed_text(text: str) -> str:
    """Texto pronto para o índice FTS5 (radicais separados por espaço)."""
    return " ".join(content_stems(text))


_SENT_SPLIT = re.compile(r"(?<=[.!?;])\s+(?=[A-ZÀ-Ý0-9\"“(*\-•|+])|\n+")


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT_SPLIT.split(text)]
    return [p for p in parts if p]

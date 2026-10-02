"""Detecção EXPLÍCITA de supersessão e de afirmações aposentadas.

Regra de ouro: nunca inferimos que A substitui B só porque A é mais novo.
Datas do acervo nem são confiáveis (há DOCX com data de 2013 herdada de
template). Só contam sinais declarados:

1. Frontmatter: supersedes / substitui / replaces / substituido_por /
   superseded_by; status: obsoleto | aposentado | deprecated | superseded.
2. Frase de cabeçalho com alvo entre aspas ou nome de arquivo:
   'Substitui o "Kentor fora do corpo" (M-D-048, aposentada)'.
   Só olhamos o cabeçalho (primeiras linhas) para não confundir com frases
   comuns como "nenhum substitui o outro".
3. No nível da FRASE: "versão anterior ... não deve mais ser usada",
   "números aposentados" etc. marcam uma afirmação específica como vencida
   dentro do próprio documento (ver retrieval/claims.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..models import ParsedDocument
from ..retrieval.text import strip_accents

FM_SUPERSEDES = ("supersedes", "substitui", "replaces", "substitui_documento")
FM_SUPERSEDED_BY = ("superseded_by", "substituido_por", "substituído_por")
FM_STATUS = ("status", "situacao", "situação")
DEPRECATED_STATUS = {
    "obsoleto", "obsoleta", "aposentado", "aposentada", "deprecated", "superseded",
    "substituido", "substituida", "revogado", "revogada", "arquivado", "arquivada",
}
FM_VERSION = ("version", "versao", "versão")
FM_DATE = ("date", "data", "atualizado", "updated", "created", "criado")

HEADER_LINES = 25
_QUOTED = r"[\"“«'`]([^\"”»'`\n]{3,80})[\"”»'`]"
_FILE = r"([\w./ -]{2,80}\.(?:md|pdf|docx|pptx|txt|svg|css))"
_SUPERSEDES_TEXT = re.compile(
    rf"(?<!nenhum )(?<!não )(?<!nao )\bsubstitui\s+(?:o|a|os|as)?\s*(?:documento|arquivo|vers[aã]o)?\s*(?:{_QUOTED}|{_FILE})"
    rf"(?:\s*\(([^)]{{1,60}})\))?",
    re.IGNORECASE,
)
_DOC_ID = re.compile(r"\b[A-Z]{1,3}-[A-Z]{1,3}-\d{2,4}\b|\bP-\d{2,3}\b")


@dataclass
class SupersessionRef:
    ref: str  # texto do alvo (título, arquivo ou id)
    ids: list[str]  # ids citados junto (ex.: M-D-048)
    evidence: str  # frase que comprova


@dataclass
class DocSignals:
    supersedes: list[SupersessionRef] = field(default_factory=list)
    superseded_by: list[str] = field(default_factory=list)
    deprecated: bool = False
    version_label: str | None = None
    doc_date: str | None = None
    declared_ids: list[str] = field(default_factory=list)


def _as_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v if str(x).strip()]
    return [str(v)] if str(v).strip() else []


def detect_signals(doc: ParsedDocument) -> DocSignals:
    fm: dict[str, Any] = doc.metadata.get("frontmatter", {}) or {}
    sig = DocSignals()

    for k in FM_SUPERSEDES:
        for ref in _as_list(fm.get(k)):
            sig.supersedes.append(SupersessionRef(ref.strip(), _DOC_ID.findall(ref), f"frontmatter {k}: {ref}"))
    for k in FM_SUPERSEDED_BY:
        sig.superseded_by += _as_list(fm.get(k))
    for k in FM_STATUS:
        if strip_accents(str(fm.get(k, "")).strip().lower()) in DEPRECATED_STATUS:
            sig.deprecated = True
    for k in FM_VERSION:
        if fm.get(k):
            sig.version_label = str(fm[k])
    for k in FM_DATE:
        if fm.get(k):
            sig.doc_date = str(fm[k])
            break
    if not sig.doc_date:
        sig.doc_date = doc.metadata.get("created") or doc.metadata.get("modified")
    if fm.get("id"):
        sig.declared_ids.append(str(fm["id"]))

    header = "\n".join(doc.full_text.split("\n")[:HEADER_LINES])
    for m in _SUPERSEDES_TEXT.finditer(header):
        ref = (m.group(1) or m.group(2) or "").strip()
        paren = m.group(3) or ""
        line = next((ln for ln in header.split("\n") if m.group(0) in ln), m.group(0))
        if ref:
            sig.supersedes.append(SupersessionRef(ref, _DOC_ID.findall(paren + " " + ref), line.strip()[:300]))
    return sig


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", strip_accents(s.lower())).strip()


def resolve_ref(ref: SupersessionRef, candidates: list[dict[str, Any]]) -> str | None:
    """Tenta achar o documento-alvo no acervo por id declarado, arquivo ou título.

    `candidates`: dicts com id, path, filename, title, declared_ids.
    Exige correspondência exata (normalizada) — sem similaridade difusa, para
    não criar supersessão falsa.
    """
    ref_n = _norm(ref.ref)
    for c in candidates:
        if set(ref.ids) & set(c.get("declared_ids") or []):
            return c["id"]
        names = {_norm(c["filename"]), _norm(c["filename"].rsplit(".", 1)[0]), _norm(c.get("title") or ""), _norm(c["path"])}
        if ref_n and ref_n in names:
            return c["id"]
    return None

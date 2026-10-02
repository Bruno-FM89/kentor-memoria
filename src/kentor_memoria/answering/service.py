"""Orquestração de uma pergunta: busca → política → decisão de status → resposta.

Decisão de status (determinística):
  1. Candidatos = busca híbrida em TODO o acervo (inclusive restrito — só
     internamente, para saber se "existe algo").
  2. Relevante = cobertura ponderada da pergunta >= MIN_COVERAGE (e, se a
     pergunta pede um valor em R$, o trecho precisa conter um valor em R$).
  3. Nenhum relevante                    → NOT_FOUND
     Melhor relevante é negado          → FORBIDDEN (sem conteúdo, sem título)
     Fontes permitidas incompatíveis     → CONFLICT (mostra todas)
     Caso contrário                      → FOUND (com fontes)
  4. (Opcional) LLM verifica se as evidências respondem mesmo e redige.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from ..config import Settings, get_settings
from ..database.db import connect, get_meta
from ..llm.answer import answer_with_llm
from ..llm.openrouter import LLMError, OpenRouterClient
from ..models import Answer, Evidence, Status
from ..permissions.policy import AccessPolicy, Identity
from ..retrieval.claims import Claim, deprecated_sentences, extract_claims
from ..retrieval.hybrid import MONEY, Candidate, QueryAnalysis, hybrid_search
from ..retrieval.index import SearchIndex
from .snippets import best_snippet, find_fragment, is_near_duplicate, key_lines, location_at

log = logging.getLogger(__name__)

MIN_COVERAGE = 0.55  # calibrado em docs/EVAL.md
CONFLICT_MIN_COVERAGE = 0.30  # rede mais larga só para achar afirmações divergentes
MAX_SOURCES = 4
MAX_CHUNKS_PER_DOC = 2
SOURCE_SCORE_WINDOW = 0.2  # fontes com cobertura muito abaixo da principal não são citadas

NOT_FOUND_MSG = "Não encontrei essa informação no material disponível."


@dataclass
class Retrieval:
    q: QueryAnalysis
    candidates: list[Candidate]
    relevant: list[Candidate]
    allowed: list[Candidate]
    denied: list[Candidate]
    retrieval_ms: float
    count_intent: bool = False


class KnowledgeService:
    def __init__(self, settings: Settings | None = None, conn: sqlite3.Connection | None = None):
        self.settings = settings or get_settings()
        self.conn = conn or connect(self.settings.db_path)
        self.policy = AccessPolicy.from_files(self.settings.policy_file, self.settings.identities_file)
        self.index = SearchIndex(self.conn)
        self.llm: OpenRouterClient | None = None
        self.last_llm_error: str | None = None
        if self.settings.llm_enabled:
            self.llm = OpenRouterClient(self.settings.openrouter_api_key or "", self.settings.openrouter_model, self.conn)

    # ------------------------------------------------------------ busca base
    def _retrieve(self, question: str, identity: Identity) -> Retrieval:
        if self.index.is_stale():
            self.index.load()
        t0 = time.perf_counter()
        q, cands = hybrid_search(self.index, question)
        count_intent = q.count_intent
        nouns = set(q.terms)

        def relevant(c: Candidate) -> bool:
            if c.coverage < MIN_COVERAGE:
                return False
            if q.wants_money and not MONEY.search(c.rec.text):
                return False  # pergunta de preço exige trecho com valor
            return True

        rel = [c for c in cands if relevant(c)]

        def key(c: Candidate):
            has_claim = count_intent and bool(extract_claims(c.rec.text, nouns))
            # 1º quanto da pergunta o trecho cobre (faixas de 0,05); 2º contém a expressão
            # exata da pergunta; 3º tem afirmação numérica se a pergunta é "quantos";
            # 4º consenso dos rankings (RRF)
            return (-round(c.coverage * 20), -c.phrase_hits, -int(has_claim), -c.fused)

        rel.sort(key=key)
        allowed, denied = self.policy.authorize(identity, rel, lambda c: c.rec.access_level)
        ms = (time.perf_counter() - t0) * 1000
        return Retrieval(q, cands, rel, allowed, denied, round(ms, 1), count_intent)

    def _evidence(self, c: Candidate, q: QueryAnalysis, identity: Identity) -> Evidence:
        # defesa em profundidade: nunca materializa evidência não autorizada
        if not self.policy.can_read(identity, c.rec.access_level):
            raise PermissionError("tentativa de materializar evidência não autorizada")
        r = c.rec
        notes = []
        resolved = {x["ref"]: x["target_document_id"] for x in r.doc_meta.get("supersedes", [])}
        for ref in r.doc_meta.get("supersedes_refs", []):
            ids = f" ({', '.join(ref.get('ids') or [])})" if ref.get("ids") else ""
            target = self._path_if_readable(resolved.get(ref["ref"]), identity)
            where = f" — versão anterior: {target}" if target else " — o documento substituído não está no acervo"
            notes.append(f"Este documento declara substituir '{ref['ref']}'{ids}{where}.")
        for s in deprecated_sentences(r.text):
            notes.append(f"Afirmação marcada como vencida no próprio documento: “{s[:200]}”")
        snippet = best_snippet(r, q)
        first_line = next((ln for ln in snippet.split("\n") if ln.strip() and not ln.startswith("[")), snippet)
        location = location_at(r, find_fragment(r.text, first_line))
        page_m = re.search(r"p\. (\d+)", location)
        return Evidence(
            document_id=r.document_id, chunk_id=r.id, source=r.doc_path, title=r.doc_title, location=location,
            snippet=snippet, score=round(c.coverage, 3), format=r.doc_format,
            page=int(page_m.group(1)) if page_m else r.page_start,
            slide=r.slide_start, section=" > ".join(r.heading_path) or None, doc_date=r.doc_date,
            version=r.doc_version, notes=notes,
        )

    def _collect_evidence(self, ret: Retrieval, identity: Identity) -> tuple[list[Evidence], list[Candidate]]:
        chosen: list[Candidate] = []
        evidence: list[Evidence] = []
        for c in ret.allowed:
            if c.rec.doc_status != "active":
                continue
            dup_of = next((i for i, x in enumerate(chosen) if is_near_duplicate(x.rec, c.rec)), None)
            if dup_of is not None:
                also = f"{c.rec.doc_path} ({c.rec.location})"
                if also not in evidence[dup_of].also_in:
                    evidence[dup_of].also_in.append(also)
                continue
            if len(chosen) >= MAX_SOURCES:
                continue
            if chosen and c.coverage < chosen[0].coverage - SOURCE_SCORE_WINDOW:
                continue
            if sum(1 for x in chosen if x.rec.document_id == c.rec.document_id) >= MAX_CHUNKS_PER_DOC:
                continue
            chosen.append(c)
            evidence.append(self._evidence(c, ret.q, identity))
        return evidence, chosen

    # ------------------------------------------------------------- conflitos
    def _detect_conflicts(self, ret: Retrieval, identity: Identity, main: list[Candidate]) -> list[dict]:
        # Conflito determinístico = contagens incompatíveis; só faz sentido quando a
        # pergunta pede uma contagem ("quantos..."). Outros conflitos: verificador LLM.
        if not ret.q.count_intent:
            return []
        nouns = set(ret.q.terms)
        pool = [
            c for c in ret.candidates
            if c.coverage >= CONFLICT_MIN_COVERAGE and c.rec.doc_status == "active"
            and self.policy.can_read(identity, c.rec.access_level)
        ]
        main_docs = {c.rec.document_id for c in main}
        by_doc: dict[str, list[tuple[Candidate, Claim]]] = {}
        for c in pool:
            for cl in extract_claims(c.rec.text, nouns):
                by_doc.setdefault(c.rec.document_id, []).append((c, cl))
        docs = list(by_doc)
        for i, da in enumerate(docs):
            for db in docs[i + 1 :]:
                if da not in main_docs and db not in main_docs:
                    continue
                for ca, cla in by_doc[da]:
                    for cb, clb in by_doc[db]:
                        if cla.noun_stem != clb.noun_stem or cla.overlaps(clb):
                            continue
                        if is_near_duplicate(ca.rec, cb.rec):
                            continue
                        return [
                            {
                                "topic": cla.noun_stem,
                                "claims": [
                                    self._claim_dict(ca, cla, identity, ret.q),
                                    self._claim_dict(cb, clb, identity, ret.q),
                                ],
                                "resolution": "Nenhum dos documentos declara substituir o outro; "
                                "o sistema não escolhe uma versão. Confirme com o responsável pelo conteúdo.",
                            }
                        ]
        return []

    def _claim_dict(self, c: Candidate, cl: Claim, identity: Identity, q: QueryAnalysis) -> dict:
        ev = self._evidence(c, q, identity)
        return {
            "value": cl.display(),
            "statement": cl.text,
            "source": ev.source,
            "location": location_at(c.rec, find_fragment(c.rec.text, cl.text)),
            "document_id": ev.document_id,
            "chunk_id": ev.chunk_id,
            "doc_date": ev.doc_date,
        }

    # ------------------------------------------------------------------ ask
    def ask(self, question: str, identity_name: str) -> Answer:
        t0 = time.perf_counter()
        identity = self.policy.identity(identity_name)
        ret = self._retrieve(question, identity)
        answer = self._decide(question, ret, identity)
        answer.identity = identity.name
        answer.timings_ms = {"retrieval": ret.retrieval_ms, "total": round((time.perf_counter() - t0) * 1000, 1)}
        self._log("ask_knowledge", identity.name, question, answer.status.value, ret, answer.timings_ms["total"],
                  model=answer.model)
        return answer

    def _decide(self, question: str, ret: Retrieval, identity: Identity) -> Answer:
        if not ret.relevant:
            return Answer(Status.NOT_FOUND, NOT_FOUND_MSG)

        top = ret.relevant[0]
        if top in ret.denied:
            owner = self.policy.owner_hint(top.rec.doc_path)
            msg = (
                "Existe informação relacionada a essa pergunta no acervo, mas ela está fora do seu nível de "
                f"acesso ({identity.name}: {identity.clearance})."
            )
            if owner:
                msg += f" Quem pode responder: {owner}."
            return Answer(Status.FORBIDDEN, msg)

        notes: list[str] = []
        if ret.denied:
            notes.append("Há também informação relacionada fora do seu nível de acesso (não exibida).")

        evidence, chosen = self._collect_evidence(ret, identity)
        superseded = [
            {"source": c.rec.doc_path, "location": c.rec.location, "superseded_by": self._path_if_readable(c.rec.superseded_by, identity)}
            for c in ret.allowed if c.rec.doc_status == "superseded"
        ]
        if not evidence:
            return Answer(
                Status.NOT_FOUND,
                "Só encontrei essa informação em documento marcado como substituído; não há versão vigente no acervo.",
                superseded_sources=superseded,
            )

        conflicts = self._detect_conflicts(ret, identity, chosen)
        model = None
        if self.llm is not None:
            llm_out = self._llm_answer(question, evidence, chosen)
            if llm_out is None and self.last_llm_error:
                notes.append(f"A IA não respondeu ({self.last_llm_error}); mostrando os trechos literais.")
            if llm_out is not None:
                model = llm_out.usage.model
                if not llm_out.answerable and not conflicts:
                    return Answer(
                        Status.NOT_FOUND, NOT_FOUND_MSG,
                        notes=["Trechos parecidos foram encontrados, mas o verificador concluiu que não respondem à pergunta."],
                        model=model,
                    )
                if llm_out.conflict and not conflicts and len({evidence[i].document_id for i in llm_out.used}) >= 2:
                    conflicts = [{
                        "topic": "divergência apontada pelo verificador",
                        "claims": [{"source": evidence[i].source, "location": evidence[i].location,
                                    "statement": evidence[i].snippet[:240]} for i in llm_out.used],
                        "resolution": llm_out.conflict_explanation,
                    }]
                if not conflicts:
                    used = [evidence[i] for i in llm_out.used] or evidence[:1]
                    return Answer(Status.FOUND, llm_out.answer, sources=used, notes=notes,
                                  superseded_sources=superseded, model=model)

        if conflicts:
            conflict_sources = self._conflict_sources(conflicts, evidence, identity, ret)
            lines = ["As fontes divergem sobre isso e nenhuma declara substituir a outra:"]
            for cl in conflicts[0]["claims"]:
                lines.append(f"- {cl['source']} ({cl['location']}): “{cl['statement']}”")
            lines.append("Não escolhi uma das versões; confirme com o responsável pelo conteúdo.")
            return Answer(Status.CONFLICT, "\n".join(lines), sources=conflict_sources, conflicts=conflicts,
                          notes=notes, superseded_sources=superseded, model=model)

        return Answer(Status.FOUND, self._extractive_answer(evidence, chosen, ret), sources=evidence, notes=notes,
                      superseded_sources=superseded, model=model)

    def _conflict_sources(self, conflicts, evidence, identity, ret) -> list[Evidence]:
        out: list[Evidence] = []
        by_chunk = {c.rec.id: c for c in ret.candidates}
        for cl in conflicts[0]["claims"]:
            cid = cl.get("chunk_id")
            ev = next((e for e in evidence if e.chunk_id == cid), None)
            if ev is None and cid in by_chunk:
                ev = self._evidence(by_chunk[cid], ret.q, identity)
            if ev is not None and ev.chunk_id not in {e.chunk_id for e in out}:
                # a evidência de um conflito é a própria afirmação divergente
                page_m = re.search(r"p\. (\d+)", cl["location"])
                ev = replace(ev, snippet=cl["statement"], location=cl["location"],
                             page=int(page_m.group(1)) if page_m else ev.page)
                out.append(ev)
        if not out:
            out = evidence
        return out

    @staticmethod
    def _short_location(ev: Evidence) -> str:
        parts = [p.strip() for p in ev.location.split(" · ")]
        head = [p for p in parts if p.startswith(("p. ", "slide"))]
        rest = [p for p in parts if not p.startswith(("p. ", "slide"))]
        section = rest[-1].split(" > ")[-1] if rest else ""
        return " · ".join(head + ([section] if section else []))

    def _extractive_answer(self, evidence: list[Evidence], chosen: list[Candidate], ret: Retrieval) -> str:
        """Resposta sem LLM: as linhas do melhor trecho que respondem à pergunta + a fonte."""
        main, rec = evidence[0], chosen[0].rec
        lines = key_lines(rec, ret.q) or [main.snippet]
        body = lines[0] if len(lines) == 1 else "\n".join(f"• {ln}" for ln in lines)
        text = f"{body}\n\nFonte: {main.source} ({self._short_location(main)})"
        for ev in evidence[1:]:
            if ev.document_id != main.document_id and ev.score >= main.score - 0.15:
                text += f"\nTambém em: {ev.source} ({self._short_location(ev)})"
                break
        return text

    def _llm_answer(self, question: str, evidence: list[Evidence], chosen: list[Candidate]):
        self.last_llm_error = None
        try:
            return answer_with_llm(self.llm, question, evidence, [c.rec.text for c in chosen])
        except LLMError as exc:
            log.warning("LLM indisponível, usando resposta extrativa: %s", exc)
            self.last_llm_error = str(exc)[:200]
            return None

    def _path_if_readable(self, document_id: str | None, identity: Identity) -> str | None:
        if not document_id:
            return None
        row = self.conn.execute("SELECT path, access_level FROM documents WHERE id=?", (document_id,)).fetchone()
        if row and self.policy.can_read(identity, row["access_level"]):
            return row["path"]
        return None

    # --------------------------------------------------------------- search
    def search(self, question: str, identity_name: str, top_k: int = 5) -> dict:
        t0 = time.perf_counter()
        identity = self.policy.identity(identity_name)
        ret = self._retrieve(question, identity)
        if not ret.relevant:
            status = Status.NOT_FOUND
        elif ret.relevant[0] in ret.denied:
            status = Status.FORBIDDEN
        else:
            status = Status.FOUND
        evidence, _ = self._collect_evidence(ret, identity) if status == Status.FOUND else ([], [])
        total = round((time.perf_counter() - t0) * 1000, 1)
        self._log("search_knowledge", identity.name, question, status.value, ret, total)
        return {
            "status": status.value,
            "identity": identity.name,
            "evidence": [e.to_dict() for e in evidence[:top_k]],
            "restricted_related": bool(ret.denied),
            "timings_ms": {"retrieval": ret.retrieval_ms, "total": total},
        }

    # ----------------------------------------------------------- get_source
    def get_source(self, document_id: str, identity_name: str, chunk_id: str | None = None) -> dict:
        identity = self.policy.identity(identity_name)
        doc = self.conn.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
        if doc is None or doc["status"] == "deleted":
            result = {"status": Status.NOT_FOUND.value, "message": "Documento não encontrado."}
        elif not self.policy.can_read(identity, doc["access_level"]):
            result = {"status": Status.FORBIDDEN.value,
                      "message": "Este documento está fora do seu nível de acesso."}
        else:
            q = "SELECT * FROM chunks WHERE document_id=? AND version=? AND active=1"
            params: list = [document_id, doc["current_version"]]
            if chunk_id:
                q += " AND id=?"
                params.append(chunk_id)
            chunks = self.conn.execute(q + " ORDER BY ordinal", params).fetchall()
            meta = json.loads(doc["metadata_json"] or "{}")
            result = {
                "status": Status.FOUND.value,
                "document_id": doc["id"], "source": doc["path"], "title": doc["title"], "format": doc["format"],
                "access_level": doc["access_level"], "document_status": doc["status"],
                "version": doc["current_version"], "content_hash": doc["content_hash"], "doc_date": doc["doc_date"],
                "superseded_by": self._path_if_readable(doc["superseded_by"], identity),
                "supersedes": [r["ref"] for r in meta.get("supersedes_refs", [])],
                "chunks": [
                    {
                        "chunk_id": c["id"],
                        "location": self.index.records[c["rowid"]].location if c["rowid"] in self.index.records
                        else None,
                        "text": c["text"],
                    }
                    for c in chunks
                ],
            }
        self._log("get_source", identity.name, f"document_id={document_id} chunk_id={chunk_id}", result["status"],
                  None, 0.0)
        return result

    # --------------------------------------------------------------- health
    def health(self) -> dict:
        if self.index.is_stale():
            self.index.load()
        counts = {
            r["status"]: r["n"]
            for r in self.conn.execute("SELECT status, COUNT(*) AS n FROM documents GROUP BY status")
        }
        last = self.conn.execute("SELECT * FROM ingestion_runs ORDER BY id DESC LIMIT 1").fetchone()
        return {
            "status": "ok" if self.index.n else "empty",
            "documents_by_status": counts,
            "active_chunks": self.index.n,
            "embedding_model": self.index.embedding_model,
            "embedding_error": self.index.embedding_error,
            "llm_enabled": self.llm is not None,
            "llm_model": self.settings.openrouter_model if self.llm else None,
            "llm_status": (
                "ativa" if self.llm else
                "desligada (KENTOR_LLM_MODE=off)" if self.settings.llm_mode == "off" else
                "desligada (sem OPENROUTER_API_KEY no .env)"
            ),
            "index_version": get_meta(self.conn, "index_version"),
            "last_ingestion": dict(last) if last else None,
            "identities": sorted(self.policy.identities),
        }

    # -------------------------------------------------------------- logging
    def _log(self, tool: str, identity: str, question: str, status: str, ret: Retrieval | None, total_ms: float,
             model: str | None = None) -> None:
        retrieved = []
        if ret is not None:
            who = self.policy.identity(identity)
            for c in ret.candidates[:10]:
                # só ids e scores — nunca texto (conteúdo restrito não vai para o log)
                retrieved.append({
                    "document_id": c.rec.document_id, "chunk_id": c.rec.id, "coverage": round(c.coverage, 3),
                    "fused": round(c.fused, 4), "relevant": c in ret.relevant,
                    "authorized": self.policy.can_read(who, c.rec.access_level),
                })
        usage = self.conn.execute(
            "SELECT prompt_tokens, completion_tokens, cost_usd FROM llm_usage ORDER BY id DESC LIMIT 1"
        ).fetchone() if model else None
        with self.conn:
            self.conn.execute(
                """INSERT INTO query_log(ts, tool, identity, question, status, retrieval_ms, total_ms, retrieved_json,
                   model, prompt_tokens, completion_tokens, cost_usd) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    datetime.now(timezone.utc).isoformat(timespec="seconds"), tool, identity, question, status,
                    ret.retrieval_ms if ret else None, total_ms, json.dumps(retrieved), model,
                    usage["prompt_tokens"] if usage else None, usage["completion_tokens"] if usage else None,
                    usage["cost_usd"] if usage else None,
                ),
            )

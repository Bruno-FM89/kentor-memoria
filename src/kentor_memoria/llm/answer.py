"""Redação e verificação de resposta por LLM (etapa OPCIONAL).

O LLM recebe apenas evidências já AUTORIZADAS para a identidade — o conteúdo
negado nunca chega ao prompt. Ele não decide acesso; só:
  1. verifica se as evidências realmente respondem à pergunta (answerable);
  2. redige a resposta citando [E1], [E2]...;
  3. aponta se as evidências se contradizem.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..models import Evidence
from .openrouter import LLMResult, OpenRouterClient

SYSTEM = """Você é a memória corporativa da Kentor. Responda em português do Brasil usando
EXCLUSIVAMENTE as evidências fornecidas. Regras:
- Não use conhecimento geral nem complete lacunas. Se as evidências não respondem
  diretamente à pergunta, answerable=false.
- Cite as evidências usadas no texto como [E1], [E2].
- Se duas evidências de documentos diferentes afirmarem coisas incompatíveis sobre o
  mesmo ponto, conflict=true e explique a divergência sem escolher um lado.
- Resposta curta (até 5 frases).
Responda SOMENTE com JSON: {"answerable": bool, "answer": str, "used": ["E1", ...],
"conflict": bool, "conflict_explanation": str}"""


@dataclass
class LLMAnswer:
    answerable: bool
    answer: str
    used: list[int]
    conflict: bool
    conflict_explanation: str
    usage: LLMResult


def build_prompt(question: str, evidence: list[Evidence], full_texts: list[str]) -> str:
    parts = [f"Pergunta: {question}", "", "Evidências:"]
    for i, (ev, text) in enumerate(zip(evidence, full_texts), start=1):
        parts.append(f"[E{i}] fonte: {ev.source} ({ev.location})\n{text[:1500]}")
    return "\n\n".join(parts)


def answer_with_llm(client: OpenRouterClient, question: str, evidence: list[Evidence], full_texts: list[str]) -> LLMAnswer:
    data, usage = client.chat_json(SYSTEM, build_prompt(question, evidence, full_texts), purpose="answer")
    used: list[int] = []
    for tag in data.get("used") or []:
        try:
            idx = int(str(tag).strip().lstrip("E").lstrip("e")) - 1
        except ValueError:
            continue
        if 0 <= idx < len(evidence) and idx not in used:
            used.append(idx)
    return LLMAnswer(
        answerable=bool(data.get("answerable")),
        answer=str(data.get("answer") or "").strip(),
        used=used,
        conflict=bool(data.get("conflict")),
        conflict_explanation=str(data.get("conflict_explanation") or "").strip(),
        usage=usage,
    )

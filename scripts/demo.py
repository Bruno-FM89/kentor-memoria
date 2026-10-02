"""Roteiro de demonstração em terminal (plano B se o cliente MCP falhar na apresentação).

Uso: python scripts/demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(ROOT / "src"))

from kentor_memoria.answering.service import KnowledgeService  # noqa: E402

STEPS = [
    ("1. Recuperação normal + fonte", "marketing", "Qual é a regra da casa para capa de carrossel?"),
    ("2. Não está no acervo", "socio", "Qual ferramenta é usada para emitir nota fiscal?"),
    ("3a. Controle de acesso (marketing)", "marketing", "Quanto a empresa cobra por um projeto de automação?"),
    ("3b. Controle de acesso (vendas)", "vendas", "Quanto a empresa cobra por um projeto de automação?"),
    ("3c. Controle de acesso (vendas, finanças)", "vendas", "Qual a meta de receita recorrente?"),
    ("4a. Só existe em PDF", "marketing", "Qual a garantia oferecida na proposta comercial?"),
    ("4b. Só existe em Word", "marketing", "Quanto tempo dura o trabalho de hooks na reunião de conteúdo?"),
    ("5. Contradição real", "marketing", "Quantos clientes a Kentor já atendeu?"),
]


def main() -> None:
    svc = KnowledgeService()
    for title, who, q in STEPS:
        a = svc.ask(q, who).to_dict()
        print("=" * 100)
        print(f"{title}\n[{who}] {q}\n→ {a['status']}  ({a['timings_ms']['total']:.0f} ms)\n")
        print(a["answer"][:900])
        for s in a["sources"]:
            print(f"   fonte: {s['source']} · {s['location']}")
        print()
    print("=" * 100)
    print("6. Idempotência: rode `kentor ingest` duas vezes e compare new_docs/unchanged/active_chunks.")


if __name__ == "__main__":
    main()

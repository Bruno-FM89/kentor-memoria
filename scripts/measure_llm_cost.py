"""Mede custo e latência REAIS da etapa LLM (OpenRouter) sobre o conjunto de avaliação.

Pré-requisito: OPENROUTER_API_KEY no .env. O custo vem do campo `usage.cost` que o
OpenRouter devolve em cada chamada (não é estimado aqui).

Uso:
  python scripts/measure_llm_cost.py                # todas as perguntas do eval_set
  python scripts/measure_llm_cost.py --limit 5      # só as 5 primeiras (economiza orçamento)
  python scripts/measure_llm_cost.py --dry-run      # não chama a API: só mede o tamanho dos prompts
"""
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(ROOT / "src"))

from kentor_memoria.answering.service import KnowledgeService  # noqa: E402
from kentor_memoria.config import Settings, get_settings  # noqa: E402
from kentor_memoria.llm.answer import SYSTEM, build_prompt  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cases = yaml.safe_load((ROOT / "tests/data/eval_set.yaml").read_text(encoding="utf-8"))
    if args.limit:
        cases = cases[: args.limit]
    base = get_settings()

    if args.dry_run:
        svc = KnowledgeService(Settings(**{**base.__dict__, "llm_mode": "off"}))
        sizes = []
        for c in cases:
            ident = svc.policy.identity(c["identity"])
            ret = svc._retrieve(c["q"], ident)
            if not ret.relevant or ret.relevant[0] in ret.denied:
                continue  # NOT_FOUND/FORBIDDEN não chamam o LLM
            ev, chosen = svc._collect_evidence(ret, ident)
            sizes.append(len(SYSTEM) + len(build_prompt(c["q"], ev, [x.rec.text for x in chosen])))
        print(f"{len(sizes)}/{len(cases)} perguntas chamariam o LLM; prompt médio {statistics.mean(sizes):.0f} "
              f"caracteres (máx {max(sizes)}). Tokens ≈ caracteres/4 (estimativa grosseira, não medição).")
        return 0

    if not base.openrouter_api_key:
        print("OPENROUTER_API_KEY não definida — nada a medir.")
        return 1
    svc = KnowledgeService(Settings(**{**base.__dict__, "llm_mode": "auto"}))
    start_id = svc.conn.execute("SELECT COALESCE(MAX(id), 0) FROM llm_usage").fetchone()[0]
    for c in cases:
        a = svc.ask(c["q"], c["identity"])
        print(f"{a.status.value:9} {a.timings_ms['total']:7.0f} ms  [{c['identity']}] {c['q']}")
    row = svc.conn.execute(
        "SELECT COUNT(*) n, SUM(prompt_tokens) pt, SUM(completion_tokens) ct, SUM(cost_usd) cost, AVG(latency_ms) lat "
        "FROM llm_usage WHERE id > ?", (start_id,)
    ).fetchone()
    total = svc.conn.execute("SELECT SUM(cost_usd) FROM llm_usage").fetchone()[0] or 0.0
    print(f"\nchamadas LLM: {row['n']} · tokens entrada {row['pt']} · saída {row['ct']} · "
          f"custo desta rodada US$ {row['cost'] or 0:.5f} · latência média LLM {row['lat'] or 0:.0f} ms")
    print(f"custo acumulado registrado no banco: US$ {total:.5f} · saldo estimado do orçamento: US$ {5 - total:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

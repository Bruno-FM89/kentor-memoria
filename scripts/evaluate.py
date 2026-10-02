"""Roda o conjunto de avaliação (tests/data/eval_set.yaml) e imprime a matriz de resultados.

Uso: python scripts/evaluate.py [--verbose]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(ROOT / "src"))

from kentor_memoria.answering.service import KnowledgeService  # noqa: E402


def check(case: dict, ans: dict) -> list[str]:
    problems = []
    if ans["status"] != case["expected"]:
        problems.append(f"status {ans['status']} != {case['expected']}")
    names = [s["source"].rsplit("/", 1)[-1] for s in ans["sources"]]
    wanted = case.get("sources") or []
    if wanted:
        hits = [w for w in wanted if w in names]
        if case.get("all_sources") and len(hits) != len(wanted):
            problems.append(f"fontes {names} não contêm todas {wanted}")
        elif not hits:
            problems.append(f"fontes {names} sem nenhuma de {wanted}")
    blob = json.dumps(ans, ensure_ascii=False)
    for s in case.get("must_contain") or []:
        if s not in blob:
            problems.append(f"falta '{s}'")
    for s in case.get("must_not_contain") or []:
        if s in blob:
            problems.append(f"VAZAMENTO '{s}'")
    return problems


def main() -> int:
    verbose = "--verbose" in sys.argv
    cases = yaml.safe_load((ROOT / "tests/data/eval_set.yaml").read_text(encoding="utf-8"))
    svc = KnowledgeService()
    ok = limit_fail = fail = 0
    times = []
    for case in cases:
        t0 = time.perf_counter()
        ans = svc.ask(case["q"], case["identity"]).to_dict()
        times.append((time.perf_counter() - t0) * 1000)
        problems = check(case, ans)
        if not problems:
            ok += 1
            mark = "OK  "
        elif case.get("known_limitation"):
            limit_fail += 1
            mark = "LIM "
        else:
            fail += 1
            mark = "FAIL"
        print(f"{mark} [{case['identity']:9}] {case['expected']:9} -> {ans['status']:9} | {case['q']}")
        if problems:
            print("       ", "; ".join(problems))
        if verbose:
            print("       ", ans["answer"][:300].replace("\n", " "))
    times.sort()
    print(f"\n{ok}/{len(cases)} OK · {limit_fail} limitações conhecidas · {fail} falhas")
    print(f"latência ask(): mediana {times[len(times)//2]:.0f} ms · p95 {times[int(len(times)*0.95)-1]:.0f} ms · "
          f"embeddings={svc.index.embedding_model} · llm={'on' if svc.llm else 'off'}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())

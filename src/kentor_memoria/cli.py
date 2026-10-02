"""CLI: kentor ingest | ask | search | source | stats | logs | ui | serve."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def cmd_ingest(args) -> int:
    from .ingestion.pipeline import ingest

    rep = ingest(Path(args.source) if args.source else None)
    d = rep.to_dict()
    if not args.verbose:
        d.pop("supersessions", None)
    _print(d)
    return 1 if rep.errors else 0


def cmd_ask(args) -> int:
    from .answering.service import KnowledgeService

    ans = KnowledgeService().ask(args.question, args.identity).to_dict()
    if args.json:
        _print(ans)
    else:
        print(f"[{ans['status']}] ({args.identity})\n{ans['answer']}\n")
        for s in ans["sources"]:
            print(f"  fonte: {s['source']} · {s['location']} · score {s['score']}")
        for n in ans["notes"]:
            print(f"  nota: {n}")
    return 0


def cmd_search(args) -> int:
    from .answering.service import KnowledgeService

    _print(KnowledgeService().search(args.query, args.identity, top_k=args.top_k))
    return 0


def cmd_source(args) -> int:
    from .answering.service import KnowledgeService

    _print(KnowledgeService().get_source(args.document_id, args.identity, chunk_id=args.chunk_id))
    return 0


def cmd_stats(args) -> int:
    from .answering.service import KnowledgeService

    svc = KnowledgeService()
    info = svc.health()
    usage = svc.conn.execute(
        "SELECT COUNT(*) AS calls, SUM(prompt_tokens) AS pt, SUM(completion_tokens) AS ct, SUM(cost_usd) AS cost "
        "FROM llm_usage"
    ).fetchone()
    info["llm_usage_total"] = dict(usage)
    _print(info)
    return 0


def cmd_logs(args) -> int:
    from .config import get_settings
    from .database.db import connect

    conn = connect(get_settings().db_path)
    rows = conn.execute(
        "SELECT ts, tool, identity, status, retrieval_ms, total_ms, model, cost_usd, question FROM query_log "
        "ORDER BY id DESC LIMIT ?", (args.n,)
    ).fetchall()
    for r in rows:
        print(f"{r['ts']} {r['tool']:16} {r['identity'] or '-':9} {r['status'] or '-':9} "
              f"ret={r['retrieval_ms'] or 0:.0f}ms tot={r['total_ms'] or 0:.0f}ms "
              f"model={r['model'] or '-'} cost={r['cost_usd'] or 0} | {r['question']}")
    return 0


def cmd_ui(args) -> int:
    from .ui.launcher import launch

    return launch(port=args.port, open_browser=not args.no_browser)


def cmd_serve(args) -> int:
    from .mcp_server.server import main as serve

    serve()
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # console do Windows (cp1252) não quebra com “ ” → etc.
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    p = argparse.ArgumentParser(prog="kentor", description="Memória corporativa da Kentor (MCP)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ingest", help="ingere/reprocessa o acervo (idempotente)")
    s.add_argument("--source", help="pasta do acervo (padrão: KENTOR_ACERVO_DIR)")
    s.add_argument("--verbose", action="store_true")
    s.set_defaults(fn=cmd_ingest)

    s = sub.add_parser("ask", help="faz uma pergunta")
    s.add_argument("question")
    s.add_argument("--identity", "-i", required=True)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_ask)

    s = sub.add_parser("search", help="busca trechos")
    s.add_argument("query")
    s.add_argument("--identity", "-i", required=True)
    s.add_argument("--top-k", type=int, default=5)
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser("source", help="mostra um documento/trecho")
    s.add_argument("document_id")
    s.add_argument("--chunk-id")
    s.add_argument("--identity", "-i", required=True)
    s.set_defaults(fn=cmd_source)

    s = sub.add_parser("stats", help="estado do índice e custo acumulado de LLM")
    s.set_defaults(fn=cmd_stats)

    s = sub.add_parser("logs", help="últimas consultas registradas")
    s.add_argument("-n", type=int, default=20)
    s.set_defaults(fn=cmd_logs)

    s = sub.add_parser("ui", help="abre a interface gráfica no navegador (http://localhost:8501)")
    s.add_argument("--port", type=int, default=8501)
    s.add_argument("--no-browser", action="store_true", help="não abrir o navegador automaticamente")
    s.set_defaults(fn=cmd_ui)

    s = sub.add_parser("serve", help="inicia o servidor MCP (stdio)")
    s.set_defaults(fn=cmd_serve)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())

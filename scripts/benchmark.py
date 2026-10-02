"""Mede tempo de ingestão (1ª e 2ª execução) e latência de consulta, num banco temporário.

Uso:
  python scripts/benchmark.py                 # acervo normal
  python scripts/benchmark.py --scale 10      # acervo replicado 10x (teste de escala)

No modo --scale, cada cópia recebe bytes diferentes (linha extra em texto,
metadado alterado em PDF/DOCX/PPTX) para não ser tratada como duplicata exata.
O PDF de 84 MB é copiado só uma vez para não estourar disco.
"""
from __future__ import annotations

import argparse
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(ROOT / "src"))

from kentor_memoria.answering.service import KnowledgeService  # noqa: E402
from kentor_memoria.config import Settings, get_settings  # noqa: E402
from kentor_memoria.ingestion.pipeline import Ingestor, discover_files  # noqa: E402

QUESTIONS = [
    ("marketing", "Qual é a regra da casa para capa de carrossel?"),
    ("marketing", "Qual ferramenta a Kentor usa para emitir nota fiscal?"),
    ("marketing", "Quanto a empresa cobra por um projeto de automação?"),
    ("socio", "Quanto a empresa cobra por um projeto de automação?"),
    ("marketing", "Qual a garantia oferecida na proposta comercial?"),
    ("marketing", "Quanto tempo dura o trabalho de hooks na reunião de conteúdo?"),
    ("marketing", "Quantos clientes a Kentor já atendeu?"),
    ("software", "Quem regenera o organograma quando o roster muda?"),
]


def replicate(src: Path, dst: Path, times: int) -> None:
    files, _ = discover_files(src)
    for i in range(times):
        for f in files:
            if f.stat().st_size > 20_000_000 and i > 0:
                continue
            rel = f.relative_to(src)
            out = dst / f"copia{i:02d}" / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            ext = f.suffix.lower()
            if ext in (".md", ".txt", ".css", ".svg"):
                text = f.read_text(encoding="utf-8", errors="replace")
                marker = f"<!-- copia {i} -->" if ext == ".svg" else f"\n\n(cópia {i})\n"
                out.write_text(text.replace("</svg>", marker + "</svg>") if ext == ".svg" else text + marker,
                               encoding="utf-8")
            elif ext == ".pdf":
                import pymupdf

                doc = pymupdf.open(f)
                meta = doc.metadata or {}
                meta["subject"] = f"copia {i}"
                doc.set_metadata(meta)
                doc.save(out)
            elif ext == ".docx":
                import docx

                d = docx.Document(str(f))
                d.core_properties.subject = f"copia {i}"
                d.save(out)
            elif ext == ".pptx":
                import pptx

                p = pptx.Presentation(str(f))
                p.core_properties.subject = f"copia {i}"
                p.save(out)
            else:
                shutil.copy(f, out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=int, default=1)
    args = ap.parse_args()
    base = get_settings()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        acervo = base.acervo_dir
        if args.scale > 1:
            acervo = tmp / "acervo"
            t0 = time.perf_counter()
            replicate(base.acervo_dir, acervo, args.scale)
            print(f"réplica {args.scale}x criada em {time.perf_counter() - t0:.1f}s")
        settings = Settings(**{**base.__dict__, "db_path": tmp / "bench.db", "acervo_dir": acervo, "llm_mode": "off"})

        rep1 = Ingestor(settings).run()
        print(f"1ª ingestão: {rep1.files_seen} arquivos, {rep1.active_documents} docs, {rep1.active_chunks} chunks, "
              f"{rep1.embedded} embeddings ({rep1.embedding_model}) em {rep1.duration_ms / 1000:.1f}s")
        rep2 = Ingestor(settings).run()
        print(f"2ª ingestão (nada mudou): {rep2.unchanged} inalterados, {rep2.new_docs} novos, "
              f"{rep2.embedded} embeddings em {rep2.duration_ms / 1000:.2f}s")

        svc = KnowledgeService(settings)
        svc.ask("aquecimento", "marketing")
        lat, ret = [], []
        for _ in range(5):
            for who, q in QUESTIONS:
                a = svc.ask(q, who)
                lat.append(a.timings_ms["total"])
                ret.append(a.timings_ms["retrieval"])
        lat.sort()
        print(f"consulta (ask, sem LLM, {len(lat)} chamadas): mediana {statistics.median(lat):.1f} ms · "
              f"p95 {lat[int(len(lat) * 0.95) - 1]:.1f} ms · retrieval mediana {statistics.median(ret):.1f} ms")


if __name__ == "__main__":
    main()

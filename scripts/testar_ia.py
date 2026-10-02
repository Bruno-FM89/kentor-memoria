"""Diagnóstico da conexão com o OpenRouter. Uso: python scripts/testar_ia.py

Não mostra a chave inteira. Faz 1 chamada mínima (custo de fração de centavo).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(ROOT / "src"))

import httpx  # noqa: E402

from kentor_memoria.config import get_settings  # noqa: E402
from kentor_memoria.llm.openrouter import LLMError, OpenRouterClient, windows_system_proxy  # noqa: E402


def main() -> int:
    s = get_settings()
    key = s.openrouter_api_key or ""
    print(f"1) Chave no .env: {'SIM (' + key[:9] + '…' + key[-4:] + ')' if key else 'NÃO ENCONTRADA'}")
    print(f"   KENTOR_LLM_MODE={s.llm_mode} · modelo={s.openrouter_model}")
    if not key:
        return 1
    proxy = windows_system_proxy()
    print(f"2) Proxy do sistema: {proxy or 'nenhum'}")
    try:
        r = httpx.get("https://openrouter.ai/api/v1/models", timeout=20, **({"proxy": proxy} if proxy else {}))
        print(f"3) Conexão com openrouter.ai: OK (HTTP {r.status_code})")
    except Exception as exc:
        print(f"3) Conexão com openrouter.ai: FALHOU → {exc}")
        print("   A rede está bloqueando o OpenRouter (Wi-Fi de faculdade/empresa, antivírus ou VPN).")
        print("   Teste em outra rede (ex.: roteador do celular) ou abra https://openrouter.ai no navegador.")
        return 1
    try:
        data, usage = OpenRouterClient(key, s.openrouter_model).chat_json(
            "Responda só com JSON.", 'Devolva {"ok": true}', purpose="diagnostico", max_tokens=20)
        print(f"4) Chamada ao modelo: OK → {data} · tokens {usage.prompt_tokens}+{usage.completion_tokens}"
              f" · custo US$ {usage.cost_usd}")
    except LLMError as exc:
        print(f"4) Chamada ao modelo: FALHOU → {exc}")
        return 1
    print("\nTudo certo: a IA vai funcionar na interface (reinicie o Abrir Kentor Memoria.bat).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

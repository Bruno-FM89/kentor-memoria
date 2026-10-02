"""Cliente mínimo do OpenRouter (API compatível com OpenAI) com registro de custo.

- A chave vem SÓ de OPENROUTER_API_KEY (nunca do código).
- `usage: {include: true}` faz o OpenRouter devolver o custo real da chamada
  (campo usage.cost, em USD). Não estimamos custo: gravamos o que a API informa.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.request
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

API_URL = "https://openrouter.ai/api/v1/chat/completions"


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    content: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: float | None
    latency_ms: float


class OpenRouterClient:
    def __init__(self, api_key: str, model: str, conn: sqlite3.Connection | None = None, timeout: float = 45.0):
        if not api_key:
            raise LLMError("OPENROUTER_API_KEY ausente")
        self.api_key = api_key
        self.model = model
        self.conn = conn
        self.timeout = timeout

    def chat_json(self, system: str, user: str, purpose: str, max_tokens: int = 700) -> tuple[dict, LLMResult]:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "usage": {"include": True},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://github.com/kentor-memoria",
            "X-Title": "kentor-memoria",
        }
        t0 = time.perf_counter()
        extra = {"proxy": proxy} if (proxy := windows_system_proxy()) else {}
        for attempt in (1, 2):  # uma nova tentativa em queda de conexão
            try:
                resp = httpx.post(API_URL, json=body, headers=headers, timeout=self.timeout, **extra)
                break
            except httpx.TransportError as exc:
                if attempt == 2:
                    raise LLMError(f"Falha de rede no OpenRouter: {exc}") from exc
                time.sleep(1.0)
            except httpx.HTTPError as exc:
                raise LLMError(f"Falha de rede no OpenRouter: {exc}") from exc
        latency = (time.perf_counter() - t0) * 1000
        if resp.status_code != 200:
            raise LLMError(f"OpenRouter HTTP {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        usage = data.get("usage") or {}
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        result = LLMResult(
            content=content,
            model=data.get("model", self.model),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            cost_usd=usage.get("cost"),
            latency_ms=round(latency, 1),
        )
        self._record(purpose, result)
        return _parse_json(content), result

    def _record(self, purpose: str, r: LLMResult) -> None:
        if self.conn is None:
            return
        with self.conn:
            self.conn.execute(
                """INSERT INTO llm_usage(ts, purpose, model, prompt_tokens, completion_tokens, cost_usd, latency_ms)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    datetime.now(timezone.utc).isoformat(timespec="seconds"), purpose, r.model,
                    r.prompt_tokens, r.completion_tokens, r.cost_usd, r.latency_ms,
                ),
            )


def windows_system_proxy() -> str | None:
    """No Windows, o proxy configurado no sistema (o mesmo do navegador) não é lido
    automaticamente pelo httpx. Se não houver HTTPS_PROXY no ambiente, usa o do sistema."""
    if sys.platform != "win32" or os.getenv("HTTPS_PROXY") or os.getenv("https_proxy"):
        return None
    try:
        return urllib.request.getproxies().get("https") or None
    except Exception:
        return None


def _parse_json(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{") :]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise LLMError(f"Resposta do LLM não é JSON: {content[:200]}")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError(f"JSON inválido do LLM: {exc}") from exc

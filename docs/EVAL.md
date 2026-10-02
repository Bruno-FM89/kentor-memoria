# Avaliação e calibração

Conjunto: `tests/data/eval_set.yaml`, com 40 perguntas reais sobre o acervo e 4 identidades. A resposta esperada de cada uma foi conferida à mão (com grep no texto extraído) durante a análise.

Rodar: `python scripts/evaluate.py` (use `--verbose` para ver as respostas).

## Resultado (embeddings LSA, LLM desligado)

| Grupo | Perguntas | OK |
|---|---|---|
| FOUND, público (md, pdf, docx, pptx, svg, css) | 14 | 14 |
| NOT_FOUND | 12 | 10 (+2 limitações conhecidas) |
| FORBIDDEN (marketing e vendas) | 6 | 6 |
| FOUND restrito (vendas e sócio) | 6 | 6 |
| CONFLICT | 2 | 2 |
| **Total** | **40** | **38** |

Nenhum vazamento: as perguntas FORBIDDEN verificam que valores, nomes e nomes de arquivo restritos não aparecem em nenhum campo da resposta.

Latência de `ask()` sem LLM: mediana ~4 ms, p95 ~30 ms (sandbox Linux com 2 vCPUs).

## Resultado com o LLM ligado (OpenRouter, `google/gemini-2.5-flash-lite`)

Medido na máquina Windows do autor, com `python scripts/measure_llm_cost.py` (mesmas 40 perguntas). Saída bruta em [medicoes/custo_llm_2026-10-02.txt](medicoes/custo_llm_2026-10-02.txt).

| | Sem LLM | Com LLM |
|---|---|---|
| Status corretos | 38/40 | **39/40** |
| "Qual banco a Kentor usa?" | FOUND (errado) | **NOT_FOUND** (verificador corrigiu) |
| "Qual CRM a Kentor usa?" | FOUND (errado) | FOUND (errado: o modelo aceitou "toda PME usa CRM") |
| Latência (perguntas que chamam o LLM) | ~4 ms | ~1,15 s mediana (0,8–2,7 s) |
| Custo da rodada | US$ 0 | **US$ 0,00316** (24 chamadas, 21.477 + 2.534 tokens) |

NOT_FOUND e FORBIDDEN são decididos antes do LLM e não o chamam. Por isso custam US$ 0 e levam ~5–12 ms, e o conteúdo negado nunca chega ao modelo.

## Calibração do limiar de cobertura (`MIN_COVERAGE`)

Cobertura = soma do IDF dos termos da pergunta que aparecem no trecho ÷ soma do IDF de todos os termos da pergunta. Varredura do limiar no mesmo conjunto:

| Limiar | OK | FOUND indevido (deveria ser NOT_FOUND) | Resposta perdida |
|---|---|---|---|
| 0,40 | 31 | 9 | 0 |
| 0,50 | 36 | 4 | 0 |
| **0,55** | **38** | **2** | **0** |
| 0,60 | 38 | 2 | 0 |
| 0,65 | 37 | 2 | 1 |
| 0,70 | 36 | 2 | 2 |

Escolhemos 0,55, a borda inferior do platô, para preservar respostas legítimas. Ressalva honesta: o limiar foi calibrado no mesmo conjunto usado para avaliar. Com um acervo maior, o certo é separar calibração e teste.

## Limitações conhecidas (sem LLM)

| Pergunta | Esperado | Obtido | Por quê |
|---|---|---|---|
| "Qual banco a Kentor usa?" | NOT_FOUND | FOUND | "banco" aparece em `banco-de-hooks.md`. A cobertura só vê palavras, não sentido. |
| "Qual CRM a Kentor usa?" | NOT_FOUND | FOUND | O Deck diz "toda PME usa… CRM, ERP". Tem as palavras, mas o sujeito é outro. |

Esses são os casos em que o texto tem as palavras, mas não a resposta. É para isso que existe o verificador LLM opcional (`KENTOR_LLM_MODE=auto` + chave). Ele recebe só as evidências autorizadas e responde `answerable=false` quando elas não respondem à pergunta; nesse caso o status vira NOT_FOUND (testado com o OpenRouter simulado em `tests/test_llm_optional.py`). Com o modelo real, ele corrigiu o caso "banco", mas não o caso "CRM" (ver tabela acima).

## Backend de embeddings

Os números acima usam o LSA, o fallback offline. O ambiente de desenvolvimento bloqueia o HuggingFace, então o modelo multilíngue padrão (`paraphrase-multilingual-MiniLM-L12-v2` via fastembed) **não pôde ser validado aqui**. A decisão de status (limiar de cobertura, exigência de R$, conflitos) não depende do backend de embeddings: ele só altera a ordem dos candidatos no RRF. Para validar na sua máquina:

```bash
rm data/kentor.db && KENTOR_EMBEDDINGS=fastembed kentor ingest
python scripts/evaluate.py
KENTOR_TEST_EMBEDDINGS=fastembed pytest
```

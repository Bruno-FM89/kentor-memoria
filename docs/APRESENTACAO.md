# Roteiro da apresentação (≤ 10 minutos)

## 1. Problema (1 min)
- Cada pessoa da Kentor trabalha com um agente que precisa conhecer a empresa. Hoje o contexto é colado à mão e envelhece, todo mundo vê tudo e, quando falta informação, o agente inventa.
- O acervo tem 44 arquivos em 7 formatos, escritos por pessoas diferentes em momentos diferentes. Parte deles se contradiz.
- O que precisa sair do outro lado: resposta com fonte, "não sei" honesto, separação de acesso e nenhuma escolha silenciosa entre versões.

## 2. Arquitetura (1,5 min)
- Diagrama em `docs/architecture.md`: arquivos → parsers → chunking → metadados + nível → SQLite (FTS5 + vetores) → busca híbrida → **política** → status → MCP → agente.
- Escolhas: Python, **SQLite** (um arquivo, sem servidor), **NumPy** para vetores (472 chunks cabem na RAM), **SDK oficial do MCP**. Sem LangChain e sem banco vetorial: não agregam valor nessa escala e esconderiam as decisões.
- Tudo roda local; o LLM é opcional.

## 3. Ingestão (1,5 min)
- Um parser por formato. O PDF guarda página e detecta títulos pelo tamanho da fonte; DOCX, tabelas em ordem; PPTX, slide e notas; SVG, textos por linha.
- **Chunking por estrutura:** documento pequeno fica inteiro (a tabela de preços não pode perder o cabeçalho); o grande vai por seção, parágrafo e frase, até cerca de 1.200 caracteres, sem cortar frase.
- **Idempotência:** SHA-256 + versão do parser. Arquivo igual é pulado; alterado vira versão 2 com os chunks antigos inativos; removido sai da busca; duplicata exata não é indexada.
- Achado: o PDF de 84 MB levava 16 s por causa das imagens; ignorando-as, leva 0,3 s. A amostra inteira é ingerida em 3,5 s.

## 4. Retrieval (1,5 min)
- Três rankings: **BM25** (palavras exatas, nomes, siglas), **embeddings** (sentido, paráfrase) e **cobertura** (quanto da pergunta o trecho contém, ponderado por raridade). Os três são fundidos por **RRF**.
- A cobertura também decide o **NOT_FOUND**: ≥ 0,55, calibrado num eval de 40 perguntas reais (38 OK).
- Detalhes úteis: pergunta de preço exige `R$` no trecho; pergunta "quantos" prioriza trechos com número.

## 5. Segurança (1 min)
- A busca vê tudo, mas **um único ponto** (`authorize`) transforma candidato em evidência. Do que foi negado sai só "existe" e quem pode responder.
- A identidade é **fixada no processo MCP**, não é um parâmetro do agente. Teste real no Claude Code: pedir `identity=socio` num servidor de marketing dá FORBIDDEN.
- O LLM nunca recebe conteúdo negado, o log não guarda texto e há teste de vazamento com 10 ataques.

## 6. Conflitos e versionamento (1 min)
- Supersessão **só com declaração** (frontmatter, "Substitui o 'X'", `status: obsoleto`), **nunca por data**: há DOCX com data de 2013 herdada do template.
- Contradição real no acervo: "10 primeiros clientes" (pitch, mai/26) × "+60 clientes atendidos" (comercial) → CONFLICT com as duas fontes.
- Dentro de um documento: "a versão anterior (R$ 120 mil) não deve mais ser usada" → a frase é marcada como vencida e aparece como nota.

## 7. Custos (0,5 min)
- Ingestão e busca: US$ 0, porque tudo roda local. O LLM (`gemini-2.5-flash-lite` via OpenRouter) só verifica e redige, e só quando já há evidência autorizada.
- Medido nas 40 perguntas do eval: 24 chamadas, US$ 0,00316, ou seja, **~US$ 0,00013 por pergunta**. Gasto total no projeto: **US$ 0,0034 de US$ 5**.
- Com o LLM, o eval foi de 38/40 para 39/40. Latência de ~1,1 s por resposta redigida.

## 8. Dificuldades e aprendizados (1 min)
- **Palavra presente ≠ resposta presente.** "Qual banco a Kentor usa?" encontra `banco-de-hooks.md`. Busca lexical não resolve isso; é o papel do verificador LLM. Deixei documentado em vez de esconder.
- O limiar de NOT_FOUND precisa de um eval: sem medir, é chute.
- A citação precisa exige cuidado. Chunks que juntam páginas pequenas precisaram de marcadores internos para a fonte dizer "p. 10", e não "p. 9-12".
- O ambiente de desenvolvimento bloqueava HuggingFace e OpenRouter. Isso me levou a um fallback offline (LSA) e a medir honestamente o que foi e o que não foi validado.
- A atualização do SDK MCP 2.x renomeou APIs; fixei a v1.

## 9. Demo (2 min)
Pela interface gráfica (`kentor ui`), seguindo `docs/DEMO.md`: capa de carrossel (fonte), garantia (PDF), hooks (Word), nota fiscal (NOT_FOUND), preço marketing × sócio (FORBIDDEN × FOUND), agente tentando trocar identidade, clientes (CONFLICT), `kentor ingest` 2x.

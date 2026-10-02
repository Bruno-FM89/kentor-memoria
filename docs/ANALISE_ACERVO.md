# Análise do acervo (feita antes de implementar)

## Inventário: 44 arquivos

| Pasta | Arquivos | Formatos | Observações |
|---|---|---|---|
| `01-estrategia/` | 12 | 5 md, 4 pdf, 1 pptx, 1 txt, 1 css | Método Centauro em 3 formas (capítulos .md, Deck ED2 .pdf de 50 p., Framework .pdf de 22 p.), doutrina de posts, design system, 2 decks comerciais |
| `02-agentes-e-skills/` | 15 | 14 md, 1 svg | Agentes-funcionários, templates, roster, organograma (SVG gerado a partir do roster) |
| `03-base-de-conhecimento/` | 4 | 1 md, 3 pdf | Guias em PDF de 2 a 3 páginas |
| `04-processos/` | 6 | 3 md, 2 docx, 1 pptx | Templates (escopo pós-R2, reunião de conteúdo), prompt de mapeamento |
| `05-restrito-ficticio/` | 5 | 5 md | Dados inventados: preços, contratos, metas, remuneração (~500 caracteres cada) |
| raiz | 1 | md | LEIA-ME |

O zip veio do macOS: ele traz `__MACOSX/`, `.DS_Store` e nomes em Unicode NFD (`Apresentação`). O sistema ignora esse lixo e normaliza os nomes para NFC, para que o id de um documento seja o mesmo em qualquer sistema operacional.

## Tamanhos

Vão de 369 caracteres (LEIA-ME restrito) a cerca de 57 mil (Framework PDF). O maior arquivo (84 MB, a apresentação comercial em PDF) é quase todo imagem e tem apenas ~8,7 mil caracteres de texto. Extrair esse PDF com imagens levava 16 s; ignorando imagens (`TEXTFLAGS_TEXT`), leva 0,3 s.

## Metadados disponíveis (e sua confiabilidade)

- Frontmatter YAML em apenas 5 arquivos (`01_fases.md`, `02_…`, `04_…`, `skill-otto.md`, `TEMPLATE_Ficha_Processo.md`).
- Datas de PDF (`creationDate`) em 5 PDFs; a apresentação comercial não tem data.
- **Datas de DOCX/PPTX não são confiáveis**: dois arquivos têm 2013 como data, herdada do template do python-docx/pptx. Por isso nenhuma decisão de supersessão usa data.
- Headings: bons nos .md; nos PDFs, só pelo tamanho da fonte; no DOCX, pelos estilos "Heading N" (um dos DOCX não usa estilos).

## Contradições e versões encontradas

| Tipo | Onde | O que o sistema faz |
|---|---|---|
| **Contradição real** | `Apresentação Kentor.pdf` p.10 ("Já em campo, com os 10 primeiros clientes", mai/2026) × `SpinOff … Apresentação comercial.pdf` p.4 ("+60 clientes atendidos", sem data) | CONFLICT com as duas fontes (Teste 5) |
| Supersessão declarada (alvo fora do acervo) | `DOUTRINA_POSTS.md`: *Substitui o "Kentor fora do corpo" (M-D-048, aposentada)* | Relação registrada como "não resolvida" e exibida como nota na fonte |
| Afirmação vencida dentro do documento | `metas-financeiras.md`: *"A versão anterior falava em R$ 120.000/mês e não deve mais ser usada"* | A frase é marcada como vencida: sai da comparação de conflitos e aparece como nota |
| Números aposentados | `Deck_Metodo_Centauro_ED2.pdf` p.39: "Números aposentados na verificação" | Idem (frase vencida) |
| Duplicação entre formatos | `Framework_Aplicacao_Centauro.pdf` reproduz `01_fases.md`, `02_principios_camadas.md` e `04_kit_certificacao.md` | Quase-duplicatas (Jaccard ≥ 0,5) são fundidas numa evidência, com `also_in` |
| Inconsistência de cadastro | O roster lista 5 heads, mas `skill-funcionarios.md` fala em "os 4 heads". Forja e Cássio existem como agentes, mas não estão no roster nem no organograma. `skill-funcionarios` aponta `.Codex/…` e o roster aponta `.claude/…` | Documentado; não há pergunta de teste para isso |
| Armadilha de NOT_FOUND | "nota fiscal" aparece no Deck ED2, mas só como terminologia a testar ("FGTS, MEI, nota fiscal"). Nenhuma ferramenta de emissão é citada | NOT_FOUND: "emitir" não existe no acervo, então a cobertura fica em 0,46 < 0,55 |
| Preço público × preço restrito | O deck da SpinOff (público) tem preço da assessoria mensal (R$ 3.997/mês); a tabela de "projeto de automação" só existe em `05-restrito-ficticio/pricing-interno.md` | Para marketing: FORBIDDEN, porque o melhor trecho é o restrito |

## O que o sistema precisa resolver

1. Interpretar 7 formatos com estruturas bem diferentes (capítulo longo, deck de slides, tabela, SVG).
2. Citar a origem exata (arquivo + seção/página/slide).
3. Separar `05-restrito-ficticio/` sem depender do agente.
4. Dizer "não sei" quando a resposta não está no acervo, mesmo que palavras parecidas estejam lá.
5. Não escolher silenciosamente entre fontes divergentes e distinguir isso de supersessão declarada.
6. Reprocessar sem duplicar e reprocessar só o que mudou.

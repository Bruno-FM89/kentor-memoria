# Roteiro de demonstração (~5 minutos) — pela interface gráfica

**Antes da call:**

```bash
.venv\Scripts\activate           # macOS/Linux: source .venv/bin/activate
kentor ingest                    # índice pronto (rodar 2x mostra que não duplica)
kentor ui                        # abre http://localhost:8501
```

Deixe o navegador em tela cheia (F11), com a barra lateral aberta. Clique em **Limpar conversa** antes de começar.

Plano B, se o navegador falhar: `python scripts/demo.py` roda o mesmo roteiro no terminal.
Plano C (agente real): o Claude Code com o `.mcp.json` do repositório. Há transcrições prontas em [transcripts/claude-code.md](transcripts/claude-code.md).

| Min | O que provar | Identidade | Ação (botão da barra lateral → **Perguntar**) | O que mostrar na tela |
|---|---|---|---|---|
| 0:00 | Visão geral | — | — | Barra lateral: ● Banco carregado · ● Busca disponível · ● Servidor MCP instalado · **44 documentos / 472 trechos**. "Tudo que aparece aqui vem do backend; a tela não decide nada." |
| 0:30 | **1. Pergunta normal** | Marketing | *Regra para capa de carrossel* | ✅ Informação encontrada: "Capa: persona dominante + cor-vinda-da-foto…" |
| 1:00 | **2. Fonte utilizada** | Marketing | abrir o card **📄 DOUTRINA_POSTS.md** | Caminho `01-estrategia/DOUTRINA_POSTS.md`, seção "2.1 Regras GLOBAIS de post", trecho usado e a nota "declara substituir 'Kentor fora do corpo' (M-D-048), que não está no acervo" |
| 1:30 | **3. Mesma pergunta, permissões diferentes** | Marketing | *Informação restrita (preço)* | 🔒 "Esta informação existe no acervo, mas não está disponível para a identidade atual… Quem pode responder: a área comercial (Vendas) ou um sócio". Nenhum valor |
| 1:50 | | **Vendas** (trocar no seletor) | mesma pergunta | Aparece "— identidade alterada para Vendas —". ✅ R$ 9.000 a R$ 15.000 (pequeno), fonte `pricing-interno.md` |
| 2:10 | | Vendas | *Informação restrita (finanças)* | 🔒 Vendas vê preço, mas **não** metas financeiras |
| 2:25 | | **Sócio** | mesma pergunta | ✅ R$ 95.000/mês + nota "a versão anterior (R$ 120.000) não deve mais ser usada" |
| 2:50 | **4. Informação inexistente** | Sócio | *Informação inexistente* | 🔎 "Não encontrei essa informação no material disponível", sem fontes. Nem o sócio recebe resposta inventada |
| 3:20 | **5. Conflito** | Marketing | *Exemplo de conflito* | ⚠️ Fonte A: comercial PDF p. 4, "+60 clientes atendidos". Fonte B: pitch PDF p. 10, "10 primeiros clientes". "Nenhum documento declara substituir o outro; o sistema não escolhe" |
| 3:50 | **6. PDF e Word** | Marketing | *Informação só no PDF*, depois *Informação só no Word* | PDF: "30 dias de garantia incondicional", **Página: 34**. Word: tabela do `.docx`, "Trabalho de hooks · 20 min" |
| 4:20 | Idempotência | terminal | `kentor ingest` | `"new_docs": 0, "unchanged": 44`, mesmo nº de trechos |
| 4:40 | Consistência | terminal | `kentor ask "Quantos clientes a Kentor já atendeu?" -i marketing` | Mesmo CONFLICT da tela. Interface, CLI e MCP usam a mesma função |

**Frase de fechamento:** "A interface é só uma janela. Quem decide o que cada pessoa vê é o backend, o mesmo que o Claude Code usa via MCP. Por isso a tela nunca recebe o conteúdo proibido."

## Se perguntarem

- **"E se alguém burlar a tela?"** Não há o que burlar: em FORBIDDEN, o dicionário que chega à interface já não tem o conteúdo. Pelo MCP, a identidade vem da configuração do processo; se o agente pedir outra, recebe FORBIDDEN.
- **"Por que um seletor de identidade?"** É para a demo. Em produção, a identidade viria do login (SSO) e o seletor sumiria.

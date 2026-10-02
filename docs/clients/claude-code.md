# Configurar no Claude Code

## Opção A — `.mcp.json` do repositório (já incluso)

Abra o Claude Code **na raiz do repositório**. Ele detecta o `.mcp.json` e pergunta se
deve habilitar os servidores `kentor-marketing`, `kentor-vendas` e `kentor-socio`.

O comando padrão é `.venv/bin/python` (macOS/Linux). No **Windows**, antes de abrir o
Claude Code, defina o Python do venv:

```powershell
$env:KENTOR_PYTHON = "$PWD\.venv\Scripts\python.exe"
claude
```

## Opção B — `claude mcp add` (uma identidade por pessoa)

```bash
# macOS / Linux
claude mcp add kentor -e KENTOR_IDENTITY=marketing -- "$PWD/.venv/bin/python" -m kentor_memoria.mcp_server
```

```powershell
# Windows
claude mcp add kentor -e KENTOR_IDENTITY=marketing -- "$PWD\.venv\Scripts\python.exe" -m kentor_memoria.mcp_server
```

Confirme com `claude mcp list` e, dentro do Claude Code, `/mcp`.

## Por que um servidor por identidade?

A identidade é fixada na configuração do processo (`KENTOR_IDENTITY`), fora do alcance
do agente. Se o modelo tentar chamar `ask_knowledge(identity="socio")` num servidor de
marketing, o servidor recusa. Numa implantação real, cada pessoa teria só o servidor
com a própria identidade (e, em produção, um token no lugar da variável).

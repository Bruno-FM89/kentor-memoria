"""Interface gráfica (Streamlit) — camada de APRESENTAÇÃO apenas.

Toda decisão (busca, permissões, FOUND/NOT_FOUND/FORBIDDEN/CONFLICT) acontece no
backend, via UIBackend.ask → KnowledgeService.ask, a mesma chamada do CLI e do MCP.
"""
from __future__ import annotations

import html
import re

import streamlit as st

from .bridge import AnswerView, SourceCard, UIBackend, load_demo_questions

TONES = {  # (fundo, borda, texto) — cor ajuda, mas ícone + texto sempre acompanham
    "found": ("#E9F6EF", "#2E8B57", "#14532D"),
    "notfound": ("#EEF2F7", "#64748B", "#1E293B"),
    "forbidden": ("#FDECEC", "#B42318", "#7A1A12"),
    "conflict": ("#FFF6E0", "#B7791F", "#744210"),
}

CSS = """
<style>
  .block-container {max-width: 1080px; padding-top: 2.2rem;}
  .km-header h1 {font-size: 2.1rem; margin: 0; color: #0B1F3A; letter-spacing: -0.01em;}
  .km-header p {margin: .15rem 0 0 0; color: #50627A; font-size: 1.02rem;}
  .km-chip {display:inline-block; padding: .2rem .65rem; border-radius: 999px; font-size: .82rem;
            background:#E6F1F6; color:#0E4A63; border:1px solid #B9D8E6; margin-right:.35rem;}
  .km-status {border-radius: 10px; padding: .6rem .9rem; font-weight: 600; font-size: 1.02rem;
              border-left: 6px solid; margin: .1rem 0 .7rem 0;}
  .km-answer {white-space: pre-wrap; line-height: 1.55; font-size: .98rem; color:#16233A;}
  .km-quote {white-space: pre-wrap; background:#F6F8FB; border-left: 3px solid #509CBA;
             padding:.6rem .8rem; border-radius: 6px; font-size:.92rem; color:#1F2D44;}
  .km-side {border:1px solid #D9E2EC; border-radius:10px; padding:.75rem .85rem; background:#FFFFFF;}
  .km-conf {border:1px solid #E7C66B; background:#FFFBF0; border-radius:10px; padding:.7rem .85rem;}
  .km-conf h4 {margin:0 0 .3rem 0; font-size:.95rem; color:#744210;}
  .km-meta {color:#50627A; font-size:.85rem;}
  .km-dot-ok {color:#2E8B57;} .km-dot-off {color:#94A3B8;}
  .km-card {background:#FFFFFF; border:1px solid #D9E2EC; border-radius:10px; padding:.8rem 1rem;
             font-size:1.02rem; color:#16233A; margin-bottom:.5rem;}
  .km-card .km-answer {font-size:1.02rem;}
  .km-list {margin:0; padding-left:1.1rem;} .km-list li {margin:.25rem 0; line-height:1.5;}
  .km-source {font-size:.92rem; color:#16233A; margin:.2rem 0 .3rem 0;}
  .km-switch {text-align:center; color:#50627A; font-size:.85rem; margin:.6rem 0;}
  div[data-testid="InputInstructions"] {display:none;}  /* dica em inglês "Press Enter…" */
  div[data-testid="stForm"] {border: 1px solid #D9E2EC; border-radius: 12px; background:#FFFFFF;}
</style>
"""

_MD_MARKS = re.compile(r"\*\*|`")  # não remove "__": aparece em nomes de arquivo reais
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _clean(text: str) -> str:
    """Só apresentação: tira negrito/crase de Markdown e deixa linhas de tabela legíveis."""
    lines = []
    for line in (text or "").split("\n"):
        if _TABLE_SEP.match(line):
            continue
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 3:
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            line = " · ".join(c for c in cells if c)
        lines.append(line)
    return _MD_MARKS.sub("", "\n".join(lines))


def _esc(text: str) -> str:
    # "$" vira entidade: o Streamlit interpretaria "R$ ... R$" como fórmula LaTeX
    return html.escape(text or "").replace("$", "&#36;")


@st.cache_resource(show_spinner="Carregando a memória da Kentor…")
def get_backend() -> UIBackend:
    return UIBackend()


# ------------------------------------------------------------------ pedaços
def status_banner(view: AnswerView) -> None:
    bg, border, fg = TONES[view.tone]
    st.markdown(
        f'<div class="km-status" style="background:{bg};border-color:{border};color:{fg}">'
        f"{view.icon}&nbsp; {_esc(view.title)}</div>",
        unsafe_allow_html=True,
    )


def source_card(i: int, s: SourceCard) -> None:
    title = f"📄 {s.filename}" + (f" — {s.location}" if s.location else "")
    title = title.replace("$", "\\$").replace("_", "\\_")  # rótulo do expander é Markdown
    with st.expander(title, expanded=False):
        rows = [("Caminho", s.path)]
        if s.section:
            rows.append(("Seção", s.section))
        if s.page:
            rows.append(("Página", str(s.page)))
        if s.slide:
            rows.append(("Slide", str(s.slide)))
        st.markdown(
            "<div class='km-meta'>" + "<br>".join(f"<b>{k}:</b> {_esc(v)}" for k, v in rows) + "</div>",
            unsafe_allow_html=True,
        )
        st.markdown("**Trecho do documento**")
        st.markdown(f"<div class='km-quote'>{_esc(_clean(s.snippet))}</div>", unsafe_allow_html=True)
        for n in s.notes:
            st.caption(f"ℹ️ {n}")
        if s.also_in:
            st.caption("Conteúdo equivalente também em: " + "; ".join(s.also_in))


def conflict_block(view: AnswerView) -> None:
    st.markdown("**⚠️ Foram encontradas informações conflitantes.**")
    cols = st.columns(len(view.conflict) or 1)
    for idx, (col, side) in enumerate(zip(cols, view.conflict)):
        letter = chr(ord("A") + idx)
        with col:
            st.markdown(
                f"<div class='km-conf'><h4>Fonte {letter}</h4>"
                f"<div><b>{_esc(side.filename)}</b></div>"
                f"<div class='km-meta'>{_esc(side.location)}</div>"
                f"<div style='margin:.45rem 0'><b>Diz:</b> {_esc(side.value)}</div>"
                f"<div class='km-quote'>{_esc(_clean(side.statement))}</div></div>",
                unsafe_allow_html=True,
            )
    if view.conflict_resolution:
        st.caption(view.conflict_resolution)


def found_block(view: AnswerView) -> None:
    """Resposta direta em destaque + de onde veio (a fonte principal) logo abaixo."""
    body = view.answer.split("\n\nFonte:", 1)[0].strip()  # a linha "Fonte:" vira o selo abaixo
    lines = [ln.strip() for ln in body.split("\n") if ln.strip()]
    if len(lines) > 1 and all(ln.startswith("• ") for ln in lines):
        inner = "".join(f"<li>{_esc(_clean(ln[2:]))}</li>" for ln in lines)
        html_body = f"<ul class='km-list'>{inner}</ul>"
    else:
        html_body = f"<div class='km-answer'>{_esc(_clean(body))}</div>"
    st.markdown(f"<div class='km-card'>{html_body}</div>", unsafe_allow_html=True)
    if view.sources:
        main = view.sources[0]
        where = " · ".join(p for p in (main.section and main.section.split(" > ")[-1],
                                         f"p. {main.page}" if main.page else None,
                                         f"slide {main.slide}" if main.slide else None) if p)
        st.markdown(
            f"<div class='km-source'>📄 Fonte: <b>{_esc(main.filename)}</b>"
            + (f" · {_esc(where)}" if where else "")
            + f"<br><span class='km-meta'>{_esc(main.path)}</span></div>",
            unsafe_allow_html=True,
        )
    if view.model:
        st.caption(f"Resposta redigida por IA ({view.model}) somente a partir das fontes abaixo.")
    else:
        st.caption("Trechos copiados literalmente do documento, sem reescrita por IA.")


def answer_block(view: AnswerView) -> None:
    status_banner(view)
    if view.status == "FORBIDDEN":
        st.markdown(
            "🔒 **Esta informação existe no acervo, mas não está disponível para a identidade atual.**"
        )
        st.markdown(f"<div class='km-answer'>{_esc(view.answer)}</div>", unsafe_allow_html=True)
        return
    if view.status == "CONFLICT":
        conflict_block(view)
    elif view.status == "FOUND":
        found_block(view)
    else:
        st.markdown(f"<div class='km-answer'>{_esc(_clean(view.answer))}</div>", unsafe_allow_html=True)
    for n in view.notes:
        st.caption(f"ℹ️ {n}")
    if view.sources:
        st.markdown("##### Fontes consultadas")
        st.caption("Clique para ver o trecho completo de cada documento.")
        for i, s in enumerate(view.sources):
            source_card(i, s)
    if view.elapsed_ms is not None:
        st.caption(f"Respondido em {view.elapsed_ms:.0f} ms")


# ------------------------------------------------------------------ página
def render() -> None:
    st.set_page_config(page_title="Kentor Memória", page_icon="📚", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)

    ss = st.session_state
    ss.setdefault("history", [])
    ss.setdefault("question", "")
    if ss.pop("_clear_question", False):  # limpa o campo depois de uma pergunta enviada
        ss.question = ""

    try:
        backend = get_backend()
    except Exception as exc:  # banco ausente/corrompido: mensagem amigável
        st.error(f"Não foi possível abrir a base de conhecimento: {exc}")
        st.stop()

    identities = backend.identities()
    by_name = {o.name: o for o in identities}
    ss.setdefault("identity", identities[0].name if identities else None)
    status = backend.system_status()

    # ---------------------------------------------------------------- sidebar
    with st.sidebar:
        st.markdown("## Kentor Memória")
        st.caption("Memória corporativa para agentes de IA")

        cur = by_name.get(ss.identity)
        if cur:
            st.markdown("**Identidade atual**")
            st.markdown(
                f"<div class='km-side'><b>{_esc(cur.label)}</b><br>"
                f"<span class='km-meta'>Nível de acesso: {_esc(cur.clearance_label)}</span></div>",
                unsafe_allow_html=True,
            )

        st.write("")
        st.markdown("**Status do sistema**")

        def dot(ok: bool, text_ok: str, text_off: str) -> str:
            cls, txt = ("km-dot-ok", text_ok) if ok else ("km-dot-off", text_off)
            return f"<span class='{cls}'>●</span> {txt}"

        st.markdown(
            "<div class='km-side'>"
            + "<br>".join([
                dot(status["db_loaded"], "Banco carregado", "Banco vazio — indexe o acervo"),
                dot(status["retrieval_ready"], "Busca disponível", "Busca indisponível"),
                dot(status["semantic_search"], "Busca semântica ativa", "Busca semântica indisponível"),
                dot(status["mcp_installed"], "Servidor MCP instalado", "Servidor MCP não instalado"),
                dot(status["llm_enabled"], f"IA para redigir: ativa ({_esc(status.get('llm_model') or '')})",
                    f"IA para redigir: {_esc(status.get('llm_status') or 'desligada')}"),
            ])
            + "</div>",
            unsafe_allow_html=True,
        )
        c1, c2 = st.columns(2)
        c1.metric("Documentos", status["documents_indexed"])
        c2.metric("Trechos", status["chunks_indexed"])

        if not status["db_loaded"]:
            if st.button("Indexar acervo agora", use_container_width=True):
                from ..ingestion.pipeline import ingest

                with st.spinner("Lendo e indexando o acervo…"):
                    rep = ingest()
                st.success(f"{rep.active_documents} documentos indexados.")
                st.rerun()

        st.markdown("---")
        st.markdown("**Perguntas para demonstração**")
        st.caption("Clique para preencher o campo de pergunta.")

        def fill(q: str) -> None:
            ss.question = q

        for d in load_demo_questions():
            st.button(d["label"], key=f"demo_{d['label']}", on_click=fill, args=(d["question"],),
                      help=d.get("hint"), use_container_width=True)

        st.markdown("---")
        if st.button("Limpar conversa", use_container_width=True):
            ss.history = []
            st.rerun()

    # ----------------------------------------------------------------- topo
    st.markdown(
        "<div class='km-header'><h1>Kentor Memória</h1>"
        "<p>Memória corporativa para agentes de IA</p></div>",
        unsafe_allow_html=True,
    )
    st.write("")

    col_id, col_info = st.columns([2, 3])
    with col_id:
        names = [o.name for o in identities]
        chosen = st.selectbox(
            "Identidade atual:",
            names,
            index=names.index(ss.identity) if ss.identity in names else 0,
            format_func=lambda n: by_name[n].label,
            key="identity_select",
        )
    if chosen != ss.identity:
        if ss.history:
            ss.history.insert(0, {"kind": "switch", "label": by_name[chosen].label})
        ss.identity = chosen
        st.rerun()
    with col_info:
        cur = by_name[ss.identity]
        st.markdown("<div style='height:1.9rem'></div>", unsafe_allow_html=True)
        st.markdown(
            f"<span class='km-chip'>👤 {_esc(cur.label)}</span>"
            f"<span class='km-chip'>Nível de acesso: {_esc(cur.clearance_label)}</span>",
            unsafe_allow_html=True,
        )

    # sem clear_on_submit: com ele, o preenchimento pelos botões de demo deixa de funcionar
    with st.form("ask_form", border=True):
        question = st.text_input(
            "Pergunta",
            key="question",
            placeholder="Pergunte algo sobre a Kentor...",
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("Perguntar", type="primary")

    if submitted:
        q = (question or "").strip()
        if not q:
            st.warning("Digite uma pergunta.")
        elif not status["db_loaded"]:
            st.warning("O acervo ainda não foi indexado. Use o botão “Indexar acervo agora” na barra lateral.")
        else:
            with st.spinner("Consultando o acervo…"):
                view = backend.ask(q, ss.identity)
            ss.history.insert(0, {"kind": "qa", "identity": ss.identity, "label": by_name[ss.identity].label,
                                  "question": q, "view": view})
            ss._clear_question = True
            st.rerun()

    # ------------------------------------------------------------- conversa
    if not ss.history:
        st.info("Escolha uma identidade, digite uma pergunta e clique em **Perguntar** — "
                "ou use as perguntas de demonstração na barra lateral.")
        return

    st.caption("Conversa desta sessão (mais recente primeiro)")
    for item in ss.history:
        if item["kind"] == "switch":
            st.markdown(f"<div class='km-switch'>— identidade alterada para <b>{_esc(item['label'])}</b> —</div>",
                        unsafe_allow_html=True)
            continue
        with st.chat_message("user", avatar="👤"):
            st.markdown(f"<span class='km-chip'>{_esc(item['label'])}</span> {_esc(item['question'])}",
                        unsafe_allow_html=True)
        with st.chat_message("assistant", avatar="📚"):
            answer_block(item["view"])

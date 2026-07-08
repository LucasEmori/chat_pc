"""AzimeAI — Chat-based Invoice to Purchase Order processor.

Interface portada do design/Web-Prototype (dark B&W, sidebar sessions,
topbar, welcome glyph, inline HITL card, composer).

Reescrita focada em:
- ZERO botões HTML/CSS via st.markdown — todo interativo é st.button nativo.
- Toda widget com key= única (estática ou baseada em id do item iterado).
- Variáveis de processo protegidas em st.session_state (sobrevivem a rerun).

Run: streamlit run app.py
"""
from __future__ import annotations

import io
import os as _os
import re
import uuid
import logging
from typing import Any

import pandas as pd
import streamlit as st

from src.cleaner import limpar_planilha, linhas_para_dataframe_pc
from src.graph import compilar_grafo, estado_inicial
from src.llm import aplicar_sufixo_moi
from src.tamanhos import expandir_lista as _expandir_tamanhos, aplicar_expansao_anel

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("azimeai")

# ============================================================
# Page config + CSS (MUST be before any other st call)
# ============================================================

st.set_page_config(
    page_title="AzimeAI",
    page_icon=None,
    layout="centered",
    initial_sidebar_state="collapsed",
)

with open("style.css", encoding="utf-8") as _f:
    st.markdown(f"<style>{_f.read()}</style>", unsafe_allow_html=True)

# ============================================================
# SVG icons — usados APENAS em markup não-interativo (chips,
# steps, labels de mensagem). Botões usam icon=":material/...:".
# ============================================================

def _load_logo() -> str:
    try:
        with open("design/logo.svg", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return """<svg width="140" height="28" viewBox="0 0 160 32" fill="none" xmlns="http://www.w3.org/2000/svg">
<rect x="1" y="1" width="30" height="30" rx="8" fill="none" stroke="#fafafa" stroke-width="2"/>
<path d="M16 8 L23 24 L9 24 Z" fill="#fafafa"/>
<path d="M16 14 L19.5 21 L12.5 21 Z" fill="#0a0a0a"/>
<text x="42" y="23" font-family="Inter,sans-serif" font-weight="600" font-size="20" fill="#fafafa" letter-spacing="-0.5">AzimeAI</text>
</svg>"""

_LOGO_SVG = _load_logo()

_ICO_CHECK = """<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>"""
_ICO_FILE = """<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>"""
_ICO_SPINNER = """<span class="azime-spinner"></span>"""

# ============================================================
# Message renderers (HTML matching prototype classes — não-interativo)
# ============================================================

def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _label_row(who: str, text: str) -> str:
    if who == "user":
        av = '<span class="av user">EU</span>'
    else:
        av = '<span class="av assistant">A</span>'
    return f'<div class="azime-msg-label">{av}<span>{_esc(text)}</span></div>'


def _msg_user(content_html: str):
    st.markdown(
        f'<div class="azime-msg azime-msg-user">'
        f'{_label_row("user", "Operador")}'
        f'<div>{content_html}</div></div>',
        unsafe_allow_html=True,
    )


def _msg_assistant(content_html: str):
    st.markdown(
        f'<div class="azime-msg azime-msg-assistant">'
        f'{_label_row("assistant", "AzimeAI")}'
        f'<div class="a-body">{content_html}</div></div>',
        unsafe_allow_html=True,
    )


def _msg_error(content: str):
    st.markdown(
        f'<div class="azime-msg-error">{content}</div>',
        unsafe_allow_html=True,
    )


def _msg_success(content: str):
    st.markdown(
        f'<div class="azime-msg-success">'
        f'<div class="azime-ok-line"><span class="okdot">{_ICO_CHECK}</span>'
        f'<span>{content}</span></div></div>',
        unsafe_allow_html=True,
    )


def _msg_warning(content: str):
    st.markdown(f'<div class="azime-msg-warning">{content}</div>',
                unsafe_allow_html=True)


def _msg_loading(text: str = "Processando"):
    st.markdown(
        f'<div class="azime-msg azime-msg-assistant">'
        f'{_label_row("assistant", "AzimeAI")}'
        f'<div class="a-body" style="display:flex;align-items:center;gap:0.5rem">'
        f'{_ICO_SPINNER}<span>{_esc(text)}</span></div></div>',
        unsafe_allow_html=True,
    )


def _file_chip_html(name: str, size: str = "47 KB", ftype: str | None = None) -> str:
    ft = ftype or (name.rsplit(".", 1)[-1].upper() if "." in name else "FILE")
    return (
        f'<div class="azime-file-chip">'
        f'<span class="fic">{_ICO_FILE}</span>'
        f'<span class="fmeta"><span class="fname">{_esc(name)}</span>'
        f'<span class="fsize">{_esc(size)}</span></span>'
        f'<span class="ftype">{_esc(ft)}</span></div>'
    )


def _df_preview(df: pd.DataFrame, total: int | None = None, max_rows: int = 8,
                height: int = 240, wide: bool = False, label: str = "",
                key: str | None = None):
    """Preview de dataframe. key= obrigatório quando chamado em loop
    (múltiplas previews no mesmo run) — evita colisão de widget IDs."""
    n = total if total is not None else len(df)
    wrapper_cls = "azime-df azime-df-pc" if wide else "azime-df"
    sub = label or " · detecção automática de cabeçalho"
    st.markdown(
        f'<div class="{wrapper_cls}"><div class="azime-df-head">'
        f'<span class="count">{n} linhas</span>'
        f'<span> · {_esc(sub)}</span></div></div>',
        unsafe_allow_html=True,
    )
    if key:
        st.dataframe(df.head(max_rows), width="stretch",
                     height=height, key=key)
    else:
        st.dataframe(df.head(max_rows), width="stretch", height=height)
    if len(df) > max_rows:
        st.caption(f"Mostrando {max_rows} de {len(df)} linhas")


def _normalizar_pc(linhas_proc: list[dict]) -> list[dict]:
    """Pós-processamento determinístico do PC antes de exibir/baixar.

    1. Sufixo -MOI no SKU para linhas moissanite (idempotente).
    2. Expansão de tamanhos (anel vira N linhas; corrente/pulseira somam cm;
       brinco/bracelete -> "0").

    Não altera a lista recebida; devolve nova lista.
    """
    if not linhas_proc:
        return linhas_proc
    saida: list[dict] = []
    for linha in linhas_proc:
        nova = dict(linha)
        nova["codigo_fornecedor"] = aplicar_sufixo_moi(
            nova.get("codigo_fornecedor", ""),
            nova.get("tipo_pedra", ""),
        )
        saida.append(nova)
    return _expandir_tamanhos(saida)


def _steps_block_animated(steps: list[str]) -> str:
    """Static steps rendered as all-done."""
    items = "".join(
        f'<div class="azime-step done"><span class="ind"><span class="ck">{_ICO_CHECK}</span></span>'
        f'<span>{_esc(s)}</span></div>'
        for s in steps
    )
    return (
        f'<div class="azime-steps">{items}'
        f'<div class="azime-rail"><i style="width:100%"></i></div></div>'
    )


# ============================================================
# Session state — TODAS as variáveis de processo protegidas
# ============================================================

ss = st.session_state

_DEFAULTS = {
    "app_stage": "init",
    "thread_id": lambda: str(uuid.uuid4()),
    "grafo": None,
    "df_limpo": None,
    "perfil": None,
    "tipo_material": None,
    "nome_arquivo": "",
    "processando": False,
    "concluido": False,
    "ultima_saida": None,
    "ultima_interrupcao": None,
    "chat_historico": [],
    "pc_confirmado": False,
    "erro_processamento": None,
    "ultimo_file_id": None,
    "marca_selecionada": "AL",
    "cod_fornecedor": "",
    "config_marca": "AL",
    "config_forn": "",
    "_stream_queue": [],
    "json_visible": False,
    "llm_provider": "google",
}

for k, v in _DEFAULTS.items():
    if k not in ss:
        ss[k] = v() if callable(v) else v

# Sincroniza provider escolhido na UI com o env — src/llm.py lê via os.getenv.
_os.environ["LLM_PROVIDER"] = ss.llm_provider


# ============================================================
# Core helpers
# ============================================================

def _montar_estado_inicial() -> dict:
    desc = f"Operador={ss.operador if 'operador' in ss else 'N/D'}; Tipo={ss.tipo_material}"
    return estado_inicial(ss.df_limpo, ss.perfil, desc, ss.nome_arquivo)


def _config() -> dict:
    return {"configurable": {"thread_id": ss.thread_id}}


def _cleanup_asyncio_tasks() -> None:
    """Cancel pending asyncio tasks before Streamlit rerun (Windows fix)."""
    try:
        import asyncio
        if hasattr(asyncio, "get_running_loop"):
            loop = asyncio.get_running_loop()
            if loop.is_running():
                pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
                for task in pending:
                    task.cancel()
    except Exception:
        pass  # Best-effort cleanup


def _rerun() -> None:
    """Safe rerun with asyncio cleanup (fixes WinError 10054)."""
    _cleanup_asyncio_tasks()
    st.rerun()


def _rodar_ate_pausa_ou_fim(input_msg: Any = None) -> None:
    cfg = _config()
    grafo = ss.grafo
    total = len(ss.df_limpo) if ss.df_limpo is not None else 0
    st.markdown('<div class="azime-progress-wrap">', unsafe_allow_html=True)
    progress_bar = st.progress(0.01)
    status_text = st.empty()
    try:
        for ev in grafo.stream(input_msg, config=cfg, stream_mode="updates"):
            for node, upd in ev.items():
                if isinstance(upd, dict) and "indice_atual" in upd:
                    p = upd.get("indice_atual", 0)
                    pct = int((p / total) * 100) if total else 0
                    progress_bar.progress(max(pct / 100.0, 0.01))
                    status_text.markdown(
                        f'<div style="font-size:12px;color:var(--meta);'
                        f'font-variant-numeric:tabular-nums;text-align:center">'
                        f"Linha {p}/{total} ({pct}%)</div>",
                        unsafe_allow_html=True,
                    )
    except Exception as e:
        st.markdown('</div>', unsafe_allow_html=True)
        logger.exception("stream falhou")
        try:
            ss.ultima_saida = grafo.get_state(cfg).values
        except Exception:
            pass
        ss.processando = True
        ss.erro_processamento = str(e)
        return

    st.markdown('</div>', unsafe_allow_html=True)
    estado = grafo.get_state(cfg)
    ss.ultima_saida = estado.values
    duvida = estado.values.get("duvida_pendente")
    if duvida:
        ss.ultima_interrupcao = True
        ss.processando = True
        ss.concluido = False
    elif estado.next:
        ss.ultima_interrupcao = estado.tasks or True
        ss.processando = True
        ss.concluido = False
    else:
        ss.ultima_interrupcao = None
        ss.processando = False
        ss.concluido = True


def _reset_session():
    for k in list(ss.keys()):
        del ss[k]


def _enqueue_stream(who: str, content: str, msg_type: str = "text"):
    ss._stream_queue.append({"role": who, "content": content, "type": msg_type})


def _on_provider_change():
    """Callback síncrono do radio de provider.

    Roda quando usuário muda seleção — seta llm_provider e env imediatamente,
    sem lag de 1 frame.
    """
    novo = ss["provider_radio"]
    ss.llm_provider = novo
    _os.environ["LLM_PROVIDER"] = novo


# ============================================================
# Provider options
# ============================================================

_PROVIDER_OPTIONS = {
    "auto": "Automático (NVIDIA → OpenRouter → Google)",
    "nvidia": "NVIDIA NIM",
    "openrouter": "OpenRouter",
    "google": "Google Gemini",
}


# ============================================================
# Header bar — logo top-left, settings popover + new session
# ============================================================

def _render_header():
    col_logo, col_actions = st.columns([2, 1])
    with col_logo:
        st.markdown(_LOGO_SVG, unsafe_allow_html=True)
    with col_actions:
        a1, a2 = st.columns(2)
        with a1:
            with st.popover("Provedor IA", icon=":material/settings:",
                            key="settings_pop"):
                st.radio(
                    "Provedor",
                    list(_PROVIDER_OPTIONS.keys()),
                    format_func=lambda k: _PROVIDER_OPTIONS[k],
                    index=list(_PROVIDER_OPTIONS).index(ss.llm_provider)
                    if ss.llm_provider in _PROVIDER_OPTIONS else 0,
                    label_visibility="collapsed",
                    key="provider_radio",
                    on_change=_on_provider_change,
                )
        with a2:
            if ss.app_stage != "init":
                if st.button("Nova sessão", icon=":material/add:",
                             key="header_new_session", width="stretch"):
                    _reset_session()
                    _rerun()


def _render_topbar():
    crumb_main = (ss.nome_arquivo or "Sessão").rsplit(".", 1)[0]
    stage_label = {
        "init": "",
        "config": " · Configurar invoice",
        "ready": " · Pronto para processar",
        "processing": " · Processando",
        "hitl": " · Aguardando confirmação",
        "done": " · Pedido gerado",
    }.get(ss.app_stage, "")
    st.markdown(
        f'<div class="azime-topbar">'
        f'<div class="crumb"><span>Sessão</span><span class="sep">/</span>'
        f'<span>{_esc(crumb_main)}</span>'
        f'<span class="sub">{_esc(stage_label)}</span></div>'
        f'<span class="spacer"></span>'
        f'<span class="meta-tag"><span class="live"></span> Thread ativa</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


# ============================================================
# Stage: INIT — Welcome screen
# ============================================================

def _render_welcome():
    st.markdown(
        """<div class="azime-welcome">
        <div class="glyph">A</div>
        <h1>Converter uma invoice em pedido de compra.</h1>
        <p>Envie um arquivo <code class="mono">.xlsx</code>
        do fornecedor. Eu limpo a planilha, mapeio o catálogo e gero o pedido
        para o ERP — perguntando só quando houver dúvida.</p>
        </div>""",
        unsafe_allow_html=True,
    )


# ============================================================
# Stage: CONFIG — inline HITL for marca / cod_fornecedor
# ============================================================

def _render_config_form():
    st.markdown(
        '<div class="azime-hitl" id="hitl-config">'
        '<div class="htitle"><span class="q">⚙</span> Configurar invoice</div>'
        '<div class="hsub">Preciso da marca e código de fornecedor antes de processar.</div>',
        unsafe_allow_html=True,
    )
    col1, col2 = st.columns(2)
    with col1:
        st.selectbox(
            "Marca", ["AL", "GR", "NV"],
            index=["AL", "GR", "NV"].index(ss.config_marca)
            if ss.config_marca in ["AL", "GR", "NV"] else 0,
            key="config_marca_sb",
        )
    with col2:
        st.text_input(
            "Código Fornecedor (ERP)", value=ss.config_forn,
            placeholder="ex.: 012432",
            key="config_forn_ti",
        )
    c1, c2 = st.columns([3, 2])
    with c1:
        if st.button("Continuar", type="primary",
                     icon=":material/arrow_forward:",
                     key="config_continue", width="stretch"):
            ss.marca_selecionada = ss.config_marca_sb
            ss.cod_fornecedor = (ss.config_forn_ti or "").strip()
            ss.app_stage = "ready"
            _rerun()
    with c2:
        if st.button("Pular, usar padrão", key="config_skip",
                     icon=":material/skip_next:", width="stretch"):
            ss.marca_selecionada = "AL"
            ss.cod_fornecedor = ""
            ss.config_marca = "AL"
            ss.config_forn = ""
            ss.app_stage = "ready"
            _rerun()
    st.markdown("</div>", unsafe_allow_html=True)


# ============================================================
# Render de uma mensagem do histórico/queue
# ============================================================

def _render_msg(msg: dict, idx: int):
    """Renderiza uma mensagem. idx usado para key única de dataframes em loop."""
    role = msg.get("role", "user")
    content = msg.get("content", "")
    msg_type = msg.get("type", "text")

    if msg_type == "error":
        _msg_error(content)
    elif msg_type == "success":
        _msg_success(content)
    elif msg_type == "warning":
        _msg_warning(content)
    elif msg_type == "loading":
        _msg_loading(content)
    elif msg_type == "preview":
        if ss.df_limpo is not None:
            _df_preview(ss.df_limpo, total=len(ss.df_limpo), max_rows=8,
                        key=f"hist_preview_{idx}")
    elif msg_type == "preview_done":
        if ss.ultima_saida:
            linhas = ss.ultima_saida.get("linhas_processadas") or []
            if linhas:
                norm = _normalizar_pc(linhas)
                _df_preview(linhas_para_dataframe_pc(norm),
                            total=len(norm), max_rows=25, height=520,
                            wide=True, label="Pedido de Compra final",
                            key=f"hist_pcdone_{idx}")
    elif msg_type == "steps":
        st.markdown(content, unsafe_allow_html=True)
    elif role == "user":
        _msg_user(content)
    elif role == "assistant":
        _msg_assistant(content)


# ============================================================
# MAIN FLOW
# ============================================================

# header bar sempre renderizado (logo top-left + settings)
_render_header()

# Controle de revisão de anéis: dict[chave_item, list[dict]|None]
#   None = usuário pulou (não expandir)
#   list  = expansão aprovada (lista de dicts com tamanho/qty)
if "_aneis_revisados" not in ss:
    ss._aneis_revisados = {}

if ss.app_stage == "init":
    _render_welcome()
    up = st.file_uploader(
        "Adicionar invoice", type=["xlsx"],
        label_visibility="visible",
        key="uploader_init",
    )

    if up is not None:
        try:
            file_id = getattr(up, "file_id", up.name)
        except Exception:
            file_id = up.name

        if file_id != ss.ultimo_file_id:
            tmp_path = io.BytesIO(up.getvalue())
            try:
                df_limpo, perfil = limpar_planilha(
                    tmp_path, nome_arquivo=up.name,
                    marca=ss.marca_selecionada,
                    codigo_fornecedor=ss.cod_fornecedor or "012432",
                )
                ss.df_limpo = df_limpo
                ss.perfil = perfil
                ss.tipo_material = perfil.get("tipo_material", "ZIRCONIA")
                ss.nome_arquivo = up.name
                ss.ultimo_file_id = file_id
                ss.chat_historico = []
                ss.grafo = None
                ss.thread_id = str(uuid.uuid4())
                ss.config_marca = ss.marca_selecionada
                ss.config_forn = ss.cod_fornecedor

                _enqueue_stream("user", _file_chip_html(up.name))
                _enqueue_stream("assistant",
                    f"Recebi a invoice. Detectei o cabeçalho, removi linhas de "
                    f"metadata e o rodapé. Encontrei "
                    f"<strong>{len(df_limpo)} itens</strong>, todos com pedra "
                    f"<code class=\"mono\">{ss.tipo_material}</code>.")
                ss._stream_queue.append(
                    {"role": "assistant", "content": "", "type": "preview"})
                _enqueue_stream("assistant",
                    "Preciso confirmar <strong>marca</strong> e "
                    "<strong>código do fornecedor</strong> antes de gerar o "
                    "pedido.")

                ss.app_stage = "config"
                _rerun()
            except Exception as e:
                _msg_error(f"Falha ao processar arquivo: {e}")
                logger.exception("limpar_planilha falhou")

else:
    _render_topbar()
    st.markdown('<div class="azime-chat-area">', unsafe_allow_html=True)

    # 1. Render histórico existente (estático) — key única por índice
    for i, msg in enumerate(ss.chat_historico):
        _render_msg(msg, i)

    # 2. Flush queue: renderiza + move p/ histórico atomicamente
    #    (primeiro move tudo p/ chat_historico, depois render — sem
    #     estado intermediário entre append e clear)
    if ss._stream_queue:
        pending = list(ss._stream_queue)
        ss.chat_historico.extend(pending)
        ss._stream_queue = []
        base = len(ss.chat_historico) - len(pending)
        for j, msg in enumerate(pending):
            _render_msg(msg, base + j)

    # 3. Stage-specific rendering

    if ss.app_stage == "config":
        _render_config_form()

    elif ss.app_stage == "ready":
        cod = (ss.cod_fornecedor or "").strip() or "012432"
        st.markdown(
            f'<div style="font-size:13px;color:var(--muted);padding:8px 0 12px">'
            f'Marca: <strong>{_esc(ss.marca_selecionada)}</strong> &nbsp;·&nbsp; '
            f'Fornecedor: <strong>{_esc(cod)}</strong></div>',
            unsafe_allow_html=True,
        )
        if st.button("Processar invoice", type="primary",
                     icon=":material/upload:",
                     width="stretch", key="process_btn"):
            try:
                if ss.grafo is None:
                    ss.grafo = compilar_grafo()
            except Exception as e:
                _msg_error(f"Erro ao compilar grafo: {e}")
                logger.exception("compilar_grafo falhou")
                _rerun()
            else:
                if ss.perfil:
                    ss.perfil["codigo"] = cod
                    ss.perfil["marca"] = ss.marca_selecionada
                _enqueue_stream("user", "Processar a invoice")
                steps_html = (
                    '<div class="azime-msg azime-msg-assistant">' +
                    _label_row("assistant", "AzimeAI") +
                    '<div class="a-body"><p>Processando com validação estruturada. '
                    'Em caso de incerteza fora do vocabulário controlado, '
                    'eu pergunto aqui mesmo.</p>' +
                    _steps_block_animated([
                        "Limpando planilha e descartando rodapé",
                        "Detectando tipo de pedra por palavra-chave",
                        "Mapeando catálogo CN → PT (categoria, banho, marca)",
                        "Validando saída com schema Pydantic",
                    ]) +
                    '<div style="display:flex;align-items:center;gap:0.5rem;'
                    'margin-top:8px;color:var(--muted)">' +
                    _ICO_SPINNER + '<span>Processando linhas...</span></div>'
                    '</div></div>'
                )
                ss._stream_queue.append(
                    {"role": "assistant", "content": steps_html, "type": "steps"})
                ss.app_stage = "processing"
                _rerun()

    elif ss.app_stage == "processing":
        _msg_loading("Processando linhas via LLM")
        estado0 = _montar_estado_inicial()
        _rodar_ate_pausa_ou_fim(input_msg=estado0)

        if ss.erro_processamento:
            ss.chat_historico.append(
                {"role": "assistant",
                 "content": f"Falha no processamento: {ss.erro_processamento[:200]}",
                 "type": "error"})
            ss.app_stage = "ready"
        elif ss.ultima_interrupcao:
            ss.app_stage = "hitl"
        else:
            total = len(ss.df_limpo)
            feito = len(ss.ultima_saida.get("linhas_processadas") or [])
            _enqueue_stream("assistant",
                f"Pedido de Compra gerado — "
                f"<strong>{feito} de {total} itens</strong> validados, "
                f"vocabulário controlado OK, schema Pydantic aprovado.")
            ss._stream_queue.append(
                {"role": "assistant", "content": "", "type": "preview_done"})
            ss.app_stage = "done"
        st.rerun()

    elif ss.app_stage == "hitl":
        from src.cleaner import COLUNAS_PT, COLUNAS_SAIDA_PC
        estado_vals = ss.ultima_saida or {}
        duvida = estado_vals.get("duvida_pendente")
        if duvida:
            ref_str = duvida.get("codigo_fornecedor", "N/A")
            # id estável p/ key dos widgets HITL — baseado na linha em dúvida.
            # Sanitiza p/ chave válida (alnum + underscore).
            duvida_id = re.sub(r"[^A-Za-z0-9]+", "_",
                               str(ref_str)).strip("_") or "sem_ref"
            motivo = duvida.get("motivo_duvida", "")
            st.markdown(
                f'<div class="azime-hitl" id="hitl-edit">'
                f'<div class="htitle"><span class="q">?</span> Confirmar campo</div>'
                f'<div class="hsub">Linha <strong>{_esc(ref_str)}</strong> · '
                f'<span style="font-size:12px;color:var(--meta)">{_esc(motivo)}</span></div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<p style="font-size:14.5px;color:var(--muted);margin-bottom:12px">'
                'Preciso da sua ajuda para completar esta linha. Confira todos '
                'os campos do Pedido de Compra abaixo e corrija o necessário.</p>',
                unsafe_allow_html=True,
            )
            # Tabela COMPLETA: campos do PC (rótulos PT do ERP).
            _CAMPOS_OCULTOS = {"foto", "dia", "preco_vendas"}
            linhas_tabela = []
            for chave in COLUNAS_SAIDA_PC:
                if chave in _CAMPOS_OCULTOS:
                    continue
                rotulo = COLUNAS_PT.get(chave, chave)
                valor = duvida.get(chave, "")
                linhas_tabela.append({"Campo": rotulo, "Valor": valor})
            st.markdown('<div class="azime-hitl-fields">', unsafe_allow_html=True)
            st.dataframe(pd.DataFrame(linhas_tabela),
                         width="stretch", height=440,
                         hide_index=True,
                         key=f"hitl_table_{duvida_id}")
            st.markdown('</div>', unsafe_allow_html=True)

            _CATS_HITL = ["ANEL", "BRINCO", "COLAR", "CORRENTE", "PULSEIRA",
                          "BRACELETE", "PINGENTE", "ARGOLA", "CONJUNTO", "BROCHE"]
            _BANHOS_HITL = ["RÓDIO", "OURO", "OURO ROSÉ", "PRETO", "AMARELO"]
            with st.form("hitl_form", clear_on_submit=False):
                cA, cB = st.columns(2)
                with cA:
                    st.selectbox(
                        "Categoria", _CATS_HITL,
                        index=_CATS_HITL.index(duvida.get("categoria", "BRINCO"))
                        if duvida.get("categoria") in _CATS_HITL else 1,
                        key=f"hitl_cat_{duvida_id}",
                    )
                with cB:
                    st.text_input(
                        "Código do Fornecedor",
                        value=duvida.get("codigo_fornecedor", ref_str),
                        help="SKU do fornecedor. '-MOI' é adicionado "
                             "automaticamente para moissanite.",
                        key=f"hitl_cod_{duvida_id}",
                    )
                st.text_input("Pedra",
                    value=duvida.get("pedra", "SEM PEDRA"),
                    key=f"hitl_pedra_{duvida_id}")
                st.text_input("Zirconia",
                    value=duvida.get("zirconia", "ZB"),
                    key=f"hitl_zir_{duvida_id}")
                cC, cD = st.columns(2)
                with cC:
                    st.selectbox(
                        "Banho", _BANHOS_HITL,
                        index=_BANHOS_HITL.index(
                            duvida.get("banho", "RÓDIO"))
                        if duvida.get("banho") in _BANHOS_HITL else 0,
                        key=f"hitl_banho_{duvida_id}",
                    )
                with cD:
                    st.selectbox(
                        "Marca", ["AL", "GR", "NV"],
                        index=["AL", "GR", "NV"].index(
                            duvida.get("marca", "AL"))
                        if duvida.get("marca") in ["AL", "GR", "NV"] else 0,
                        key=f"hitl_marca_{duvida_id}",
                    )
                st.text_input(
                    "Tamanho",
                    value=duvida.get("tamanho", "0"),
                    help="Brinco/Bracelete: 0. Corrente/Pulseira: medida em "
                         "cm. Anel: distribuição '#5 - 40 #6 - 35 ...' "
                         "(expandido depois).",
                    key=f"hitl_tam_{duvida_id}",
                )
                st.text_area("Remarks",
                    value=duvida.get("remarks", ""),
                    key=f"hitl_rem_{duvida_id}")
                submit = st.form_submit_button("Continuar",
                                               width="stretch",
                                               type="primary",
                                               icon=":material/check:")
                if submit:
                    from langgraph.types import Command
                    nova_marca = ss[f"hitl_marca_{duvida_id}"]
                    nova_cat = ss[f"hitl_cat_{duvida_id}"]
                    nova_cod = ss[f"hitl_cod_{duvida_id}"]
                    nova_pedra = ss[f"hitl_pedra_{duvida_id}"]
                    nova_zir = ss[f"hitl_zir_{duvida_id}"]
                    nova_banho = ss[f"hitl_banho_{duvida_id}"]
                    nova_tam = ss[f"hitl_tam_{duvida_id}"]
                    nova_rem = ss[f"hitl_rem_{duvida_id}"]
                    # Material segue a marca: NV -> SEMIJOIA, AL/GR -> PRATA
                    novo_material = ("SEMIJOIA" if nova_marca == "NV"
                                     else "PRATA")
                    correcoes = {
                        "categoria": nova_cat,
                        "codigo_fornecedor": nova_cod.strip(),
                        "pedra": nova_pedra,
                        "zirconia": nova_zir,
                        "banho": nova_banho,
                        "marca": nova_marca,
                        "material": novo_material,
                        "tamanho": nova_tam.strip(),
                        "remarks": nova_rem,
                    }
                    resolved_html = (
                        f'<div class="azime-msg azime-msg-assistant">' +
                        _label_row("assistant", "AzimeAI") +
                        '<div class="a-body"><div class="azime-ok-line">'
                        f'<span class="okdot">{_ICO_CHECK}</span>'
                        f'Confirmado: <strong>categoria = {_esc(nova_cat)}</strong>, '
                        f'<strong>banho = {_esc(nova_banho)}</strong>, '
                        f'<strong>tamanho = {_esc(nova_tam.strip())}</strong>. '
                        'Retomando o loop.</div></div></div>'
                    )
                    ss.chat_historico.append(
                        {"role": "user",
                         "content": f"Corrigi a linha {ref_str}"})
                    ss.chat_historico.append(
                        {"role": "assistant", "content": resolved_html})
                    _rodar_ate_pausa_ou_fim(
                        input_msg=Command(resume=correcoes))
                    if ss.concluido:
                        total = len(ss.df_limpo)
                        feito = len(ss.ultima_saida.get(
                            "linhas_processadas") or [])
                        _enqueue_stream("assistant",
                            f"Pedido de Compra gerado — "
                            f"<strong>{feito} de {total} itens</strong> "
                            f"validados.")
                        ss._stream_queue.append({
                            "role": "assistant", "content": "",
                            "type": "preview_done"})
                        ss.app_stage = "done"
                    _rerun()
            st.markdown('</div>', unsafe_allow_html=True)

    elif ss.app_stage == "done":
        if ss.concluido and ss.ultima_saida:
            linhas_proc = ss.ultima_saida.get("linhas_processadas") or []
            if linhas_proc:
                # Normalização determinística (sufixo -MOI + expansão de
                # tamanhos) — aplicada na exibição e no download.
                linhas_norm = _normalizar_pc(linhas_proc)

                # ── Revisão de anéis ──────────────────────────────
                #   Antes de mostrar o preview, verifica se há anéis
                #   pendentes de revisão humana (expandir_linhas em
                #   tamanhos.py marcou _proposta_expansao_anel).
                aneis_pendentes = [
                    l for l in linhas_norm
                    if l.get("_proposta_expansao_anel")
                    and (str(l.get("codigo_fornecedor", "")) + "_" + l.get("tamanho", "")
                         not in ss._aneis_revisados)
                ]
                # Limpa revisões órfãs (itens que sumiram)
                chaves_ativas = {
                    str(l.get("codigo_fornecedor", "")) + "_" + l.get("tamanho", "")
                    for l in linhas_norm
                }
                ss._aneis_revisados = {
                    k: v for k, v in ss._aneis_revisados.items() if k in chaves_ativas
                }

                if aneis_pendentes:
                    st.markdown(
                        '<div style="margin:12px 0 8px;font-size:11px;'
                        'text-transform:uppercase;letter-spacing:0.08em;'
                        'color:var(--meta);font-weight:500">'
                        'REVISÃO DE ANÉIS</div>',
                        unsafe_allow_html=True,
                    )
                    for linha in aneis_pendentes:
                        proposta = linha.get("_proposta_expansao_anel", [])
                        ref = linha.get("codigo_fornecedor", "?")
                        chave = str(ref) + "_" + linha.get("tamanho", "")
                        with st.container():
                            st.markdown(
                                f'<div class="azime-hitl-card">'
                                f'<div style="font-size:12px;font-weight:500;'
                                f'margin-bottom:6px">Anel · {_esc(ref)}</div>'
                                f'<div style="font-size:11px;color:var(--meta);'
                                f'margin-bottom:8px">'
                                f'{_esc(linha.get("motivo_duvida",""))}</div>'
                                f'</div>',
                                unsafe_allow_html=True,
                            )
                            df_proposta = pd.DataFrame(proposta)
                            df_proposta.columns = ["Tamanho", "Quantidade"]
                            st.dataframe(
                                df_proposta, width="stretch", height=180,
                                hide_index=True,
                                key=f"anel_prop_tab_{chave}",
                            )
                            c1, c2 = st.columns([1, 1])
                            with c1:
                                if st.button(
                                    "Confirmar expansão",
                                    key=f"anel_ok_{chave}",
                                    type="primary",
                                    icon=":material/check:",
                                ):
                                    ss._aneis_revisados[chave] = aplicar_expansao_anel(linha)
                                    _rerun()
                            with c2:
                                if st.button(
                                    "Manter fechado (sem expandir)",
                                    key=f"anel_pular_{chave}",
                                ):
                                    ss._aneis_revisados[chave] = None
                                    _rerun()
                    st.markdown("---")
                    st.stop()  # trava — só prossegue quando todos revisados

                # Aplica expansões aprovadas no linhas_norm
                if ss._aneis_revisados:
                    novas_norm: list[dict] = []
                    for l in linhas_norm:
                        ch = str(l.get("codigo_fornecedor", "")) + "_" + l.get("tamanho", "")
                        exp = ss._aneis_revisados.get(ch)
                        if exp is None:
                            # Pulado — remove flag e segue com 1 linha
                            r = dict(l)
                            r.pop("_proposta_expansao_anel", None)
                            r["duvida_pendente"] = False
                            r["motivo_duvida"] = ""
                            novas_norm.append(r)
                        elif exp:
                            # Expandido — substitui pelas N linhas
                            novas_norm.extend(exp)
                        else:
                            novas_norm.append(l)
                    linhas_norm = novas_norm
                ss._ultimas_linhas_expandidas = linhas_norm

                # ── Preview final ─────────────────────────────────
                df_pc = linhas_para_dataframe_pc(linhas_norm)
                has_preview = any(
                    m.get("type") == "preview_done" for m in ss.chat_historico)
                if has_preview:
                    _df_preview(df_pc, total=len(linhas_norm), max_rows=25,
                                height=520, wide=True,
                                label="Pedido de Compra final",
                                key="done_pc_preview")

                n_duvidas = sum(
                    1 for l in linhas_norm if l.get("duvida_pendente"))
                if n_duvidas:
                    _msg_warning(
                        f"{n_duvidas} linha(s) com dúvida pendente. "
                        "Revise antes de confirmar.")

                st.markdown(
                    '<div style="margin-top:14px;margin-bottom:8px;'
                    'font-size:10.5px;text-transform:uppercase;'
                    'letter-spacing:0.08em;color:var(--meta);font-weight:500">'
                    'AJUSTES VIA CHAT</div>',
                    unsafe_allow_html=True,
                )
                with st.form("chat_form", clear_on_submit=True):
                    st.text_area(
                        "Edição",
                        placeholder="Descreva a alteração... "
                        "(ex.: linha 3: quantidade 50, banho OURO)",
                        label_visibility="collapsed",
                        key="chat_edicao",
                    )
                    enviado = st.form_submit_button("Enviar",
                                                    width="stretch",
                                                    icon=":material/send:")
                    if enviado and (ss.chat_edicao or "").strip():
                        from src.llm import aplicar_edicao_pc
                        perfil_chat = ss.perfil or {}
                        editado, resposta = aplicar_edicao_pc(
                            linhas_proc, (ss.chat_edicao or "").strip(),
                            perfil_chat)
                        saida = dict(ss.ultima_saida)
                        saida["linhas_processadas"] = editado
                        ss.ultima_saida = saida
                        ss.pc_confirmado = False
                        _enqueue_stream("user", _esc((ss.chat_edicao or "").strip()))
                        _enqueue_stream("assistant", resposta)
                        _rerun()

                st.space("small")
                col_dl, col_json = st.columns([1, 1])
                with col_dl:
                    if not ss.pc_confirmado:
                        if st.button("Confirmar Pedido",
                                     type="primary", icon=":material/check:",
                                     width="stretch",
                                     key="confirm_pc"):
                            ss.pc_confirmado = True
                            _rerun()
                    else:
                        _msg_success("Pedido de Compra confirmado. Download pronto.")
                        linhas_finais = ss.get("_ultimas_linhas_expandidas") or _normalizar_pc(
                            ss.ultima_saida.get("linhas_processadas") or []
                        )
                        df_final = linhas_para_dataframe_pc(linhas_finais)
                        buf = io.BytesIO()
                        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                            df_final.to_excel(
                                writer, index=False,
                                sheet_name="Pedido de Compra")
                        st.download_button(
                            "Baixar Pedido.xlsx",
                            data=buf.getvalue(),
                            file_name=f"PC_{ss.nome_arquivo or 'saida'}"
                            .replace(".xlsx", "_PROCESSADO.xlsx"),
                            mime="application/vnd.openxmlformats-"
                                 "officedocument.spreadsheetml.sheet",
                            width="stretch",
                            icon=":material/download:",
                            key="download_pc",
                        )
                with col_json:
                    if st.button("Ver JSON estruturado",
                                 width="stretch",
                                 icon=":material/code:",
                                 key="view_json"):
                        ss.json_visible = not ss.json_visible
                        _rerun()

                if ss.json_visible and linhas_norm:
                    import json as _json
                    first = linhas_norm[0] if linhas_norm else {}
                    st.markdown(
                        f'<pre class="azime-mono-block">'
                        f'{_json.dumps(first, indent=2, ensure_ascii=False)}'
                        f'</pre>',
                        unsafe_allow_html=True,
                    )

                sid = (
                    f"PC-{(ss.thread_id or '000000')[:6].upper()} · "
                    f"MARCA {ss.marca_selecionada} · "
                    f"FORN {ss.cod_fornecedor.strip() or '012432'}"
                )
                st.markdown(
                    f'<div class="azime-result-id">{_esc(sid)}</div>',
                    unsafe_allow_html=True,
                )

    if ss.erro_processamento and ss.app_stage != "processing":
        st.markdown(
            f'<div class="azime-msg-error">'
            f'Erro: {_esc(ss.erro_processamento[:300])}</div>',
            unsafe_allow_html=True,
        )
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Tentar novamente", width="stretch", key="resume",
                         icon=":material/refresh:"):
                ss.erro_processamento = None
                ss.app_stage = "processing"
                _rerun()
        with col2:
            if st.button("Cancelar", width="stretch", key="cancel",
                         icon=":material/close:"):
                ss.erro_processamento = None
                ss.grafo = None
                ss.processando = False
                ss.app_stage = "ready"
                _rerun()

    st.markdown('</div>', unsafe_allow_html=True)

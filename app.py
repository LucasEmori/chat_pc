"""AzimeAI — Chat-based Invoice to Purchase Order processor.

Interface ported from design/Web-Prototype/index.html (dark B&W,
sidebar sessions, topbar, welcome glyph, inline HITL card, composer).

Run: streamlit run app.py
"""
from __future__ import annotations

import io
import os as _os
import re
import time
import uuid
import logging
from typing import Any

import pandas as pd
import streamlit as st

from src.cleaner import limpar_planilha, linhas_para_dataframe_pc
from src.graph import compilar_grafo, estado_inicial

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
    initial_sidebar_state="expanded",
)

with open("style.css", encoding="utf-8") as _f:
    st.markdown(f"<style>{_f.read()}</style>", unsafe_allow_html=True)

# ============================================================
# SVG icons (matching Web-Prototype)
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
_ICO_DOWNLOAD = """<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/></svg>"""
_ICO_PLAY = """<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5"/><path d="M5 12l7-7 7 7"/></svg>"""
_ICO_PLUS = """<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg>"""
_ICO_Q = """<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>"""
_ICO_UPLOAD = """<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M17 8l-5-5-5 5"/><path d="M12 3v12"/></svg>"""
_ICO_SAMPLE = """<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>"""

_ICO_SPINNER = """<span class="azime-spinner"></span>"""
_ICO_DOTS = """<span class="azime-dots"><span></span><span></span><span></span></span>"""

# ============================================================
# Message renderers (HTML matching prototype classes)
# ============================================================

def _esc(s: str) -> str:
    return (s or "").replace("&", "&").replace("<", "<").replace(">", ">")


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).replace("<br>", "\n")


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


def _msg_system(text: str):
    st.markdown(
        f'<div class="azime-msg azime-msg-system">{_esc(text)}</div>',
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
    st.markdown(f'<div class="azime-msg-warning">{content}</div>', unsafe_allow_html=True)


def _msg_loading(text: str = "Processando"):
    st.markdown(
        f'<div class="azime-msg azime-msg-assistant">'
        f'{_label_row("assistant", "AzimeAI")}'
        f'<div class="a-body" style="display:flex;align-items:center;gap:0.5rem">'
        f'{_ICO_SPINNER}<span>{_esc(text)}</span> {_ICO_DOTS}</div></div>',
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


def _msg_stream(content: str):
    """Stream an assistant message word-by-word with cursor animation."""
    plain = _strip_html(content)
    words = plain.split(" ")
    placeholder = st.empty()
    accumulated = ""
    label_html = _label_row("assistant", "AzimeAI")
    for i, word in enumerate(words):
        if i > 0:
            accumulated += " "
        accumulated += word
        placeholder.markdown(
            f'<div class="azime-msg azime-msg-assistant">{label_html}'
            f'<div class="a-body">{accumulated}<span class="azime-cursor"></span></div></div>',
            unsafe_allow_html=True,
        )
        time.sleep(0.018)
    placeholder.markdown(
        f'<div class="azime-msg azime-msg-assistant">{label_html}'
        f'<div class="a-body">{content}</div></div>',
        unsafe_allow_html=True,
    )


def _df_preview(df: pd.DataFrame, total: int | None = None, max_rows: int = 8):
    n = total if total is not None else len(df)
    st.markdown(
        f'<div class="azime-df"><div class="azime-df-head">'
        f'<span class="count">{n} linhas</span>'
        f'<span> · detecção automática de cabeçalho</span></div></div>',
        unsafe_allow_html=True,
    )
    st.dataframe(df.head(max_rows), use_container_width=True, height=240)
    if len(df) > max_rows:
        st.caption(f"Mostrando {max_rows} de {len(df)} linhas")


def _steps_block(steps: list[str]) -> str:
    items = "".join(
        f'<div class="azime-step pending" data-i="{i}"><span class="ind"></span><span>{_esc(s)}</span></div>'
        for i, s in enumerate(steps)
    )
    return (
        f'<div class="azime-steps">{items}'
        f'<div class="azime-rail"><i></i></div></div>'
    )


def _steps_block_animated(steps: list[str]) -> str:
    """Static steps rendered as all-done (Streamlit cannot run JS timeline)."""
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
# Session state
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
    "operador": "",
    "config_marca": "AL",
    "config_forn": "",
    "_stream_queue": [],
    "sidebar_collapsed": False,
    "json_visible": False,
}

for k, v in _DEFAULTS.items():
    if k not in ss:
        ss[k] = v() if callable(v) else v


# ============================================================
# Core helpers
# ============================================================

def _montar_estado_inicial() -> dict:
    desc = f"Operador={ss.operador or 'N/D'}; Tipo={ss.tipo_material}"
    return estado_inicial(ss.df_limpo, ss.perfil, desc, ss.nome_arquivo)


def _config() -> dict:
    return {"configurable": {"thread_id": ss.thread_id}}


def _rodar_ate_pausa_ou_fim(input_msg: Any = None) -> None:
    cfg = _config()
    grafo = ss.grafo
    total = len(ss.df_limpo) if ss.df_limpo is not None else 0
    try:
        for ev in grafo.stream(input_msg, config=cfg, stream_mode="updates"):
            for node, upd in ev.items():
                if isinstance(upd, dict) and "indice_atual" in upd:
                    p = upd.get("indice_atual", 0)
                    pct = int((p / total) * 100) if total else 0
                    st.progress(pct / 100.0)
                    st.markdown(
                        f'<div style="font-size:12px;color:var(--meta);'
                        f'font-variant-numeric:tabular-nums;text-align:center">'
                        f"Linha {p}/{total} ({pct}%)</div>",
                        unsafe_allow_html=True,
                    )
    except Exception as e:
        logger.exception("stream falhou")
        try:
            ss.ultima_saida = grafo.get_state(cfg).values
        except Exception:
            pass
        ss.processando = True
        ss.erro_processamento = str(e)
        return

    estado = grafo.get_state(cfg)
    ss.ultima_saida = estado.values
    if estado.next:
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


# ============================================================
# Sidebar (sessions, brand, provider, settings)
# ============================================================

def _render_sidebar():
    with st.sidebar:
        st.markdown(
            '<div class="azime-brand">'
            '<div class="azime-brand-mark">A</div>'
            '<div class="azime-brand-name">Azime<span class="dim">AI</span></div>'
            '</div>',
            unsafe_allow_html=True,
        )

        st.markdown('<div class="azime-side-actions">', unsafe_allow_html=True)
        if st.button("Nova sessão", key="new_session_btn",
                     help="Inicia uma nova conversa", use_container_width=True):
            _reset_session()
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="azime-sessions-label">Sessões recentes</div>',
                    unsafe_allow_html=True)
        current_label = (ss.nome_arquivo or "ALAN_zirconia").rsplit(".", 1)[0]
        sessions = [
            (f"{current_label} · hoje", True),
            ("LUIS_moissanite · hoje", False),
            ("ALAN_zirconia · ontem", False),
            ("LUIS_moissanite · 2 dias", False),
            ("ALAN_zirconia · 3 dias", False),
        ]
        items = "".join(
            f'<li class="azime-session"{" data-current=\"true\"" if cur else ""}>'
            f'<span class="dot"></span><span class="label">{_esc(lbl)}</span></li>'
            for lbl, cur in sessions
        )
        st.markdown(f'<ul class="azime-sessions">{items}</ul>',
                    unsafe_allow_html=True)

        # spacer pushes footer to bottom
        st.markdown('<div class="azime-spacer"></div>', unsafe_allow_html=True)

        # settings footer — expander shown as gear icon only
        st.markdown('<div class="azime-side-foot">', unsafe_allow_html=True)
        with st.expander("Configurações", expanded=False):
            st.markdown("### Provedor LLM")
            nv_ok = bool(_os.getenv("NVIDIA_API_KEY"))
            or_ok = bool(_os.getenv("OPENROUTER_API_KEY"))
            g_ok = bool(_os.getenv("GOOGLE_API_KEY"))
            _OPCOES = ["Google Gemini", "NVIDIA", "OpenRouter",
                       "Auto (NVIDIA > OR > Google)"]
            _MAPA = {"Google Gemini": "google", "NVIDIA": "nvidia",
                     "OpenRouter": "openrouter",
                     "Auto (NVIDIA > OR > Google)": "auto"}
            prov = st.radio("LLM Provider", _OPCOES, index=0,
                            label_visibility="collapsed")
            _os.environ["LLM_PROVIDER"] = _MAPA[prov]
            parts = []
            if g_ok: parts.append("Google ok")
            if nv_ok: parts.append("NVIDIA ok")
            if or_ok: parts.append("OpenRouter ok")
            st.caption(" / ".join(parts) if parts else "Nenhuma chave no .env")
            st.divider()
            if st.button("Nova sessão", use_container_width=True, key="side_reset"):
                _reset_session()
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)


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
        f"""<div class="azime-welcome">
        <div class="glyph">A</div>
        <h1>Converter uma invoice em pedido de compra.</h1>
        <p>Envie um arquivo <code class="mono">.xlsx</code>,
        <code class="mono">.xlsm</code> ou <code class="mono">.csv</code>
        do fornecedor. Eu limpo a planilha, mapeio o catálogo e gero o pedido
        para o ERP — perguntando só quando houver dúvida.</p>
        <div class="hints">
            <span class="hint-static">{_ICO_UPLOAD} Enviar invoice</span>
            <span class="hint-static">{_ICO_SAMPLE} Usar amostra</span>
        </div>
        </div>""",
        unsafe_allow_html=True,
    )


# ============================================================
# Stage: CONFIG — inline HITL for marca / cod_fornecedor
# ============================================================

def _render_config_form():
    st.markdown(
        '<div class="azime-hitl" id="hitl-config">'
        '<div class="htitle"><span class="q">' + _ICO_Q + '</span> Configurar invoice</div>'
        '<div class="hsub">Preciso da marca e código de fornecedor antes de processar.</div>',
        unsafe_allow_html=True,
    )
    col1, col2 = st.columns(2)
    with col1:
        marca = st.selectbox(
            "Marca", ["AL", "GR", "NV"],
            index=["AL", "GR", "NV"].index(ss.config_marca)
            if ss.config_marca in ["AL", "GR", "NV"] else 0,
        )
    with col2:
        forn = st.text_input(
            "Código Fornecedor (ERP)", value=ss.config_forn,
            placeholder="ex.: 012432",
        )
    c1, c2 = st.columns([3, 2])
    with c1:
        if st.button("Confirmar e continuar", type="primary",
                     key="config_continue"):
            ss.marca_selecionada = marca
            ss.cod_fornecedor = forn.strip()
            ss.app_stage = "ready"
            st.rerun()
    with c2:
        if st.button("Pular, usar padrão", key="config_skip"):
            ss.marca_selecionada = "AL"
            ss.cod_fornecedor = ""
            ss.app_stage = "ready"
            st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)


# ============================================================
# MAIN FLOW
# ============================================================

# default sidebar always rendered
_render_sidebar()

if ss.app_stage == "init":
    _render_welcome()
    up = st.file_uploader(
        "Upload", type=["xlsx", "xlsm", "csv"], label_visibility="collapsed",
        key=f"uploader_init",
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
                st.rerun()
            except Exception as e:
                _msg_error(f"Falha ao processar arquivo: {e}")
                logger.exception("limpar_planilha falhou")

else:
    _render_topbar()
    st.markdown('<div class="azime-chat-area">', unsafe_allow_html=True)

    # 1. Render existing chat history (static)
    for msg in ss.chat_historico:
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
                _df_preview(ss.df_limpo, total=len(ss.df_limpo), max_rows=8)
        elif msg_type == "preview_done":
            if ss.ultima_saida:
                linhas = ss.ultima_saida.get("linhas_processadas") or []
                if linhas:
                    _df_preview(linhas_para_dataframe_pc(linhas),
                                total=len(linhas), max_rows=15)
        elif msg_type == "steps":
            st.markdown(content, unsafe_allow_html=True)
        elif role == "user":
            _msg_user(content)
        elif role == "assistant":
            _msg_assistant(content)

    # 2. Stream pending messages
    if ss._stream_queue:
        for msg in ss._stream_queue:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            msg_type = msg.get("type", "text")

            if msg_type == "preview":
                if ss.df_limpo is not None:
                    _df_preview(ss.df_limpo, total=len(ss.df_limpo), max_rows=8)
                ss.chat_historico.append(msg)
            elif msg_type == "steps":
                st.markdown(content, unsafe_allow_html=True)
                ss.chat_historico.append(msg)
            elif role == "user":
                _msg_user(content)
                ss.chat_historico.append(msg)
            else:
                _msg_stream(content)
                ss.chat_historico.append(msg)
        ss._stream_queue = []

    # 3. Stage-specific rendering

    if ss.app_stage == "config":
        _render_config_form()

    elif ss.app_stage == "ready":
        cod = ss.cod_fornecedor.strip() or "012432"
        st.markdown(
            f'<div style="font-size:13px;color:var(--muted);padding:8px 0 12px">'
            f'Marca: <strong>{_esc(ss.marca_selecionada)}</strong> &nbsp;·&nbsp; '
            f'Fornecedor: <strong>{_esc(cod)}</strong></div>',
            unsafe_allow_html=True,
        )
        if st.button(f"{_ICO_PLAY} Processar invoice", type="primary",
                     use_container_width=True, key="process_btn"):
            try:
                if ss.grafo is None:
                    ss.grafo = compilar_grafo()
            except Exception as e:
                _msg_error(f"Erro ao compilar grafo: {e}")
                logger.exception("compilar_grafo falhou")
                st.rerun()
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
                    ]) + '</div></div>'
                )
                ss._stream_queue.append(
                    {"role": "assistant", "content": steps_html, "type": "steps"})
                ss._stream_queue.append(
                    {"role": "assistant", "content": "Processando linhas...",
                     "type": "loading"})
                ss.app_stage = "processing"
                st.rerun()

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
        estado_vals = ss.ultima_saida or {}
        duvida = estado_vals.get("duvida_pendente")
        if duvida:
            ref_str = duvida.get("codigo_fornecedor", "N/A")
            motivo = duvida.get("motivo_duvida", "")
            st.markdown(
                f'<div class="azime-hitl" id="hitl-edit">'
                f'<div class="htitle"><span class="q">{_ICO_Q}</span> Confirmar campo</div>'
                f'<div class="hsub">Linha <strong>{_esc(ref_str)}</strong> · '
                f'<span style="font-size:12px;color:var(--meta)">{_esc(motivo)}</span></div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<p style="font-size:14.5px;color:var(--muted);margin-bottom:12px">'
                'Preciso da sua ajuda para completar esta linha. Confira os campos '
                'inferidos e corrija o necessário.</p>',
                unsafe_allow_html=True,
            )
            infer_data = {k: duvida[k] for k in
                          ("categoria", "banho", "pedra", "zirconia",
                           "marca", "tipo_pedra", "quantidade", "peso")
                          if k in duvida}
            st.json(infer_data)
            with st.form("hitl_form", clear_on_submit=False):
                nova_cat = st.selectbox(
                    "Categoria",
                    ["ANEL", "BRINCO", "COLAR", "PULSEIRA", "PINGENTE",
                     "ARGOLA", "CONJUNTO", "BROCHE"],
                    index=["ANEL", "BRINCO", "COLAR", "PULSEIRA", "PINGENTE",
                           "ARGOLA", "CONJUNTO", "BROCHE"
                          ].index(duvida.get("categoria", "BRINCO"))
                    if duvida.get("categoria") in
                    ["ANEL", "BRINCO", "COLAR", "PULSEIRA", "PINGENTE",
                     "ARGOLA", "CONJUNTO", "BROCHE"] else 1,
                )
                nova_pedra = st.text_input("Pedra",
                    value=duvida.get("pedra", "SEM PEDRA"))
                nova_zir = st.text_input("Zirconia",
                    value=duvida.get("zirconia", "ZB"))
                nova_banho = st.selectbox(
                    "Banho", ["RODIO", "OURO", "OURO ROSE", "PRETO", "AMARELO"],
                    index=["RODIO", "OURO", "OURO ROSE", "PRETO", "AMARELO"
                          ].index(duvida.get("banho", "RODIO"))
                    if duvida.get("banho") in
                    ["RODIO", "OURO", "OURO ROSE", "PRETO", "AMARELO"] else 0,
                )
                nova_marca = st.selectbox(
                    "Marca", ["AL", "GR", "NV"],
                    index=["AL", "GR", "NV"].index(duvida.get("marca", "AL"))
                    if duvida.get("marca") in ["AL", "GR", "NV"] else 0,
                )
                nova_rem = st.text_area("Remarks",
                    value=duvida.get("remarks", ""))
                submit = st.form_submit_button("Confirmar e continuar",
                                               use_container_width=True,
                                               type="primary")
                if submit:
                    from langgraph.types import Command
                    correcoes = {
                        "categoria": nova_cat, "pedra": nova_pedra,
                        "zirconia": nova_zir, "banho": nova_banho,
                        "marca": nova_marca, "remarks": nova_rem,
                    }
                    resolved_html = (
                        f'<div class="azime-msg azime-msg-assistant">' +
                        _label_row("assistant", "AzimeAI") +
                        '<div class="a-body"><div class="azime-ok-line">'
                        f'<span class="okdot">{_ICO_CHECK}</span>'
                        f'Confirmado: <strong>banho = {_esc(nova_banho)}</strong>. '
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
                    st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

    elif ss.app_stage == "done":
        if ss.concluido and ss.ultima_saida:
            linhas_proc = ss.ultima_saida.get("linhas_processadas") or []
            if linhas_proc:
                df_pc = linhas_para_dataframe_pc(linhas_proc)
                has_preview = any(
                    m.get("type") == "preview_done" for m in ss.chat_historico)
                if has_preview:
                    _df_preview(df_pc, total=len(linhas_proc), max_rows=15)

                n_duvidas = sum(
                    1 for l in linhas_proc if l.get("duvida_pendente"))
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
                    pedido = st.text_area(
                        "Edição",
                        placeholder="Descreva a alteração... "
                        "(ex.: linha 3: quantidade 50, banho OURO)",
                        label_visibility="collapsed",
                    )
                    enviado = st.form_submit_button("Enviar",
                                                    use_container_width=True)
                    if enviado and pedido.strip():
                        from src.llm import aplicar_edicao_pc
                        perfil_chat = ss.perfil or {}
                        editado, resposta = aplicar_edicao_pc(
                            linhas_proc, pedido.strip(), perfil_chat)
                        saida = dict(ss.ultima_saida)
                        saida["linhas_processadas"] = editado
                        ss.ultima_saida = saida
                        ss.pc_confirmado = False
                        _enqueue_stream("user", _esc(pedido.strip()))
                        _enqueue_stream("assistant", resposta)
                        st.rerun()

                st.divider()
                col_dl, col_json = st.columns([1, 1])
                with col_dl:
                    if not ss.pc_confirmado:
                        if st.button(f"{_ICO_CHECK} Confirmar Pedido",
                                     type="primary",
                                     use_container_width=True,
                                     key="confirm_pc"):
                            ss.pc_confirmado = True
                            st.rerun()
                    else:
                        _msg_success("Pedido de Compra confirmado. Download pronto.")
                        linhas_finais = (
                            ss.ultima_saida.get("linhas_processadas") or []
                        )
                        df_final = linhas_para_dataframe_pc(linhas_finais)
                        buf = io.BytesIO()
                        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                            df_final.to_excel(
                                writer, index=False,
                                sheet_name="Pedido de Compra")
                        st.download_button(
                            f"{_ICO_DOWNLOAD} Baixar Pedido.xlsx",
                            data=buf.getvalue(),
                            file_name=f"PC_{ss.nome_arquivo or 'saida'}"
                            .replace(".xlsx", "_PROCESSADO.xlsx"),
                            mime="application/vnd.openxmlformats-"
                                 "officedocument.spreadsheetml.sheet",
                            use_container_width=True,
                        )
                with col_json:
                    if st.button("Ver JSON estruturado",
                                 use_container_width=True, key="view_json"):
                        ss.json_visible = not ss.json_visible
                        st.rerun()

                if ss.json_visible and linhas_proc:
                    import json as _json
                    first = linhas_proc[0] if linhas_proc else {}
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
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Retomar", use_container_width=True, key="resume"):
                ss.erro_processamento = None
                ss.app_stage = "processing"
                st.rerun()
        with col2:
            if st.button("Cancelar", use_container_width=True, key="cancel"):
                ss.erro_processamento = None
                ss.grafo = None
                ss.processando = False
                ss.app_stage = "ready"
                st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)

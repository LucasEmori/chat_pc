"""Endpoints HTTP da AzimeAI.

Mapeamento 1:1 com o fluxo do app.py (Streamlit), exposto como REST + SSE.
Toda a lógica de domínio é delegada a `src/` — aqui só há胶水 HTTP.

Concorrência:
- `grafo.stream(...)` é síncrono e bloqueante (chama LLM). Para não travar o
  event loop do FastAPI durante uma invoice longa, o processamento roda num
  worker de threadpool e publica eventos numa `asyncio.Queue`; o generator
  async do SSE consome essa fila. Assim N sessões processam em paralelo sem
  se bloquearem e o endpoint permanece responsivo.
- Mutações de estado são serializadas pelo lock da sessão.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import tempfile
import threading
from typing import Any, Optional

import pandas as pd
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.cleaner import (
    COLUNAS_PT,
    COLUNAS_SAIDA_PC,
    limpar_planilha,
    linhas_para_dataframe_pc,
)
from src.graph import compilar_grafo, estado_inicial
from src.llm import aplicar_edicao_pc, aplicar_sufixo_moi
from src.tamanhos import aplicar_expansao_anel, expandir_lista as _expandir_tamanhos

from .sessions import SessionState, sessions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# Categorias/banhos usados nos forms HITL (espelho de app.py).
_CATS_HITL = ["ANEL", "BRINCO", "COLAR", "CORRENTE", "PULSEIRA",
              "BRACELETE", "PINGENTE", "ARGOLA", "CONJUNTO", "BROCHE"]
_BANHOS_HITL = ["RÓDIO", "OURO", "OURO ROSÉ", "PRETO", "AMARELO"]
_CAMPOS_OCULTOS = {"foto", "dia", "preco_vendas"}


# ============================================================
# Schemas de request/response
# ============================================================

class SessionCreated(BaseModel):
    session_id: str
    thread_id: str
    stage: str


class ConfigureIn(BaseModel):
    marca: str = "AL"
    cod_fornecedor: str = ""
    # Cotação CNY→USD. Obrigatório quando perfil['moeda']=='CNY'; sem efeito em USD.
    fator_cny: Optional[float] = None


class HitlResolveIn(BaseModel):
    categoria: str
    codigo_fornecedor: str
    pedra: str
    zirconia: str
    banho: str
    marca: str
    tamanho: str
    remarks: str = ""


class PcEditIn(BaseModel):
    mensagem: str


class AnelDecisionIn(BaseModel):
    chave: str           # "codigo_tamanho"
    aprovar: bool        # True = expandir; False = manter fechado


# ============================================================
# Helpers
# ============================================================

def _normalizar_pc(linhas_proc: list[dict]) -> list[dict]:
    """Pós-processamento determinístico do PC (sufixo -MOI + expansão).

    Espelho de `_normalizar_pc` em app.py. Idempotente; não muta a entrada.
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


def _linhas_to_records(linhas: list[dict]) -> list[dict]:
    """Converte linhas normalizadas em records PT (ERP) para o frontend."""
    df = linhas_para_dataframe_pc(linhas)
    return json.loads(df.to_json(orient="records", force_ascii=False))


def _df_preview_records(df: pd.DataFrame, max_rows: int = 8) -> list[dict]:
    return json.loads(df.head(max_rows).to_json(orient="records", force_ascii=False))


def _perfil_desc(st: SessionState) -> str:
    return f"Operador=N/D; Tipo={st.tipo_material}"





def _sanitize_key(ref: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(ref)).strip("_") or "sem_ref"


def _snapshot_pc(st: SessionState) -> dict:
    """Monta o payload final do PC (linhas normalizadas + records PT)."""
    linhas_proc = (st.ultima_saida or {}).get("linhas_processadas") or []
    if not linhas_proc:
        return {"linhas": [], "records": [], "total": 0,
                "nome_arquivo": st.nome_arquivo}
    norm = _normalizar_pc(linhas_proc)
    return {
        "linhas": norm,
        "records": _linhas_to_records(norm),
        "total": len(norm),
        "nome_arquivo": st.nome_arquivo,
    }


def _sse(event_type: str, data: dict) -> str:
    """Formata uma mensagem SSE: `data: {...}\n\n`."""
    payload = {"type": event_type, **data}
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def _chat_msg(who: str, content: str, msg_type: str = "text") -> dict:
    return {"role": who, "content": content, "type": msg_type}


# ============================================================
# Rotas: sessão
# ============================================================

@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/session", response_model=SessionCreated)
def create_session() -> SessionCreated:
    st = sessions.criar()
    return SessionCreated(
        session_id=st.session_id, thread_id=st.thread_id, stage=st.stage
    )


@router.post("/reset", response_model=SessionCreated)
def reset_session(session_id: str) -> SessionCreated:
    try:
        st = sessions.require(session_id)
    except KeyError:
        raise HTTPException(404, "Sessão não encontrada")
    st = sessions.reset(session_id)
    return SessionCreated(
        session_id=st.session_id, thread_id=st.thread_id, stage=st.stage
    )


# ============================================================
# Upload + limpeza da invoice
# ============================================================

@router.post("/upload")
async def upload(
    session_id: str,
    file: UploadFile = File(...),
) -> dict:
    """Recebe .xlsx/.csv, salva em temp, roda `limpar_planilha`, prepara config.

    Espelho do bloco `if up is not None` em app.py.
    """
    try:
        st = sessions.require(session_id)
    except KeyError:
        raise HTTPException(404, "Sessão não encontrada")

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Arquivo vazio")

    nome = file.filename or "invoice.xlsx"
    sufixo = ".csv" if nome.lower().endswith(".csv") else ".xlsx"

    with sessions.lock_for(session_id):
        # limpar_planilha exige path de arquivo — persistimos os bytes em temp.
        with tempfile.NamedTemporaryFile(suffix=sufixo, delete=False) as tmp:
            tmp.write(raw)
            tmp_path = tmp.name
        try:
            df_limpo, perfil = limpar_planilha(
                tmp_path, nome_arquivo=nome,
                marca=st.marca, codigo_fornecedor=st.cod_fornecedor or "012432",
            )
        except Exception as e:
            logger.exception("limpar_planilha falhou")
            raise HTTPException(422, f"Falha ao processar arquivo: {e}")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        st.df_limpo = df_limpo
        st.perfil = perfil
        st.tipo_material = perfil.get("tipo_material", "ZIRCONIA")
        st.nome_arquivo = nome
        st.grafo = None
        st.thread_id = st.thread_id  # mantém; novo upload invalida grafo antigo
        st.chat_historico = []
        st.ultima_saida = None
        st.pc_confirmado = False
        st.erro_processamento = None
        st.marca = st.marca or "AL"
        st.stage = "config"
        st.touch()

    return {
        "stage": st.stage,
        "nome_arquivo": nome,
        "tipo_material": st.tipo_material,
        "n_itens": int(len(df_limpo)),
        "preview": _df_preview_records(df_limpo),
        "perfil": perfil,
    }


# ============================================================
# Configurar marca + fornecedor
# ============================================================

@router.post("/configure")
def configure(payload: ConfigureIn, session_id: str) -> dict:
    try:
        st = sessions.require(session_id)
    except KeyError:
        raise HTTPException(404, "Sessão não encontrada")

    with sessions.lock_for(session_id):
        st.marca = payload.marca
        st.cod_fornecedor = (payload.cod_fornecedor or "").strip()
        # CNY: user confirma/sobrescreve fator sugerido pelo cleaner.
        # Se divergente, re-aplica conversão no df_limpo já carregado.
        if payload.fator_cny is not None and payload.fator_cny > 0:
            if st.perfil is None:
                st.perfil = {}
            fator_antigo = st.perfil.get("fator_cny_sugerido") or st.perfil.get("fator_cny")
            st.perfil["fator_cny"] = payload.fator_cny
            st.perfil["moeda"] = "CNY"
            if (payload.fator_cny != fator_antigo
                    and st.df_limpo is not None
                    and fator_antigo is not None):
                # recalcular: precisa re-dividir amount_cny pelo novo fator.
                # desfaz colunas USD derivadas e re-aplica conversão.
                from src.cleaner import _aplicar_conversao_cny
                # restaura amount_cny/silver_price_cny (preservados pelo cleaner).
                st.df_limpo = _aplicar_conversao_cny(st.df_limpo, payload.fator_cny)
                logger.info("Fator CNY re-aplicado: %s -> %s",
                            fator_antigo, payload.fator_cny)
        st.stage = "ready"
        st.touch()
    return {
        "stage": st.stage, "marca": st.marca,
        "cod_fornecedor": st.cod_fornecedor,
        "moeda": (st.perfil or {}).get("moeda", "USD"),
        "fator_cny": (st.perfil or {}).get("fator_cny"),
    }


# ============================================================
# Processamento (SSE) — coração concorrente
# ============================================================

@router.get("/process/stream")
async def process_stream(session_id: str) -> StreamingResponse:
    """Inicia/retoma o processamento do grafo e stream via SSE.

    Publica eventos: `progress` (indice/total), `hitl` (duvida_pendente),
    `done` (PC final), `error`. O trabalho síncrono roda em threadpool;
    a comunicação thread→async é feita por uma fila.
    """
    try:
        st = sessions.require(session_id)
    except KeyError:
        raise HTTPException(404, "Sessão não encontrada")

    queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def _worker() -> None:
        """Roda em threadpool: compila grafo (se preciso), itera stream,
        publica eventos SSE na fila e atualiza o estado da sessão."""
        try:
            with sessions.lock_for(session_id):
                if st.grafo is None:
                    st.grafo = compilar_grafo()
                if st.perfil:
                    st.perfil["codigo"] = st.cod_fornecedor or "012432"
                    st.perfil["marca"] = st.marca
                estado = estado_inicial(
                    st.df_limpo, st.perfil, _perfil_desc(st), st.nome_arquivo
                )
                total = len(st.df_limpo) if st.df_limpo is not None else 0
                st.stage = "processing"
                st.touch()

            cfg = st.config
            grafo = st.grafo
            for ev in grafo.stream(estado, config=cfg, stream_mode="updates"):
                for _node, upd in ev.items():
                    if isinstance(upd, dict) and "indice_atual" in upd:
                        p = upd.get("indice_atual", 0)
                        loop.call_soon_threadsafe(
                            queue.put_nowait,
                            _sse("progress", {"at": p, "total": total}),
                        )

            # Stream terminou: inspecionar estado final.
            estado_final = grafo.get_state(cfg)
            vals = estado_final.values or {}
            st.ultima_saida = dict(vals)
            duvida = vals.get("duvida_pendente")
            if duvida:
                st.ultima_interrupcao = True
                st.stage = "hitl"
                st.touch()
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    _sse("hitl", {"duvida": duvida}),
                )
            else:
                st.ultima_interrupcao = None
                st.stage = "done"
                st.touch()
                snap = _snapshot_pc(st)
                feito = len(snap["records"])
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    _sse("done", {
                        "feito": feito, "total": total,
                        "records": snap["records"],
                        "linhas": snap["linhas"],
                    }),
                )
        except Exception as e:  # noqa: BLE001
            logger.exception("process stream falhou")
            try:
                st.erro_processamento = str(e)
                st.stage = "ready"
            except Exception:
                pass
            loop.call_soon_threadsafe(
                queue.put_nowait,
                _sse("error", {"msg": str(e)[:400]}),
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)  # sinal de fim

    async def _event_gen():
        # Agenda o worker no threadpool padrão do asyncio.
        loop.run_in_executor(None, _worker)
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        _event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # desativa buffering em proxies
            "Connection": "keep-alive",
        },
    )


# ============================================================
# HITL — resolver dúvida via Command(resume=...)
# ============================================================

@router.post("/hitl/resolve")
async def hitl_resolve(payload: HitlResolveIn, session_id: str) -> dict:
    """Submete correção humana; retoma o grafo e retorna novo snapshot.

    Reexecuta o stream pós-resume; publica `done`/`hitl`/`error`.
    Equivalente ao submit do form HITL em app.py.
    """
    try:
        st = sessions.require(session_id)
    except KeyError:
        raise HTTPException(404, "Sessão não encontrada")

    from langgraph.types import Command

    novo_material = "SEMIJOIA" if payload.marca == "NV" else "PRATA"
    correcoes = {
        "categoria": payload.categoria,
        "codigo_fornecedor": payload.codigo_fornecedor.strip(),
        "pedra": payload.pedra,
        "zirconia": payload.zirconia,
        "banho": payload.banho,
        "marca": payload.marca,
        "material": novo_material,
        "tamanho": payload.tamanho.strip(),
        "remarks": payload.remarks,
    }

    with sessions.lock_for(session_id):
        if st.grafo is None:
            raise HTTPException(409, "Grafo não inicializado")
        cfg = st.config
        grafo = st.grafo
        total = len(st.df_limpo) if st.df_limpo is not None else 0

        # Retoma o grafo a partir do interrupt.
        try:
            for _ev in grafo.stream(Command(resume=correcoes), config=cfg,
                                    stream_mode="updates"):
                pass  # só consumimos até a próxima pausa/fim
        except Exception as e:  # noqa: BLE001
            logger.exception("hitl resume falhou")
            st.erro_processamento = str(e)
            st.stage = "ready"
            return {"stage": "ready", "error": str(e)[:400]}

        estado = grafo.get_state(cfg)
        vals = estado.values or {}
        st.ultima_saida = dict(vals)
        duvida = vals.get("duvida_pendente")

        if duvida:
            st.ultima_interrupcao = True
            st.stage = "hitl"
            st.touch()
            return {"stage": "hitl", "duvida": duvida}
        st.ultima_interrupcao = None
        st.stage = "done"
        st.touch()
        snap = _snapshot_pc(st)
        return {
            "stage": "done",
            "feito": len(snap["records"]),
            "total": total,
            "records": snap["records"],
            "linhas": snap["linhas"],
        }


# ============================================================
# Edição via chat (LLM editor)
# ============================================================

@router.post("/pc/edit")
def pc_edit(payload: PcEditIn, session_id: str) -> dict:
    try:
        st = sessions.require(session_id)
    except KeyError:
        raise HTTPException(404, "Sessão não encontrada")

    with sessions.lock_for(session_id):
        linhas_proc = (st.ultima_saida or {}).get("linhas_processadas") or []
        if not linhas_proc:
            raise HTTPException(409, "Nenhum PC para editar")
        editado, resposta = aplicar_edicao_pc(
            linhas_proc, payload.mensagem, st.perfil or {}
        )
        saida = dict(st.ultima_saida)
        saida["linhas_processadas"] = editado
        st.ultima_saida = saida
        st.pc_confirmado = False
        st.touch()
        snap = _snapshot_pc(st)
        return {
            "resposta": resposta,
            "records": snap["records"],
            "linhas": snap["linhas"],
        }


# ============================================================
# Revisão de anéis
# ============================================================

@router.post("/anel/decide")
def anel_decide(payload: AnelDecisionIn, session_id: str) -> dict:
    """Confirma (expande) ou pula a expansão de um anel.

    `chave` = "<codigo_fornecedor>_<tamanho>". Espelho dos botões anel em app.py.
    """
    try:
        st = sessions.require(session_id)
    except KeyError:
        raise HTTPException(404, "Sessão não encontrada")

    with sessions.lock_for(session_id):
        linhas_proc = (st.ultima_saida or {}).get("linhas_processadas") or []
        if not linhas_proc:
            raise HTTPException(409, "Nenhum PC carregado")
        norm = _normalizar_pc(linhas_proc)
        # Localiza a linha-alvo pela chave.
        alvo = None
        for l in norm:
            ch = str(l.get("codigo_fornecedor", "")) + "_" + l.get("tamanho", "")
            if ch == payload.chave and l.get("_proposta_expansao_anel"):
                alvo = l
                break
        if alvo is None:
            raise HTTPException(404, "Anel não encontrado para revisão")

        if payload.aprovar:
            st._aneis_revisados[payload.chave] = aplicar_expansao_anel(alvo)
        else:
            st._aneis_revisados[payload.chave] = None
        st.touch()

        snap = _snapshot_with_anéis(st)
        return {
            "records": snap["records"],
            "linhas": snap["linhas"],
            "pendentes": snap["pendentes"],
        }


def _snapshot_with_anéis(st: SessionState) -> dict:
    """Aplica decisões de anéis ao PC normalizado e retorna snapshot."""
    linhas_proc = (st.ultima_saida or {}).get("linhas_processadas") or []
    if not linhas_proc:
        return {"linhas": [], "records": [], "total": 0, "pendentes": []}
    linhas_norm = _normalizar_pc(linhas_proc)

    # Limpa revisões órfãs.
    chaves_ativas = {
        str(l.get("codigo_fornecedor", "")) + "_" + l.get("tamanho", "")
        for l in linhas_norm
    }
    st._aneis_revisados = {
        k: v for k, v in st._aneis_revisados.items() if k in chaves_ativas
    }

    novas: list[dict] = []
    pendentes: list[dict] = []
    for l in linhas_norm:
        ch = str(l.get("codigo_fornecedor", "")) + "_" + l.get("tamanho", "")
        if l.get("_proposta_expansao_anel") and ch not in st._aneis_revisados:
            pendentes.append(l)
            novas.append(l)
            continue
        exp = st._aneis_revisados.get(ch)
        if exp is None and ch in st._aneis_revisados:
            # Pulado — remove flag, mantém 1 linha.
            r = dict(l)
            r.pop("_proposta_expansao_anel", None)
            r["duvida_pendente"] = False
            r["motivo_duvida"] = ""
            novas.append(r)
        elif exp:
            novas.extend(exp)
        else:
            novas.append(l)

    return {
        "linhas": novas,
        "records": _linhas_to_records(novas),
        "total": len(novas),
        "pendentes": pendentes,
    }


@router.get("/pc/preview")
def pc_preview(session_id: str) -> dict:
    """Snapshot atual do PC (linhas + records PT + anéis pendentes)."""
    try:
        st = sessions.require(session_id)
    except KeyError:
        raise HTTPException(404, "Sessão não encontrada")
    snap = _snapshot_with_anéis(st)
    return {
        "records": snap["records"],
        "linhas": snap["linhas"],
        "total": snap["total"],
        "pendentes": snap["pendentes"],
        "pc_confirmado": st.pc_confirmado,
        "nome_arquivo": st.nome_arquivo,
        "marca": st.marca,
        "cod_fornecedor": st.cod_fornecedor,
        "thread_id": st.thread_id,
    }


# ============================================================
# Confirmar + download
# ============================================================

@router.post("/pc/confirm")
def pc_confirm(session_id: str) -> dict:
    try:
        st = sessions.require(session_id)
    except KeyError:
        raise HTTPException(404, "Sessão não encontrada")
    with sessions.lock_for(session_id):
        st.pc_confirmado = True
        st.touch()
    return {"pc_confirmado": True}


@router.get("/pc/download")
def pc_download(session_id: str) -> StreamingResponse:
    """Gera o .xlsx final do Pedido de Compra (ERP-shaped)."""
    try:
        st = sessions.require(session_id)
    except KeyError:
        raise HTTPException(404, "Sessão não encontrada")

    snap = _snapshot_with_anéis(st)
    if not snap["linhas"]:
        raise HTTPException(409, "Nenhum PC para baixar")

    df_final = linhas_para_dataframe_pc(snap["linhas"])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df_final.to_excel(writer, index=False, sheet_name="Pedido de Compra")
    buf.seek(0)

    base = st.nome_arquivo or "saida.xlsx"
    nome = f"PC_{base}".replace(".xlsx", "_PROCESSADO.xlsx")
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


@router.get("/pc/json")
def pc_json(session_id: str) -> dict:
    """Primeira linha normalizada (JSON estruturado) — botão 'Ver JSON'."""
    try:
        st = sessions.require(session_id)
    except KeyError:
        raise HTTPException(404, "Sessão não encontrada")
    snap = _snapshot_with_anéis(st)
    first = snap["linhas"][0] if snap["linhas"] else {}
    return {"linha": first}

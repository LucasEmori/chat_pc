"""Grafo LangGraph: processa linha-a-linha, com interrupt para HITL.

Fluxo:
    START -> processar -> [duvida?] -> hitl (interrupt) -> processar
                                    -> próxima linha -> ...
                                    -> END

O checkpointer (MemorySaver) é OBRIGATÓRIO para que o estado sobreviva
à pausa do interrupt. thread_id identifica a sessão.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt

from .schema import PedidoEstado, LinhaPedidoCompra
from .llm import processar_linha

logger = logging.getLogger(__name__)

# Palavras-chave para detectar se motivo_duvida menciona SÓ pedra/zirconia
# (nesses casos não abrimos HITL — user preenche depois).
_RE_SO_PEDRA_ZIRCONIA = re.compile(
    r"\b(pedra|zirconia|zirc\xf4nia)\b", re.IGNORECASE
)
# Palavras-chave de OUTROS campos que exigem HITL
_RE_OUTROS_CAMPOS = re.compile(
    r"\b(categoria|banho|marca|codigo_fornecedor|c\xf3digo|tamanho|"
    r"quantidade|peso|labor|silver|prata|material|foob|"
    r"ref|pre\xE7o|price|size|qty|unit)\b", re.IGNORECASE
)


def _so_duvida_pedra_zirconia(motivo: str) -> bool:
    """True se motivo menciona apenas pedra/zirconia (sem outros campos)."""
    if not motivo:
        return False
    tem_pedra_zir = bool(_RE_SO_PEDRA_ZIRCONIA.search(motivo))
    tem_outros = bool(_RE_OUTROS_CAMPOS.search(motivo))
    return tem_pedra_zir and not tem_outros


def node_processar(state: PedidoEstado) -> dict:
    """Invoca o LLM na linha[indice_atual] e acumula o resultado.

    Semântica full-list: devolve `linhas_processadas` completa (cópia + 1).
    Isso permite ao node_hitl substituir o último item sem reducer ambíguo.
    """
    linhas = state.get("linhas_originais", [])
    indice = state.get("indice_atual", 0)
    perfil = state.get("perfil", {})
    fornecedor = state.get("fornecedor", "DESCONHECIDO")

    if indice >= len(linhas):
        return {"indice_atual": indice}  # fim

    linha_dict = linhas[indice]

    logger.info("Processando linha %d/%d ref=%s", indice + 1, len(linhas),
                linha_dict.get("ref"))

    saida: LinhaPedidoCompra = processar_linha(linha_dict, perfil, fornecedor)
    saida_dict = saida.model_dump()

    processadas = list(state.get("linhas_processadas", []))
    processadas.append(saida_dict)

    # Filtro: se a única dúvida é pedra/zirconia, não abrir HITL.
    # Usuário preenche pedra/zirconia manualmente depois no PC final.
    abrir_hitl = saida.duvida_pendente
    if abrir_hitl and _so_duvida_pedra_zirconia(saida.motivo_duvida or ""):
        logger.info(
            "Dúvida apenas em pedra/zirconia (ref=%s) — HITL suprimido.",
            linha_dict.get("ref"))
        abrir_hitl = False

    return {
        "linhas_processadas": processadas,
        "indice_atual": indice + 1,
        "duvida_pendente": saida_dict if abrir_hitl else None,
    }


def node_hitl(state: PedidoEstado) -> dict:
    """Pausa a execução expondo a linha em dúvida.

    `interrupt(payload)` suspende o grafo; o checkpointer salva o estado.
    O caller (Streamlit) lê state['duvida_pendente'] + o payload via
    result['__interrupt__'] e exibe o formulário.

    Ao resumir com Command(resume=correcoes), o retorno de interrupt()
    recebe um dict com campos corrigidos pelo humano. Substituímos a última
    linha em linhas_processadas pela versão corrigida (full-list semantics).
    """
    payload = {
        "linha": state.get("duvida_pendente"),
        "indice": state.get("indice_atual", 0) - 1,
        "motivo_duvida": (state.get("duvida_pendente") or {}).get("motivo_duvida", ""),
    }
    correcao = interrupt(payload)  # <- pausa aqui

    if not isinstance(correcao, dict):
        correcao = {"remarks": str(correcao)}

    processadas = list(state.get("linhas_processadas", []))
    idx_ultima = len(processadas) - 1
    if idx_ultima >= 0:
        atual = dict(processadas[idx_ultima])
        atual.update(correcao)
        atual["duvida_pendente"] = False
        atual["motivo_duvida"] = ""
        try:
            LinhaPedidoCompra.model_validate(atual)
        except Exception as e:  # noqa: BLE001
            atual["remarks"] = (atual.get("remarks", "") +
                                f" [WARN pós-HITL: {e}]")
        processadas[idx_ultima] = atual

    return {
        "linhas_processadas": processadas,
        "duvida_pendente": None,
    }


def rotear(state: PedidoEstado) -> str:
    """Edge condicional pós-processar.

    - Se duvida_pendente ativa -> 'hitl'
    - Senão se há mais linhas -> 'processar' (loop)
    - Senão -> END
    """
    if state.get("duvida_pendente"):
        return "hitl"
    indice = state.get("indice_atual", 0)
    total = len(state.get("linhas_originais", []))
    if indice < total:
        return "processar"
    return END


def compilar_grafo():
    """Constrói e compila o StateGraph com MemorySaver (HITL-ready)."""
    builder = StateGraph(PedidoEstado)
    builder.add_node("processar", node_processar)
    builder.add_node("hitl", node_hitl)

    builder.add_edge(START, "processar")
    builder.add_conditional_edges(
        "processar",
        rotear,
        {"hitl": "hitl", "processar": "processar", END: END},
    )
    builder.add_edge("hitl", "processar")  # após HITL, volta ao loop

    # Checkpointer é OBRIGATÓRIO: sem ele, interrupt() não consegue salvar.
    checkpointer = MemorySaver()
    return builder.compile(checkpointer=checkpointer)


def estado_inicial(df_linhas, perfil: dict, fornecedor: str,
                   nome_arquivo: str) -> PedidoEstado:
    """Monta estado inicial a partir de DataFrame limpo.

    `fornecedor` aqui é apenas rótulo descritivo (operador + tipo) para log.
    """
    from .cleaner import linha_para_dict as _lpd
    linhas = [_lpd(row) for _, row in df_linhas.iterrows()]
    return {
        "linhas_originais": linhas,
        "linhas_processadas": [],
        "indice_atual": 0,
        "fornecedor": fornecedor,
        "perfil": perfil,
        "nome_arquivo": nome_arquivo,
        "duvida_pendente": None,
    }

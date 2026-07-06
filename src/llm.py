"""Wrappers de acesso ao ChatNVIDIA (NVIDIA NIM) com retry e fallback OpenRouter.

with_structured_output(LinhaPedidoCompra) força o provedor a devolver um
objeto tipado. Em caso de ValidationError, reenviamos o erro ao LLM como
contexto para autocorreção (1 retry).

Se NVIDIA falhar (rate limit / quota / 401 / 403), cai no OpenRouter.
Se ambos falharem, retorna esqueleto com duvida_pendente=True.
"""
from __future__ import annotations

import os
import logging
from typing import Optional

from dotenv import load_dotenv
from pydantic import ValidationError

from .schema import LinhaPedidoCompra, EditResponse
from .prompts import (
    PROMPT_SISTEMA,
    PROMPT_EDIT_SISTEMA,
    construir_prompt_usuario,
    construir_prompt_correcao,
    construir_prompt_edicao,
)

load_dotenv()

logger = logging.getLogger(__name__)


def _provedor_ativo() -> str:
    """Lê LLM_PROVIDER do env (setado pelo radio em app.py).
    Valores: 'nvidia', 'openrouter', 'auto' (default).
    """
    return os.getenv("LLM_PROVIDER", "auto")

# Caches NVIDIA
_CHAT = None
_CHAT_STRUCTURED = None
_CHAT_EDITOR = None

# Caches OpenRouter
_CHAT_OR = None
_CHAT_OR_STRUCTURED = None
_CHAT_OR_EDITOR = None

# Caches Google
_CHAT_GOOGLE = None
_CHAT_GOOGLE_STRUCTURED = None
_CHAT_GOOGLE_EDITOR = None

_FALLBACK_AVISADO = False


def obter_chat():
    """Cria (caching) ChatNVIDIA base sem structured output."""
    global _CHAT
    if _CHAT is None:
        from langchain_nvidia_ai_endpoints import ChatNVIDIA
        _CHAT = ChatNVIDIA(
            model=os.getenv("NVIDIA_MODEL", "meta/llama-3.3-70b-instruct"),
            api_key=os.getenv("NVIDIA_API_KEY"),
            temperature=0,
            max_tokens=1024,
        )
    return _CHAT


def obter_chat_estruturado():
    """ChatNVIDIA com with_structured_output(LinhaPedidoCompra)."""
    global _CHAT_STRUCTURED
    if _CHAT_STRUCTURED is None:
        _CHAT_STRUCTURED = obter_chat().with_structured_output(LinhaPedidoCompra)
    return _CHAT_STRUCTURED


def obter_chat_editor():
    """ChatNVIDIA com with_structured_output(EditResponse) pós-PC."""
    global _CHAT_EDITOR
    if _CHAT_EDITOR is None:
        _CHAT_EDITOR = obter_chat().with_structured_output(EditResponse)
    return _CHAT_EDITOR


def _obter_chat_openrouter():
    """Cria (caching) ChatOpenAI apontando para OpenRouter."""
    global _CHAT_OR
    if _CHAT_OR is None:
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            logger.warning("OPENROUTER_API_KEY ausente. Fallback desativado.")
            return None
        try:
            from langchain_openai import ChatOpenAI
            _CHAT_OR = ChatOpenAI(
                model=os.getenv("OPENROUTER_MODEL",
                                "nvidia/nemotron-3-ultra-550b-a55b:free"),
                api_key=api_key,
                base_url="https://openrouter.ai/api/v1",
                temperature=0,
                max_tokens=4096,
                default_headers={
                    "HTTP-Referer": "https://chatpc.app",
                    "X-Title": "ChatPC Invoice Processor",
                },
            )
        except ImportError:
            logger.warning(
                "langchain-openai não instalado. OpenRouter fallback "
                "indisponível."
            )
            _CHAT_OR = None
    return _CHAT_OR


def _obter_chat_openrouter_estruturado():
    """OpenRouter com with_structured_output(LinhaPedidoCompra)."""
    global _CHAT_OR_STRUCTURED
    if _CHAT_OR_STRUCTURED is None:
        chat = _obter_chat_openrouter()
        if chat is not None:
            _CHAT_OR_STRUCTURED = chat.with_structured_output(
                LinhaPedidoCompra, method="json_mode"
            )
    return _CHAT_OR_STRUCTURED


def _obter_chat_openrouter_editor():
    """OpenRouter com with_structured_output(EditResponse)."""
    global _CHAT_OR_EDITOR
    if _CHAT_OR_EDITOR is None:
        chat = _obter_chat_openrouter()
        if chat is not None:
            _CHAT_OR_EDITOR = chat.with_structured_output(
                EditResponse, method="json_mode"
            )
    return _CHAT_OR_EDITOR


def _obter_chat_google():
    """Cria (caching) ChatGoogleGenerativeAI (Gemini).

    Gemini aceita structured output nativamente (sem json_mode).
    max_output_tokens generoso porque Gemini 2.5 usa reasoning tokens.
    """
    global _CHAT_GOOGLE
    if _CHAT_GOOGLE is None:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            logger.warning("GOOGLE_API_KEY ausente. Google desativado.")
            return None
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            _CHAT_GOOGLE = ChatGoogleGenerativeAI(
                model=os.getenv("GOOGLE_MODEL", "gemini-2.5-flash"),
                api_key=api_key,
                temperature=0,
                max_output_tokens=8192,
            )
        except ImportError:
            logger.warning(
                "langchain-google-genai não instalado. Google indisponível."
            )
            _CHAT_GOOGLE = None
    return _CHAT_GOOGLE


def _obter_chat_google_estruturado():
    """Google Gemini com with_structured_output(LinhaPedidoCompra)."""
    global _CHAT_GOOGLE_STRUCTURED
    if _CHAT_GOOGLE_STRUCTURED is None:
        chat = _obter_chat_google()
        if chat is not None:
            _CHAT_GOOGLE_STRUCTURED = chat.with_structured_output(
                LinhaPedidoCompra
            )
    return _CHAT_GOOGLE_STRUCTURED


def _obter_chat_google_editor():
    """Google Gemini com with_structured_output(EditResponse)."""
    global _CHAT_GOOGLE_EDITOR
    if _CHAT_GOOGLE_EDITOR is None:
        chat = _obter_chat_google()
        if chat is not None:
            _CHAT_GOOGLE_EDITOR = chat.with_structured_output(EditResponse)
    return _CHAT_GOOGLE_EDITOR


def _fazer_esqueleto(linha: dict, perfil: dict, erro_str: str,
                     max_tentativas: int) -> LinhaPedidoCompra:
    """Cria LinhaPedidoCompra esqueleto com duvida_pendente."""
    return LinhaPedidoCompra(
        categoria="BRINCO",  # placeholder; humano corrigirá
        codigo_fornecedor=str(linha.get("ref") or linha.get("codigo") or ""),
        foto="",
        material=perfil.get("material_padrao", "PRATA"),
        fornecedor=perfil.get("codigo", ""),
        banho="RÓDIO",
        pedra="SEM PEDRA",
        zirconia="ZB",
        tamanho="0",
        tipo_pedra=perfil.get("tipo_pedra_padrao", "ZIRCONIA / FUSION"),
        marca=perfil.get("marca", "AL"),
        quantidade=int(linha.get("qty") or 0) or 1,
        peso=float(linha.get("unit_weight") or 0) or 0.0,
        labor_price=float(linha.get("labor_price") or 0) or 0.0,
        silver_price=float(linha.get("silver_price") or 0) or 0.0,
        dia="",
        unit_price_fob=0.0,
        preco_vendas=0.0,
        remarks=str(erro_str),
        duvida_pendente=True,
        motivo_duvida=(
            f"Falha após {max_tentativas} tentativas. "
            f"Último erro: {erro_str}"
        ),
        confianca=0.0,
    )


def processar_linha(linha: dict, perfil: dict, fornecedor_nome: str,
                    max_tentativas: int = 2) -> LinhaPedidoCompra:
    """Processa linha respeitando LLM_PROVIDER.

    - 'nvidia': só NVIDIA
    - 'openrouter': só OpenRouter
    - 'google': só Google Gemini
    - 'auto' (default): NVIDIA → OpenRouter → Google (em sequência)

    Retorna sempre LinhaPedidoCompra. Tudo falhar → esqueleto HITL.
    """
    global _FALLBACK_AVISADO
    provedor = _provedor_ativo()
    mensagem_user = construir_prompt_usuario(linha, perfil, fornecedor_nome)
    ultima_exc: Optional[Exception] = None
    ultima_saida_dict: dict = {}

    def _tentar(chat_structured, nome_prov: str) -> Optional[LinhaPedidoCompra]:
        nonlocal mensagem_user, ultima_exc, ultima_saida_dict
        for tentativa in range(1, max_tentativas + 1):
            try:
                saida = chat_structured.invoke([
                    {"role": "system", "content": PROMPT_SISTEMA},
                    {"role": "user", "content": mensagem_user},
                ])
                if isinstance(saida, LinhaPedidoCompra):
                    return saida
                return LinhaPedidoCompra.model_validate(saida)
            except Exception as e:
                ultima_exc = e
                logger.warning(
                    "%s tentativa %s falhou: %s",
                    nome_prov.upper(), tentativa, e,
                )
                if tentativa < max_tentativas:
                    try:
                        nova_user = construir_prompt_correcao(
                            str(e), linha, perfil,
                            fornecedor_nome, ultima_saida_dict,
                        )
                        mensagem_user = nova_user
                    except Exception as inner:
                        logger.error("construir prompt correção falhou: %s", inner)
        return None

    def _tentar_google_unica() -> Optional[LinhaPedidoCompra]:
        """Google: 1 tentativa direta (Gemini raramente precisa de retry)."""
        nonlocal ultima_exc
        chat = _obter_chat_google_estruturado()
        if chat is None:
            return None
        try:
            saida = chat.invoke([
                {"role": "system", "content": PROMPT_SISTEMA},
                {"role": "user", "content": mensagem_user},
            ])
            if isinstance(saida, LinhaPedidoCompra):
                return saida
            return LinhaPedidoCompra.model_validate(saida)
        except Exception as e:
            ultima_exc = e
            logger.warning("GOOGLE falhou: %s", e)
            return None

    # ---- Somente NVIDIA ----
    if provedor == "nvidia":
        chat_nv = obter_chat_estruturado()
        resultado = _tentar(chat_nv, "nvidia")
        if resultado:
            return resultado
        erro = str(ultima_exc)[:500] if ultima_exc else "erro desconhecido"
        return _fazer_esqueleto(linha, perfil, erro, max_tentativas)

    # ---- Somente OpenRouter ----
    if provedor == "openrouter":
        chat_or = _obter_chat_openrouter_estruturado()
        if chat_or is None:
            return _fazer_esqueleto(
                linha, perfil,
                "OPENROUTER_API_KEY ausente ou langchain-openai não instalado",
                max_tentativas,
            )
        if not _FALLBACK_AVISADO:
            logger.info("Usando OpenRouter exclusivo (modelo: %s)",
                        os.getenv("OPENROUTER_MODEL"))
            _FALLBACK_AVISADO = True
        resultado = _tentar(chat_or, "openrouter")
        if resultado:
            return resultado
        erro = str(ultima_exc)[:500] if ultima_exc else "erro desconhecido"
        return _fazer_esqueleto(linha, perfil, erro, max_tentativas)

    # ---- Somente Google ----
    if provedor == "google":
        if _obter_chat_google() is None:
            return _fazer_esqueleto(
                linha, perfil,
                "GOOGLE_API_KEY ausente ou langchain-google-genai não instalado",
                max_tentativas,
            )
        if not _FALLBACK_AVISADO:
            logger.info("Usando Google exclusivo (modelo: %s)",
                        os.getenv("GOOGLE_MODEL"))
            _FALLBACK_AVISADO = True
        resultado = _tentar_google_unica()
        if resultado:
            return resultado
        erro = str(ultima_exc)[:500] if ultima_exc else "erro desconhecido"
        return _fazer_esqueleto(linha, perfil, erro, max_tentativas)

    # ---- Auto: NVIDIA → OpenRouter → Google ----
    chat_nv = obter_chat_estruturado()
    resultado = _tentar(chat_nv, "nvidia")
    if resultado:
        return resultado

    erro_nv = str(ultima_exc)[:500] if ultima_exc else "erro desconhecido"
    logger.warning("NVIDIA exaurido para linha %s. Fallback OpenRouter.",
                   linha.get("ref") or linha.get("codigo", "?"))

    chat_or = _obter_chat_openrouter_estruturado()
    if chat_or is not None:
        if not _FALLBACK_AVISADO:
            logger.info("Fallback OpenRouter (modelo: %s)",
                        os.getenv("OPENROUTER_MODEL"))
            _FALLBACK_AVISADO = True
        mensagem_user = construir_prompt_usuario(linha, perfil, fornecedor_nome)
        try:
            saida = chat_or.invoke([
                {"role": "system", "content": PROMPT_SISTEMA},
                {"role": "user", "content": mensagem_user},
            ])
            if isinstance(saida, LinhaPedidoCompra):
                return saida
            return LinhaPedidoCompra.model_validate(saida)
        except Exception as e:
            ultima_exc = e
            logger.error("OpenRouter fallback falhou: %s", e)

    # Última tentativa: Google
    if _obter_chat_google() is not None:
        logger.warning("Fallback final: Google Gemini.")
        mensagem_user = construir_prompt_usuario(linha, perfil, fornecedor_nome)
        resultado_g = _tentar_google_unica()
        if resultado_g:
            return resultado_g
        erro_g = str(ultima_exc)[:500]
        erro_final = f"NVIDIA: {erro_nv} | Google: {erro_g}"
        return _fazer_esqueleto(linha, perfil, erro_final, max_tentativas)

    return _fazer_esqueleto(linha, perfil, erro_nv, max_tentativas)


def aplicar_edicao_pc(pc_atual: list[dict], msg_usuario: str,
                      perfil: dict) -> tuple[list[dict], str]:
    """Editor conversacional pós-PC respeitando LLM_PROVIDER.

    Recebe o PC atual (lista de dicts) e um pedido em linguagem natural do
    operador. O LLM devolve o PC COMPLETO editado + uma mensagem curta.

    Nunca lança exceção: em caso de falha retorna (pc_atual, msg_erro).

    Returns:
        (pc_editado_dicts, mensagem_assistente)
    """
    global _FALLBACK_AVISADO

    if not pc_atual:
        return pc_atual, "PC vazio, nada a editar."

    provedor = _provedor_ativo()
    prompt = construir_prompt_edicao(pc_atual, msg_usuario, perfil)

    def _invocar(chat_editor) -> Optional[EditResponse]:
        resp = chat_editor.invoke([
            {"role": "system", "content": PROMPT_EDIT_SISTEMA},
            {"role": "user", "content": prompt},
        ])
        if not isinstance(resp, EditResponse):
            resp = EditResponse.model_validate(resp)
        return resp

    def _extrair(resp: EditResponse) -> tuple[list[dict], str]:
        editado = [linha.model_dump() for linha in resp.pc_editado]
        if not editado:
            return (list(pc_atual),
                    resp.mensagem or "Modelo devolveu lista vazia.")
        return editado, resp.mensagem

    # ---- Somente NVIDIA ----
    if provedor == "nvidia":
        try:
            return _extrair(_invocar(obter_chat_editor()))
        except Exception as e:
            logger.warning("NVIDIA editor falhou: %s", e)
            return (list(pc_atual),
                    f"Não foi possível aplicar a alteração: {e}")

    # ---- Somente OpenRouter ----
    if provedor == "openrouter":
        chat_or = _obter_chat_openrouter_editor()
        if chat_or is None:
            return (list(pc_atual),
                    "OpenRouter não configurado (sem chave ou sem pacote).")
        try:
            return _extrair(_invocar(chat_or))
        except Exception as e:
            logger.warning("OpenRouter editor falhou: %s", e)
            return (list(pc_atual),
                    f"Não foi possível aplicar a alteração: {e}")

    # ---- Somente Google ----
    if provedor == "google":
        chat_g = _obter_chat_google_editor()
        if chat_g is None:
            return (list(pc_atual),
                    "Google não configurado (sem chave ou sem pacote).")
        try:
            return _extrair(_invocar(chat_g))
        except Exception as e:
            logger.warning("Google editor falhou: %s", e)
            return (list(pc_atual),
                    f"Não foi possível aplicar a alteração: {e}")

    # ---- Auto: NVIDIA → OpenRouter → Google ----
    e_nv = None
    try:
        return _extrair(_invocar(obter_chat_editor()))
    except Exception as e:
        e_nv = e
        logger.warning("NVIDIA editor falhou: %s. Tentando OpenRouter...", e)

    chat_or = _obter_chat_openrouter_editor()
    if chat_or is not None:
        if not _FALLBACK_AVISADO:
            logger.info("Fallback OpenRouter editor (modelo: %s)",
                        os.getenv("OPENROUTER_MODEL"))
            _FALLBACK_AVISADO = True
        try:
            return _extrair(_invocar(chat_or))
        except Exception as e_or:
            logger.error("OpenRouter editor falhou: %s. Tentando Google...",
                         e_or)

    # Última tentativa: Google
    chat_g = _obter_chat_google_editor()
    if chat_g is not None:
        try:
            return _extrair(_invocar(chat_g))
        except Exception as e_g:
            logger.error("Google editor também falhou: %s", e_g)
            return (list(pc_atual),
                    f"Todos provedores falharam. NVIDIA: {e_nv} | "
                    f"Google: {e_g}")

    return (list(pc_atual),
            f"Não foi possível aplicar a alteração. NVIDIA: {e_nv}")

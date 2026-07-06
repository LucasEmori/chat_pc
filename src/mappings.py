"""Mapas estáticos de vocabulário controlado e detecção de tipo de material.

Importante: o prefixo ALAN/LUIS no nome do arquivo é apenas o OPERADOR
(pessoa do time que processa), NÃO é fornecedor. O fornecedor real é o
fabricante chinês (código ERP 012432, MARCA AL) e é o mesmo para todas
as samples. A variação semântica relevante é o TIPO DE PEDRA:
    - zirconia (锆石) -> TIPO PEDRA 'ZIRCONIA / FUSION'
    - moissanite (莫桑石) -> TIPO PEDRA 'MOISSANITE'

A detecção é feita por conteúdo (ideograma/palavra-chave na planilha),
não pelo nome do operador.
"""
from __future__ import annotations

import logging
from typing import Literal

logger = logging.getLogger(__name__)

TipoMaterial = Literal["ZIRCONIA", "MOISSANITE"]

# Categoria: chinês -> PT-BR (vocabulário do ERP)
CATEGORIA_CN_PT: dict[str, str] = {
    "耳环": "BRINCO",
    "戒指": "ANEL",
    "戒": "ANEL",
    "项链": "COLAR",
    "手链": "PULSEIRA",
    "手镯": "PULSEIRA",
    "手环": "PULSEIRA",
    "吊坠": "PINGENTE",
    "坠": "PINGENTE",
    "耳钉": "BRINCO",
    "耳坠": "BRINCO",
    "套装": "CONJUNTO",
    "套": "CONJUNTO",
    "胸针": "BROCHE",
    "戒指/吊坠": "PINGENTE",
}

# Plating (banho) -> vocabulário ERP
BANHO_PLATING_PT: dict[str, str] = {
    "rodhium plate": "RÓDIO",
    "rodhium plate 镀白": "RÓDIO",
    "rhodium plate": "RÓDIO",
    "镀白": "RÓDIO",
    "rhodium": "RÓDIO",
    "rodhium": "RÓDIO",
    "gold": "OURO",
    "gold plate": "OURO",
    "gold plated": "OURO",
    "镀金": "OURO",
    "rose gold": "OURO ROSÉ",
    "rosegold": "OURO ROSÉ",
    "black plate": "PRETO",
    "black plate镀黑": "PRETO",
    "black plated": "PRETO",
    "champagne gold": "OURO",
    "yellow gold": "OURO",
    "silver": "RÓDIO",
}

# STONE COLOR -> (Pedra, sigla Zirconia)
# Siglas do ERP: ZB=zirconia branca, MS=moissanite, TZN=tanzanita,
#                YEL=amarela, PIN=sáfira pink, LIS=lírio, COLOMBIANA, etc.
PEDRA_STONE_PT: dict[str, tuple[str, str]] = {
    "all white": ("SEM PEDRA", "ZB"),
    "白": ("SEM PEDRA", "ZB"),
    "白莫桑石": ("CRISTAL", "MS"),
    "moissanite": ("CRISTAL", "MS"),
    "moissanite stone": ("CRISTAL", "MS"),
    "white": ("SEM PEDRA", "ZB"),
    # azuis
    "acquamarine and small cz white": ("ÁGUA MARINHA", "ZB"),
    "acquamarine + white": ("ÁGUA MARINHA", "ZB"),
    "aquamarine and small cz white": ("ÁGUA MARINHA", "ZB"),
    "水兰玻107，其余白": ("ÁGUA MARINHA", "ZB"),
    # tanzanita
    "tanzanite and small cz white": ("TANZANITA", "TZN"),
    "tanzanite and small cz": ("TANZANITA", "TZN"),
    "大石坦桑锆，其余白": ("TANZANITA", "TZN"),
    # rubi / safira pink
    "ruby 3 and small cz white": ("SÁFIRA PINK", "PIN"),
    "ruby3": ("SÁFIRA PINK", "PIN"),
    "ruby 3 + white": ("SÁFIRA PINK", "PIN"),
    "大石#3红刚玉，其余白": ("SÁFIRA PINK", "PIN"),
    "#3红刚玉": ("SÁFIRA PINK", "PIN"),
    # esmeralda fusion (CB01)
    "cb01 and small cz white": ("ESMERALDA FUSION", "ZB"),
    "cb01 and small cz": ("ESMERALDA FUSION", "ZB"),
    "大石合成石cb01,其余白": ("ESMERALDA FUSION", "ZB"),
    # colombiana (CB12)
    "cb12 and small cz white": ("COLOMBIANA", "ZB"),
    "cb12 and small cz": ("COLOMBIANA", "ZB"),
    # amarelo
    "all very light yellow": ("AMARELO", "YEL"),
    "very light yellow": ("AMARELO", "YEL"),
    "大石鹅黄锆，其余白": ("AMARELO", "YEL"),
    "yellow and small cz white": ("AMARELO", "YEL"),
    "yellow": ("AMARELO", "YEL"),
    # cristal / preto
    "black cz": ("CRISTAL BLACK", "ZB"),
    "黑纳米": ("CRISTAL BLACK", "ZB"),
}

# Marcas validas (selecionado pelo operador no app)
# AL, GR, NV — definido pelo usuário antes do processamento
MARCAS_VALIDAS = {"AL", "GR", "NV"}

# Lista de fornecedores (códigos ERP)
# O operador digita o código manualmente

# Perfil base do fornecedor (fabricante chinês).
# 'material_padrao' sempre PRATA (joia base).
# 'marca' e 'codigo' sobrescritos pela seleção do operador no app.
PERFIL_FORNECEDOR_BASE: dict = {
    "material_padrao": "PRATA",
}

# Marcadores de tipo de pedra para auto-detecção por conteúdo
MARCADORES_MOISSANITE = {"莫桑石", "moissanite", "mossanite", "白莫桑石"}
MARCADORES_ZIRCONIA = {"锆石", "zirconia", "cz white", "fusion"}


def detectar_tipo_material(nome_arquivo: str, df_raw=None) -> TipoMaterial:
    """Detecta se a Invoice é zirconia ou moissanite inspecionando
    nome do arquivo + (opcional) conteúdo bruto da planilha.

    Heurística:
      1. Procura marcadores no nome do arquivo (mais barato)
      2. Se ambíguo, varre primeiras 30 linhas do DataFrame bruto
      3. Default: zirconia (mais comum no catálogo histórico)
    """
    nome_lower = (nome_arquivo or "").lower()
    if any(m in nome_lower for m in MARCADORES_MOISSANITE):
        return "MOISSANITE"
    if any(m in nome_lower for m in MARCADORES_ZIRCONIA):
        return "ZIRCONIA"

    if df_raw is not None:
        try:
            # Empilhar todos os valores em uma única strings e lowerizar.
            # df.astype(str).str.lower() NÃO funciona em DataFrame ( só em Series)
            amostra = df_raw.head(30)
            valores = amostra.values.flatten().tolist()
            texto = " ".join(str(v).lower() for v in valores if v is not None)
            if any(m in texto for m in MARCADORES_MOISSANITE):
                return "MOISSANITE"
            if any(m in texto for m in MARCADORES_ZIRCONIA):
                return "ZIRCONIA"
        except Exception as e:  # noqa: BLE001
            logger.warning("detecção por conteúdo falhou: %s", e)

    logger.info("tipo de material indefinido, default ZIRCONIA")
    return "ZIRCONIA"


def montar_perfil(tipo: TipoMaterial, marca: str = "AL",
                  codigo_fornecedor: str = "012432") -> dict:
    """Monta perfil completo combinando base fixa + tipo de pedra + sobreescritas.

    Args:
        tipo: ZIRCONIA ou MOISSANITE (detectado por conteúdo).
        marca: AL, GR ou NV (selecionado pelo operador).
        codigo_fornecedor: Código ERP do fornecedor (digitado pelo operador).
    """
    perfil = dict(PERFIL_FORNECEDOR_BASE)
    perfil["codigo"] = codigo_fornecedor
    perfil["marca"] = marca
    if tipo == "MOISSANITE":
        perfil["tipo_pedra_padrao"] = "MOISSANITE"
    else:
        perfil["tipo_pedra_padrao"] = "ZIRCONIA / FUSION"
    perfil["tipo_material"] = tipo
    return perfil


def obter_perfil(nome_arquivo: str, df_raw=None,
                 marca: str = "AL",
                 codigo_fornecedor: str = "012432") -> tuple[TipoMaterial, dict]:
    """Ponto de entrada único: (tipo_material, perfil_dict)."""
    tipo = detectar_tipo_material(nome_arquivo, df_raw)
    return tipo, montar_perfil(tipo, marca, codigo_fornecedor)

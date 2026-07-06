"""Limpeza de Invoice com pandas: detecta header, descarta metadata/footer,
faz forward-fill de variantes e normaliza colunas para chaves estáveis.

Layout típico (confirmado nas samples ALAN + LUIS):
- Sheet 0 chamada 'S299 (3)' ou similar
- ~7 linhas iniciais vazias/metadata
- Linha com 'Ref.' / 'Item No.' (EN) seguida da linha '序号' (CN)
- Dados a partir da próxima linha
- Cada Ref gera 1+ linhas-variante (STONE COLOR/Plating diferentes);
  nas linhas-variante subsequentes, as colunas Ref/Produto ficam vazias
  -> forward-fill
- Footer: linhas 'total' / 'after X% discount' / 'certificate' sem Ref
  -> descartar (mas certificate pode virar item separado, ver observe)
"""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from .mappings import obter_perfil

logger = logging.getLogger(__name__)


# Mapa de cabeçalho crú (EN/CN/variações) -> chave estável
# Importante: na Invoice ALAN, col1 "Ref."(EN)/"序号"(CN) é NÚMERO SEQUENCIAL
# enquanto col3 "Item No."(EN)/"产品编号"(CN) é o CÓDIGO REAL (SE22101-W).
# Separar para evitar colisão.
_NORMALIZACAO_COLUNAS = {
    # sequencial (col1) - descartado depois, mas precisa de chave própria
    "ref.": "num_seq",
    "ref": "num_seq",
    "序号": "num_seq",
    # categoria / produto
    "产品类别": "categoria_cn",
    "产品编号": "ref",
    "item no.": "ref",
    "dec.": "dec",
    "款式做法以及改版说明": "obs_cn",
    # pedra
    "stone color": "stone_color",
    "石头色": "stone_color",
    "石头色中文": "stone_color_cn",
    "chinese": "stone_color_cn",
    # banho
    "plating": "plating",
    "电镀": "plating",
    # tamanho
    "size 美围": "size",
    # quantidades / pesos
    "q'ty          (pcs)": "qty",
    "q'ty (pcs)": "qty",
    "q'ty(pcs)": "qty",
    "数量（pcs）": "qty",
    "unit weight(g)": "unit_weight",
    "unit weight": "unit_weight",
    "成品单重（g/pcs）": "unit_weight",
    "total wt(g)": "total_wt",
    "总重（g）": "total_wt",
    # precos
    "mossanite stone price by pcs": "stone_price",
    "莫桑石价/件": "stone_price",
    "silver price   (usd/g)": "silver_price",
    "silver price (usd/g)": "silver_price",
    "银价单价按克": "silver_price",
    "labor price   (usd/g)": "labor_price",
    "labor price (usd/g)": "labor_price",
    "工费单价按克": "labor_price",
    "price   (usd/g)": "price_usd_g",
    "price (usd/g)": "price_usd_g",
    "单价按克": "price_usd_g",
    "total               (usd)": "total_usd",
    "total (usd)": "total_usd",
    "总金额": "total_usd",
}


def _detectar_linha_header(df_raw: pd.DataFrame) -> Optional[int]:
    """Encontra índice (0-based) da linha de cabeçalho CN a ser usada.

    Estratégia: preferir sempre a linha com '序号' (header CN) pois ela tem
    todos os campos necessários em PT/ideograma (产品类别, 产品编号, etc.).
    Caso não exista, cair para marcador EN 'item no.' ou 'ref.'.

    Em invoices ALAN/LUIS há 2 linhas header: EN (linha 8) e CN (linha 10).
    Sempre usamos a CN para evitar perda de 产品类别.
    """
    candidatos: list[int] = []
    for i in range(min(30, len(df_raw))):
        linha_vals = [str(v).strip().lower() for v in df_raw.iloc[i].tolist()]
        if any("序号" in v for v in linha_vals):
            candidatos.append(i)
    if candidatos:
        return candidatos[-1]  # última linha com 序号 (header CN final)
    # fallback EN
    for i in range(min(30, len(df_raw))):
        linha_vals = [str(v).strip().lower() for v in df_raw.iloc[i].tolist()]
        if any(v in ("ref.", "ref", "item no.") for v in linha_vals):
            return i
    return None


def _normalizar_nome_coluna(nome: object) -> str:
    if nome is None:
        return ""
    s = str(nome).strip().lower()
    # collapse espaços internos para casar com chaves do mapa
    while "  " in s:
        s = s.replace("  ", " ")
    return _NORMALIZACAO_COLUNAS.get(s, s)


def _e_footer(linha: pd.Series) -> bool:
    """Heurística: linhas que NÃO são item válido (total/discount/certificate
    /resíduo pós-ffill). Em qualquer coluna-chave pode aparecer marcador."""
    # concatena valores stringifyados para checar marcadores em qualquer coluna
    vals_txt = " ".join(
        str(v).strip().lower() for v in linha.tolist()
        if v is not None and not (isinstance(v, float) and pd.isna(v))
    )
    if "total" in vals_txt or "discount" in vals_txt or "certificate" in vals_txt:
        return True
    # Sem qty ou qty==0 -> não é item (captura resíduos pós-ffill vazios)
    qty = linha.get("qty")
    if pd.isna(qty) or qty in (0, "0", "0.0"):
        return True
    # Sem peso unitário -> provável linha de total/summary (qty alta sem peso)
    uw = linha.get("unit_weight")
    if pd.isna(uw) or uw in (0, "0", "0.0"):
        return True
    # Sem ref válido -> não é item
    ref = str(linha.get("ref", "")).strip().lower()
    if ref in ("", "nan", "none"):
        return True
    return False


def limpar_planilha(caminho: str, nome_arquivo: str = "",
                    marca: str = "AL",
                    codigo_fornecedor: str = "012432") -> tuple[pd.DataFrame, dict]:
    """Lê xlsx/csv, detecta header, normaliza, descarta metadata/footer.

    Retorna (DataFrame limpo, perfil_material).
    O perfil é determinado por conteúdo (zirconia vs moissanite), NÃO pelo
    nome do operador (ALAN/LUIS) que pode aparecer no nome do arquivo.

    DataFrame tem colunas estáveis:
        categoria_cn, ref, dec, obs_cn, stone_color, stone_color_cn,
        plating, size, qty, unit_weight, total_wt, stone_price,
        silver_price, labor_price, price_usd_g, total_usd
    """
    # 1. Ler cru
    if str(caminho).lower().endswith((".xlsx", ".xlsm")):
        df_raw = pd.read_excel(caminho, sheet_name=0, header=None, dtype=object)
    elif str(caminho).lower().endswith(".csv"):
        df_raw = pd.read_csv(caminho, header=None, dtype=object)
    else:
        # tentar excel por padrão
        df_raw = pd.read_excel(caminho, sheet_name=0, header=None, dtype=object)

    # 1.5 Detectar tipo de material por CONTEÚDO (zirconia/moissanite).
    # Importante: o prefixo ALAN/LUIS no nome é apenas o operador do time,
    # NÃO é fornecedor. Variação real é o tipo de pedra.
    _, perfil = obter_perfil(nome_arquivo or caminho, df_raw=df_raw,
                             marca=marca, codigo_fornecedor=codigo_fornecedor)

    # 2. Detectar header
    linha_header = _detectar_linha_header(df_raw)
    if linha_header is None:
        raise ValueError(
            "Não foi possível detectar a linha de cabeçalho "
            "(esperado marcador 'Ref.'/'序号' nas primeiras 30 linhas)."
        )

    # 3. Recriar DataFrame com header detectado
    cabecalho = df_raw.iloc[linha_header].tolist()
    df = df_raw.iloc[linha_header + 1:].copy()
    df.columns = [_normalizar_nome_coluna(c) for c in cabecalho]
    df = df.reset_index(drop=True)

    # Descartar colunas sem nome / duplicadas / NaN-string mantendo
    # apenas as chaves estáveis reconhecidas.
    visto: set[str] = set()
    cols_keep: list[str] = []
    for c in df.columns:
        if c in ("", "nan", "none") or c in visto:
            continue
        visto.add(c)
        cols_keep.append(c)
    df = df[cols_keep]

    # 4. Garantir colunas esperadas (mesmo que vazias)
    for col in ("categoria_cn", "ref", "num_seq", "stone_color", "stone_color_cn",
                "plating", "qty", "unit_weight", "labor_price",
                "silver_price", "price_usd_g", "total_usd",
                "stone_price", "size"):
        if col not in df.columns:
            df[col] = None

    # 5. Forward-fill colunas chave (variante herda Ref/Categoria).
    #    Importante: 'ref' é o código real (Item No.); variantes seguintes
    #    costumam ter a célula vazia e devem herdar o código da linha anterior.
    for col in ("ref", "categoria_cn"):
        if col in df.columns:
            df[col] = df[col].ffill()

    # 6. Coerção numérica
    for col in ("qty", "unit_weight", "total_wt", "stone_price",
                "silver_price", "labor_price", "price_usd_g", "total_usd"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 7. Descartar footer
    mascara_footer = df.apply(_e_footer, axis=1)
    n_removidos = int(mascara_footer.sum())
    if n_removidos:
        logger.info("Descartadas %d linhas de footer (total/discount/certificate).", n_removidos)
    df = df[~mascara_footer].reset_index(drop=True)

    # 8. Descartar linhas totalmente vazias
    df = df.dropna(how="all").reset_index(drop=True)

    # 9. Anotar coluna origem ref legível (mantém 'ref' como string)
    df["ref"] = df["ref"].astype("object").astype(str).str.strip()
    df = df[df["ref"].str.len() > 0].reset_index(drop=True)

    return df, perfil


COLUNAS_SAIDA_PC = [
    "categoria", "codigo_fornecedor", "foto", "material", "fornecedor",
    "banho", "pedra", "zirconia", "tamanho", "tipo_pedra", "marca",
    "quantidade", "peso", "labor_price", "silver_price", "dia",
    "unit_price_fob", "preco_vendas", "remarks",
]

# Mapeamento snake_case interno -> colunas EXATAS do MODELO ERP (PT)
# Usado por linhas_para_dataframe_pc para gerar saída compatível.
COLUNAS_PT: dict[str, str] = {
    "categoria": "Categoria",
    "codigo_fornecedor": "Código do Fornecedor",
    "foto": "Foto",
    "material": "Material",
    "fornecedor": "Fornecedor",
    "banho": "Banho",
    "pedra": "Pedra",
    "zirconia": "Zirconia",
    "tamanho": "Tamanho",
    "tipo_pedra": "TIPO PEDRA",
    "marca": "MARCA",
    "quantidade": "Quantidade",
    "peso": "Peso",
    "labor_price": "Labor Price   (USD/g)  ",
    "silver_price": " Silver Price   (USD/g) ",
    "dia": "Dia",
    "unit_price_fob": "Unit Price per piece FOB (USD) ",
    "preco_vendas": "Preço de Vendas",
    "remarks": "Remarks",
}


def linha_para_dict(linha: pd.Series) -> dict:
    """Converte uma linha limpa em dict pronto para o prompt do LLM."""
    return {
        "categoria_cn": _safe_str(linha.get("categoria_cn")),
        "ref": _safe_str(linha.get("ref")),
        "obs_cn": _safe_str(linha.get("obs_cn")),
        "stone_color": _safe_str(linha.get("stone_color")),
        "stone_color_cn": _safe_str(linha.get("stone_color_cn")),
        "plating": _safe_str(linha.get("plating")),
        "size": _safe_str(linha.get("size")),
        "qty": _safe_num(linha.get("qty")),
        "unit_weight": _safe_num(linha.get("unit_weight")),
        "total_wt": _safe_num(linha.get("total_wt")),
        "stone_price": _safe_num(linha.get("stone_price")) or 0.0,
        "silver_price": _safe_num(linha.get("silver_price")) or 0.0,
        "labor_price": _safe_num(linha.get("labor_price")) or 0.0,
        "price_usd_g": _safe_num(linha.get("price_usd_g")),
        "total_usd": _safe_num(linha.get("total_usd")),
    }


def _safe_str(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def _safe_num(v) -> float:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def linhas_para_dataframe_pc(linhas_processadas: list[dict]) -> pd.DataFrame:
    """Converte lista de dicts (LinhaPedidoCompra.model_dump) em DataFrame
    com colunas EXATAS do MODELO ERP (PT).
    """
    df = pd.DataFrame(linhas_processadas)
    # Garantir todas as colunas internas presentes
    for c in COLUNAS_SAIDA_PC:
        if c not in df.columns:
            df[c] = None
    df = df[COLUNAS_SAIDA_PC]
    # Renomear snake_case -> colunas PT do ERP
    df = df.rename(columns=COLUNAS_PT)
    return df

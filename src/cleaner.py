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
import re
from typing import Optional

import pandas as pd

from .mappings import obter_perfil, resolver_banho, resolver_categoria

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
    "platting": "plating",
    "plate": "plating",
    "plate description": "plating",
    "plating color": "plating",
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
    # ── Invoice CNY (fornecedor Renato/CEREJA) ──
    # Header: "No. | Code | Description | Weight | Quantity | Total Weight |
    #         Labor Price | Silver Price | Discount | Amount | ...
    # Unidades: CNY/pc, CNY/g. Conversão USD feita em _aplicar_conversao_cny.
    "no.": "num_seq",
    "code": "ref",
    "description": "categoria_en",
    "weight": "unit_weight",
    "quantity": "qty",
    "total weight": "total_wt",
    "labor price": "labor_price_cny",
    "silver price": "silver_price_cny",
    "discount": "discount_cny",
    "amount": "amount_cny",
    "valor unitario cny": "valor_unit_cny",
    "valor unitario usd": "valor_unit_usd_fornec",
    "silver price usd/g": "silver_usd_g_fornec",
    "labor usd/g": "labor_usd_g_fornec",
    "stone weight": "stone_weight",
    "pi": "pi_ref",
    # ── Invoice Grant/IZABEL (PT-fed, EN header puro) ──
    # Header: "Modelo novitah | [dup] | Pic. | Item No. | Type | Stone |
    #         Plating | Size | Quantity | novitah | encomenda | Price | Amount"
    # Colunas ignoradas (operador internas): Modelo novitah, Pic., novitah,
    # encomenda, Unnamed: 13 (preço da pedra by pcs — descartado, não usado
    # no output do PC). Amount = Price × Quantity (total) — também descartado.
    # 'quantity' já mapeado p/ qty (linha 90, conflito CNY sem colisão real
    # pois chave estável mesma; mapeamento é idempotente neste caso).
    "type": "categoria_en",
    "stone": "stone_color",
    # 'price' aqui é preço por peça FOB em USD (Grant já calculado pelo
    # fornecedor). Map p/ 'price_unit_fob' distinto de 'price_usd_g' para
    # não colidir com preço por grama do formato ALAN/LUIS.
    "price": "price_unit_fob",
}


def _detectar_linha_header(df_raw: pd.DataFrame, max_linhas: int = 30) -> Optional[int]:
    """Detecta a linha de cabeçalho que sera usada para montar o DataFrame.

    Pipeline unico (score-based) substitui estrategia anterior de fallbacks
    encadeados. Cada uma das primeiras ``max_linhas`` linhas é pontuada
    pela presenca de marcadores conhecidos; a linha de maior score vence.

    Marcadores e pesos:
      - '序号' (header CN, USD invoices Alan/Luis)  → peso 4 (decisivo)
      - 'ref.'/'ref'/'item no.'                     → peso 2 (item no.=3 p/ Grant)
      - '产品编号' (código do produto, CN)          → peso 2
      - 'no.'/'code'/'description' (header CNY)     → peso 1 cada
      - 'stone color' / 'plating' / 'weight'         → peso 0.5 cada
        (headers auxiliares; somados discriminam)
      - 'type'/'stone'/'quantity' (header Grant/IZABEL) → peso 2 cada
        (header EN puro, "Item No." já peso 3; type+plating+quantity+stone
        discriminam vs linha de dados com item no. isolado)
      - 'size'/'price'/'amount' (header Grant)       → peso 1 cada

    Critério de definição: score ≥ 2. Empate → última linha (header
    geralmente aparece DEPOIS de linhas de metadata/title).

    Robusto contra:
      - linhas de title/metadata com 1 marcador isolado;
      - linhas de dados que casualmente mencionem 'ref' numa célula;
      - headers em dois idiomas empilhados (EN+CN): o CN vence (peso 4).
    """
    if df_raw is None or len(df_raw) == 0:
        return None
    limite = min(max_linhas, len(df_raw))
    melhor_idx: Optional[int] = None
    melhor_score: float = 0.0
    for i in range(limite):
        vals = [str(v).strip().lower() for v in df_raw.iloc[i].tolist()
                if v is not None and not (isinstance(v, float) and pd.isna(v))]
        if not vals:
            continue
        score = 0.0
        for v in vals:
            if "序号" in v:
                score += 4
            elif v in ("ref.", "ref") or v.startswith("item no."):
                # Grant/IZABEL usa "Item No." como Código FORNECEDOR
                # (preço 3 p/ vencer linhas de dados com item no. citado).
                # ALAN/LUIS escala p/ 2 (não-vencedor isolado).
                score += 3 if v == "item no." else 2
            elif v == "产品编号":
                score += 2
            elif v in ("no.", "code", "description"):
                score += 1
            elif v in ("type", "stone", "quantity"):
                score += 2
            elif v in ("size", "price", "amount"):
                score += 1
            elif v == "stone color" or v.startswith("plating") or v == "weight":
                score += 0.5
        if score >= melhor_score and score > 0:
            melhor_score = score
            melhor_idx = i
    if melhor_score < 2.0:
        return None
    return melhor_idx


def detectar_fator_cny(df_raw: pd.DataFrame, header_idx: int,
                       max_busca: int = 5) -> Optional[float]:
    """Localiza cotação CNY/USD em metadata.

    Formato Renato: L0 col 'amount/quantidade' como texto;
    L1 mesma coluna contém valor numérico (ex.: 6.72).

    Formato teste.xlsx: fator não está explícito; aparece "Total USD:"
    no footer. Calculado como amount_cny_total / total_usd_footer.

    Estratégia (3 níveis):
    1. Varre linhas [header_idx-max_busca, header_idx) por única célula
       numérica > 1 e < 20 (faixa plausível de cotação CNY/USD).
    2. Se não achar, varre linhas DEPOIS do header em busca de mesmo padrão.
    3. Se ainda não achar, tenta calcular via colunas: se footer tem
       'total usd' e 'amount' (somatório), fator = amount_total / usd_total.

    Devolve float ou None (não é invoice CNY / cotação ausente).
    """
    if header_idx is None or header_idx < 1:
        return None

    # Guard: header com '序号' → invoice USD (Alan/Luis). Não procura fator.
    # Só invoices CNY (Renato/CEREJA) têm header 'No. | Code | Description'.
    hdr_vals = [str(v or "").strip().lower()
                for v in df_raw.iloc[header_idx].tolist()]
    if any("序号" in v for v in hdr_vals):
        return None

    inicio = max(0, header_idx - max_busca)

    # Localiza coluna marcada 'amount/quantidade' em linhas acima do header
    col_alvo: Optional[int] = None
    for r in range(inicio, header_idx):
        for c in range(len(df_raw.columns)):
            v = str(df_raw.iloc[r, c] or "").strip().lower()
            if "amount" in v and ("quantidade" in v or "quant" in v):
                col_alvo = c
                break
        if col_alvo is not None:
            break

    def _varrer_intervalo(r_start: int, r_end: int) -> Optional[float]:
        """Varre linhas [r_start, r_end) buscando célula numérica em (1, 20)."""
        if r_start < 0:
            r_start = 0
        if r_end > len(df_raw):
            r_end = len(df_raw)
        cands: list[tuple[float, int, int]] = []
        for r in range(r_start, r_end):
            for c in range(len(df_raw.columns)):
                v = df_raw.iloc[r, c]
                if v is None or isinstance(v, str):
                    continue
                try:
                    num = float(v)
                except (TypeError, ValueError):
                    continue
                if 1.0 < num < 20.0:
                    cands.append((num, r, c))
        if not cands:
            return None
        # Prefere célula na coluna marcada; senão primeiro candidato
        if col_alvo is not None:
            for num, r, c in cands:
                if c == col_alvo:
                    return num
        return cands[0][0]

    def _varrer_intervalo_footer(r_start: int, r_end: int,
                                  col_pref: Optional[int]) -> Optional[float]:
        """Varre rodapé atrás de fator — ignora linhas com 'code'/'ref' válido.

        O nível 2 varre linhas depois do header, mas DESCONSIDERA linhas
        de dados (que têm ref/qty válido). Assim não confunde peso unitário
        (ex.: 5.96) com fator de cotação.
        Procura apenas em linhas que:
        - têm célula textual (footer markers: 'total', 'usd', 'rate'),
          OU
        - não têm coluna 'code'/'ref' preenchida (linhas de resumo).
        """
        if r_start < 0:
            r_start = 0
        if r_end > len(df_raw):
            r_end = len(df_raw)
        # identify coluna de 'code'/'ref' no header
        hdr_row = df_raw.iloc[header_idx].tolist()
        col_code = None
        for ci, cv in enumerate(hdr_row):
            cvn = str(cv or "").strip().lower()
            if cvn in ("code", "ref", "item no.", "产品编号"):
                col_code = ci
                break
        cands: list[tuple[float, int, int]] = []
        for r in range(r_start, r_end):
            # ignora linha de dados (col_code preenchida e não-numérica)
            if col_code is not None:
                v_code = df_raw.iloc[r, col_code]
                if v_code is not None and not (
                    isinstance(v_code, float) and pd.isna(v_code)
                ):
                    continue
            for c in range(len(df_raw.columns)):
                v = df_raw.iloc[r, c]
                if v is None or isinstance(v, str):
                    continue
                try:
                    num = float(v)
                except (TypeError, ValueError):
                    continue
                if 1.0 < num < 20.0:
                    cands.append((num, r, c))
        if not cands:
            return None
        if col_pref is not None:
            for num, r, c in cands:
                if c == col_pref:
                    return num
        return cands[0][0]

    # Nível 1 — acima do header
    fator = _varrer_intervalo(inicio, header_idx)
    if fator is not None:
        return fator

    # Nível 2 — abaixo do header, SOMENTE em linhas sem 'ref'/'code' (footer)
    # Evita capturar pesos/preços unitários como fator (ex.: unit_weight=5.96)
    fim = min(len(df_raw), header_idx + 50)
    fator = _varrer_intervalo_footer(header_idx + 1, fim, col_alvo)
    if fator is not None:
        logger.info("Fator CNY detectado abaixo do header: %s", fator)
        return fator

    # Nível 3 — calcula via footer: 'in total' (amount CNY) vs 'total usd'
    # Procura celulas com marcadores textuais e extrai valores associados.
    try:
        total_cny: Optional[float] = None
        total_usd_val: Optional[float] = None
        amount_col_local = None
        hdr_row = df_raw.iloc[header_idx].tolist()
        for hci, hcv in enumerate(hdr_row):
            if hcv is not None and "amount" in str(hcv).strip().lower():
                amount_col_local = hci
                break
        for r in range(header_idx + 1, min(len(df_raw), header_idx + 30)):
            row = df_raw.iloc[r].tolist()
            txt_linha = " ".join(str(v or "").strip().lower() for v in row
                                  if v is not None and isinstance(v, str))
            # 'in total' com valor numerico na coluna amount
            if "in total" in txt_linha and amount_col_local is not None:
                v = row[amount_col_local]
                if v is not None and not isinstance(v, str):
                    try:
                        total_cny = float(v)
                    except (TypeError, ValueError):
                        pass
            # 'total usd' em qualquer coluna: valor numerico na proxima coluna
            for c, val in enumerate(row):
                txt = str(val or "").strip().lower()
                if "total usd" in txt or ("usd" in txt and "total" in txt):
                    for c2 in range(c + 1, len(row)):
                        v2 = row[c2]
                        if v2 is None or isinstance(v2, str):
                            continue
                        try:
                            cand = float(v2)
                        except (TypeError, ValueError):
                            continue
                        if not pd.isna(cand) and cand > 0:
                            total_usd_val = cand
                            break
                    break
        if total_cny is not None and total_usd_val is not None and total_usd_val > 0:
            calc = total_cny / total_usd_val
            if 1.0 < calc < 20.0:
                logger.info(
                    "Fator CNY calculado via footer: amount_total=%s / usd=%s = %s",
                    total_cny, total_usd_val, calc)
                return calc
    except Exception as e:
        logger.warning("cálculo fator CNY via footer falhou: %s", e)

    return None


def _aplicar_conversao_cny(df: pd.DataFrame, fator: float) -> pd.DataFrame:
    """Converte colunas CNY para USD usando fator (cotação CNY/USD).

    Fórmulas (validadas contra sample E-72):
      amount_cny_total = amount_cny (já total por lote)  [CNY]
      total_usd = amount_cny / fator                       [USD por lote]
      silver_price = silver_price_cny / fator              [USD/g]
      valor_unit_usd = total_usd / qty                     [USD/pc]
      price_usd_g = valor_unit_usd / unit_weight            [USD/g peça]
      labor_price = price_usd_g - silver_price              [USD/g (labor puro)]

    Comentário: labor_price = USD/g total da peça MENOS Silver USD/g,
    conforme definido pelo user (regra de negócio CNY).
    """
    if fator is None or fator is None or fator <= 0:
        return df
    df = df.copy()
    # Garantir colunas CNY numéricas (fonte original sempre em CNY)
    for col in ("amount_cny", "silver_price_cny",
                "labor_price_cny", "discount_cny", "valor_unit_cny"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    # amount_cny → total_usd. Idempotente: sempre sobrescreve a partir
    # da fonte CNY (não soma), para re-conversões com fator diferente.
    if "amount_cny" in df.columns:
        df["total_usd"] = df["amount_cny"] / fator
    # silver CNY → USD/g (sobrescreve)
    if "silver_price_cny" in df.columns:
        df["silver_price"] = df["silver_price_cny"] / fator
    # labor + unit_price via fórmula definida pelo user
    if {"total_usd", "qty", "unit_weight"} <= set(df.columns):
        qty = df["qty"].clip(lower=1)  # evita div/0
        uw = df["unit_weight"].clip(lower=0.0001)
        valor_unit_usd = df["total_usd"] / qty
        df["price_usd_g"] = valor_unit_usd / uw
        if "silver_price" in df.columns:
            # labor_price = USD/g total da peça - Silver USD/g
            df["labor_price"] = (df["price_usd_g"] - df["silver_price"]).clip(lower=0)
    return df


def _detectar_coluna_tamanho(df_raw: pd.DataFrame, linha_header: int) -> Optional[int]:
    """Escaneia raw DataFrame ANTES da remoção do header para achar coluna de tamanho.

    Estratégia (3 níveis):
    1. Todas as linhas de header (CN + EN) com 'size'/'美围'
    2. Primeiras linhas de dados: padrão de anel (#5 - 40, #6-35...)
    3. Primeiras linhas de dados: padrão de medida (NNcm, NN+NN+NNcm)

    Retorna índice da coluna ou None.
    """
    # Nível 1 — escanear TODAS as linhas de cima até o CN header
    # (o EN header costuma ter "SIZE 美围" que some no CN header)
    for row_i in range(linha_header, -1, -1):
        row_vals = df_raw.iloc[row_i].tolist()
        for col_idx, val in enumerate(row_vals):
            txt = str(val).strip().lower()
            if "size" in txt or "美围" in txt:
                return col_idx

    # Nível 2-3 — escanear até 10 linhas de dados
    # (algumas invoices têm 5+ linhas de brincos antes do primeiro item com tamanho)
    max_row = min(linha_header + 12, len(df_raw))
    for row_i in range(linha_header + 1, max_row):
        row_vals = df_raw.iloc[row_i].tolist()
        for col_idx, val in enumerate(row_vals):
            txt = str(val).strip()
            if not txt:
                continue
            if re.search(r"#\s*\d\s*[-–]\s*\d+", txt):
                return col_idx
            if re.search(r"\d{1,3}(?:[.,]\d+)?\s*cm", txt, re.IGNORECASE):
                return col_idx
            if re.search(r"^\d{1,3}(?:[.,]\d+)?(?:\+\d{1,3}(?:[.,]\d+)?)+$", txt):
                return col_idx

    return None


def _normalizar_nome_coluna(nome: object) -> str:
    if nome is None:
        return ""
    if isinstance(nome, float) and pd.isna(nome):
        return ""
    s = str(nome).strip().lower()
    # Normalizar whitespace interno (newlines, tabs, espaços múltiplos)
    s = re.sub(r"\s+", " ", s)
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
    # Item válido se tem categoria (ou plating/stone_color) E qty>0.
    # Caso "new development": itens podem não ter ref nem unit_weight definidos
    # ainda, mas são pedidos reais (categoria + qty plausível).
    cat = str(linha.get("categoria_cn", "")).strip().lower()
    plating = str(linha.get("plating", "")).strip().lower()
    stone = str(linha.get("stone_color", "")).strip().lower()
    tem_categoria = cat not in ("", "nan", "none", "total") and "total" not in cat
    tem_pedra = plating not in ("", "nan", "none") or stone not in ("", "nan", "none")
    qty = linha.get("qty")
    qty_positiva = False
    try:
        qty_positiva = float(qty) > 0
    except (TypeError, ValueError):
        pass
    if (tem_categoria or tem_pedra) and qty_positiva:
        return False
    # Sem qty ou qty==0 -> não é item (captura resíduos pós-ffill vazios)
    if pd.isna(qty) or qty in (0, "0", "0.0"):
        return True
    # Footer row: qty>0 mas ref/price/stone/plating todos vazios
    # -> linha de total/summary (Grant) ou resíduo pós-ffill (ALAN).
    # Marcador decisivo: price_unit_fob vazio E stone_color vazio E
    # plating vazio = não há dados de produto, só qty/amount total.
    ref = str(linha.get("ref", "")).strip().lower()
    price = linha.get("price_unit_fob")
    price_vazio = price is None or (isinstance(price, float) and pd.isna(price))
    if price_vazio and not tem_pedra:
        return True
    # Sem ref válido -> não é item
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

    Detecta moeda automaticamente:
      - USD (invoices Alan/Luis): header com '序号' ou 'Ref./item no.'
      - CNY (invoices Renato/CEREJA): header com 'No. | Code | Description'
        e metadata com fator CNY/USD. Conversão USD aplicada em cleaner;
        perfil['moeda']='CNY' e perfil['fator_cny_sugerido']=float.

    DataFrame tem colunas estáveis:
        categoria_cn, categoria_en, ref, num_seq, dec, obs_cn,
        stone_color, stone_color_cn, plating, size, qty, unit_weight,
        total_wt, stone_price, silver_price, labor_price, price_usd_g,
        total_usd (em USD sempre).
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
            "(esperado marcador 'Ref.'/'序号' (USD) ou 'No. | Code | "
            "Description' (CNY) nas primeiras 30 linhas)."
        )

    # 2.1 Detectar sheet CNY (renato/cereja). Fator > 0 → invoice em CNY.
    fator_cny = detectar_fator_cny(df_raw, linha_header)
    moeda = "CNY" if fator_cny is not None else "USD"
    if moeda == "CNY":
        perfil["moeda"] = "CNY"
        perfil["fator_cny_sugerido"] = fator_cny
        logger.info("Invoice CNY detectada. Fator sugerido: %s", fator_cny)
    else:
        perfil["moeda"] = "USD"

    # 2.5 Detectar coluna de tamanho no raw DF ANTES de descartar o header.
    #     Colunas numeradas do cabeçalho CN (ex.: "3","4","5"...) engolem a
    #     coluna "SIZE 美围". Escaneamos as primeiras linhas de dados por
    #     padrões de tamanho (anel #5-40 / corrente NNcm) e forçamos o nome
    #     da coluna para "size" para o dado não se perder.
    col_tamanho = _detectar_coluna_tamanho(df_raw, linha_header)

    # 3. Recriar DataFrame com header detectado
    cabecalho = df_raw.iloc[linha_header].tolist()

    if col_tamanho is not None:
        nome_orig = str(cabecalho[col_tamanho]).strip().lower()
        # Só força remapeamento se a coluna NÃO for naturalmente "size"
        if _NORMALIZACAO_COLUNAS.get(nome_orig, nome_orig) != "size":
            cabecalho[col_tamanho] = "size"

    df = df_raw.iloc[linha_header + 1:].copy()
    cols_norm = [_normalizar_nome_coluna(c) for c in cabecalho]
    # Descartar colunas sem nome / duplicadas ANTES do assign para evitar
    # DataFrame com colunas repetidas (pd.to_numeric quebra em dup).
    # Mantemos apenas primeira ocorrência de cada chave estável.
    visto_pre: set[str] = set()
    idx_keep: list[int] = []
    cols_keep_pre: list[str] = []
    for ci, cn in enumerate(cols_norm):
        if cn in ("", "nan", "none") or cn in visto_pre:
            continue
        visto_pre.add(cn)
        idx_keep.append(ci)
        cols_keep_pre.append(cn)
    df = df.iloc[:, idx_keep].copy()
    df.columns = cols_keep_pre
    df = df.reset_index(drop=True)

    # Descartar colunas sem nome / duplicadas / NaN-string mantendo
    # apenas as chaves estáveis reconhecidas (já feito acima; mantém
    # por compatibilidade).
    visto: set[str] = set()
    cols_keep: list[str] = []
    for c in df.columns:
        if c in ("", "nan", "none") or c in visto:
            continue
        visto.add(c)
        cols_keep.append(c)
    df = df[cols_keep]

    # 4. Garantir colunas esperadas (mesmo que vazias)
    colunas_padrao = ("categoria_cn", "categoria_en", "ref", "num_seq",
                      "stone_color", "stone_color_cn", "plating", "size",
                      "qty", "unit_weight", "total_wt", "stone_price",
                      "silver_price", "labor_price", "price_usd_g", "total_usd",
                      "price_unit_fob")
    colunas_cny = ("amount_cny", "silver_price_cny", "labor_price_cny",
                   "discount_cny", "valor_unit_cny")
    for col in colunas_padrao + colunas_cny:
        if col not in df.columns:
            df[col] = None

    # 5. Forward-fill colunas chave (variante herda Ref/Categoria).
    #    Importante: 'ref' é o código real (Item No.); variantes seguintes
    #    costumam ter a célula vazia e devem herdar o código da linha anterior.
    #    Guard: ref só herda se a CATEGORIA ORIGINAL também estiver vazia
    #    (mesmo item, variante de pedra/banho). Se categoria muda é produto
    #    DISTINTO sem código — não herdamos ref (caso "new development" sem
    #    código atribuído). Para decidir capturamos o estado original da
    #    categoria ANTES do ffill dela.
    #    Adicionalmente, footer rows (totais/discount) não devem herdar via
    #    ffill — marcamos-as pré-ffill com base em qty vazia/zero (linhas de
    #    footer clássicas ALAN/LUIS). Footer com qty alto (total Grant) é
    #    tratado depois em _e_footer (ref vazia + price vazio).
    if "ref" in df.columns:
        cat_orig_nan = (df["categoria_cn"].isna() if "categoria_cn" in df.columns
                        else pd.Series([True] * len(df)))
    qty_orig = df["qty"] if "qty" in df.columns else pd.Series([None] * len(df))
    nao_qty_vazia = ~(qty_orig.isna() | qty_orig.isin([0, "0", "0.0"]))
    for col in ("categoria_cn", "categoria_en"):
        if col in df.columns:
            df[col] = df[col].where(nao_qty_vazia)
            df[col] = df[col].ffill()
    if "ref" in df.columns:
        # ffill ref: apenas onde categoria original era NaN (variante mesma)
        ffill_mask = df["ref"].isna() & cat_orig_nan & nao_qty_vazia
        if ffill_mask.any():
            last_ref = None
            for i in range(len(df)):
                cur_ref = df.at[df.index[i], "ref"]
                is_na = (isinstance(cur_ref, float) and pd.isna(cur_ref)) or cur_ref is None or (isinstance(cur_ref, str) and not cur_ref.strip())
                if not is_na:
                    last_ref = cur_ref
                if ffill_mask.iloc[i] and last_ref is not None:
                    df.at[df.index[i], "ref"] = last_ref

    # 6. Coerção numérica
    for col in ("qty", "unit_weight", "total_wt", "stone_price",
                "silver_price", "labor_price", "price_usd_g", "total_usd",
                "price_unit_fob",
                "amount_cny", "silver_price_cny", "labor_price_cny",
                "discount_cny", "valor_unit_cny"):
        if col in df.columns:
            serie = df[col].squeeze()
            df[col] = pd.to_numeric(serie, errors="coerce")

    # 6.5 Conversão CNY → USD (only quando moeda=CNY).
    #     Path USD (Alan/Luis) não passa aqui — flag previne.
    if moeda == "CNY" and fator_cny is not None:
        df = _aplicar_conversao_cny(df, fator_cny)

    # 7. Descartar footer
    mascara_footer = df.apply(_e_footer, axis=1)
    n_removidos = int(mascara_footer.sum())
    if n_removidos:
        logger.info("Descartadas %d linhas de footer (total/discount/certificate).", n_removidos)
    df = df[~mascara_footer].reset_index(drop=True)

    # 8. Descartar linhas totalmente vazias
    df = df.dropna(how="all").reset_index(drop=True)

    # 9. Anotar coluna origem ref legível (mantém 'ref' como string)
    #    NaN/None viram string vazia (itens "new development" sem código).
    df["ref"] = df["ref"].astype("object").fillna("").astype(str).str.strip()
    df["ref"] = df["ref"].replace({"nan": "", "None": "", "NaN": ""})
    # Manter linha se tem ref válido OU é item "new development" sem código
    # (categoria preenchida + qty>0). Invoices novas podem ter itens pendentes
    # de atribuição de código pelo fornecedor.
    ref_valido = df["ref"].str.len() > 0
    item_sem_codigo = pd.Series(False, index=df.index)
    if "categoria_cn" in df.columns and "qty" in df.columns:
        cat_ok = ~df["categoria_cn"].astype(str).str.strip().isin(
            ["", "nan", "None", "NaN"])
        qty_ok = df["qty"].fillna(0).astype(float) > 0
        item_sem_codigo = cat_ok & qty_ok & ~ref_valido
    df = df[ref_valido | item_sem_codigo].reset_index(drop=True)

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
        "categoria_en": _safe_str(linha.get("categoria_en")),
        "ref": _safe_str(linha.get("ref")),
        "obs_cn": _safe_str(linha.get("obs_cn")),
        "stone_color": _safe_str(linha.get("stone_color")),
        "stone_color_cn": _safe_str(linha.get("stone_color_cn")),
        "plating": _safe_str(linha.get("plating")),
        "size": _safe_str(linha.get("size")),
        # Texto onde costuma vir a medida de tamanho (corrente/pulseira) ou
        # a distribuição de tamanhos (anel "#5 - 40 #6 - 35 ..."). Pode estar
        # na coluna de descrição/obs da invoice.
        "descricao_tamanho": _safe_str(linha.get("obs_cn")) or
                             _safe_str(linha.get("size")),
        "qty": _safe_num(linha.get("qty")),
        "unit_weight": _safe_num(linha.get("unit_weight")),
        "total_wt": _safe_num(linha.get("total_wt")),
        "stone_price": _safe_num(linha.get("stone_price")) or 0.0,
        "silver_price": _safe_num(linha.get("silver_price")) or 0.0,
        "labor_price": _safe_num(linha.get("labor_price")) or 0.0,
        "price_usd_g": _safe_num(linha.get("price_usd_g")),
        "total_usd": _safe_num(linha.get("total_usd")),
        # Grant/IZABEL: preço por peça FOB já calculado pelo fornecedor.
        # LLM copia direto p/ unit_price_fob (sem labor+silver*peso).
        "price_unit_fob": _safe_num(linha.get("price_unit_fob")),
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

    Pós-processamento por marca (PC final):
      - banho e categoria convertidos para a terminologia da marca
        escolhida pelo operador (AL/GR/NV).
      - colunas 'pedra' e 'zirconia' deixadas VAZIAS — o usuário
        define esses valores manualmente após receber o PC.
      - Marca NV: remove colunas Labor Price, Silver Price e Dia
        (modelo ERP da NV não inclui breakdown de preço).
    """
    linhas_sanitizadas: list[dict] = []
    marca_sessao = ""
    for linha in linhas_processadas:
        nova = dict(linha)
        marca = (nova.get("marca") or "").upper().strip()
        if marca:
            marca_sessao = marca
        nova["banho"] = resolver_banho(str(nova.get("banho", "")), marca)
        nova["categoria"] = resolver_categoria(str(nova.get("categoria", "")), marca)
        # Pedra e Zirconia: vazias no PC final — usuário define.
        nova["pedra"] = ""
        nova["zirconia"] = ""
        linhas_sanitizadas.append(nova)
    df = pd.DataFrame(linhas_sanitizadas)
    # Garantir todas as colunas internas presentes
    for c in COLUNAS_SAIDA_PC:
        if c not in df.columns:
            df[c] = None
    df = df[COLUNAS_SAIDA_PC]
    # Renomear snake_case -> colunas PT do ERP
    df = df.rename(columns=COLUNAS_PT)
    # Marca NV: remover colunas Labor Price, Silver Price e Dia
    if marca_sessao == "NV":
        cols_drop = [
            COLUNAS_PT["labor_price"],
            COLUNAS_PT["silver_price"],
            COLUNAS_PT["dia"],
        ]
        df = df.drop(columns=[c for c in cols_drop if c in df.columns])
    return df

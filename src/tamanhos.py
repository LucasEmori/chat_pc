"""Regras de Tamanho do Pedido de Compra por categoria.

Roda DEPOIS do LLM e ANTES de montar o DataFrame final — é puramente
determinística, não depende do modelo.

Regras (espelhadas das samples reais samples/Pedidos de Compra/000345-000355):
- ANEL: a invoice traz o tamanho bruto como "#5 - 40 #6 - 35 #7 - 45 ..." no
  campo tamanho. Expandimos 1 linha em N (uma por tamanho 5-9), cada uma com
  quantidade ABSOLUTA por tamanho (não porcentagem — padrão validado nas
  samples: tam=05 qty=40).
- BRINCO / BRACELETE: tamanho = "0".
- CORRENTE / COLAR / PULSEIRA: somar medidas "NN[,.]NNcm + NNcm + ..." (ex.
  "15,5CM+1CM+1CM" -> 17.5 -> "18"). Se não casar -> duvida_pendente.
- Demais categorias: mantém.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Categorias cujo tamanho é sempre "0"
_CATEGORIAS_ZERO = {"BRINCO", "BRACELETE", "PINGENTE", "ARGOLA", "BROCHE",
                    "CONJUNTO", "CERTIFICADO"}

# Categorias cujo tamanho vem de medida (cm) na invoice
_CATEGORIAS_MEDIDA = {"CORRENTE", "COLAR", "PULSEIRA"}

# Regex para anel: "#5 - 40", "#6 -35", "#7–45" etc.
_RE_ANEL = re.compile(r"#\s*(\d)\s*[-–]\s*(\d+)", re.IGNORECASE)
# Variante percentual: "#6-15%", "#7 - 50%", "#8-35%"
_RE_ANEL_PCT = re.compile(r"#\s*(\d)\s*[-–]\s*(\d+(?:[.,]\d+)?)\s*%", re.IGNORECASE)

# Regex para medidas: "15,5CM", "1CM", "40 cm"
_RE_MEDIDA = re.compile(r"(\d{1,3}(?:[.,]\d+)?)\s*cm", re.IGNORECASE)



_RE_NUMERO = re.compile(r"^\s*(\d{1,3}(?:[.,]\d+)?)", re.IGNORECASE)


def extrair_tamanho_cm(texto: str) -> Optional[int]:
    """Soma todas as medidas no texto e retorna o inteiro truncado.

    "15,5CM+1CM+1CM,延长链..." -> 17
    "40+2.5+2.5CM" -> 45
    "15,5 cm + 1,0 +1,0，..." -> 17
    "40+2,5+2,5，延长链同原链条" -> 45
    "42CM" -> 42
    Retorna None se nenhuma medida casar.
    """
    if not texto:
        return None

    # Se houver parcelas separadas por '+' com ao menos 2 numéricas,
    # normaliza cada parcela numérica com sufixo CM (medida de corrente
    # mesmo sem unidade explícita, ex.: "40+2,5+2,5，延长链...").
    if "+" in texto:
        partes = texto.split("+")
        # Só normaliza se parecer medida (2+ partes numéricas)
        nums = sum(1 for p in partes if _RE_NUMERO.match(p.strip()))
        if nums >= 2:
            norm = []
            for p in partes:
                p_strip = p.strip()
                if _RE_MEDIDA.search(p_strip):
                    norm.append(p_strip)
                else:
                    m = _RE_NUMERO.match(p_strip)
                    if m:
                        num = m.group(1)
                        rest = p_strip[m.end():]
                        norm.append(num + "cm" + rest)
                    else:
                        norm.append(p_strip)
            texto = "+".join(norm)

    matches = _RE_MEDIDA.findall(texto)
    if not matches:
        return None
    total = 0.0
    for m in matches:
        total += float(m.replace(",", "."))
    # Trunca (int), não arredonda — convenção das samples reais
    return int(total)


def _parse_anel(tamanho_bruto: str) -> tuple[list[tuple[str, int]], bool]:
    """Extrai ([(tamanho, valor), ...], is_percentual).

    Se is_percentual=True: valor é percentual 1-100 e precisa de
    quantidade total da linha para calcular qty absoluta.
    Se False: valor é quantidade absoluta.
    """
    if not tamanho_bruto:
        return [], False
    pares_pct = _RE_ANEL_PCT.findall(tamanho_bruto)
    if pares_pct:
        pares: list[tuple[str, int]] = []
        for tam, pct in pares_pct:
            try:
                p = int(float(pct.replace(",", ".")))
            except ValueError:
                continue
            if p > 0:
                pares.append((tam.zfill(2), p))
        if pares:
            return pares, True
    pares = []
    for tam, qty in _RE_ANEL.findall(tamanho_bruto):
        try:
            q = int(float(qty.replace(",", ".")))
        except ValueError:
            continue
        if q > 0:
            pares.append((tam.zfill(2), q))
    return pares, False


def expandir_linhas(linha: dict) -> list[dict]:
    """Aplica a regra de tamanho a uma LinhaPedidoCompra (dict).

    Retorna 1+ linhas. Anel vira N linhas (uma por tamanho). Demais categorias
    devolvem 1 linha com tamanho normalizado. Se a categoria exige medida e
    esta não pôde ser inferida, marca duvida_pendente=True.
    """
    cat = (linha.get("categoria") or "").upper().strip()
    tamanho = str(linha.get("tamanho") or "").strip()

    # ANEL: marcar para revisão humana, não expandir automaticamente
    if cat == "ANEL" and not linha.get("_ja_expandido"):
        pares, is_pct = _parse_anel(tamanho)
        if not pares:
            # sem tamanhos parseáveis — marca dúvida em vez de engolir
            nova = dict(linha)
            nova["duvida_pendente"] = True
            motivo = (nova.get("motivo_duvida") or "")
            if "Tamanho" not in motivo:
                nova["motivo_duvida"] = (
                    (motivo + " | " if motivo else "") +
                    f"Tamanho do anel não pôde ser interpretado. "
                    f"Texto recebido: '{tamanho[:80]}'"
                )
            nova["confianca"] = min(float(nova.get("confianca") or 1.0), 0.5)
            return [nova]
        # Se percentual, converte para quantidade absoluta usando qty total
        if is_pct:
            qty_total = int(linha.get("quantidade") or 0)
            if qty_total <= 0:
                # sem qty total, mantém proposta como pct e marca dúvida
                nova = dict(linha)
                nova["_proposta_expansao_anel"] = [
                    {"tamanho": t, "quantidade": p} for t, p in pares
                ]
                nova["duvida_pendente"] = True
                nova["motivo_duvida"] = (
                    (nova.get("motivo_duvida") or "") +
                    " | Anel com tamanhos em % – quantidade total ausente."
                )
                nova["confianca"] = min(float(nova.get("confianca") or 1.0), 0.5)
                return [nova]
            soma_pct = sum(p for _, p in pares)
            if soma_pct <= 0:
                nova = dict(linha)
                nova["duvida_pendente"] = True
                nova["motivo_duvida"] = (
                    (nova.get("motivo_duvida") or "") +
                    f" | Anel – percentuais somam 0: {pares}"
                )
                return [nova]
            # Distribuição proporcional com correção de resíduo
            # Se soma_pct != 100, normaliza proporcionalmente
            qts: list[int] = []
            acumulado = 0
            for i, (_, p) in enumerate(pares):
                if i == len(pares) - 1:
                    # último tamanho absorve o resíduo para totalizar qty_total
                    qts.append(int(qty_total - acumulado))
                else:
                    q = round(qty_total * p / soma_pct)
                    q = int(q)
                    qts.append(q)
                    acumulado += q
            pares_abs = [(t, q) for (t, _), q in zip(pares, qts)]
            # Garantia: se algum q <= 0 por arredondamento, aciona HITL
            if any(q <= 0 for _, q in pares_abs):
                nova = dict(linha)
                nova["_proposta_expansao_anel"] = [
                    {"tamanho": t, "quantidade": p} for t, p in pares
                ]
                nova["duvida_pendente"] = True
                nova["motivo_duvida"] = (
                    (nova.get("motivo_duvida") or "") +
                    f" | Anel – distribuição % resultou em qtd ≤ 0: {pares_abs}"
                )
                nova["confianca"] = min(float(nova.get("confianca") or 1.0), 0.5)
                return [nova]
            pares_str = "; ".join(f"#{t}={q}" for t, q in pares_abs)
            nova = dict(linha)
            nova["_proposta_expansao_anel"] = [
                {"tamanho": t, "quantidade": q} for t, q in pares_abs
            ]
            nova["duvida_pendente"] = True
            motivo = nova.get("motivo_duvida") or ""
            if "revisão" not in motivo.lower():
                nova["motivo_duvida"] = (
                    (motivo + " | " if motivo else "") +
                    f"Anel — revisar distribuição (% calculado): {pares_str}"
                )
            nova["confianca"] = min(float(nova.get("confianca") or 1.0), 0.5)
            return [nova]
        # Quantidade absoluta — caminho existente
        nova = dict(linha)
        nova["_proposta_expansao_anel"] = [
            {"tamanho": t, "quantidade": q} for t, q in pares
        ]
        nova["duvida_pendente"] = True
        motivo = (nova.get("motivo_duvida") or "")
        if "revisão" not in motivo.lower():
            pares_str = "; ".join(f"#{t}={q}" for t, q in pares)
            nova["motivo_duvida"] = (
                (motivo + " | " if motivo else "") +
                f"Anel — revise classificação e distribuição: {pares_str}"
            )
        nova["confianca"] = min(float(nova.get("confianca") or 1.0), 0.5)
        return [nova]

    # Categorias de tamanho fixo "0"
    if cat in _CATEGORIAS_ZERO:
        nova = dict(linha)
        nova["tamanho"] = "0"
        return [nova]

    # Tenta extrair números do texto de tamanho para QUALQUER categoria
    # (não só CORRENTE/COLAR/PULSEIRA). Se encontrar valores numéricos
    # com separador '+', soma tudo — útil para categorias atípicas ou
    # casos onde o LLM não classificou exatamente como medida.
    medido = extrair_tamanho_cm(tamanho)
    if medido is not None:
        nova = dict(linha)
        nova["tamanho"] = str(medido)
        return [nova]

    # Categorias que exigem tamanho obrigatório: não conseguiu inferir -> HITL
    if cat in _CATEGORIAS_MEDIDA:
        nova = dict(linha)
        nova["duvida_pendente"] = True
        motivo = (nova.get("motivo_duvida") or "")
        if "Tamanho" not in motivo:
            nova["motivo_duvida"] = (
                (motivo + " | " if motivo else "") +
                f"Tamanho não encontrado na invoice para {cat}. "
                f"Texto recebido: '{tamanho[:80]}'"
            )
        nova["confianca"] = min(float(nova.get("confianca") or 1.0), 0.5)
        return [nova]

    # Demais categorias: mantém como está
    return [linha]


def expandir_lista(linhas: list[dict]) -> list[dict]:
    """Aplica expandir_linhas a cada item e achata o resultado."""
    saida: list[dict] = []
    for linha in linhas:
        saida.extend(expandir_linhas(linha))
    return saida


def aplicar_expansao_anel(linha: dict) -> list[dict]:
    """Expande linha de anel aprovada em N linhas (uma por tamanho).

    Só deve ser chamada DEPOIS da revisão humana. A entrada precisa ter
    ``_proposta_expansao_anel`` (a proposta gerada por ``expandir_linhas``).
    """
    proposta = linha.get("_proposta_expansao_anel")
    if not proposta:
        return [dict(linha)]
    base = {k: v for k, v in linha.items()
            if not k.startswith("_") and k not in ("duvida_pendente", "motivo_duvida")}
    saida: list[dict] = []
    for p in proposta:
        row = dict(base)
        # Prefixo "'" força Excel a tratar como texto, preservando zero à
        # esquerda do tamanho do anel (ex.: '05, '06). Sem isso, Excel
        # converte "05" para 5 numérico.
        tam = str(p["tamanho"])
        row["tamanho"] = f"'{tam}" if not tam.startswith("'") else tam
        row["quantidade"] = p["quantidade"]
        row["_ja_expandido"] = True
        saida.append(row)
    return saida

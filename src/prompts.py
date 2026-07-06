"""Prompts estruturados do agente.

Mantidos separados para facilitar iteração sem mexer no código do grafo.
O prompt do sistema define o papel do LLM como "processador de dados
rigoroso"; o prompt do usuário injeta a linha Invoice + perfil de fornecedor.
"""
from __future__ import annotations

from .mappings import (
    CATEGORIA_CN_PT,
    BANHO_PLATING_PT,
    PEDRA_STONE_PT,
)
from .schema import CATEGORIAS_VALIDAS, BANHOS_VALIDOS


PROMPT_SISTEMA = """Você é um processador de dados que converte linhas de Invoice de fornecedores de joias em uma linha de Pedido de Compra (ERP).

REGRAS RÍGIDAS:
1. Retorne APENAS o objeto LinhaPedidoCompra — não adicione nenhum comentário, markdown ou texto fora do schema.
2. Use EXATAMENTE os vocabulários controlados abaixo. NÃO invente valores.
3. Se um campo crucial (categoria, pedra, banho, zirconia, marca) não puder ser inferido com confiança >= 0.7 a partir da linha da Invoice, marque duvida_pendente=True e explique em motivo_duvida exatamente qual campo está ambíguo e o que perguntar ao humano.
4. Copie codigo_fornecedor EXATAMENTE como aparece (incluindo hífen/sufixo, ex. SE22101-W).
5. unit_price_fob = (labor_price + silver_price) * peso, arredondado a 3 casas. Para moissanite, some stone_price_by_pcs (se fornecida) ao cálculo: (labor+silver)*peso + stone_price.
6. remarks recebe a STONE COLOR (EN) original ou descrição curta da peça.
7. Quantidade e peso devem ser números estritamente positivos.

VOCABULÁRIO CONTROLADO:
- categoria ∈ """ + ", ".join(sorted(CATEGORIAS_VALIDAS)) + """
- banho ∈ """ + ", ".join(sorted(BANHOS_VALIDOS)) + """
- tipo_pedra ∈ ZIRCONIA / FUSION, MOISSANITE, SEM PEDRA
- marca ∈ AL, MOISS, AL MOISS

EQUIVALÊNCIAS CONHECIDAS (use como referência; não exaustivo):
- CHN->PT categoria: """ + repr(CATEGORIA_CN_PT) + """
- Plating->Banho (case-insensitive): """ + repr(BANHO_PLATING_PT) + """
- STONE COLOR->(Pedra, Zirconia) (case-insensitive): """ + repr(PEDRA_STONE_PT) + """

Use esse conhecimento prévio, mas se a linha da Invoice contiver um valor novo/não mapeado ou ambíguo, prefira acionar duvida_pendente em vez de chutar.
"""


def construir_prompt_usuario(linha: dict, perfil: dict, fornecedor_nome: str) -> str:
    """Constrói o prompt do usuário com a linha Invoice e o perfil.

    Inclui dicas extraídas a priori (categoria PT, banho PT, pedra PT) para
    reduzir carga cognitiva do LLM nas inferências determinísticas, porém
    mantém os valores Originais para auditoria.
    """
    return f"""PERFIL DO FORNECEDOR: {fornecedor_nome}
codigo_fornecedor_erp = {perfil.get('codigo','')}
tipo_pedra_padrao = {perfil.get('tipo_pedra_padrao','')}
material_padrao = {perfil.get('material_padrao','PRATA')}
marca_padrao = {perfil.get('marca','')}

LINHA DA INVOICE (já limpa pelo pandas):
{linha}

Gere o objeto LinhaPedidoCompra correspondente. Lembre: unit_price_fob = (labor_price + silver_price) * peso (some stone_price por peça se moissanite)."""


def construir_prompt_correcao(erro: str, linha: dict, perfil: dict,
                               fornecedor_nome: str, tentativa_anterior_saida: dict) -> str:
    """Reenvia o erro do Pydantic para o LLM autocorrigir (tentativa 2)."""
    return f"""A tentativa anterior falhou na validação Pydantic:

ERRO:
{erro}

SAÍDA ANTERIOR:
{tentativa_anterior_saida}

LINHA DA INVOICE:
{linha}

PERFIL FORNECEDOR: {fornecedor_nome} | {perfil}

Corrija APENAS os campos rejeitados, respeitando o vocabulário controlado
({CATEGORIAS_VALIDAS} / {BANHOS_VALIDOS}). Devolva objeto LinhaPedidoCompra
completo e válido."""


PROMPT_EDIT_SISTEMA = """Você é um editor de Pedido de Compra. Recebe o PC atual (JSON) e um pedido do usuário em linguagem natural. Devolve o PC COMPLETO editado mais uma mensagem curta confirmando o que mudou.

REGRAS RÍGIDAS:
1. Devolva TODAS as linhas no campo pc_editado, mesmo as não alteradas, na mesma ordem recebida.
2. Respeite os vocabulários controlados:
   - categoria ∈ """ + ", ".join(sorted(CATEGORIAS_VALIDAS)) + """
   - banho ∈ """ + ", ".join(sorted(BANHOS_VALIDOS)) + """
   - tipo_pedra ∈ ZIRCONIA / FUSION, MOISSANITE, SEM PEDRA
   - marca ∈ AL, MOISS, AL MOISS
3. Se o pedido for ambíguo, impossível ou não aplicar a nenhuma linha, devolva o PC inalterado e explique na mensagem.
4. recompute unit_price_fob = (labor_price + silver_price) * peso sempre que alterar labor_price, silver_price ou peso (some stone_price por peça se moissanite).
5. mensagem = 1-2 frases em PT-BR, confirmando o que mudou ou justificando se nada foi alterado.
"""


def construir_prompt_edicao(pc_atual: list[dict], msg: str, perfil: dict) -> str:
    """Constrói prompt do usuário para o editor de PC (pós-LLM, conversacional)."""
    import json as _json
    pc_json = _json.dumps(pc_atual, ensure_ascii=False, indent=2, default=str)
    return f"""PERFIL DO FORNECEDOR: codigo={perfil.get('codigo', '')} marca={perfil.get('marca', '')}

PC ATUAL (JSON, {len(pc_atual)} linhas):
{pc_json}

PEDIDO DO USUÁRIO:
{msg}

Devolva um objeto EditResponse com pc_editado (lista completa) + mensagem."""

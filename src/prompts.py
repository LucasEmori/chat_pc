"""Prompts estruturados do agente.

Mantidos separados para facilitar iteração sem mexer no código do grafo.
O prompt do sistema define o papel do LLM como "processador de dados
rigoroso"; o prompt do usuário injeta a linha Invoice + perfil de fornecedor.
"""
from __future__ import annotations

from .mappings import (
    CATEGORIA_CN_PT,
    CATEGORIA_EN_PT,
    BANHO_PLATING_PT,
    PEDRA_STONE_PT,
)
from .schema import CATEGORIAS_VALIDAS, BANHOS_VALIDOS


PROMPT_SISTEMA = """Você é um processador de dados que converte linhas de Invoice de fornecedores de joias em uma linha de Pedido de Compra (ERP).

REGRAS RÍGIDAS:
1. Retorne APENAS o objeto LinhaPedidoCompra — não adicione nenhum comentário, markdown ou texto fora do schema.
2. Use EXATAMENTE os vocabulários controlados abaixo. NÃO invente valores.
3. PRINCÍPIO GERAL: NUNCA chute um valor. Se não encontrar uma resposta clara e direta para um campo na linha da Invoice, DEIXE EM BRANCO (string vazia, ou 0.0 para numéricos) e acione duvida_pendente=True explicando em motivo_duvida exatamente qual campo ficou sem resposta e o que perguntar ao humano. Campos cruciais (categoria, pedra, banho, zirconia, marca, codigo_fornecedor) sempre exigem confiança >= 0.7; os demais campos (peso, quantidade, tamanho, remarks, labor_price, silver_price, etc.) também disparam duvida_pendente quando não houver valor claro na Invoice — não preencha com estimativa.
4. Copie codigo_fornecedor EXATAMENTE como aparece na Invoice (incluindo hífen/sufixo, ex. SE22101-W). NÃO adicione sufixos — o sistema adiciona "-MOI" automaticamente quando for moissanite.
5. unit_price_fob = (labor_price + silver_price) * peso, arredondado a 3 casas. Para moissanite, some stone_price_by_pcs (se fornecida) ao cálculo: (labor+silver)*peso + stone_price. Se labor_price ou silver_price não estiverem claros, deixe 0.0 e acione duvida_pendente.
   EXCEÇÃO: se a linha da invoice traz um campo "price_unit_fob" (preço por peça FOB já calculado pelo fornecedor, formato Grant/IZABEL), COPIE esse valor diretamente para unit_price_fob. Nesse caso mantenha labor_price=0, silver_price=0, peso=0 (sem HITL — o fornecedor já fechou o preço).
6. remarks recebe a STONE COLOR (EN) original ou descrição curta da peça. Se não houver descrição, deixe vazio.
7. Quantidade e peso devem ser números estritamente positivos quando presentes; se não estiverem claros na Invoice, deixe 0/0.0 e acione duvida_pendente.
8. MATERIAL é definido pela MARCA: se marca=NV use SEMIJOIA; se marca=AL ou GR use PRATA. Use o material_padrao do perfil recebido.
9. BRACELETE (手镯, bracelete rígido) é categoria distinta de PULSEIRA (手链/手环, pulseira flexível).
10. TAMANHO: para ANEL, copie EXATAMENTE o texto bruto da coluna de tamanho da invoice (ex. "#5 - 40 #6 - 35 #7 - 45 #8 - 20 #9 - 10") no campo tamanho — o sistema expande em linhas separadas por tamanho. Para CORRENTE/COLAR/PULSEIRA copie a medida bruta (ex. "15,5CM+1CM+1CM") para o sistema somar. Para BRINCO/BRACELETE deixe "0".
11. Campos SEMPRE VAZIOS (nunca preencha): foto="", dia="", preco_vendas=0.0. Estes nunca geram duvida_pendente.

VOCABULÁRIO CONTROLADO:
- categoria ∈ """ + ", ".join(sorted(CATEGORIAS_VALIDAS)) + """
- banho ∈ """ + ", ".join(sorted(BANHOS_VALIDOS)) + """
- tipo_pedra ∈ ZIRCONIA / FUSION, MOISSANITE, SEM PEDRA
- marca ∈ AL, GR, NV

EQUIVALÊNCIAS CONHECIDAS (use como referência; não exaustivo):
- CHN->PT categoria: """ + repr(CATEGORIA_CN_PT) + """
- EN->PT categoria (case-insensitive, coluna categoria_en): """ + repr(CATEGORIA_EN_PT) + """
- Plating->Banho (case-insensitive): """ + repr(BANHO_PLATING_PT) + """
- STONE COLOR->(Pedra, Zirconia) (case-insensitive): """ + repr(PEDRA_STONE_PT) + """

CATEGORIA:
- A invoice pode trazer a categoria em INGLÊS (coluna categoria_en, ex.: "earring", "bracelet", "ring") ou CHINÊS (categoria_cn). Use o mapeamento correspondente.
-Use CATEGORIA_EN_PT para a coluna categoria_en (case-insensitive). Por exemplo: "bracelet" -> BRACELETE, "earring" -> BRINCO, "ring" -> ANEL.

EXTRAÇÃO DE BANHO (PLATING):
- A coluna "plating" pode estar vazia mesmo quando o item TEM banho definido. Nesse caso, PROCURE em TODAS as colunas textuais da linha (stone_color, obs_cn, stone_color_cn, categoria_cn, remarks) por palavras-chave de banho.
- Regras diretas (case-insensitive, qualquer coluna):
  * "rhodium" / "rodhium" / "white" / "silver" / "prata" → RÓDIO
  * "gold" / "golden" / "dourado" / "ouro" / "champagne" → OURO
  * "rose gold" / "rosegold" / "ouro rosé" → OURO ROSÉ
  * "black" / "preto" / "dark" → PRETO
  * "yellow" / "amarelo" → AMARELO
- Se a coluna plating contém texto composto (ex.: "rodhium plate 镀白", "gold plate"), extraia a primeira palavra-chave de banho reconhecida.
- Se NENHUMA coluna contiver palavra-chave de banho, deixe banho="" (vazio) e acione duvida_pendente — não chute RÓDIO como padrão.

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

Gere o objeto LinhaPedidoCompra correspondente. Lembre: unit_price_fob = (labor_price + silver_price) * peso (some stone_price por peça se moissanite). Para ANEL, copie o tamanho bruto no campo tamanho; o sistema expande por tamanho depois."""


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
   - marca ∈ AL, GR, NV
3. Se o pedido for ambíguo, impossível ou não aplicar a nenhuma linha, devolva o PC inalterado e explique na mensagem.
4. recompute unit_price_fob = (labor_price + silver_price) * peso sempre que alterar labor_price, silver_price ou peso (some stone_price por peça se moissanite).
5. mensagem = 1-2 frases em PT-BR, confirmando o que mudou ou justificando se nada foi alterado.
6. NUNCA chute ou invente valores: se o usuário pedir algo que não está claro, mantenha o campo como está (ou vazio) e explique na mensagem que a informação não pôde ser determinada, perguntando o que falta.
7. Campos SEMPRE VAZIOS (nunca preencha): foto="", dia="", preco_vendas=0.0.
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

"""Schema Pydantic do Pedido de Compra + Estado do LangGraph.

A classe LinhaPedidoCompra é o CONTRATO do LLM: com with_structured_output
o ChatNVIDIA é forçado a devolver exatamente este objeto, eliminando texto
livre/alucinação. Campos de incerteza (duvida_pendente, motivo_duvida,
confianca) permitem rotear para HITL quando o LLM não consegue inferir.

Field(description=...) guia o LLM sobre o que esperar em cada campo - isso
é reforçado também no prompt (prompts.py), mas a descrição no Field é o que
o provedor NVIDIA NIM enxerga no schema JSON enviado.
"""
from __future__ import annotations

from typing import Optional, TypedDict

from pydantic import BaseModel, Field, field_validator


# Vocabulários controlados para validação (mantidos em sync com mappings.py)
CATEGORIAS_VALIDAS = {
    "ANEL", "BRINCO", "COLAR", "CORRENTE", "PULSEIRA", "BRACELETE",
    "PINGENTE", "ARGOLA", "CONJUNTO", "BROCHE", "CERTIFICADO",
}
BANHOS_VALIDOS = {"RÓDIO", "OURO", "OURO ROSÉ", "PRETO", "AMARELO"}
TIPOS_PEDRA_VALIDOS = {"ZIRCONIA / FUSION", "MOISSANITE", "SEM PEDRA"}
MARCAS_VALIDAS = {"AL", "GR", "NV"}


class LinhaPedidoCompra(BaseModel):
    """Uma linha pronta para o Pedido de Compra (ERP).

    Use somente campos abaixo. Se não conseguir inferir um campo com
    confiança alta, marque duvida_pendente=True e explique em motivo_duvida
    qual informação está faltando ou ambígua.
    """

    categoria: str = Field(
        description="Categoria do produto: ANEL, BRINCO, COLAR, CORRENTE, "
                    "PULSEIRA, BRACELETE, PINGENTE, ARGOLA, CONJUNTO, BROCHE."
    )
    codigo_fornecedor: str = Field(
        description="Referência do fornecedor, ex.: SE22101-W, SB08094-L. "
                    "Copie EXATAMENTE como aparece na Invoice."
    )
    foto: str = Field("", description="URL/foto. Deixe vazio.")
    material: str = Field(
        description="Material base definido pela MARCA: se marca=NV use "
                    "SEMIJOIA; se marca=AL ou GR use PRATA. Default PRATA."
    )
    fornecedor: str = Field(
        description="Código interno do fornecedor no ERP (ex. 012432). "
                    "Use o código do perfil recebido no prompt."
    )
    banho: str = Field(
        description="Banho: RÓDIO, OURO, OURO ROSÉ, PRETO, AMARELO."
    )
    pedra: str = Field(
        description="Tipo de pedra principal: SEM PEDRA, ÁGUA MARINHA, "
                    "SÁFIRA PINK, ESMERALDA FUSION, TANZANITA, COLOMBIANA, "
                    "AMARELO, CRISTAL BLACK."
    )
    zirconia: str = Field(
        description="Sigla 2-3 chars: ZB (zirconia branca), MS (moissanite), "
                    "TZN (tanzanita), YEL (amarela), PIN (sáfira pink), LIS."
    )
    tamanho: str = Field(
        "0",
        description="Tamanho/medida. Default '0'. Para ANEL copie EXATAMENTE "
                    "o texto bruto da coluna de tamanho da invoice (ex.: "
                    "'#5 - 40 #6 - 35 #7 - 45 #8 - 20 #9 - 10'); o sistema "
                    "expande em linhas separadas por tamanho. Para "
                    "CORRENTE/PULSEIRA/COLAR copie a medida (ex. "
                    "'15,5CM+1CM+1CM') para o sistema somar."
    )
    tipo_pedra: str = Field(
        description="'ZIRCONIA / FUSION' para zirconia, 'MOISSANITE' para "
                    "moissanite. Use o tipo do perfil recebido."
    )
    marca: str = Field(description="Marca/linha: AL ou MOISS.")
    quantidade: int = Field(
        description="Quantidade de peças (inteiro positivo)."
    )
    peso: float = Field(description="Peso unitário em gramas (float).")
    labor_price: float = Field(
        description="Labor Price (USD/g)."
    )
    silver_price: float = Field(
        description="Silver Price (USD/g)."
    )
    dia: str = Field("", description="Deixe vazio.")
    unit_price_fob: float = Field(
        description="Unit Price per piece FOB (USD) = (labor_price + silver_price) * peso."
    )
    preco_vendas: float = Field(
        0.0, description="Preço de Vendas. Deixe 0.0."
    )
    remarks: str = Field(
        description="Remarks/descrição: copie a STONE COLOR (EN) original "
                    "ou descrição complementar da peça."
    )

    # Controle de incerteza para HITL
    duvida_pendente: bool = Field(
        False,
        description="True quando NÃO foi possível inferir um ou mais campos "
                    "cruciais (categoria, pedra, banho, zirconia, marca) com "
                    "confiança aceitável a partir da descrição original."
    )
    motivo_duvida: str = Field(
        "",
        description="Se duvida_pendente=True, explique exatamente qual campo "
                    "está ambíguo e o que o humano precisa responder."
    )
    confianca: float = Field(
        1.0,
        description="Confiança média na linha (0.0-1.0). Use <0.7 se houve "
                    "inferência incerta."
    )

    @field_validator("quantidade")
    @classmethod
    def _chk_qty(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"quantidade deve ser > 0, recebido {v}")
        return v

    @field_validator("peso", "labor_price", "silver_price", "unit_price_fob")
    @classmethod
    def _chk_nao_neg(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"valor numérico não pode ser negativo: {v}")
        return v

    @field_validator("categoria")
    @classmethod
    def _chk_cat(cls, v: str) -> str:
        v = (v or "").upper().strip()
        if v and v not in CATEGORIAS_VALIDAS:
            raise ValueError(f"categoria '{v}' fora do vocabulário controlado")
        return v

    @field_validator("banho")
    @classmethod
    def _chk_banho(cls, v: str) -> str:
        v = (v or "").upper().strip()
        if v and v not in BANHOS_VALIDOS:
            raise ValueError(f"banho '{v}' fora do vocabulário controlado")
        return v

    @field_validator("tipo_pedra")
    @classmethod
    def _chk_tipo_pedra(cls, v: str) -> str:
        v = (v or "").upper().strip()
        if v and v not in TIPOS_PEDRA_VALIDOS:
            raise ValueError(f"tipo_pedra '{v}' fora do vocabulário controlado")
        return v


class EditResponse(BaseModel):
    """Resposta do LLM-editor: PC completo editado + mensagem curta.

    Sempre devolve TODAS as linhas (mesmo as não alteradas), na mesma ordem,
    para que o caller substitua o estado sem ambiguidade (full-list semantics,
    mesmo padrão usado em PedidoEstado.linhas_processadas).
    """

    pc_editado: list[LinhaPedidoCompra] = Field(
        description="Lista COMPLETA de LinhaPedidoCompra após aplicar a "
                    "alteração solicitada pelo usuário. Inclua todas as "
                    "linhas, mesmo as não alteradas, na mesma ordem."
    )
    mensagem: str = Field(
        description="Resposta curta (1-2 frases) em PT-BR confirmando o que "
                    "foi alterado, ou explicando ambiguidade."
    )


class PedidoEstado(TypedDict, total=False):
    """Estado do grafo LangGraph.

    Linhas guardadas como dict (não BaseModel) para serialização no
    checkpointer; convertemos de/para LinhaPedidoCompra nos nós.

    Importante: NÃO usamos reducer (operator.add) em linhas_processadas.
    Cada nó devolve a lista COMPLETA atualizada - assim o node_hitl pode
    substituir o último item sem ambiguidade semântica.
    """
    linhas_originais: list[dict]          # Linhas Invoice já limpas (input)
    linhas_processadas: list[dict]        # Acumulador (full-list semantics)
    indice_atual: int
    fornecedor: str
    perfil: dict
    nome_arquivo: str
    duvida_pendente: Optional[dict]       # linha que gerou HITL
    total_erro: int

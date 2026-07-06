# Invoice → Pedido de Compra (HITL)

Sistema agêntico que converte planilhas de Invoice (fornecedores variados — ALAN zirconia, LUIS moissanite, …) em Pedido de Compra padronizado para ERP, com Human-in-the-loop quando o LLM sinaliza incerteza.

## Stack
- **pandas** — limpeza e normalização das planilhas
- **streamlit** — UI: upload, preview, formulário HITL, download
- **langgraph** — orquestração com estado + `interrupt()` (pausa HITL) + `MemorySaver` (checkpointer)
- **langchain-nvidia-ai-endpoints** — LLM (Llama 3.3 / Qwen) via NVIDIA NIM
- **pydantic** — validação estruturada da saída do LLM (`with_structured_output`)

## Estrutura
```
chat_pc/
├── requirements.txt
├── .env.example
├── app.py                   # Streamlit UI
└── src/
    ├── schema.py            # LinhaPedidoCompra (Pydantic) + PedidoEstado (TypedDict)
    ├── prompts.py           # Prompt do sistema/usuário (vocabulário controlado)
    ├── llm.py               # ChatNVIDIA + retry por ValidationError
    ├── cleaner.py           # pandas: header detection, ffill variantes, descarte footer
    ├── graph.py             # StateGraph: processar -> [hitl interrupt] -> loop
    └── mappings.py          # Catálogos CN→PT, Plating→Banho, perfis por fornecedor
```

## Como rodar
```powershell
# 1. Venv já criado em ./venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Configurar API key
copy .env.example .env
# editar .env e setar NVIDIA_API_KEY=nvapi-...

# 3. Rodar
streamlit run app.py
```

## Fluxo do agente
1. Upload `.xlsx`/`.csv` → `cleaner.limpar_planilha()` detecta header (linha com `Ref.` ou `序号`), descarta 7 linhas iniciais de metadata, faz forward-fill de variantes (Ref/Produto), descarta footer (`total`, `after X% discount`, `certificate`).
2. Botão **Iniciar** compila o grafo com `MemorySaver()` (obrigatório para HITL) e cria thread_id único.
3. Node `processar`: invoca `ChatNVIDIA.with_structured_output(LinhaPedidoCompra)` — o LLM é forçado a devolver objeto tipado (sem texto livre).
4. Edge condicional: se `duvida_pendente=True` → node `hitl` chama `interrupt({linha, motivo})` → estado salvo pelo checkpointer, UI mostra card com formulário.
5. Usuário responde → `Command(resume=correcoes)` substitui última linha e retoma loop.
6. Fim → `linhas_para_dataframe_pc()` monta DataFrame com 19 colunas ERP → botão download `.xlsx`.

## Vocabulário controlado (validado por Pydantic)
| Campo          | Valores                                                                              |
|----------------|--------------------------------------------------------------------------------------|
| categoria      | ANEL, BRINCO, COLAR, PULSEIRA, PINGENTE, ARGOLA, CONJUNTO, BROCHE                   |
| banho          | RÓDIO, OURO, OURO ROSÉ, PRETO, AMARELO                                               |
| tipo_pedra     | ZIRCONIA / FUSION, MOISSANITE, SEM PEDRA                                             |
| marca          | AL, MOISS                                                                            |
| zirconia       | ZB, MS, TZN, YEL, PIN, LIS                                                           |

Saídas fora do vocabulário disparam `ValidationError` → retry automático (1x) reenviando o erro ao LLM; se persistir, vira `duvida_pendente=True` para HITL.

## Samples
As pastas `samples/Invoice/` (input) e `samples/Pedidos de Compra/` (output esperado) fornecem o padrão de mapeamento. 10 invoices (zirconia + moissanite) ↔ 10 PCs com numeração 000345–000355.

**Importante:** o prefixo `ALAN`/`LUIS` no nome do arquivo é apenas o **operador** (pessoa do time que processou a Invoice), **NÃO é o fornecedor**. O fornecedor real (fabricante chinês, código ERP `012432`, MARCA `AL`) é o mesmo em todas as samples. A variação semântica relevante entre arquivos é o **tipo de pedra**:
- `锆石` (zirconia) → `TIPO PEDRA = ZIRCONIA / FUSION`
- `莫桑石` (moissanite) → `TIPO PEDRA = MOISSANITE`

A detecção é feita por **conteúdo** da planilha (palavra-chave/ideograma), nunca pelo nome do operador.

## Próximos passos (não implementados)
- Persistência SQLite checkpointer (trocar `MemorySaver` por `AsyncSqliteSaver`) para sessões longas.
- Streaming de eventos (`stream_mode="custom"`) para UI mais responsiva.
- Autoaprendizado: gravar correções HITL em arquivo e alimentar `mappings.py` automaticamente.

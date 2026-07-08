# AzimeAI — Invoice → Pedido de Compra (HITL)

Sistema agêntico que converte planilhas de Invoice (fornecedores variados — ALAN zirconia, LUIS moissanite, …) em Pedido de Compra padronizado para ERP, com Human-in-the-loop quando o LLM sinaliza incerteza.

## Stack
- **pandas** — limpeza e normalização das planilhas
- **FastAPI** + **uvicorn** — API REST + SSE + frontend estático (monolito)
- **langgraph** — orquestração com estado + `interrupt()` (pausa HITL) + `MemorySaver` (checkpointer)
- **langchain** (NVIDIA NIM / OpenRouter / Google Gemini) — LLM com fallback chain
- **pydantic** — validação estruturada da saída do LLM (`with_structured_output`)
- Frontend **HTML/CSS/JS vanilla** (sem framework, sem build step)

## Estrutura
```
chat_pc/
├── server.py                # Entrypoint FastAPI (API + estáticos)
├── api/
│   ├── sessions.py          # SessionManager thread-safe (in-memory, lock por sessão)
│   └── routes.py            # Endpoints REST + SSE (/api/*)
├── src/                     # Lógica de domínio (inalterada, 0 acoplamento c/ UI)
│   ├── schema.py            # LinhaPedidoCompra (Pydantic) + PedidoEstado (TypedDict)
│   ├── prompts.py           # Prompt do sistema/usuário (vocabulário controlado)
│   ├── llm.py               # Providers + retry por ValidationError
│   ├── cleaner.py           # pandas: header detection, ffill variantes, descarte footer
│   ├── graph.py             # StateGraph: processar -> [hitl interrupt] -> loop
│   ├── mappings.py          # Catálogos CN→PT, Plating→Banho, perfis por fornecedor
│   └── tamanhos.py          # Regras de tamanho (anel → revisão, corrente → soma cm)
├── static/                  # Frontend servido pelo próprio FastAPI
│   ├── index.html
│   ├── css/style.css        # Design system dark B&W (portado do Web-Prototype)
│   ├── js/app.js            # Estado cliente + fetch + SSE + render das 6 stages
│   └── assets/logo.svg
├── requirements.txt
├── Procfile                 # Railway/Heroku
├── railway.toml
├── runtime.txt              # python-3.12
└── _app_streamlit_legacy.py # Versão Streamlit original (referência, fora do deploy)
```

## Como rodar (dev)
```powershell
# 1. Venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Configurar API key
copy .env.example .env
# editar .env e setar ao menos uma chave (NVIDIA_API_KEY, OPENROUTER_API_KEY ou GOOGLE_API_KEY)

# 3. Rodar
uvicorn server:app --reload
# → http://localhost:8000
```

## Deploy (Railway)
1. Conectar o repo à Railway (ou `railway up`).
2. A Railway detecta Python via `requirements.txt` e roda o `startCommand` do `railway.toml` (`uvicorn server:app --host 0.0.0.0 --port $PORT`).
3. Setar variáveis de ambiente no dashboard: `LLM_PROVIDER`, `NVIDIA_API_KEY`, `OPENROUTER_API_KEY`, `GOOGLE_API_KEY` etc. (`PORT` é injetado automaticamente).
4. Healthcheck em `/api/health`.
5. Single replica recomendada (estado in-memory). Para multi-replica, migrar `MemorySaver` → `PostgresSaver`/`SqliteSaver` (ver abaixo).

## Concorrência
- Cada sessão tem seu próprio grafo compilado + `MemorySaver` isolado — HITL/resume nunca colidem entre sessões.
- `SessionManager` mantém um `threading.RLock` por `session_id`: mutações sobre a mesma sessão são serializadas, sessões distintas rodam em paralelo.
- O `grafo.stream(...)` (síncrono/bloqueante) roda no threadpool do FastAPI e publica eventos numa `asyncio.Queue`; o generator async do SSE consome a fila. Logo, N invoices processam concorrentemente sem bloquear o event loop.

## Fluxo do agente
1. Upload `.xlsx`/`.csv` → `cleaner.limpar_planilha()` detecta header (linha com `Ref.` ou `序号`), descarta metadata, faz forward-fill de variantes (Ref/Produto), descarta footer (`total`, `after X% discount`, `certificate`).
2. **Processar** compila o grafo com `MemorySaver()` (obrigatório para HITL) e cria thread_id único.
3. Node `processar`: invoca o LLM com `with_structured_output(LinhaPedidoCompra)` — saída tipada, sem texto livre.
4. Edge condicional: se `duvida_pendente=True` → node `hitl` chama `interrupt({linha, motivo})` → estado salvo pelo checkpointer, UI mostra card HITL.
5. Usuário responde → `Command(resume=correcoes)` substitui última linha e retoma loop.
6. Fim → `linhas_para_dataframe_pc()` monta DataFrame com 19 colunas ERP → download `.xlsx`.

## Vocabulário controlado (validado por Pydantic)
| Campo          | Valores                                                                              |
|----------------|--------------------------------------------------------------------------------------|
| categoria      | ANEL, BRINCO, COLAR, CORRENTE, PULSEIRA, BRACELETE, PINGENTE, ARGOLA, CONJUNTO, BROCHE, CERTIFICADO |
| banho          | RÓDIO, OURO, OURO ROSÉ, PRETO, AMARELO                                               |
| tipo_pedra     | ZIRCONIA / FUSION, MOISSANITE, SEM PEDRA                                             |
| marca          | AL, GR, NV                                                                           |

Saídas fora do vocabulário disparam `ValidationError` → retry automático (1x) reenviando o erro ao LLM; se persistir, vira `duvida_pendente=True` para HITL.

## Samples
As pastas `samples/Invoice/` (input) e `samples/Pedidos de Compra/` (output esperado) fornecem o padrão de mapeamento.

**Importante:** o prefixo `ALAN`/`LUIS` no nome do arquivo é apenas o **operador**, **NÃO é o fornecedor**. A variação semântica relevante é o **tipo de pedra**: `锆石` (zirconia) → `ZIRCONIA / FUSION`; `莫桑石` (moissanite) → `MOISSANITE`. Detecção por conteúdo, nunca por nome de operador.

## API (resumo)
| Método | Rota | Descrição |
|---|---|---|
| POST | `/api/session` | Cria sessão |
| POST | `/api/upload` | Upload + limpeza da invoice |
| POST | `/api/configure` | Marca + código fornecedor |
| GET | `/api/process/stream` | Processamento via SSE (progress/hitl/done/error) |
| POST | `/api/hitl/resolve` | Submete correção HITL |
| POST | `/api/pc/edit` | Edição via chat (LLM editor) |
| POST | `/api/anel/decide` | Confirma/pula expansão de anel |
| GET | `/api/pc/preview` | Snapshot atual do PC |
| POST | `/api/pc/confirm` | Confirma pedido |
| GET | `/api/pc/download` | Download `.xlsx` |
| GET | `/api/pc/json` | JSON estruturado da 1ª linha |
| POST | `/api/reset` | Nova sessão |

Docs OpenAPI interativas em `/api/docs`.

## Próximos passos
- Persistência durável: trocar `MemorySaver` por `PostgresSaver`/`SqliteSaver` para HITL sobreviver a redeploy e escalar multi-replica.
- Autoaprendizado: gravar correções HITL e alimentar `mappings.py` automaticamente.

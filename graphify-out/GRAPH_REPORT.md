# Graph Report - chat_pc  (2026-07-08)

## Corpus Check
- 20 files · ~37,389 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 374 nodes · 610 edges · 49 communities (16 shown, 33 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 26 edges (avg confidence: 0.65)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `20520c6f`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- [[_COMMUNITY_LLM Chat Providers|LLM Chat Providers]]
- [[_COMMUNITY_Streamlit UI App|Streamlit UI App]]
- [[_COMMUNITY_Product & Design System|Product & Design System]]
- [[_COMMUNITY_State Graph & Workflow|State Graph & Workflow]]
- [[_COMMUNITY_Invoice Data Cleaning|Invoice Data Cleaning]]
- [[_COMMUNITY_Dependencies & README|Dependencies & README]]
- [[_COMMUNITY_Mappings & Prompts|Mappings & Prompts]]
- [[_COMMUNITY_Color Design Tokens|Color Design Tokens]]
- [[_COMMUNITY_Prototype JS Interactions|Prototype JS Interactions]]
- [[_COMMUNITY_Purchase Operators|Purchase Operators]]
- [[_COMMUNITY_Future Auto-Learning|Future: Auto-Learning]]
- [[_COMMUNITY_Future SQLite Checkpointer|Future: SQLite Checkpointer]]
- [[_COMMUNITY_Future Streaming|Future: Streaming]]
- [[_COMMUNITY_Future Content Detection|Future: Content Detection]]
- [[_COMMUNITY_app.js|app.js]]
- [[_COMMUNITY_SessionState|SessionState]]
- [[_COMMUNITY_AzimeAI — Design System Master|AzimeAI — Design System Master]]
- [[_COMMUNITY_4f165bfc-f69f-4660-a6dc-1306588c0b8b implementation handoff|4f165bfc-f69f-4660-a6dc-1306588c0b8b implementation handoff]]
- [[_COMMUNITY_AzimeAI — Invoice → Pedido de Compra (HITL)|AzimeAI — Invoice → Pedido de Compra (HITL)]]
- [[_COMMUNITY_Product|Product]]
- [[_COMMUNITY_startWorkflow function|startWorkflow function]]
- [[_COMMUNITY___init__.py|__init__.py]]
- [[_COMMUNITY_Chat page architecture (app_stage = configreadyprocessingdone)|Chat page architecture (app_stage = config/ready/processing/done)]]
- [[_COMMUNITY_Claude.ai (Anthropic) as visual reference|Claude.ai (Anthropic) as visual reference]]
- [[_COMMUNITY_HITL doubt card component (inline message)|HITL doubt card component (inline message)]]
- [[_COMMUNITY_Restricted Monochrome color strategy|Restricted Monochrome color strategy]]
- [[_COMMUNITY_WCAG 2.1 AA accessibility compliance|WCAG 2.1 AA accessibility compliance]]
- [[_COMMUNITY_Welcome page architecture (app_stage = init)|Welcome page architecture (app_stage = init)]]
- [[_COMMUNITY_Design Handoff document (implementation contract)|Design Handoff document (implementation contract)]]
- [[_COMMUNITY_Chat-first interaction principle|Chat-first interaction principle]]
- [[_COMMUNITY_Human-in-the-loop (HITL) pattern|Human-in-the-loop (HITL) pattern]]
- [[_COMMUNITY_Invoice → Pedido de Compra conversion|Invoice → Pedido de Compra conversion]]
- [[_COMMUNITY_Monochromatic design principle|Monochromatic design principle]]
- [[_COMMUNITY_app.py (Streamlit UI)|app.py (Streamlit UI)]]
- [[_COMMUNITY_Invoice → Pedido de Compra (HITL) System|Invoice → Pedido de Compra (HITL) System]]
- [[_COMMUNITY_cleaner.py (pandas header detection, ffill, footer discard)|cleaner.py (pandas: header detection, ffill, footer discard)]]
- [[_COMMUNITY_Controlled vocabulary (categoria, banho, tipo_pedra, marca, zirconia)|Controlled vocabulary (categoria, banho, tipo_pedra, marca, zirconia)]]
- [[_COMMUNITY_graph.py (StateGraph processar → HITL interrupt → loop)|graph.py (StateGraph: processar → HITL interrupt → loop)]]
- [[_COMMUNITY_mappings.py (CN→PT catalogs, Plating→Banho, supplier profiles)|mappings.py (CN→PT catalogs, Plating→Banho, supplier profiles)]]
- [[_COMMUNITY_prompts.py (Systemuser prompts with controlled vocabulary)|prompts.py (System/user prompts with controlled vocabulary)]]
- [[_COMMUNITY_schema.py (LinhaPedidoCompra Pydantic + PedidoEstado TypedDict)|schema.py (LinhaPedidoCompra Pydantic + PedidoEstado TypedDict)]]
- [[_COMMUNITY_ValidationError retry mechanism (1x auto-retry, then HITL)|ValidationError retry mechanism (1x auto-retry, then HITL)]]
- [[_COMMUNITY_langchain (=0.3)|langchain (>=0.3)]]
- [[_COMMUNITY_langchain-nvidia-ai-endpoints (=0.3)|langchain-nvidia-ai-endpoints (>=0.3)]]
- [[_COMMUNITY_langgraph (=0.2)|langgraph (>=0.2)]]
- [[_COMMUNITY_pandas (=2.2)|pandas (>=2.2)]]
- [[_COMMUNITY_pydantic (=2.7)|pydantic (>=2.7)]]
- [[_COMMUNITY_streamlit (=1.31)|streamlit (>=1.31)]]

## God Nodes (most connected - your core abstractions)
1. `el()` - 17 edges
2. `SessionState` - 16 edges
3. `LinhaPedidoCompra` - 16 edges
4. `limpar_planilha()` - 13 edges
5. `esc()` - 13 edges
6. `4f165bfc-f69f-4660-a6dc-1306588c0b8b implementation handoff` - 13 edges
7. `SessionManager` - 12 edges
8. `processar_linha()` - 12 edges
9. `appendMsgNode()` - 12 edges
10. `_render_msg()` - 11 edges

## Surprising Connections (you probably didn't know these)
- `AzimeAI application screenshot or mockup` --references--> `AzimeAI`  [INFERRED]
  azimeai (1).png → PRODUCT.md
- `AzimeAI SVG logo (geometric monogram: rounded square + triangle A)` --references--> `AzimeAI`  [EXTRACTED]
  design/logo.svg → PRODUCT.md
- `_montar_estado_inicial()` --calls--> `estado_inicial()`  [EXTRACTED]
  _app_streamlit_legacy.py → src/graph.py
- `_linhas_to_records()` --calls--> `linhas_para_dataframe_pc()`  [EXTRACTED]
  api/routes.py → src/cleaner.py
- `upload()` --calls--> `limpar_planilha()`  [EXTRACTED]
  api/routes.py → src/cleaner.py

## Import Cycles
- None detected.

## Communities (49 total, 33 thin omitted)

### Community 0 - "LLM Chat Providers"
Cohesion: 0.07
Nodes (39): aplicar_edicao_pc(), _fazer_esqueleto(), obter_chat(), obter_chat_editor(), obter_chat_estruturado(), _obter_chat_google(), _obter_chat_google_editor(), _obter_chat_google_estruturado() (+31 more)

### Community 1 - "Streamlit UI App"
Cohesion: 0.06
Nodes (49): Any, _normalizar_pc(), Pós-processamento determinístico do PC (sufixo -MOI + expansão).      Espelho de, _cleanup_asyncio_tasks(), _config(), _df_preview(), _esc(), _file_chip_html() (+41 more)

### Community 2 - "Product & Design System"
Cohesion: 0.33
Nodes (6): AzimeAI application screenshot or mockup, AzimeAI SVG logo (geometric monogram: rounded square + triangle A), AzimeAI Design System Master, AzimeAI Chat interface (HTML prototype), AzimeAI chat interface design screenshot, AzimeAI

### Community 3 - "State Graph & Workflow"
Cohesion: 0.19
Nodes (15): _montar_estado_inicial(), compilar_grafo(), estado_inicial(), node_hitl(), node_processar(), Grafo LangGraph: processa linha-a-linha, com interrupt para HITL.  Fluxo:     ST, Edge condicional pós-processar.      - Se duvida_pendente ativa -> 'hitl'     -, Constrói e compila o StateGraph com MemorySaver (HITL-ready). (+7 more)

### Community 4 - "Invoice Data Cleaning"
Cohesion: 0.09
Nodes (33): configure(), Series, _aplicar_conversao_cny(), _detectar_coluna_tamanho(), detectar_fator_cny(), _detectar_linha_header(), _e_footer(), limpar_planilha() (+25 more)

### Community 5 - "Dependencies & README"
Cohesion: 0.67
Nodes (3): llm.py (ChatNVIDIA + retry on ValidationError), langchain-google-genai (>=2.0), langchain-openai (>=0.2)

### Community 6 - "Mappings & Prompts"
Cohesion: 0.07
Nodes (37): anel_decide(), AnelDecisionIn, ConfigureIn, create_session(), _df_preview_records(), hitl_resolve(), HitlResolveIn, _linhas_to_records() (+29 more)

### Community 8 - "Prototype JS Interactions"
Cohesion: 0.67
Nodes (3): resetSession function, resolveHitl function, showResult function

### Community 15 - "app.js"
Cohesion: 0.18
Nodes (39): $(), afterAnelDecision(), api, appendDoneFooter(), appendMsgNode(), appendToChat(), boot(), dfTable() (+31 more)

### Community 16 - "SessionState"
Cohesion: 0.11
Nodes (13): Gerenciador de sessões in-memory, thread-safe.  Espelha o `st.session_state` que, Get ou 404-like. Caller decide como tratar None., Lock recursivo associado à sessão (para serializar mutações)., Reseta o estado de processo mas mantém o session_id.          Gera nova thread_i, Estado de uma sessão de processamento (uma invoice → um PC).      Campos espelha, Registry de sessões concorrentes, com lock global fino (por sessão).      Um loc, Cria uma nova sessão e retorna seu estado inicial., SessionManager (+5 more)

### Community 17 - "AzimeAI — Design System Master"
Cohesion: 0.08
Nodes (24): Animations, Anti-Patterns (Avoid), AzimeAI — Design System Master, Brand Identity, Buttons, Chat (app_stage = config/ready/processing/done), Chat Messages, Color Strategy: Restrained Monochrome (+16 more)

### Community 18 - "4f165bfc-f69f-4660-a6dc-1306588c0b8b implementation handoff"
Cohesion: 0.14
Nodes (13): 4f165bfc-f69f-4660-a6dc-1306588c0b8b implementation handoff, Assets and supporting files, CJX-ready UX contract, Coding checklist for AI tools, Color and brand contract, Design fidelity contract, Entry points, Implementation sequence for AI coding tools (+5 more)

### Community 19 - "AzimeAI — Invoice → Pedido de Compra (HITL)"
Cohesion: 0.17
Nodes (11): API (resumo), AzimeAI — Invoice → Pedido de Compra (HITL), Como rodar (dev), Concorrência, Deploy (Railway), Estrutura, Fluxo do agente, Próximos passos (+3 more)

### Community 21 - "Product"
Cohesion: 0.22
Nodes (8): Accessibility & Inclusion, Anti-references, Brand Personality, Design Principles, Product, Product Purpose, Register, Users

### Community 22 - "startWorkflow function"
Cohesion: 0.50
Nodes (4): runSteps function, startWorkflow function, Demo state machine (empty → uploaded → processing → hitl → result), Agent flow: upload → clean → LLM structured output → HITL → download

## Knowledge Gaps
- **88 isolated node(s):** `ICO`, `STAGE_LABELS`, `state`, `api`, `Register` (+83 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **33 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `SessionState` connect `SessionState` to `Mappings & Prompts`?**
  _High betweenness centrality (0.034) - this node is a cross-community bridge._
- **Why does `limpar_planilha()` connect `Invoice Data Cleaning` to `Streamlit UI App`, `Mappings & Prompts`?**
  _High betweenness centrality (0.028) - this node is a cross-community bridge._
- **Why does `LinhaPedidoCompra` connect `LLM Chat Providers` to `State Graph & Workflow`, `Mappings & Prompts`?**
  _High betweenness centrality (0.022) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `SessionState` (e.g. with `AnelDecisionIn` and `ConfigureIn`) actually correct?**
  _`SessionState` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `LinhaPedidoCompra` (e.g. with `obter_chat_estruturado()` and `_obter_chat_google_estruturado()`) actually correct?**
  _`LinhaPedidoCompra` has 3 INFERRED edges - model-reasoned connections that need verification._
- **What connects `AzimeAI — Chat-based Invoice to Purchase Order processor.  Interface portada d`, `Preview de dataframe. key= obrigatório quando chamado em loop     (múltiplas pr`, `Pós-processamento determinístico do PC antes de exibir/baixar.      1. Sufixo` to the rest of the system?**
  _176 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `LLM Chat Providers` be split into smaller, more focused modules?**
  _Cohesion score 0.07215541165587419 - nodes in this community are weakly interconnected._
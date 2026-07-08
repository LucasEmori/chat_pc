/* ============================================================
   AzimeAI — frontend controller (vanilla JS).
   Substitui a camada de render do app.py (Streamlit).

   Estado mínimo no cliente; a verdade está no servidor (api/sessions).
   Render functions espelham `_render_*` e message-types de app.py:
   text | error | success | warning | loading | preview | preview_done
   | steps.
   ============================================================ */
"use strict";

// ── Ícones inline (espelho de _ICO_* em app.py) ──────────────
const ICO = {
  check: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>',
  file: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>',
  upload: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>',
  arrow: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>',
  skip: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 4 15 12 5 20 5 4"/><line x1="19" y1="5" x2="19" y2="19"/></svg>',
  download: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>',
  code: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>',
  send: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>',
  refresh: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>',
  close: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
  spinner: '<span class="azime-spinner"></span>',
};

const STAGE_LABELS = {
  init: "",
  config: " · Configurar invoice",
  ready: " · Pronto para processar",
  processing: " · Processando",
  hitl: " · Aguardando confirmação",
  done: " · Pedido gerado",
};

// ── Estado cliente ────────────────────────────────────────────
const state = {
  sessionId: null,
  stage: "init",
  provider: "auto",
  nomeArquivo: "",
  tipoMaterial: null,
  chatHistorico: [],   // array de mensagens {role, content, type, extra?}
  pendentes: [],       // anéis pendentes de revisão
  pcConfirmado: false,
  moeda: "USD",                 // "USD" (default) ou "CNY"
  fatorCnySugerido: null,       // float sugerido pelo cleaner quando moeda=CNY
};

// ── DOM helpers ───────────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const stageEl = () => $("#stage");
const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const el = (tag, cls, html) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html != null) e.innerHTML = html;
  return e;
};

// ── API client ────────────────────────────────────────────────
const api = {
  async createSession() {
    const r = await fetch("/api/session", { method: "POST" });
    if (!r.ok) throw new Error("falha ao criar sessão");
    return r.json();
  },
  async upload(file) {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch(`/api/upload?session_id=${state.sessionId}`, {
      method: "POST", body: fd,
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `upload falhou (${r.status})`);
    }
    return r.json();
  },
  async configure(marca, cod, fatorCny) {
    const body = { marca, cod_fornecedor: cod };
    if (fatorCny != null && fatorCny > 0) body.fator_cny = fatorCny;
    const r = await fetch(`/api/configure?session_id=${state.sessionId}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return r.json();
  },
  streamUrl() {
    return `/api/process/stream?session_id=${state.sessionId}`;
  },
  async hitlResolve(payload) {
    const r = await fetch(`/api/hitl/resolve?session_id=${state.sessionId}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return r.json();
  },
  async pcEdit(msg) {
    const r = await fetch(`/api/pc/edit?session_id=${state.sessionId}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mensagem: msg }),
    });
    return r.json();
  },
  async anelDecide(chave, aprovar) {
    const r = await fetch(`/api/anel/decide?session_id=${state.sessionId}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chave, aprovar }),
    });
    return r.json();
  },
  async pcPreview() {
    const r = await fetch(`/api/pc/preview?session_id=${state.sessionId}`);
    return r.json();
  },
  async pcConfirm() {
    const r = await fetch(`/api/pc/confirm?session_id=${state.sessionId}`, { method: "POST" });
    return r.json();
  },
  downloadUrl() {
    return `/api/pc/download?session_id=${state.sessionId}`;
  },
  async pcJson() {
    const r = await fetch(`/api/pc/json?session_id=${state.sessionId}`);
    return r.json();
  },
  async reset() {
    const r = await fetch(`/api/reset?session_id=${state.sessionId}`, { method: "POST" });
    return r.json();
  },
};

// ── Logo ──────────────────────────────────────────────────────
async function loadLogo() {
  try {
    const r = await fetch("/assets/logo.svg");
    if (r.ok) $("#logo-slot").innerHTML = await r.text();
  } catch {
    $("#logo-slot").innerHTML = '<span style="font-weight:600;letter-spacing:-0.5px">AzimeAI</span>';
  }
}

// ── Render: estrutura de mensagem (espelho de _label_row) ─────
function labelRow(who, text) {
  const av = who === "user"
    ? '<span class="av user">EU</span>'
    : '<span class="av assistant">A</span>';
  return `<div class="azime-msg-label">${av}<span>${esc(text)}</span></div>`;
}

function renderUserMsg(contentHtml) {
  const m = el("div", "azime-msg azime-msg-user");
  m.innerHTML = labelRow("user", "Operador") + `<div>${contentHtml}</div>`;
  return m;
}
function renderAssistantMsg(contentHtml) {
  const m = el("div", "azime-msg azime-msg-assistant");
  m.innerHTML = labelRow("assistant", "AzimeAI") + `<div class="a-body">${contentHtml}</div>`;
  return m;
}
function renderErrorMsg(content) {
  const m = el("div", "azime-msg-error");
  m.textContent = content;
  return m;
}
function renderSuccessMsg(content) {
  const m = el("div", "azime-msg-success");
  m.innerHTML = `<div class="ok-line"><span class="okdot">${ICO.check}</span><span>${content}</span></div>`;
  return m;
}
function renderWarningMsg(content) {
  const m = el("div", "azime-msg-warning");
  m.textContent = content;
  return m;
}
function renderLoadingMsg(text = "Processando") {
  const m = el("div", "azime-msg azime-msg-assistant");
  m.innerHTML = labelRow("assistant", "AzimeAI") +
    `<div class="a-body" style="display:flex;align-items:center;gap:0.5rem">${ICO.spinner}<span>${esc(text)}</span></div>`;
  return m;
}

function fileChipHtml(name, size = "47 KB", ftype) {
  const ft = ftype || (name.includes(".") ? name.split(".").pop().toUpperCase() : "FILE");
  return `<div class="azime-file-chip">
    <span class="fic">${ICO.file}</span>
    <span class="fmeta"><span class="fname">${esc(name)}</span><span class="fsize">${esc(size)}</span></span>
    <span class="ftype">${esc(ft)}</span></div>`;
}

function stepsBlockHtml(steps) {
  const items = steps.map((s) =>
    `<div class="azime-step done"><span class="ind"><span class="ck">${ICO.check}</span></span><span>${esc(s)}</span></div>`
  ).join("");
  return `<div class="azime-steps">${items}<div class="azime-rail"><i style="width:100%"></i></div></div>`;
}

// ── Render: tabela de dados (preview) ─────────────────────────
function dfTable(records, { wide = false, label = "", total, maxRows = 25 } = {}) {
  if (!records || !records.length) return el("div");
  const n = total ?? records.length;
  const sub = label || " · detecção automática de cabeçalho";
  const wrap = el("div", wide ? "azime-df azime-df-pc" : "azime-df");
  const head = el("div", "azime-df-head",
    `<span class="count">${n} linhas</span><span> · ${esc(sub)}</span>`);
  const cols = Object.keys(records[0]);
  const shown = records.slice(0, maxRows);
  const table = document.createElement("table");
  table.innerHTML = `<thead><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead>
    <tbody>${shown.map((row) =>
      `<tr>${cols.map((c) => `<td>${esc(row[c])}</td>`).join("")}</tr>`
    ).join("")}</tbody>`;
  wrap.appendChild(head);
  wrap.appendChild(table);
  return wrap;
}

// ── Stage rendering ───────────────────────────────────────────
function setStage(s) {
  state.stage = s;
  $("#crumb-name").textContent = (state.nomeArquivo || "Sessão").replace(/\.[^.]+$/, "");
  $("#crumb-stage").textContent = STAGE_LABELS[s] || "";
  $("#topbar").classList.toggle("hidden", s === "init");
  $("#new-session-btn").classList.toggle("hidden", s === "init");
  document.body.classList.toggle("pc-wide", s === "done" && window.innerWidth >= 1100);
}

function renderWelcome() {
  const main = stageEl();
  main.innerHTML = "";
  const w = el("div", "azime-welcome",
    `<div class="glyph">A</div>
     <h1>Converter uma invoice em pedido de compra.</h1>
     <p>Envie um arquivo <code class="mono">.xlsx</code> do fornecedor. Eu limpo a planilha, mapeio o catálogo e gero o pedido para o ERP — perguntando só quando houver dúvida.</p>`);
  main.appendChild(w);

  // Dropzone + input file
  const dz = el("label", "azime-dropzone",
    `<div class="azime-upload-icon">${ICO.upload}</div>
     <div class="azime-upload-title"><strong>Adicionar invoice</strong></div>
     <div class="azime-upload-sub">.XLSX · .XLSM · .CSV</div>
     <input type="file" accept=".xlsx,.xlsm,.csv" id="file-input" hidden />`);
  main.appendChild(dz);
  const input = dz.querySelector("#file-input");
  input.addEventListener("change", () => {
    if (input.files[0]) handleUpload(input.files[0]);
  });
  // drag&drop
  ["dragenter", "dragover"].forEach((evt) =>
    dz.addEventListener(evt, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((evt) =>
    dz.addEventListener(evt, (e) => { e.preventDefault(); dz.classList.remove("drag"); }));
  dz.addEventListener("drop", (e) => {
    const f = e.dataTransfer.files[0];
    if (f) handleUpload(f);
  });
}

function renderChatShell() {
  const main = stageEl();
  main.innerHTML = "";
  const area = el("div", "azime-chat-area");
  area.id = "chat-area";
  main.appendChild(area);
  return area;
}

function appendToChat(node) {
  let area = $("#chat-area");
  if (!area) area = renderChatShell();
  area.appendChild(node);
  area.scrollTop = area.scrollHeight;
}

function renderHistory() {
  const area = renderChatShell();
  state.chatHistorico.forEach((msg) => appendMsgNode(msg));
}

function appendMsgNode(msg) {
  const { role, content, type } = msg;
  if (type === "error") return appendToChat(renderErrorMsg(content));
  if (type === "success") return appendToChat(renderSuccessMsg(content));
  if (type === "warning") return appendToChat(renderWarningMsg(content));
  if (type === "loading") return appendToChat(renderLoadingMsg(content));
  if (type === "preview") return appendToChat(dfTable(content, { label: "", total: msg.total }));
  if (type === "preview_done") return appendToChat(dfTable(content, { wide: true, label: "Pedido de Compra final", total: msg.total }));
  if (type === "steps") return appendToChat((() => { const m = el("div"); m.innerHTML = content; return m.firstChild; })());
  if (role === "user") return appendToChat(renderUserMsg(content));
  return appendToChat(renderAssistantMsg(content));
}

function pushHistory(msg) {
  state.chatHistorico.push(msg);
  appendMsgNode(msg);
}

// ── Form: configurar marca + fornecedor (stage config) ────────
function renderConfigForm() {
  const isCny = state.moeda === "CNY";
  const fatorSugerido = state.fatorCnySugerido != null ? String(state.fatorCnySugerido) : "6.72";
  const card = el("div", "azime-hitl");
  card.id = "hitl-config";
  card.innerHTML = `
    <div class="htitle"><span class="q">⚙</span> Configurar invoice</div>
    <div class="hsub">Preciso da marca e código de fornecedor antes de processar.</div>
    <div class="azime-hitl-grid">
      <div class="field">
        <label for="cfg-marca">Marca</label>
        <select class="azime-select" id="cfg-marca">
          <option value="AL">AL</option><option value="GR">GR</option><option value="NV">NV</option>
        </select>
      </div>
      <div class="field">
        <label for="cfg-cod">Código Fornecedor (ERP)</label>
        <input class="azime-input" id="cfg-cod" placeholder="ex.: 012432" />
      </div>
    </div>
    ${isCny ? `
    <div class="field" style="margin-top:10px">
      <label for="cfg-fator-cny">Cotação do dólar (CNY → USD)</label>
      <input class="azime-input" id="cfg-fator-cny" type="number" step="0.01" min="0.01"
             value="${esc(fatorSugerido)}" placeholder="ex.: 6.72" />
      <div class="hsub" style="margin-top:2px">Confirmar/sobrescrever o fator sugerido. Aplica-se a labor, silver, preço unitário e total.</div>
    </div>` : ""}
    <div class="azime-row grow-3-2">
      <button class="azime-btn azime-btn-primary azime-btn-stretch" id="cfg-continue">${ICO.arrow} Continuar</button>
      <button class="azime-btn azime-btn-secondary azime-btn-stretch" id="cfg-skip">${ICO.skip} Pular, usar padrão</button>
    </div>`;
  appendToChat(card);
  card.querySelector("#cfg-continue").addEventListener("click", async () => {
    const marca = card.querySelector("#cfg-marca").value;
    const cod = card.querySelector("#cfg-cod").value.trim();
    const fatorInput = card.querySelector("#cfg-fator-cny");
    const fatorCny = isCny && fatorInput
      ? parseFloat((fatorInput.value || "").replace(",", "."))
      : null;
    if (isCny && (!fatorCny || fatorCny <= 0)) {
      pushHistory({ role: "assistant",
        content: "Cotação do dólar inválida. Digite um número maior que zero (ex.: 6.72).",
        type: "text" });
      return;
    }
    card.remove();
    await api.configure(marca, cod, fatorCny);
    renderReadyActions(marca, cod);
  });
  card.querySelector("#cfg-skip").addEventListener("click", async () => {
    card.remove();
    // Skip aceita fator sugerido (fallback 6.72) para não travar o fluxo CNY.
    const fatorSkip = isCny ? (state.fatorCnySugerido || 6.72) : null;
    await api.configure("AL", "", fatorSkip);
    renderReadyActions("AL", "012432");
  });
}

function renderReadyActions(marca, cod) {
  const cod2 = (cod || "").trim() || "012432";
  const meta = el("div", "azime-meta-inline",
    `Marca: <strong>${esc(marca)}</strong> &nbsp;·&nbsp; Fornecedor: <strong>${esc(cod2)}</strong>`);
  appendToChat(meta);
  const btn = el("button", "azime-btn azime-btn-primary azime-btn-stretch",
    `${ICO.upload} Processar invoice`);
  btn.id = "process-btn";
  btn.addEventListener("click", startProcessing);
  appendToChat(btn);
}

// ── Processamento (SSE) ───────────────────────────────────────
async function startProcessing() {
  const btn = $("#process-btn");
  if (btn) btn.remove();

  pushHistory({ role: "user", content: "Processar a invoice", type: "text" });

  const stepsHtml = `<div class="azime-msg azime-msg-assistant">${labelRow("assistant", "AzimeAI")}
    <div class="a-body"><p>Processando com validação estruturada. Em caso de incerteza fora do vocabulário controlado, eu pergunto aqui mesmo.</p>
    ${stepsBlockHtml([
      "Limpando planilha e descartando rodapé",
      "Detectando tipo de pedra por palavra-chave",
      "Mapeando catálogo CN → PT (categoria, banho, marca)",
      "Validando saída com schema Pydantic",
    ])}
    <div style="display:flex;align-items:center;gap:0.5rem;margin-top:8px;color:var(--muted)">${ICO.spinner}<span>Processando linhas...</span></div>
    </div></div>`;
  pushHistory({ role: "assistant", content: stepsHtml, type: "steps" });

  setStage("processing");

  // Barra de progresso
  const progWrap = el("div", "azime-progress-wrap");
  progWrap.innerHTML = `<div class="azime-progress"><i id="prog-fill"></i></div>
    <div class="azime-progress-label" id="prog-label">Linha 0/0 (0%)</div>`;
  appendToChat(progWrap);

  const es = new EventSource(api.streamUrl());
  es.onmessage = (e) => {
    const data = JSON.parse(e.data);
    handleSSEEvent(data, es, progWrap);
  };
  es.onerror = () => {
    // O servidor fecha a conexão ao fim (None sentinel). Se já saímos, ignorar.
    if (state.stage === "done" || state.stage === "hitl") { es.close(); return; }
    // Senão, erro real de conexão.
    if (progWrap && progWrap.parentNode) progWrap.remove();
    pushHistory({ role: "assistant", content: "Conexão interrompida durante o processamento.", type: "error" });
    es.close();
  };
}

function handleSSEEvent(data, es, progWrap) {
  switch (data.type) {
    case "progress": {
      const p = data.at, total = data.total;
      const pct = total ? Math.round((p / total) * 100) : 0;
      const fill = $("#prog-fill");
      const label = $("#prog-label");
      if (fill) fill.style.width = Math.max(pct, 1) + "%";
      if (label) label.textContent = `Linha ${p}/${total} (${pct}%)`;
      break;
    }
    case "hitl": {
      if (progWrap && progWrap.parentNode) progWrap.remove();
      es.close();
      setStage("hitl");
      renderHitlCard(data.duvida);
      break;
    }
    case "done": {
      if (progWrap && progWrap.parentNode) progWrap.remove();
      es.close();
      setStage("done");
      pushHistory({
        role: "assistant",
        content: `Pedido de Compra gerado — <strong>${data.feito} de ${data.total} itens</strong> validados, vocabulário controlado OK, schema Pydantic aprovado.`,
        type: "text",
      });
      pushHistory({ role: "assistant", content: data.records, type: "preview_done", total: data.feito });
      renderDoneView(data.linhas);
      break;
    }
    case "error": {
      if (progWrap && progWrap.parentNode) progWrap.remove();
      es.close();
      pushHistory({ role: "assistant", content: `Falha no processamento: ${data.msg}`, type: "error" });
      setStage("ready");
      renderReadyActions(state.marca || "AL", state.cod || "012432");
      break;
    }
  }
}

// ── HITL card (stage hitl) ────────────────────────────────────
function renderHitlCard(duvida) {
  const ref = duvida.codigo_fornecedor || "N/A";
  const motivo = duvida.motivo_duvida || "";

  // tabela completa de campos
  const campos = [
    "categoria", "codigo_fornecedor", "material", "fornecedor", "banho",
    "pedra", "zirconia", "tamanho", "tipo_pedra", "marca", "quantidade",
    "peso", "labor_price", "silver_price", "unit_price_fob", "remarks",
  ];
  const labels = {
    categoria: "Categoria", codigo_fornecedor: "Código do Fornecedor", material: "Material",
    fornecedor: "Fornecedor", banho: "Banho", pedra: "Pedra", zirconia: "Zirconia",
    tamanho: "Tamanho", tipo_pedra: "Tipo Pedra", marca: "Marca", quantidade: "Quantidade",
    peso: "Peso", labor_price: "Labor Price", silver_price: "Silver Price",
    unit_price_fob: "Unit Price FOB", remarks: "Remarks",
  };
  const records = campos.map((c) => ({ Campo: labels[c] || c, Valor: duvida[c] ?? "" }));

  const card = el("div", "azime-hitl");
  card.id = "hitl-edit";
  card.innerHTML = `
    <div class="htitle"><span class="q">?</span> Confirmar campo</div>
    <div class="hsub">Linha <strong>${esc(ref)}</strong> · <span style="font-size:12px;color:var(--meta)">${esc(motivo)}</span></div>
    <p style="font-size:14.5px;color:var(--muted);margin-bottom:12px">Preciso da sua ajuda para completar esta linha. Confira todos os campos do Pedido de Compra abaixo e corrija o necessário.</p>
    <div class="azime-hitl-fields" id="hitl-fields"></div>
    <div class="azime-hitl-grid" style="margin-top:8px">
      <div class="field">
        <label for="hitl-cat">Categoria</label>
        <select class="azime-select" id="hitl-cat">
          ${["ANEL","BRINCO","COLAR","CORRENTE","PULSEIRA","BRACELETE","PINGENTE","ARGOLA","CONJUNTO","BROCHE"]
            .map((c) => `<option ${c===duvida.categoria?"selected":""}>${c}</option>`).join("")}
        </select>
      </div>
      <div class="field">
        <label for="hitl-cod">Código do Fornecedor</label>
        <input class="azime-input" id="hitl-cod" value="${esc(duvida.codigo_fornecedor || ref)}" title="SKU do fornecedor. '-MOI' é adicionado para moissanite." />
      </div>
      <div class="field full">
        <label for="hitl-pedra">Pedra</label>
        <input class="azime-input" id="hitl-pedra" value="${esc(duvida.pedra || "")}" />
      </div>
      <div class="field full">
        <label for="hitl-zir">Zirconia</label>
        <input class="azime-input" id="hitl-zir" value="${esc(duvida.zirconia || "")}" />
      </div>
      <div class="field">
        <label for="hitl-banho">Banho</label>
        <select class="azime-select" id="hitl-banho">
          ${["RÓDIO","OURO","OURO ROSÉ","PRETO","AMARELO"].map((b) => `<option ${b===duvida.banho?"selected":""}>${b}</option>`).join("")}
        </select>
      </div>
      <div class="field">
        <label for="hitl-marca">Marca</label>
        <select class="azime-select" id="hitl-marca">
          ${["AL","GR","NV"].map((m) => `<option ${m===duvida.marca?"selected":""}>${m}</option>`).join("")}
        </select>
      </div>
      <div class="field full">
        <label for="hitl-tam">Tamanho</label>
        <input class="azime-input" id="hitl-tam" value="${esc(duvida.tamanho || "0")}" title="Brinco/Bracelete: 0. Corrente/Pulseira: cm. Anel: distribuição." />
      </div>
      <div class="field full">
        <label for="hitl-rem">Remarks</label>
        <textarea class="azime-textarea" id="hitl-rem">${esc(duvida.remarks || "")}</textarea>
      </div>
    </div>
    <button class="azime-btn azime-btn-primary azime-btn-stretch" id="hitl-submit" style="margin-top:14px">${ICO.check} Continuar</button>`;
  appendToChat(card);
  $("#hitl-fields").appendChild(dfTable(records, { label: "campos do Pedido de Compra", total: records.length, maxRows: 50 }));

  card.querySelector("#hitl-submit").addEventListener("click", async () => {
    const payload = {
      categoria: $("#hitl-cat").value,
      codigo_fornecedor: $("#hitl-cod").value,
      pedra: $("#hitl-pedra").value,
      zirconia: $("#hitl-zir").value,
      banho: $("#hitl-banho").value,
      marca: $("#hitl-marca").value,
      tamanho: $("#hitl-tam").value,
      remarks: $("#hitl-rem").value,
    };
    card.remove();
    pushHistory({ role: "user", content: `Corrigi a linha ${ref}`, type: "text" });
    const res = await api.hitlResolve(payload);
    if (res.stage === "hitl") {
      setStage("hitl");
      renderHitlCard(res.duvida);
    } else if (res.stage === "done") {
      setStage("done");
      pushHistory({
        role: "assistant",
        content: `Confirmado. Retomando o loop. Pedido de Compra gerado — <strong>${res.feito} de ${res.total} itens</strong> validados.`,
        type: "text",
      });
      pushHistory({ role: "assistant", content: res.records, type: "preview_done", total: res.feito });
      renderDoneView(res.linhas);
    } else if (res.error) {
      pushHistory({ role: "assistant", content: `Erro: ${res.error}`, type: "error" });
    }
  });
}

// ── Done view (stage done) ────────────────────────────────────
function renderDoneView(linhas) {
  // Revisão de anéis pendentes
  state.pendentes = (linhas || []).filter((l) => l._proposta_expansao_anel);
  if (state.pendentes.length) {
    renderAnelReview();
    return;
  }
  renderDoneActions();
}

function renderAnelReview() {
  const lbl = el("div", "azime-section-label", "REVISÃO DE ANÉIS");
  appendToChat(lbl);
  state.pendentes.forEach((linha) => {
    const proposta = linha._proposta_expansao_anel || [];
    const ref = linha.codigo_fornecedor || "?";
    const chave = ref + "_" + (linha.tamanho || "");
    const card = el("div", "azime-hitl");
    card.dataset.chave = chave;
    card.innerHTML = `
      <div style="font-size:12px;font-weight:500;margin-bottom:6px">Anel · ${esc(ref)}</div>
      <div style="font-size:11px;color:var(--meta);margin-bottom:8px">${esc(linha.motivo_duvida || "")}</div>
      <div class="azime-hitl-fields" id="anel-tab-${esc(chave)}"></div>
      <div class="azime-row" style="margin-top:10px">
        <button class="azime-btn azime-btn-primary" id="anel-ok-${esc(chave)}">${ICO.check} Confirmar expansão</button>
        <button class="azime-btn" id="anel-pular-${esc(chave)}">Manter fechado</button>
      </div>`;
    appendToChat(card);
    const tab = card.querySelector(`#anel-tab-${CSS.escape(chave)}`);
    tab.appendChild(dfTable(proposta.map((p) => ({ Tamanho: p.tamanho, Quantidade: p.quantidade })),
      { label: "proposta de expansão", total: proposta.length, maxRows: 50 }));
    card.querySelector(`#anel-ok-${CSS.escape(chave)}`).addEventListener("click", async () => {
      const res = await api.anelDecide(chave, true);
      card.remove();
      afterAnelDecision(res);
    });
    card.querySelector(`#anel-pular-${CSS.escape(chave)}`).addEventListener("click", async () => {
      const res = await api.anelDecide(chave, false);
      card.remove();
      afterAnelDecision(res);
    });
  });
  appendToChat(el("hr", "azime-divider"));
}

async function afterAnelDecision(res) {
  // Atualiza pendentes removendo os resolvidos
  state.pendentes = res.pendentes || [];
  // Se ainda há cards de anel na tela, esperar; senão, ir p/ ações finais.
  if (!document.querySelector('.azime-hitl[data-chave]')) {
    if (state.pendentes.length === 0) {
      renderDoneActions(res.records, res.linhas);
    }
  }
}

function renderDoneActions(recordsOverride, linhasOverride) {
  // Limpa possível divider órfão
  const divs = document.querySelectorAll(".azime-divider");
  divs.forEach((d) => d.remove());

  // Atualiza preview com dados frescos
  api.pcPreview().then((snap) => {
    // re-render do preview_done já exibido: substitui o último preview_done
    const previews = document.querySelectorAll(".azime-df-pc");
    if (previews.length && snap.records.length) {
      const last = previews[previews.length - 1];
      const newTable = dfTable(snap.records, { wide: true, label: "Pedido de Compra final", total: snap.total });
      last.replaceWith(newTable);
    }
    state.pendentes = snap.pendentes || [];
    state.pcConfirmado = snap.pc_confirmado;

    // dúvidas pendentes
    const nDuvidas = (snap.linhas || []).filter((l) => l.duvida_pendente).length;
    if (nDuvidas) {
      pushHistory({ role: "assistant", content: `${nDuvidas} linha(s) com dúvida pendente. Revise antes de confirmar.`, type: "warning" });
    }

    appendDoneFooter(snap);
  });
}

function appendDoneFooter(snap) {
  const footer = el("div");
  footer.id = "done-footer";
  footer.innerHTML = `<div class="azime-section-label">AJUSTES VIA CHAT</div>`;

  // Form de edição
  const form = el("div");
  form.innerHTML = `
    <textarea class="azime-textarea" id="chat-edit" placeholder="Descreva a alteração... (ex.: linha 3: quantidade 50, banho OURO)"></textarea>
    <button class="azime-btn azime-btn-primary azime-btn-stretch" id="chat-send" style="margin-top:8px">${ICO.send} Enviar</button>`;
  footer.appendChild(form);

  // Confirm + download + JSON
  const row = el("div", "azime-row");
  row.style.marginTop = "12px";
  if (!state.pcConfirmado) {
    row.innerHTML = `<button class="azime-btn azime-btn-primary" id="confirm-pc">${ICO.check} Confirmar Pedido</button>`;
  } else {
    row.innerHTML = `<button class="azime-btn" id="download-pc">${ICO.download} Baixar Pedido.xlsx</button>`;
  }
  row.innerHTML += `<button class="azime-btn" id="view-json">${ICO.code} Ver JSON estruturado</button>`;
  footer.appendChild(row);

  const sid = `PC-${(snap.thread_id || "000000").slice(0, 6).toUpperCase()} · MARCA ${snap.marca} · FORN ${(snap.cod_fornecedor || "012432").trim()}`;
  footer.appendChild(el("div", "azime-result-id", esc(sid)));
  appendToChat(footer);

  // Handlers
  form.querySelector("#chat-send").addEventListener("click", async () => {
    const msg = $("#chat-edit").value.trim();
    if (!msg) return;
    pushHistory({ role: "user", content: esc(msg), type: "text" });
    $("#chat-edit").value = "";
    const res = await api.pcEdit(msg);
    pushHistory({ role: "assistant", content: esc(res.resposta), type: "text" });
    // Atualiza preview + footer
    const ok = $("#done-footer");
    if (ok) ok.remove();
    renderDoneActions(res.records, res.linhas);
  });

  const confirmBtn = footer.querySelector("#confirm-pc");
  if (confirmBtn) {
    confirmBtn.addEventListener("click", async () => {
      await api.pcConfirm();
      state.pcConfirmado = true;
      pushHistory({ role: "assistant", content: "Pedido de Compra confirmado. Download pronto.", type: "success" });
      footer.remove();
      appendDoneFooter({ ...snap, pc_confirmado: true });
    });
  }
  const dlBtn = footer.querySelector("#download-pc");
  if (dlBtn) {
    dlBtn.addEventListener("click", () => {
      window.location.href = api.downloadUrl();
    });
  }
  const jsonBtn = footer.querySelector("#view-json");
  if (jsonBtn) {
    jsonBtn.addEventListener("click", async () => {
      const { linha } = await api.pcJson();
      const block = el("pre", "azime-mono-block");
      block.textContent = JSON.stringify(linha, null, 2);
      appendToChat(block);
    });
  }
}

// ── Upload handler ────────────────────────────────────────────
async function handleUpload(file) {
  setStage("config");
  const area = renderChatShell();

  // chip do arquivo
  const sizeKb = Math.max(1, Math.round(file.size / 1024)) + " KB";
  pushHistory({ role: "user", content: fileChipHtml(file.name, sizeKb), type: "text" });

  try {
    const res = await api.upload(file);
    state.nomeArquivo = res.nome_arquivo;
    state.tipoMaterial = res.tipo_material;
    // Moeda/cotação vêm do perfil devolvido pelo cleaner (USD default).
    const perfil = res.perfil || {};
    state.moeda = perfil.moeda === "CNY" ? "CNY" : "USD";
    state.fatorCnySugerido = perfil.fator_cny_sugerido || null;
    setStage("config");

    pushHistory({
      role: "assistant",
      content: `Recebi a invoice. Detectei o cabeçalho, removi linhas de metadata e o rodapé. Encontrei <strong>${res.n_itens} itens</strong>, todos com pedra <code class="mono">${esc(res.tipo_material)}</code>.`,
      type: "text",
    });
    pushHistory({ role: "assistant", content: res.preview, type: "preview", total: res.n_itens });
    if (state.moeda === "CNY") {
      pushHistory({
        role: "assistant",
        content: `Detectei a invoice em <strong>CNY</strong> (fator sugerido: <code class="mono">${state.fatorCnySugerido}</code>). Preciso da <strong>cotação do dólar (CNY→USD)</strong> para converter os preços.`,
        type: "text",
      });
    } else {
      pushHistory({
        role: "assistant",
        content: "Preciso confirmar <strong>marca</strong> e <strong>código do fornecedor</strong> antes de gerar o pedido.",
        type: "text",
      });
    }

    renderConfigForm();
  } catch (e) {
    pushHistory({ role: "assistant", content: `Falha ao processar arquivo: ${e.message}`, type: "error" });
  }
}

// ── Nova sessão ───────────────────────────────────────────────
async function novaSessao() {
  state.chatHistorico = [];
  state.pendentes = [];
  state.nomeArquivo = "";
  state.pcConfirmado = false;
  const res = await api.reset();
  setStage("init");
  renderWelcome();
}

// ── Boot ──────────────────────────────────────────────────────
async function boot() {
  await loadLogo();
  $("#new-session-btn").addEventListener("click", novaSessao);

  try {
    const s = await api.createSession();
    state.sessionId = s.session_id;
    setStage("init");
    renderWelcome();
  } catch (e) {
    stageEl().innerHTML = `<div class="azime-msg-error">Não foi possível iniciar: ${esc(e.message)}</div>`;
  }
}

document.addEventListener("DOMContentLoaded", boot);

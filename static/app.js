import * as pdfjsLib from "/static/vendor/pdf.mjs?v=5.6.205";
import { WorkerMessageHandler } from "/static/vendor/pdf.worker.mjs?v=5.6.205";

const PDF_WORKER_URL = "/static/vendor/pdf.worker.mjs?v=5.6.205";
pdfjsLib.GlobalWorkerOptions.workerSrc = PDF_WORKER_URL;

// PDF.js 会在浏览器无法创建模块 Worker 时退回主线程；预先注册处理器，
// 避免回退路径再次动态下载 worker，从而消除偶发的 fake worker 加载失败。
globalThis.pdfjsWorker = { WorkerMessageHandler };

const elements = {
  stockForm: document.getElementById("stockForm"),
  stockCode: document.getElementById("stockCode"),
  analyzeStockButton: document.getElementById("analyzeStockButton"),
  progressLine: document.getElementById("progressLine"),
  headerStatus: document.getElementById("headerStatus"),
  emptyState: document.getElementById("emptyState"),
  dashboard: document.getElementById("dashboard"),
  companyName: document.getElementById("companyName"),
  yearRange: document.getElementById("yearRange"),
  scopeText: document.getElementById("scopeText"),
  kpiGrid: document.getElementById("kpiGrid"),
  trendTitle: document.getElementById("trendTitle"),
  metricSelect: document.getElementById("metricSelect"),
  chartLegend: document.getElementById("chartLegend"),
  trendChart: document.getElementById("trendChart"),
  metricTableBody: document.getElementById("metricTableBody"),
  metricNote: document.getElementById("metricNote"),
  evidenceTitle: document.getElementById("evidenceTitle"),
  evidenceBadge: document.getElementById("evidenceBadge"),
  evidenceFile: document.getElementById("evidenceFile"),
  evidenceSection: document.getElementById("evidenceSection"),
  evidenceCaption: document.getElementById("evidenceCaption"),
  pdfStage: document.getElementById("pdfStage"),
  pdfPlaceholder: document.getElementById("pdfPlaceholder"),
  pdfCanvasWrap: document.getElementById("pdfCanvasWrap"),
  pdfCanvas: document.getElementById("pdfCanvas"),
  pdfHighlight: document.getElementById("pdfHighlight"),
  prevPage: document.getElementById("prevPage"),
  nextPage: document.getElementById("nextPage"),
  pageInput: document.getElementById("pageInput"),
  pageCount: document.getElementById("pageCount"),
  zoomOut: document.getElementById("zoomOut"),
  zoomIn: document.getElementById("zoomIn"),
  zoomValue: document.getElementById("zoomValue"),
  qualityButton: document.getElementById("qualityButton"),
  qualityDialog: document.getElementById("qualityDialog"),
  qualitySummary: document.getElementById("qualitySummary"),
  warningList: document.getElementById("warningList"),
  reportYear: document.getElementById("reportYear"),
  reportType: document.getElementById("reportType"),
  disclosureTask: document.getElementById("disclosureTask"),
  disclosureTaskText: document.getElementById("disclosureTaskText"),
  financialTask: document.getElementById("financialTask"),
  financialTaskText: document.getElementById("financialTaskText"),
  disclosureTab: document.getElementById("disclosureTab"),
  disclosureTabState: document.getElementById("disclosureTabState"),
  financialTab: document.getElementById("financialTab"),
  financialTabState: document.getElementById("financialTabState"),
  disclosurePanel: document.getElementById("disclosurePanel"),
  financialPanel: document.getElementById("financialPanel"),
  disclosureEmptyState: document.getElementById("disclosureEmptyState"),
  disclosureError: document.getElementById("disclosureError"),
  financialError: document.getElementById("financialError"),
  disclosureDashboard: document.getElementById("disclosureDashboard"),
  disclosureCompany: document.getElementById("disclosureCompany"),
  disclosurePeriod: document.getElementById("disclosurePeriod"),
  disclosurePeerNote: document.getElementById("disclosurePeerNote"),
  disclosureCards: document.getElementById("disclosureCards"),
  comparisonNote: document.getElementById("comparisonNote"),
  disclosureComparison: document.getElementById("disclosureComparison"),
  disclosureHistory: document.getElementById("disclosureHistory"),
  disclosureSourceSummary: document.getElementById("disclosureSourceSummary"),
  disclosureAudit: document.getElementById("disclosureAudit"),
};

const state = {
  result: null,
  activeMetricId: "revenue",
  pdfDocument: null,
  pdfFileId: null,
  pdfPageNumber: 1,
  pdfZoom: 1,
  activeEvidence: null,
  renderTask: null,
  pdfLoadToken: 0,
  pdfRenderToken: 0,
  disclosureResult: null,
  isBusy: false,
  activeTab: "disclosure",
  tasks: { disclosure: "idle", financial: "idle" },
};

function clientLog(level, message, details = {}) {
  const payload = {
    level,
    message: String(message || "浏览器未提供错误消息"),
    details: {
      ...details,
      pageUrl: window.location.href,
      userAgent: navigator.userAgent,
      occurredAt: new Date().toISOString(),
    },
  };
  fetch("/api/client-log", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    keepalive: true,
  }).catch(() => {
    // 日志上报本身失败时保持静默，避免递归产生新错误。
  });
}

function reportClientError(message, error, details = {}) {
  clientLog("error", message, {
    ...details,
    errorName: error?.name || "Error",
    errorMessage: error?.message || String(error),
    stack: error?.stack || "",
  });
}

window.addEventListener("error", (event) => {
  clientLog("error", event.message || "未捕获的 JavaScript 错误", {
    source: event.filename || "",
    line: event.lineno || 0,
    column: event.colno || 0,
    stack: event.error?.stack || "",
  });
});

window.addEventListener("unhandledrejection", (event) => {
  const reason = event.reason;
  reportClientError("未处理的 Promise 拒绝", reason instanceof Error ? reason : new Error(String(reason)));
});

async function api(url, options = {}) {
  const response = await fetch(url, options);
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const error = new Error(payload?.error || `请求失败（${response.status}）`);
    error.status = response.status;
    error.apiUrl = url;
    throw error;
  }
  return payload;
}

function setProgress(message, isError = false) {
  elements.progressLine.textContent = message;
  elements.progressLine.classList.toggle("is-error", isError);
}

function setBusy(busy) {
  state.isBusy = busy;
  const validCode = /^\d{6}$/.test(elements.stockCode.value.trim());
  elements.analyzeStockButton.disabled = busy || !validCode;
  elements.stockCode.disabled = busy;
  elements.reportYear.disabled = busy;
  elements.reportType.disabled = busy;
  syncHeaderStatus();
}

const TASK_LABELS = { idle: "等待", running: "进行中", done: "完成", error: "失败" };

function updateTask(name, status, detail) {
  state.tasks[name] = status;
  const card = name === "disclosure" ? elements.disclosureTask : elements.financialTask;
  const text = name === "disclosure" ? elements.disclosureTaskText : elements.financialTaskText;
  const tab = name === "disclosure" ? elements.disclosureTab : elements.financialTab;
  const tabState = name === "disclosure" ? elements.disclosureTabState : elements.financialTabState;
  card.dataset.state = status;
  tab.dataset.state = status;
  text.textContent = detail || TASK_LABELS[status];
  tabState.textContent = TASK_LABELS[status];
  syncHeaderStatus();
}

function syncHeaderStatus() {
  const statuses = Object.values(state.tasks);
  const running = statuses.filter((value) => value === "running").length;
  const done = statuses.filter((value) => value === "done").length;
  const failed = statuses.filter((value) => value === "error").length;
  if (running) {
    elements.headerStatus.textContent = `双路径分析中 · ${2 - running}/2 已结束`;
  } else if (done || failed) {
    elements.headerStatus.textContent = `本次完成 ${done}/2${failed ? ` · 失败 ${failed}/2` : ""}`;
  } else {
    elements.headerStatus.textContent = "等待输入股票代码";
  }
}

function switchTab(name) {
  state.activeTab = name;
  const disclosureActive = name === "disclosure";
  elements.disclosureTab.classList.toggle("is-active", disclosureActive);
  elements.disclosureTab.setAttribute("aria-selected", String(disclosureActive));
  elements.financialTab.classList.toggle("is-active", !disclosureActive);
  elements.financialTab.setAttribute("aria-selected", String(!disclosureActive));
  elements.disclosurePanel.classList.toggle("is-active", disclosureActive);
  elements.disclosurePanel.hidden = !disclosureActive;
  elements.financialPanel.classList.toggle("is-active", !disclosureActive);
  elements.financialPanel.hidden = disclosureActive;
  if (!disclosureActive && state.result) {
    requestAnimationFrame(() => renderMetric(state.activeMetricId));
  }
}

document.querySelectorAll("[data-tab]").forEach((tab) => {
  tab.addEventListener("click", () => switchTab(tab.dataset.tab));
});

elements.stockCode.addEventListener("input", () => {
  elements.stockCode.value = elements.stockCode.value.replace(/\D/g, "").slice(0, 6);
  setBusy(false);
});

async function runFinancialAnalysis(stockCode) {
  updateTask("financial", "running", "正在检索、下载并解析五年年报…");
  elements.financialError.hidden = true;
  try {
    const result = await api("/api/analyze-stock", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stock_code: stockCode }),
    });
    renderDashboard(result);
    const reports = result.annual_report_archive?.reports || [];
    const downloaded = reports.filter((item) => !item.reused).length;
    updateTask("financial", "done", `完成：${reports.length} 份年报，下载 ${downloaded} 份`);
    return result;
  } catch (error) {
    reportClientError("股票代码分析失败", error, {
      stockCode,
      apiUrl: error?.apiUrl || "/api/analyze-stock",
      status: error?.status || null,
    });
    elements.financialError.textContent = `FinancialIndicatorsAssistant：${error.message}`;
    elements.financialError.hidden = false;
    updateTask("financial", "error", error.message);
    throw error;
  }
}

async function runDisclosureAnalysis(stockCode) {
  updateTask("disclosure", "running", "正在核对历史数据、同行与巨潮披露记录…");
  elements.disclosureError.hidden = true;
  try {
    const result = await api("/api/disclosure", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        stock_code: stockCode,
        report_year: Number(elements.reportYear.value),
        report_type: elements.reportType.value,
      }),
    });
    renderDisclosureDashboard(result);
    updateTask("disclosure", "done", `完成：${result.filters.report_year} ${result.report_meta.short_label}`);
    return result;
  } catch (error) {
    reportClientError("披露时间分析失败", error, {
      stockCode,
      apiUrl: error?.apiUrl || "/api/disclosure",
      status: error?.status || null,
    });
    elements.disclosureError.textContent = `DisclosureTimeAssistant：${error.message}`;
    elements.disclosureError.hidden = false;
    updateTask("disclosure", "error", error.message);
    throw error;
  }
}

elements.stockForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const stockCode = elements.stockCode.value.trim();
  if (!/^\d{6}$/.test(stockCode)) {
    setProgress("请输入 6 位股票代码。", true);
    return;
  }
  setBusy(true);
  setProgress(`已同时启动 ${stockCode} 的披露时间与财务指标分析；可在两个页签之间切换。`);
  const results = await Promise.allSettled([
    runDisclosureAnalysis(stockCode),
    runFinancialAnalysis(stockCode),
  ]);
  const completed = results.filter((item) => item.status === "fulfilled").length;
  const failed = results.length - completed;
  setProgress(
    failed ? `并行分析结束：${completed}/2 条路径成功，${failed}/2 条路径失败。成功结果仍可正常查看。` : "并行分析完成：两条路径均已生成结果。",
    completed === 0,
  );
  setBusy(false);
});

const dateText = (value) => value || "暂无数据";
const kindText = (type) => ({ ACTUAL: "实际披露", RESERVATION: "预约披露", MISSING: "暂无数据" })[type] || type;
const kindClass = (type) => ({ ACTUAL: "actual", RESERVATION: "reservation", MISSING: "missing" })[type] || "missing";

function safeHttpUrl(value) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch {
    return "";
  }
}

function disclosureSourceCell(row) {
  if (row.source_type === "HISTORY_XLSX") {
    return `<div class="source-detail">历史 Excel · 第 ${escapeHtml(row.source_row_number)} 行<br>${escapeHtml(row.source_file)}</div>`;
  }
  if (row.source_type === "CNINFO_OFFICIAL") {
    const url = safeHttpUrl(row.source_url);
    return `<div class="source-detail">${url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">巨潮资讯网官方</a>` : "巨潮资讯网官方"}<br>抓取：${escapeHtml(row.fetched_at)}</div>`;
  }
  return '<div class="source-detail missing">没有可验证来源</div>';
}

function renderDisclosureDashboard(data) {
  state.disclosureResult = data;
  elements.disclosureEmptyState.hidden = true;
  elements.disclosureDashboard.hidden = false;
  elements.disclosureCompany.textContent = `${data.target_company.short_name}（${data.target_company.stock_code}）`;
  elements.disclosurePeriod.textContent = `${data.filters.report_year} · ${data.report_meta.label}`;
  elements.disclosurePeerNote.textContent = data.peer_resolution.automatic_reason;

  const target = data.rows.find((row) => row.is_target);
  const rank = data.metrics.target_rank ? `${data.metrics.target_rank} / ${data.metrics.company_count}` : "—";
  const delta = data.metrics.median_delta_days;
  const deltaText = delta === null ? "无法比较" : delta === 0 ? "与中位数同日" : `${Math.abs(delta)} 天${delta < 0 ? "更早" : "更晚"}`;
  const cards = [
    ["目标公司", data.target_company.short_name, data.target_company.stock_code, ""],
    ["本期采用日期", dateText(target.display_date), kindText(target.display_date_type), kindClass(target.display_date_type)],
    ["同行排序", rank, "按采用日期由早到晚", ""],
    ["同行中位日期", dateText(data.metrics.median_date), deltaText, ""],
  ];
  elements.disclosureCards.innerHTML = cards.map((item) => `
    <article class="disclosure-card"><span class="label">${escapeHtml(item[0])}</span><strong class="${item[3]}">${escapeHtml(item[1])}</strong><small>${escapeHtml(item[2])}</small></article>
  `).join("");

  const selectedPeers = data.peer_resolution.selected_peers || [];
  const peersByCode = Object.fromEntries(selectedPeers.map((peer) => [peer.stock_code, peer]));
  elements.comparisonNote.textContent = data.peer_resolution.automatic_status === "resolved"
    ? `IndustryCode ${data.peer_resolution.industry_code} · 自动选择 ${selectedPeers.length} 家同行`
    : data.peer_resolution.automatic_reason;
  const comparisonRows = data.rows.map((row) => {
    const peer = peersByCode[row.stock_code];
    const assetText = peer ? `${(Number(peer.total_assets) / 100000000).toLocaleString("zh-CN", { maximumFractionDigits: 2 })} 亿元` : "—";
    return `<tr class="${row.is_target ? "target" : ""}">
      <td><div class="company">${escapeHtml(row.short_name)}${row.is_target ? " · 目标" : ""}</div><div class="code">${escapeHtml(row.stock_code)}</div></td>
      <td>${row.is_target ? "目标公司" : `<strong>${escapeHtml(assetText)}</strong>${peer ? `<div class="code">${escapeHtml(peer.asset_year)} 年总资产</div>` : ""}`}</td>
      <td><strong class="${kindClass(row.display_date_type)}">${escapeHtml(dateText(row.display_date))}</strong></td>
      <td class="actual">${escapeHtml(dateText(row.actual_disclosure_date))}</td>
      <td class="reservation">${escapeHtml(dateText(row.selected_reservation_date))}<div class="code">${escapeHtml(row.selected_reservation_label || "")}</div></td>
      <td><span class="date-pill ${kindClass(row.display_date_type)}">${escapeHtml(kindText(row.display_date_type))}</span></td>
      <td>${disclosureSourceCell(row)}</td>
    </tr>`;
  }).join("");
  elements.disclosureComparison.innerHTML = `<table class="disclosure-table"><thead><tr><th>公司</th><th>同行选择依据</th><th>本期采用日期</th><th>实际披露</th><th>最终预约</th><th>采用类型</th><th>来源</th></tr></thead><tbody>${comparisonRows}</tbody></table>`;

  const types = ["Q1", "H1", "Q3", "FY"];
  const labels = { Q1: "一季报", H1: "半年报", Q3: "三季报", FY: "年报" };
  const historyRows = data.history.map((year) => `<tr><td><strong>${escapeHtml(year.report_year)}</strong></td>${types.map((type) => {
    const row = year.records[type];
    return `<td><div class="history-cell ${kindClass(row.display_date_type)}"><strong>${escapeHtml(dateText(row.display_date))}</strong><span>${escapeHtml(kindText(row.display_date_type))}</span></div></td>`;
  }).join("")}</tr>`).join("");
  elements.disclosureHistory.innerHTML = `<table class="disclosure-table"><thead><tr><th>年度</th>${types.map((type) => `<th>${labels[type]}</th>`).join("")}</tr></thead><tbody>${historyRows}</tbody></table>`;

  const refresh = data.data_source.official_refresh;
  const errors = refresh.errors || [];
  const refreshText = ({ completed: "巨潮增量抓取完成", cache_current: "巨潮缓存仍有效", not_needed: "本次无需巨潮增量", disabled: "离线模式", partial: "巨潮部分抓取失败", failed: "巨潮抓取失败" })[refresh.status] || refresh.status;
  elements.disclosureSourceSummary.innerHTML = `
    <p><strong>数据策略：</strong>${escapeHtml(data.data_source.notice)}</p>
    <p><strong>同行策略：</strong>${escapeHtml(data.peer_resolution.automatic_reason)}</p>
    <p><strong>本次刷新：</strong>${escapeHtml(refreshText)}；更新 ${escapeHtml(refresh.updated_records)} 条，未找到 ${escapeHtml(refresh.not_found_records)} 条。</p>
    ${errors.length ? `<p class="reservation"><strong>抓取异常：</strong>${errors.map(escapeHtml).join("<br>")}</p>` : ""}
  `;
  const audit = data.data_source.history || {};
  const peerAudit = data.data_source.peer_selection || {};
  elements.disclosureAudit.textContent = [
    `模式: ${data.data_source.mode}`,
    `历史文件: ${audit.source_file || "—"}`,
    `Excel 数据行: ${audit.source_rows ?? "—"}`,
    `有效记录: ${audit.scope_records ?? "—"}`,
    `公司数: ${audit.scope_companies ?? "—"}`,
    `Excel 最新报告期: ${audit.latest_period || "—"}`,
    `行业文件: ${peerAudit.industry?.source_file || "—"}`,
    `总资产数据: ${peerAudit.total_assets?.data_file || "—"}`,
    `巨潮报告期原始缓存: ${refresh.sections_cache_file || "无"}`,
    `巨潮记录库: ${data.data_source.database_file}`,
  ].join("\n");
}

function metricById(metricId) {
  return state.result?.metrics.find((metric) => metric.metric_id === metricId) || null;
}

function valueFor(metric, year) {
  return metric?.values?.[String(year)] || null;
}

function deltaClass(changeValue) {
  const numeric = Number(changeValue);
  if (!Number.isFinite(numeric) || numeric === 0) return "neutral";
  return numeric > 0 ? "positive" : "negative";
}

function renderDashboard(result) {
  state.result = result;
  elements.emptyState.hidden = true;
  elements.dashboard.hidden = false;
  elements.companyName.textContent = result.company_name || "未知公司";
  elements.yearRange.textContent = result.years.length ? `${result.years[0]}–${result.years.at(-1)}` : "";
  const policyLabel = result.value_policy === "same_year_report_preferred"
    ? "各年原报告优先"
    : result.value_policy === "latest_restated"
      ? "最新重述口径"
      : result.value_policy;
  elements.scopeText.textContent = `${result.accounting_scope} · ${policyLabel}`;

  elements.metricSelect.replaceChildren();
  result.metrics.forEach((metric) => {
    const option = document.createElement("option");
    option.value = metric.metric_id;
    option.textContent = metric.label;
    elements.metricSelect.append(option);
  });
  state.activeMetricId = result.metrics.some((metric) => metric.metric_id === "revenue") ? "revenue" : result.metrics[0]?.metric_id;
  elements.metricSelect.value = state.activeMetricId;
  renderKpis();
  renderMetric(state.activeMetricId);
  renderQuality();
}

function renderKpis() {
  const latestYear = state.result.latest_year;
  const ids = ["revenue", "net_profit", "operating_cash_flow", "roe"];
  elements.kpiGrid.replaceChildren();
  ids.forEach((metricId) => {
    const metric = metricById(metricId);
    if (!metric) return;
    const entry = valueFor(metric, latestYear);
    const card = document.createElement("article");
    card.className = "kpi-card";
    const label = document.createElement("span");
    label.className = "label";
    label.textContent = `${latestYear} · ${metric.short_label}`;
    const value = document.createElement("strong");
    value.className = "value";
    value.textContent = entry?.display_value || "未披露";
    const delta = document.createElement("span");
    delta.className = `delta ${deltaClass(entry?.change_value)}`;
    delta.textContent = entry?.status === "ok" ? `同比 ${entry.change_display}` : entry?.reason || "未可靠定位";
    card.append(label, value, delta);
    elements.kpiGrid.append(card);
  });
}

elements.metricSelect.addEventListener("change", (event) => renderMetric(event.target.value));

function statusLabel(entry) {
  if (entry.status !== "ok") return { label: "未披露", className: "" };
  if (entry.evidence?.report_year !== entry.year) return { label: "跨年补充", className: "fallback" };
  if (entry.is_fallback) return { label: "补充来源", className: "fallback" };
  if (entry.restatement_status === "adjusted") return { label: "调整后", className: "adjusted" };
  return { label: "原表提取", className: "" };
}

function renderMetric(metricId) {
  state.activeMetricId = metricId;
  const metric = metricById(metricId);
  if (!metric) return;
  const changeUnit = metric.kind === "percent" ? "百分点" : "%";
  elements.trendTitle.textContent = `${metric.label}（${metric.display_unit}，${changeUnit}）`;
  renderChart(metric);
  elements.metricTableBody.replaceChildren();
  [...state.result.years].reverse().forEach((year) => {
    const entry = valueFor(metric, year);
    const row = document.createElement("tr");
    const yearCell = document.createElement("td");
    yearCell.textContent = year;
    const valueCell = document.createElement("td");
    valueCell.className = "numeric";
    valueCell.textContent = entry?.display_value || "未披露";
    const deltaCell = document.createElement("td");
    deltaCell.className = `numeric delta ${deltaClass(entry?.change_value)}`;
    deltaCell.textContent = entry?.change_display || "—";
    if (entry?.reason) deltaCell.title = entry.reason;
    const statusCell = document.createElement("td");
    const status = statusLabel(entry || { status: "missing" });
    const chip = document.createElement("span");
    chip.className = `status-chip ${status.className}`;
    chip.textContent = status.label;
    statusCell.append(chip);
    const actionCell = document.createElement("td");
    if (entry?.status === "ok" && entry.evidence) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "evidence-link";
      button.textContent = "查看证据";
      button.addEventListener("click", () => loadEvidence(metric, year, entry));
      actionCell.append(button);
    }
    row.append(yearCell, valueCell, deltaCell, statusCell, actionCell);
    elements.metricTableBody.prepend(row);
  });

  const entries = state.result.years.map((year) => valueFor(metric, year)).filter(Boolean);
  if (entries.some((entry) => entry.status === "ok" && entry.evidence?.report_year !== entry.year)) {
    elements.metricNote.textContent = "个别年度在本年年报中未可靠定位，已明确标记为“跨年补充”；其证据文件名会如实显示来源报告年度。";
  } else if (entries.some((entry) => entry.is_fallback)) {
    elements.metricNote.textContent = "指定摘要表未完整披露该指标；带“补充来源”的数值来自合并利润表，证据类型不会被隐藏。";
  } else if (entries.some((entry) => entry.restatement_status === "adjusted")) {
    elements.metricNote.textContent = "部分年度采用后续年报披露的调整后数。调整前数仍保留在标准化数据的 alternatives 字段中。";
  } else {
    elements.metricNote.textContent = metric.kind === "percent"
      ? "收益率指标使用百分点变化，避免把百分点与相对同比混为一谈。"
      : "原始金额按元保存，界面统一换算为亿元；同比使用未四舍五入的原始值计算。";
  }
  resetEvidencePrompt();
}

function niceNumber(value, round) {
  if (!Number.isFinite(value) || value <= 0) return 1;
  const exponent = Math.floor(Math.log10(value));
  const fraction = value / (10 ** exponent);
  let niceFraction;
  if (round) {
    niceFraction = fraction < 1.5 ? 1 : fraction < 3 ? 2 : fraction < 7 ? 5 : 10;
  } else {
    niceFraction = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10;
  }
  return niceFraction * (10 ** exponent);
}

function chartAxis(values, targetTickCount = 4) {
  const finiteValues = values.filter(Number.isFinite);
  let rawMin = Math.min(0, ...finiteValues);
  let rawMax = Math.max(0, ...finiteValues);
  if (rawMin === rawMax) {
    rawMin = rawMin === 0 ? 0 : rawMin - Math.abs(rawMin) * 0.1;
    rawMax = rawMax === 0 ? 1 : rawMax + Math.abs(rawMax) * 0.1;
  }
  const step = niceNumber((rawMax - rawMin) / targetTickCount, true);
  const min = Math.floor(rawMin / step) * step;
  const max = Math.ceil(rawMax / step) * step;
  const ticks = [];
  const count = Math.round((max - min) / step);
  for (let index = 0; index <= count; index += 1) {
    ticks.push(Number((min + step * index).toPrecision(12)));
  }
  return { min, max, step, ticks };
}

function formatAxisTick(value, step) {
  const decimals = step >= 1 ? 0 : Math.min(2, Math.max(1, Math.ceil(-Math.log10(step))));
  return value.toLocaleString("zh-CN", {
    minimumFractionDigits: 0,
    maximumFractionDigits: decimals,
  });
}

function renderChart(metric) {
  const canvas = elements.trendChart;
  const rect = canvas.getBoundingClientRect();
  const cssWidth = Math.max(460, rect.width || canvas.parentElement.clientWidth || 700);
  const cssHeight = 320;
  const ratio = Math.max(1, window.devicePixelRatio || 1);
  canvas.width = Math.round(cssWidth * ratio);
  canvas.height = Math.round(cssHeight * ratio);
  canvas.style.height = `${cssHeight}px`;
  const context = canvas.getContext("2d");
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, cssWidth, cssHeight);

  const styles = getComputedStyle(document.documentElement);
  const colors = {
    ink: styles.getPropertyValue("--ink").trim(),
    muted: styles.getPropertyValue("--muted").trim(),
    line: styles.getPropertyValue("--line").trim(),
    blue: styles.getPropertyValue("--blue").trim(),
    red: styles.getPropertyValue("--red").trim(),
    panel: styles.getPropertyValue("--panel").trim(),
  };
  const years = state.result.years;
  const entries = years.map((year) => valueFor(metric, year));
  const absoluteValues = entries.map((entry) => {
    if (entry?.status !== "ok") return null;
    const value = Number(entry.value);
    return metric.kind === "amount" ? value / 100000000 : value;
  });
  const changeValues = entries.map((entry) => entry?.change_value == null ? null : Number(entry.change_value));
  const absoluteAxis = chartAxis(absoluteValues);
  const changeAxis = chartAxis(changeValues);
  const absoluteUnit = metric.display_unit;
  const changeUnit = metric.kind === "percent" ? "百分点" : "%";
  canvas.dataset.leftAxisUnit = absoluteUnit;
  canvas.dataset.rightAxisUnit = changeUnit;
  canvas.dataset.xAxis = "年份";
  const margin = { left: 76, right: 76, top: 43, bottom: 52 };
  const plotWidth = cssWidth - margin.left - margin.right;
  const plotHeight = cssHeight - margin.top - margin.bottom;
  const xStep = plotWidth / Math.max(years.length, 1);
  const barWidth = Math.min(48, xStep * 0.46);
  const yAbsolute = (value) => margin.top + (absoluteAxis.max - value) / (absoluteAxis.max - absoluteAxis.min) * plotHeight;
  const yChange = (value) => margin.top + (changeAxis.max - value) / (changeAxis.max - changeAxis.min) * plotHeight;

  context.font = "12px Microsoft YaHei UI, sans-serif";
  context.textBaseline = "middle";

  context.font = "600 12px Microsoft YaHei UI, sans-serif";
  context.fillStyle = colors.blue;
  context.textAlign = "left";
  context.fillText(`柱状图（${absoluteUnit}）`, margin.left, 15);
  context.fillStyle = colors.red;
  context.textAlign = "right";
  context.fillText(`折线图（${changeUnit}）`, margin.left + plotWidth, 15);

  context.font = "12px Microsoft YaHei UI, sans-serif";
  absoluteAxis.ticks.forEach((tick) => {
    const y = yAbsolute(tick);
    context.strokeStyle = colors.line;
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(margin.left, y);
    context.lineTo(margin.left + plotWidth, y);
    context.stroke();

    context.strokeStyle = colors.blue;
    context.beginPath();
    context.moveTo(margin.left - 4, y);
    context.lineTo(margin.left, y);
    context.stroke();
    context.fillStyle = colors.blue;
    context.textAlign = "right";
    context.fillText(formatAxisTick(tick, absoluteAxis.step), margin.left - 9, y);
  });

  context.strokeStyle = colors.blue;
  context.lineWidth = 1.4;
  context.beginPath();
  context.moveTo(margin.left, margin.top);
  context.lineTo(margin.left, margin.top + plotHeight);
  context.stroke();

  changeAxis.ticks.forEach((tick) => {
    const y = yChange(tick);
    context.strokeStyle = colors.red;
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(margin.left + plotWidth, y);
    context.lineTo(margin.left + plotWidth + 4, y);
    context.stroke();
    context.fillStyle = colors.red;
    context.textAlign = "left";
    context.fillText(formatAxisTick(tick, changeAxis.step), margin.left + plotWidth + 9, y);
  });

  context.strokeStyle = colors.red;
  context.lineWidth = 1.4;
  context.beginPath();
  context.moveTo(margin.left + plotWidth, margin.top);
  context.lineTo(margin.left + plotWidth, margin.top + plotHeight);
  context.stroke();

  const absoluteZeroY = yAbsolute(0);

  absoluteValues.forEach((value, index) => {
    const x = margin.left + xStep * index + xStep / 2;
    context.fillStyle = colors.blue;
    if (Number.isFinite(value)) {
      const y = yAbsolute(value);
      const barTop = Math.min(y, absoluteZeroY);
      const barHeight = Math.max(1, Math.abs(absoluteZeroY - y));
      context.globalAlpha = 0.84;
      context.fillRect(x - barWidth / 2, barTop, barWidth, barHeight);
      context.globalAlpha = 1;
      context.fillStyle = colors.muted;
      context.textAlign = "center";
      const label = metric.kind === "amount" ? value.toFixed(value > 100 ? 0 : 2) : value.toFixed(2);
      const labelY = value >= 0 ? y - 10 : y + 11;
      context.fillText(label, x, Math.max(margin.top + 8, Math.min(margin.top + plotHeight - 8, labelY)));
    }
    context.fillStyle = colors.muted;
    context.textAlign = "center";
    context.fillText(String(years[index]), x, margin.top + plotHeight + 19);
  });

  context.strokeStyle = colors.line;
  context.lineWidth = 1;
  context.beginPath();
  context.moveTo(margin.left, margin.top + plotHeight);
  context.lineTo(margin.left + plotWidth, margin.top + plotHeight);
  context.stroke();
  context.fillStyle = colors.muted;
  context.textAlign = "center";
  context.fillText("年份", margin.left + plotWidth / 2, cssHeight - 10);

  const points = changeValues.map((value, index) => Number.isFinite(value) ? {
    value,
    x: margin.left + xStep * index + xStep / 2,
    y: yChange(value),
  } : null);
  context.strokeStyle = colors.red;
  context.lineWidth = 2.2;
  context.beginPath();
  let segmentOpen = false;
  points.forEach((point) => {
    if (!point) {
      segmentOpen = false;
      return;
    }
    if (segmentOpen) context.lineTo(point.x, point.y);
    else context.moveTo(point.x, point.y);
    segmentOpen = true;
  });
  context.stroke();
  points.filter(Boolean).forEach((point) => {
    context.fillStyle = colors.panel;
    context.strokeStyle = colors.red;
    context.lineWidth = 2;
    context.beginPath();
    context.arc(point.x, point.y, 4, 0, Math.PI * 2);
    context.fill();
    context.stroke();
    context.fillStyle = colors.muted;
    context.textAlign = "center";
    const sign = point.value > 0 ? "+" : "";
    context.fillText(`${sign}${point.value.toFixed(1)}`, point.x, point.y - 13);
  });

  elements.chartLegend.innerHTML = `
    <span class="legend-item"><i class="legend-bar"></i>柱状图（${absoluteUnit}）</span>
    <span class="legend-item"><i class="legend-line"></i>折线图（${changeUnit}）</span>`;
  canvas.setAttribute(
    "aria-label",
    `${metric.label}${years[0] || ""}年至${years.at(-1) || ""}年趋势图；蓝色柱状图使用左侧${absoluteUnit}轴，红色折线图使用右侧${changeUnit}轴，共用年份横轴。`,
  );
}

async function loadEvidence(metric, year, entry) {
  const evidence = entry.evidence;
  const token = ++state.pdfLoadToken;
  state.activeEvidence = evidence;
  state.pdfPageNumber = evidence.page_number;
  state.pdfZoom = 1;
  elements.zoomValue.textContent = "100%";
  elements.evidenceTitle.textContent = `${year} · ${metric.short_label}`;
  elements.evidenceFile.textContent = evidence.file_name;
  elements.evidenceSection.textContent = `${evidence.section} · 第 ${evidence.page_number} 页`;
  elements.evidenceBadge.textContent = "正在定位";
  elements.evidenceCaption.textContent = `高亮行：${evidence.row_label}；列：${evidence.column_label}。原始值 ${entry.raw_value}，标准化后 ${entry.display_value}。`;
  if (window.matchMedia("(max-width: 1080px)").matches) {
    elements.evidenceTitle.closest(".evidence-column")?.scrollIntoView({ block: "start", behavior: "smooth" });
  }
  await ensurePdfLoaded(evidence, token);
  if (token === state.pdfLoadToken && state.pdfDocument) {
    elements.evidenceBadge.textContent = evidence.report_year !== year
      ? "跨年补充"
      : entry.is_fallback
        ? "补充来源"
        : entry.restatement_status === "adjusted"
          ? "调整后口径"
          : "原表提取";
    elements.evidenceSection.textContent = `${evidence.section} · 当前显示第 ${state.pdfPageNumber} 页`;
  }
}

function resetEvidencePrompt() {
  state.activeEvidence = null;
  state.pdfRenderToken += 1;
  elements.evidenceTitle.textContent = "请选择有数据的年度";
  elements.evidenceBadge.textContent = "等待定位";
  elements.evidenceFile.textContent = "—";
  elements.evidenceSection.textContent = "—";
  elements.evidenceCaption.textContent = "点击左侧“查看证据”，PDF 阅读器会切换到对应文件和页码。";
  elements.pdfHighlight.hidden = true;
  elements.pdfCanvasWrap.hidden = true;
  elements.pdfPlaceholder.hidden = false;
  elements.pdfPlaceholder.innerHTML = "<strong>PDF 阅读器</strong><span>点击左侧“查看证据”后加载并跳转</span>";
  elements.pageInput.value = "1";
  elements.pageCount.textContent = "—";
  elements.prevPage.disabled = true;
  elements.nextPage.disabled = true;
  elements.pdfStage.dataset.pageNumber = "";
}

async function cancelActivePdfRender() {
  const task = state.renderTask;
  if (!task) return;
  try {
    task.cancel();
    await task.promise;
  } catch (error) {
    if (error?.name !== "RenderingCancelledException") throw error;
  } finally {
    if (state.renderTask === task) state.renderTask = null;
  }
}

async function ensurePdfLoaded(evidence, token) {
  try {
    if (!state.pdfDocument || state.pdfFileId !== evidence.file_id) {
      await cancelActivePdfRender();
      if (state.pdfDocument) await state.pdfDocument.destroy();
      state.pdfDocument = null;
      state.pdfFileId = evidence.file_id;
      elements.pdfPlaceholder.hidden = false;
      elements.pdfCanvasWrap.hidden = true;
      elements.pdfPlaceholder.innerHTML = "<strong>正在加载 PDF…</strong><span>首次打开文件可能需要数秒</span>";
      const task = pdfjsLib.getDocument({ url: evidence.pdf_url });
      const documentRef = await task.promise;
      if (token !== state.pdfLoadToken) {
        await documentRef.destroy();
        return;
      }
      state.pdfDocument = documentRef;
    }
    if (token !== state.pdfLoadToken || !state.pdfDocument) return;
    elements.pageCount.textContent = String(state.pdfDocument.numPages);
    elements.pageInput.max = String(state.pdfDocument.numPages);
    await renderPdfPage(evidence.page_number, token);
  } catch (error) {
    if (token !== state.pdfLoadToken) return;
    reportClientError("PDF 证据加载或渲染失败", error, {
      fileId: evidence.file_id,
      fileName: evidence.file_name,
      targetPage: evidence.page_number,
      pdfUrl: evidence.pdf_url,
    });
    elements.pdfPlaceholder.hidden = false;
    elements.pdfCanvasWrap.hidden = true;
    elements.pdfPlaceholder.innerHTML = `<strong>PDF 加载失败</strong><span>${escapeHtml(error.message)}</span>`;
    elements.evidenceBadge.textContent = "加载失败";
  }
}

async function renderPdfPage(pageNumber, loadToken = state.pdfLoadToken) {
  if (!state.pdfDocument) return;
  const renderToken = ++state.pdfRenderToken;
  await cancelActivePdfRender();
  if (renderToken !== state.pdfRenderToken || loadToken !== state.pdfLoadToken || !state.pdfDocument) return;
  const documentRef = state.pdfDocument;
  const safePage = Math.min(Math.max(1, Number(pageNumber) || 1), documentRef.numPages);
  state.pdfPageNumber = safePage;
  elements.pageInput.value = String(safePage);
  elements.prevPage.disabled = safePage <= 1;
  elements.nextPage.disabled = safePage >= documentRef.numPages;
  const page = await documentRef.getPage(safePage);
  if (renderToken !== state.pdfRenderToken || loadToken !== state.pdfLoadToken) return;
  const baseViewport = page.getViewport({ scale: 1 });
  const availableWidth = Math.max(280, elements.pdfStage.clientWidth - 32);
  const fitScale = Math.min(1.5, availableWidth / baseViewport.width);
  const viewport = page.getViewport({ scale: fitScale * state.pdfZoom });
  const outputScale = Math.max(1, window.devicePixelRatio || 1);
  const canvas = elements.pdfCanvas;
  const context = canvas.getContext("2d", { alpha: false });
  canvas.width = Math.floor(viewport.width * outputScale);
  canvas.height = Math.floor(viewport.height * outputScale);
  canvas.style.width = `${Math.floor(viewport.width)}px`;
  canvas.style.height = `${Math.floor(viewport.height)}px`;
  elements.pdfCanvasWrap.style.width = canvas.style.width;
  elements.pdfCanvasWrap.style.height = canvas.style.height;
  elements.pdfPlaceholder.hidden = true;
  elements.pdfCanvasWrap.hidden = false;
  state.renderTask = page.render({
    canvasContext: context,
    viewport,
    transform: outputScale === 1 ? null : [outputScale, 0, 0, outputScale, 0, 0],
  });
  try {
    await state.renderTask.promise;
  } catch (error) {
    if (error?.name !== "RenderingCancelledException") throw error;
  }
  if (renderToken !== state.pdfRenderToken || loadToken !== state.pdfLoadToken) return;
  state.renderTask = null;
  elements.pdfStage.dataset.pageNumber = String(safePage);
  renderHighlight(safePage, viewport.width, viewport.height);
}

function renderHighlight(pageNumber, width, height) {
  const evidence = state.activeEvidence;
  if (!evidence || evidence.page_number !== pageNumber) {
    elements.pdfHighlight.hidden = true;
    return;
  }
  const box = evidence.bbox_pct;
  elements.pdfHighlight.hidden = false;
  elements.pdfHighlight.style.left = `${box.left * width}px`;
  elements.pdfHighlight.style.top = `${box.top * height}px`;
  elements.pdfHighlight.style.width = `${box.width * width}px`;
  elements.pdfHighlight.style.height = `${Math.max(8, box.height * height)}px`;
  requestAnimationFrame(() => {
    elements.pdfHighlight.scrollIntoView({ block: "center", behavior: "smooth" });
  });
}

elements.prevPage.addEventListener("click", () => renderPdfPage(state.pdfPageNumber - 1));
elements.nextPage.addEventListener("click", () => renderPdfPage(state.pdfPageNumber + 1));
elements.pageInput.addEventListener("change", () => renderPdfPage(elements.pageInput.value));
elements.zoomOut.addEventListener("click", () => {
  state.pdfZoom = Math.max(0.6, state.pdfZoom - 0.15);
  elements.zoomValue.textContent = `${Math.round(state.pdfZoom * 100)}%`;
  renderPdfPage(state.pdfPageNumber);
});
elements.zoomIn.addEventListener("click", () => {
  state.pdfZoom = Math.min(2.4, state.pdfZoom + 0.15);
  elements.zoomValue.textContent = `${Math.round(state.pdfZoom * 100)}%`;
  renderPdfPage(state.pdfPageNumber);
});

function renderQuality() {
  const quality = state.result.quality;
  elements.qualitySummary.textContent = `已提取 ${quality.found_cells}/${quality.expected_cells} 个目标单元格，完整度 ${(quality.completeness * 100).toFixed(1)}%。缺失项不会由模型补猜。`;
  elements.warningList.replaceChildren();
  const warnings = quality.warnings.length ? quality.warnings : ["未发现需要人工处理的结构性问题。"];
  warnings.forEach((warning) => {
    const item = document.createElement("li");
    item.textContent = warning;
    elements.warningList.append(item);
  });
}

elements.qualityButton.addEventListener("click", () => elements.qualityDialog.showModal());

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    const metric = metricById(state.activeMetricId);
    if (metric) renderChart(metric);
    if (state.pdfDocument) renderPdfPage(state.pdfPageNumber);
  }, 180);
});

setBusy(false);

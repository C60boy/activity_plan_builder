/* Activity Plan Builder - Studio */
"use strict";

const state = {
  boot: null,
  plan: null,
  step: 1,
  moduleTab: "all",
  search: "",
  previewOpen: true,
  zoom: 0.85,
  tableTarget: "global",
  expanded: new Set(),
  importedProfile: null,
  profiles: [],
  dirty: false,
  buildResult: null,
  toastTimer: null
};

const STEPS = [
  { n: 1, title: "基本信息", desc: "活动概况与联系人" },
  { n: 2, title: "模块编排", desc: "可选模块与顺序" },
  { n: 3, title: "版式规范", desc: "学校字体格式" },
  { n: 4, title: "表格样式", desc: "预设表格外观" },
  { n: 5, title: "内容与导出", desc: "补全并生成 DOCX" }
];

const TABLE_KIND_LABELS = {
  schedule: "活动流程",
  budget: "经费预算",
  division: "人员分工",
  materials: "物资清单",
  promotion: "宣传方案",
  timeline: "筹备推进",
  risk: "风险研判",
  awards: "奖项设置",
  form: "表单附件",
  program: "节目单"
};

/* 第 4 步只展示“结构不同”的表格样式；纯颜色/线框差异的样式仅保留数据兼容 */
const VISIBLE_TABLE_STYLES = ["three-line", "horizontal-only", "timeline", "budget", "form"];

const TYPE_OPTIONS = ["晚会", "音乐会", "音乐节", "升旗仪式", "迎新活动", "运动会", "社团活动", "讲座论坛", "志愿服务", "综合活动"];

const FONT_OPTIONS = [
  "方正小标宋简体", "方正小标宋", "黑体", "楷体_GB2312", "楷体", "仿宋_GB2312", "仿宋",
  "宋体", "微软雅黑", "思源宋体", "华文中宋", "华文仿宋", "Times New Roman"
];

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const clone = (obj) => JSON.parse(JSON.stringify(obj));

function esc(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[ch]));
}

function debounce(fn, wait) {
  let timer = null;
  return function (...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), wait);
  };
}

function deepMerge(base, extra) {
  if (Array.isArray(extra)) return clone(extra);
  if (extra && typeof extra === "object") {
    const out = base && typeof base === "object" && !Array.isArray(base) ? clone(base) : {};
    Object.keys(extra).forEach((key) => {
      out[key] = deepMerge(out[key], extra[key]);
    });
    return out;
  }
  return extra;
}

function getPath(obj, path) {
  return path.split(".").reduce((acc, key) => (acc == null ? acc : acc[key]), obj);
}

function setPath(obj, path, value) {
  const keys = path.split(".");
  let node = obj;
  for (let i = 0; i < keys.length - 1; i += 1) {
    if (node[keys[i]] == null || typeof node[keys[i]] !== "object") node[keys[i]] = {};
    node = node[keys[i]];
  }
  node[keys[keys.length - 1]] = value;
}

function fmtNumber(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value || "");
  return Number.isInteger(num) ? String(num) : num.toFixed(1).replace(/\.0$/, "");
}

function cnNumber(n) {
  const digits = "零一二三四五六七八九";
  if (n <= 0) return String(n);
  if (n < 10) return digits[n];
  if (n === 10) return "十";
  if (n < 20) return "十" + digits[n % 10];
  const tens = Math.floor(n / 10);
  const ones = n % 10;
  return digits[tens] + "十" + (ones ? digits[ones] : "");
}

function catalog() {
  return state.boot ? state.boot.modules.modules : [];
}
function catalogMap() {
  const map = {};
  catalog().forEach((m) => { map[m.id] = m; });
  return map;
}
function tableStyleMap() {
  const map = {};
  if (!state.boot) return map;
  state.boot.tableStyles.styles.forEach((s) => { map[s.id] = s; });
  return map;
}
function enabledModules() {
  return (state.plan.modules || [])
    .filter((m) => m.enabled)
    .sort((a, b) => a.order - b.order);
}
function getModule(id) {
  return (state.plan.modules || []).find((m) => m.id === id);
}
function placeholderCount() {
  const matches = JSON.stringify(state.plan).match(/【[^】]*】/g);
  return matches ? matches.length : 0;
}

/* ---------------- boot ---------------- */
async function boot() {
  $("#main").innerHTML = `<div class="empty-state"><strong>正在载入方案</strong>正在读取模块库与格式预设…</div>`;
  try {
    const res = await fetch("/api/bootstrap", { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    state.boot = data;
    state.plan = data.plan;
    state.profiles = loadProfiles();
    $("#planPath").textContent = data.planPath;
    bindGlobalEvents();
    renderAll();
  } catch (err) {
    $("#main").innerHTML = `<div class="empty-state" style="text-align:left">
      <strong>请通过本地 Studio 启动</strong>
      <p>当前页面没有连上本地服务。请在活动方案目录下执行：</p>
      <pre style="white-space:pre-wrap;background:#f7f2e7;padding:12px;border-radius:8px;font-size:12px">python scripts/apb.py studio --open</pre>
      <p>启动后浏览器会自动打开配置台。错误信息：${esc(err.message)}</p>
    </div>`;
  }
}

/* ---------------- global events ---------------- */
function bindGlobalEvents() {
  document.addEventListener("click", handleClick);
  document.addEventListener("input", handleInput);
  document.addEventListener("change", handleChange);
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      saveDraft();
    }
    if (event.key === "Escape") closeModal();
  });
}

function handleClick(event) {
  const el = event.target.closest("[data-action]");
  if (!el) {
    const targetPill = event.target.closest("[data-table-target]");
    if (targetPill) {
      state.tableTarget = targetPill.dataset.tableTarget;
      renderTables();
    }
    return;
  }
  if (event.target.closest(".switch") && el.dataset.action === "toggle-module") return;
  const action = el.dataset.action;

  if (action === "step") { goStep(Number(el.dataset.step)); return; }
  if (action === "toggle-preview") {
    state.previewOpen = !state.previewOpen;
    $("#layout").classList.toggle("preview-hidden", !state.previewOpen);
    if (state.previewOpen) renderPreview();
    return;
  }
  if (action === "zoom-in" || action === "zoom-out") {
    state.zoom = Math.min(1.2, Math.max(0.5, state.zoom + (action === "zoom-in" ? 0.05 : -0.05)));
    $("#zoomLabel").textContent = Math.round(state.zoom * 100) + "%";
    applyZoom();
    return;
  }
  if (action === "toggle-module") { toggleModule(el.dataset.id); return; }
  if (action === "move-module") { moveModule(el.dataset.id, Number(el.dataset.dir)); return; }
  if (action === "module-tab") { state.moduleTab = el.dataset.tab; renderModules(); return; }
  if (action === "add-recommended") { addRecommended(); return; }
  if (action === "clear-optional") { clearOptional(); return; }
  if (action === "sync-event") { syncEvent(); return; }
  if (action === "apply-preset") { applyPreset(el.dataset.id); return; }
  if (action === "parse-style") { parseStyleText(); return; }
  if (action === "save-profile") { saveProfile(); return; }
  if (action === "apply-profile") { applyProfile(Number(el.dataset.index)); return; }
  if (action === "delete-profile") { deleteProfile(Number(el.dataset.index)); return; }
  if (action === "select-table-style") { selectTableStyle(el.dataset.id); return; }
  if (action === "apply-all-tables") { applyAllTables(); return; }
  if (action === "toggle-editor") { toggleEditor(el.dataset.id); return; }
  if (action === "expand-all") { enabledModules().forEach((m) => state.expanded.add(m.id)); renderContent(); return; }
  if (action === "collapse-all") { state.expanded.clear(); renderContent(); return; }
  if (action === "add-block") { addBlock(el.dataset.id, el.dataset.type); return; }
  if (action === "delete-block") { deleteBlock(el.dataset.id, Number(el.dataset.index)); return; }
  if (action === "move-block") { moveBlock(el.dataset.id, Number(el.dataset.index), Number(el.dataset.dir)); return; }
  if (action === "add-table-row") { addTableRow(el.dataset.owner); return; }
  if (action === "add-table-col") { addTableCol(el.dataset.owner); return; }
  if (action === "delete-table-row") { deleteTableRow(el.dataset.owner, Number(el.dataset.row)); return; }
  if (action === "save-draft") { saveDraft(); return; }
  if (action === "handoff") { handoff(); return; }
  if (action === "build") { buildDocx(); return; }
  if (action === "download-json") { downloadJSON(); return; }
  if (action === "validate") { refreshValidation(); toast("已完成校验", "success"); return; }
  if (action === "close-modal") { closeModal(); return; }
}

function handleInput(event) {
  const el = event.target;
  if (el.dataset.field) {
    const [group, key] = el.dataset.field.split(".");
    if (group === "contact") state.plan.event.contact[key] = el.value;
    else if (group === "event") state.plan.event[key] = el.value;
    markDirty();
    schedulePreview();
    if (group === "event") scheduleSync();
    return;
  }
  if (el.dataset.stylePath) {
    let value = el.value;
    if (el.dataset.styleType === "number") value = Number(value) || 0;
    setPath(state.plan.style, el.dataset.stylePath, value);
    if (el.dataset.stylePath === "body.lineSpacing.pt" || el.dataset.stylePath === "body.lineSpacing.value") {
      setPath(state.plan.style, "body.lineSpacing.mode", "exact");
    }
    markDirty();
    schedulePreview();
    return;
  }
  if (el.dataset.styleLine) {
    const mode = el.value;
    setPath(state.plan.style, "body.lineSpacing.mode", mode);
    markDirty();
    schedulePreview();
    return;
  }
  if (el.dataset.blockText != null) {
    const [modId, index] = el.dataset.blockText.split(":");
    const block = getModule(modId)?.blocks?.[Number(index)];
    if (block) block.text = el.value;
    markDirty();
    schedulePreview();
    return;
  }
  if (el.dataset.blockList != null) {
    const [modId, index] = el.dataset.blockList.split(":");
    const block = getModule(modId)?.blocks?.[Number(index)];
    if (block) block.items = el.value.split("\n").map((x) => x.trim()).filter(Boolean);
    markDirty();
    schedulePreview();
    return;
  }
  if (el.dataset.tableCell != null) {
    updateTableCell(el);
    return;
  }
  if (el.id === "moduleSearch") {
    state.search = el.value;
    filterModuleCards(el.value);
    return;
  }
}

function handleChange(event) {
  const el = event.target;
  if (el.dataset.toggleModule) { toggleModule(el.dataset.toggleModule); return; }
  if (el.hasAttribute("data-tables-enabled")) {
    state.plan.tableStyles.enabled = el.checked;
    markDirty();
    renderTables();
    renderPreview();
    return;
  }
  if (el.dataset.field === "event.date") {
    const value = el.value;
    state.plan.event.date = value;
    if (value) {
      const d = new Date(value + "T00:00:00");
      if (!Number.isNaN(d.getTime())) {
        const week = "日一二三四五六"[d.getDay()];
        state.plan.event.dateText = `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`;
        state.plan.event.weekday = `星期${week}`;
      }
    } else {
      state.plan.event.dateText = "";
      state.plan.event.weekday = "";
    }
    markDirty();
    renderBasic();
    schedulePreview();
    scheduleSync();
    return;
  }
  if (el.dataset.needsAgent) {
    const mod = getModule(el.dataset.needsAgent);
    if (mod) mod.needsAgent = el.checked;
    markDirty();
    return;
  }
  if (el.dataset.blockOrdered != null) {
    const [modId, index] = el.dataset.blockOrdered.split(":");
    const block = getModule(modId)?.blocks?.[Number(index)];
    if (block) block.ordered = el.checked;
    markDirty();
    schedulePreview();
    return;
  }
  if (el.dataset.stylePath) {
    let value = el.type === "checkbox" ? el.checked : el.value;
    if (el.dataset.styleType === "number") value = Number(value) || 0;
    setPath(state.plan.style, el.dataset.stylePath, value);
    markDirty();
    schedulePreview();
    return;
  }
  if (el.id === "styleFile" && el.files && el.files[0]) {
    uploadStyleFile(el.files[0]);
    return;
  }
  if (el.dataset.typeSelect === "event") {
    state.plan.event.type = el.value;
    markDirty();
  }
}

let previewTimer = null;
function schedulePreview() {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(renderPreview, 110);
}

let syncTimer = null;
function scheduleSync() {
  clearTimeout(syncTimer);
  syncTimer = setTimeout(() => syncEvent(true), 500);
}

/* ---------------- rendering: shell ---------------- */
function renderAll() {
  renderSteps();
  renderMain();
  renderPreview();
  updateMeta();
}

function renderSteps() {
  $("#steps").innerHTML = STEPS.map((s) => {
    const cls = ["step", state.step === s.n ? "active" : "", state.step > s.n ? "done" : ""].join(" ").trim();
    return `<button class="${cls}" data-action="step" data-step="${s.n}">
      <span class="step-index">${state.step > s.n ? "✓" : s.n}</span>
      <span class="step-text"><strong>${s.title}</strong><span>${s.desc}</span></span>
    </button>`;
  }).join("");
}

function goStep(n) {
  state.step = n;
  renderSteps();
  renderMain();
  updateMeta();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function renderMain() {
  if (!state.plan) return;
  if (state.step === 1) renderBasic();
  else if (state.step === 2) renderModules();
  else if (state.step === 3) renderStyle();
  else if (state.step === 4) renderTables();
  else renderContent();
  bindStepEvents();
}

function stepHead(eyebrow, title, desc) {
  return `<div class="step-head">
    <p class="eyebrow">${esc(eyebrow)}</p>
    <h2 class="step-title">${esc(title)}</h2>
    <p class="step-desc">${desc}</p>
  </div>`;
}

/* ---------------- step 1: basic ---------------- */
function renderBasic() {
  const e = state.plan.event;
  const typeOptions = TYPE_OPTIONS.includes(e.type) ? TYPE_OPTIONS : [e.type, ...TYPE_OPTIONS];
  $("#main").innerHTML = stepHead("STEP 01 / BRIEF", "先把活动说清楚",
    "这些信息会自动写入活动主题、时间地点、组织单位与落款。填得越具体，后续 Agent 补全越准确。")
    + `<div class="card pad">
      <div class="form-grid">
        <div class="field full"><label>活动名称 <em>*</em></label>
          <input data-field="event.title" value="${esc(e.title)}" placeholder="例如：联合研究生院元旦晚会">
          <span class="hint">导出时会自动补成“XX活动方案”，除非名称里已包含“方案/策划”。</span></div>
        <div class="field"><label>活动主题</label>
          <input data-field="event.theme" value="${esc(e.theme)}" placeholder="例如：元启新章·农耀青春"></div>
        <div class="field"><label>活动类型</label>
          <select data-type-select="event">${typeOptions.map((t) => `<option ${t === e.type ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></div>
        <div class="field"><label>活动日期</label>
          <input type="date" data-field="event.date" value="${esc(e.date)}">
          <span class="hint">${e.dateText ? esc(e.dateText + (e.weekday ? " " + e.weekday : "")) : "选择日期后自动换算星期"}</span></div>
        <div class="field"><label>活动时段</label>
          <input data-field="event.time" value="${esc(e.time)}" placeholder="例如：19:00—21:30"></div>
        <div class="field full"><label>活动地点</label>
          <input data-field="event.location" value="${esc(e.location)}" placeholder="校区 + 楼宇 + 具体场地，户外活动补充备用场地"></div>
        <div class="field full"><label>活动对象</label>
          <input data-field="event.audience" value="${esc(e.audience)}" placeholder="例如：联合研究生院全体学生，预计 500 人"></div>
        <div class="field"><label>主办单位</label>
          <input data-field="event.organizer" value="${esc(e.organizer)}" placeholder="例如：河南农业大学联合研究生院"></div>
        <div class="field"><label>承办单位</label>
          <input data-field="event.undertaker" value="${esc(e.undertaker)}" placeholder="例如：联合研究生院学生会"></div>
        <div class="field"><label>协办单位</label>
          <input data-field="event.coOrganizer" value="${esc(e.coOrganizer)}" placeholder="可不填"></div>
        <div class="field"><label>预计规模</label>
          <input data-field="event.scale" value="${esc(e.scale)}" placeholder="例如：500 人"></div>
        <div class="field full"><label>活动简述</label>
          <textarea data-field="event.brief" placeholder="用 3—5 句话说明缘起、玩法和希望达到的效果，Agent 会据此补全背景、目的与内容。">${esc(e.brief)}</textarea></div>
        <div class="field"><label>联系人</label>
          <input data-field="contact.name" value="${esc(e.contact?.name)}" placeholder="姓名"></div>
        <div class="field"><label>联系电话</label>
          <input data-field="contact.phone" value="${esc(e.contact?.phone)}" placeholder="手机号"></div>
        <div class="field"><label>联系邮箱</label>
          <input data-field="contact.email" value="${esc(e.contact?.email)}" placeholder="报名或咨询邮箱"></div>
      </div>
      <div class="export-actions">
        <button class="btn primary" data-action="step" data-step="2">下一步：选择模块</button>
        <button class="btn ghost" data-action="sync-event">同步到正文模块</button>
      </div>
    </div>
    <div class="section">
      <div class="notice"><div><strong>写作提示</strong><br>不确定活动名称时可以先写“元旦晚会”，导出时自动补成“元旦晚会活动方案”。人名、电话、审批信息统一用【待定】，避免编造。</div></div>
    </div>`;
}

/* ---------------- step 2: modules ---------------- */
function renderModules() {
  const map = catalogMap();
  const chosen = new Set(enabledModules().map((m) => m.id));
  const categories = state.boot.modules.categories;
  const tabs = [{ id: "all", name: "全部" }, ...categories.map((c) => ({ id: c.id, name: c.name }))];
  const q = state.search.trim().toLowerCase();

  const cards = catalog().filter((m) => {
    if (state.moduleTab !== "all" && m.category !== state.moduleTab) return false;
    if (q) {
      const blob = (m.title + m.description + m.id).toLowerCase();
      if (!blob.includes(q)) return false;
    }
    return true;
  }).map((m) => {
    const selected = chosen.has(m.id);
    const locked = m.category === "core";
    const badgeTable = m.defaultTable ? `<span class="badge table">表格</span>` : "";
    const badgeKey = m.badge ? `<span class="badge key">${esc(m.badge)}</span>` : "";
    const badgeCore = locked ? `<span class="badge core">核心</span>` : "";
    return `<div class="module-card ${selected ? "selected" : ""} ${locked ? "locked" : ""}"
        data-action="toggle-module" data-id="${m.id}" data-search="${esc((m.title + m.description).toLowerCase())}">
      <div class="module-card-head">
        <div class="module-title">${esc(m.title)}</div>
        <label class="switch" title="${locked ? "核心模块不可关闭" : "启用/关闭"}">
          <input type="checkbox" data-toggle-module="${m.id}" ${selected ? "checked" : ""} ${locked ? "disabled" : ""}>
          <span class="track"></span>
        </label>
      </div>
      <div class="module-desc">${esc(m.description)}</div>
      <div class="module-badges">${badgeCore}${badgeTable}${badgeKey}</div>
    </div>`;
  }).join("");

  const ordered = enabledModules();
  const rows = ordered.map((m, index) => {
    const core = map[m.id]?.category === "core";
    return `<div class="selected-row">
      <span class="order-no">${index + 1}</span>
      <span class="row-title">${esc(m.title)}</span>
      ${m.needsAgent ? `<span class="badge">待 Agent 补全</span>` : ""}
      <div class="row-actions">
        <button data-action="move-module" data-id="${m.id}" data-dir="-1" ${index === 0 ? "disabled" : ""} title="上移">↑</button>
        <button data-action="move-module" data-id="${m.id}" data-dir="1" ${index === ordered.length - 1 ? "disabled" : ""} title="下移">↓</button>
        <button data-action="toggle-module" data-id="${m.id}" ${core ? "disabled" : ""} title="移除">×</button>
      </div>
    </div>`;
  }).join("");

  $("#main").innerHTML = stepHead("STEP 02 / MODULES", "选择这次真正需要的章节",
    "核心模块已锁定。推荐模块适合大多数大型校园活动；进阶模块用于审批、执行与复盘。勾选后会立刻出现在右侧预览中。")
    + `<div class="module-toolbar">
        <div class="module-tabs">${tabs.map((t) => `<button class="tab ${state.moduleTab === t.id ? "active" : ""}" data-action="module-tab" data-tab="${t.id}">${t.name}</button>`).join("")}</div>
        <input id="moduleSearch" class="search-input" placeholder="搜索模块，例如：预算、安全、宣传" value="${esc(state.search)}">
        <button class="btn ghost small" data-action="add-recommended">加入推荐</button>
        <button class="btn ghost small" data-action="clear-optional">清空可选</button>
      </div>
      <div class="module-grid">${cards || `<div class="empty-state">没有匹配的模块。</div>`}</div>
      <div class="section selected-panel">
        <div class="section-head"><div><h3 class="section-title">当前结构（${ordered.length} 个模块）</h3>
          <p class="section-desc">顺序即正文一级标题顺序，“落款”和“附件”始终排在最后。</p></div></div>
        <div class="selected-list">${rows}</div>
      </div>
      <div class="stat-strip">
        <div class="stat"><strong>${ordered.length}</strong><span>启用模块</span></div>
        <div class="stat"><strong>${ordered.filter((m) => m.needsAgent).length}</strong><span>待 Agent 补全</span></div>
        <div class="stat"><strong>${placeholderCount()}</strong><span>占位符</span></div>
        <div class="stat"><strong>${estimatePages()}</strong><span>预估页数</span></div>
      </div>
      <div class="export-actions">
        <button class="btn primary" data-action="step" data-step="3">下一步：导入学校格式</button>
      </div>`;
}

function toggleModule(id) {
  const src = catalogMap()[id];
  if (!src) return;
  if (src.category === "core") return;
  let mod = getModule(id);
  if (!mod) {
    mod = makeModule(id);
    state.plan.modules.push(mod);
  } else {
    mod.enabled = !mod.enabled;
  }
  if (mod.enabled && mod.needsAgent == null) mod.needsAgent = true;
  renumberModules();
  renderModules();
  renderPreview();
  updateMeta();
  markDirty();
}

function makeModule(id) {
  const src = catalogMap()[id];
  const mod = {
    id,
    title: src.title,
    enabled: true,
    order: state.plan.modules.length + 1,
    blocks: clone(src.defaultBlocks || []),
    needsAgent: true,
    note: ""
  };
  if (src.defaultTable) mod.table = clone(src.defaultTable);
  if (src.defaultAttachments) mod.attachments = clone(src.defaultAttachments);
  return mod;
}

function renumberModules() {
  const enabled = enabledModules();
  enabled.forEach((m, i) => { m.order = i + 1; });
  const disabled = state.plan.modules.filter((m) => !m.enabled);
  disabled.forEach((m, i) => { m.order = 100 + i; });
}

function moveModule(id, dir) {
  const list = enabledModules();
  const index = list.findIndex((m) => m.id === id);
  const target = index + dir;
  if (index < 0 || target < 0 || target >= list.length) return;
  [list[index], list[target]] = [list[target], list[index]];
  list.forEach((m, i) => { m.order = i + 1; });
  renderModules();
  renderPreview();
  markDirty();
}

function addRecommended() {
  const chosen = new Set(enabledModules().map((m) => m.id));
  catalog().filter((m) => m.category === "recommended" && !chosen.has(m.id)).forEach((m) => {
    const mod = getModule(m.id);
    if (mod) mod.enabled = true;
    else state.plan.modules.push(makeModule(m.id));
  });
  renumberModules();
  renderModules();
  renderPreview();
  updateMeta();
  markDirty();
  toast("已加入推荐模块", "success");
}

function clearOptional() {
  state.plan.modules.forEach((m) => {
    if (catalogMap()[m.id]?.category !== "core") m.enabled = false;
  });
  renumberModules();
  renderModules();
  renderPreview();
  updateMeta();
  markDirty();
}

function filterModuleCards(query) {
  const q = query.trim().toLowerCase();
  $$(".module-card").forEach((card) => {
    card.hidden = q && !card.dataset.search.includes(q);
  });
}

/* ---------------- step 3: style ---------------- */
function renderStyle() {
  const s = state.plan.style;
  const presets = state.boot.stylePresets.presets;
  const source = state.importedProfile?.source || s.source;
  const confidence = source?.confidence || {};
  const activePreset = presets.find((p) => p.id === state.plan.styleRef);

  $("#main").innerHTML = stepHead("STEP 03 / TYPOGRAPHY", "让版式符合学校要求",
    "可以直接选预设，也可以上传学校的 Word 模板，系统会自动识别标题、正文、行距、页边距和表头格式。识别后仍可手动微调。")
    + `<div class="section">
        <div class="section-head"><div><h3 class="section-title">格式预设</h3><p class="section-desc">从常用高校版式开始，再按学校要求微调。</p></div></div>
        <div class="preset-grid">${presets.map((p) => `<div class="preset-card ${activePreset?.id === p.id ? "active" : ""}" data-action="apply-preset" data-id="${p.id}">
          <h4>${esc(p.name)}</h4><p>${esc(p.description)}</p>
          <div class="preset-spec">
            <span>标题 ${esc(p.title.eastAsia)} ${fmtNumber(p.title.sizePt)}pt</span>
            <span>正文 ${esc(p.body.eastAsia)} ${fmtNumber(p.body.sizePt)}pt</span>
            <span>${p.body.lineSpacing.mode === "exact" ? "行距 " + fmtNumber(p.body.lineSpacing.pt) + "pt" : "行距 " + fmtNumber(p.body.lineSpacing.value) + " 倍"}</span>
          </div>
        </div>`).join("")}</div>
      </div>
      <div class="section">
        <div class="section-head"><div><h3 class="section-title">一键导入学校格式</h3><p class="section-desc">上传学校已排好版的 DOCX，或粘贴文字版格式要求。</p></div></div>
        <label class="import-zone" id="importZone" for="styleFile">
          <span class="import-mark">格</span>
          <span class="import-copy"><strong>拖入学校模板 .docx，或点击选择文件</strong>
            <p>自动识别页边距、标题/一级标题/正文字体字号、行距、首行缩进与表头样式；识别结果会立即应用。</p></span>
          <input id="styleFile" type="file" accept=".docx">
          <span class="btn small">选择文件</span>
        </label>
        <div style="margin-top:10px" class="field">
          <label>或粘贴文字要求</label>
          <textarea id="styleText" placeholder="例如：正文仿宋_GB2312三号，行距28磅，首行缩进2字符；标题方正小标宋二号；页边距上3.7厘米、下3.5厘米、左2.8厘米、右2.6厘米。"></textarea>
          <div class="export-actions"><button class="btn ghost small" data-action="parse-style">解析文字要求</button></div>
        </div>
        ${source ? `<div class="import-result">
          <div class="import-result-head"><strong>识别结果 · ${esc(source.file || "文字规范")}</strong>
            <span class="confidence">${Object.entries(confidence).map(([k, v]) => `<span class="conf ${esc(v)}">${esc(confidenceLabel(k))} ${esc(confValue(v))}</span>`).join("")}</span>
          </div>
          <div class="detect-grid">
            ${detectItem("标题", `${s.title.eastAsia} / ${fmtNumber(s.title.sizePt)}pt`)}
            ${detectItem("一级标题", `${s.h1.eastAsia} / ${fmtNumber(s.h1.sizePt)}pt`)}
            ${detectItem("二级标题", `${s.h2.eastAsia} / ${fmtNumber(s.h2.sizePt)}pt`)}
            ${detectItem("正文", `${s.body.eastAsia} / ${fmtNumber(s.body.sizePt)}pt`)}
            ${detectItem("行距", s.body.lineSpacing.mode === "exact" ? fmtNumber(s.body.lineSpacing.pt) + "pt" : fmtNumber(s.body.lineSpacing.value) + " 倍")}
            ${detectItem("首行缩进", fmtNumber(s.body.firstLineIndentChars) + " 字符")}
            ${detectItem("页边距", `${fmtNumber(s.page.marginsCm.top)} / ${fmtNumber(s.page.marginsCm.bottom)} / ${fmtNumber(s.page.marginsCm.left)} / ${fmtNumber(s.page.marginsCm.right)} cm`)}
            ${detectItem("表格样式", state.plan.tableStyles.global)}
          </div>
        </div>` : ""}
      </div>
      <div class="section">
        <div class="section-head"><div><h3 class="section-title">手动微调</h3><p class="section-desc">所有字段都会直接作用于右侧 A4 预览和最终 DOCX。</p></div></div>
        <div class="card pad">
          <div class="manual-grid">
            ${fontField("标题字体", "title.eastAsia")}
            ${numField("标题字号 (pt)", "title.sizePt")}
            <div class="style-field"><label>标题加粗</label><label class="inline-check"><input type="checkbox" data-style-path="title.bold" ${s.title.bold ? "checked" : ""}> 加粗</label></div>
            ${fontField("一级标题字体", "h1.eastAsia")}
            ${numField("一级标题字号 (pt)", "h1.sizePt")}
            <div class="style-field"><label>一级标题加粗</label><label class="inline-check"><input type="checkbox" data-style-path="h1.bold" ${s.h1.bold ? "checked" : ""}> 加粗</label></div>
            ${fontField("二级标题字体", "h2.eastAsia")}
            ${numField("二级标题字号 (pt)", "h2.sizePt")}
            <div class="style-field"><label>二级标题加粗</label><label class="inline-check"><input type="checkbox" data-style-path="h2.bold" ${s.h2.bold ? "checked" : ""}> 加粗</label></div>
            ${fontField("正文字体", "body.eastAsia")}
            ${numField("正文字号 (pt)", "body.sizePt")}
            <div class="style-field"><label>行距模式</label>
              <select data-style-line="mode">
                <option value="exact" ${s.body.lineSpacing.mode === "exact" ? "selected" : ""}>固定值（磅）</option>
                <option value="multiple" ${s.body.lineSpacing.mode === "multiple" ? "selected" : ""}>倍数</option>
              </select></div>
            ${numField("行距数值", s.body.lineSpacing.mode === "exact" ? "body.lineSpacing.pt" : "body.lineSpacing.value")}
            ${numField("首行缩进（字符）", "body.firstLineIndentChars")}
            ${numField("页边距 上 (cm)", "page.marginsCm.top")}
            ${numField("页边距 下 (cm)", "page.marginsCm.bottom")}
            ${numField("页边距 左 (cm)", "page.marginsCm.left")}
            ${numField("页边距 右 (cm)", "page.marginsCm.right")}
            ${numField("表格字号 (pt)", "table.fontSizePt")}
            <div class="style-field"><label>页码</label><label class="inline-check"><input type="checkbox" data-style-path="footer.enabled" ${s.footer.enabled ? "checked" : ""}> 页脚居中显示“— 1 —”</label></div>
          </div>
          <datalist id="fontList">${FONT_OPTIONS.map((f) => `<option value="${esc(f)}">`).join("")}</datalist>
          <div class="export-actions">
            <input id="profileName" class="search-input" style="max-width:220px" placeholder="给这套学校格式起个名字">
            <button class="btn ghost small" data-action="save-profile">保存为我的学校</button>
          </div>
          ${state.profiles.length ? `<div class="profile-list">${state.profiles.map((p, i) => `<div class="profile-row">
            <strong>${esc(p.name)}</strong><span>${esc(p.savedAt)}</span>
            <button class="btn ghost small" data-action="apply-profile" data-index="${i}">应用</button>
            <button class="btn danger small" data-action="delete-profile" data-index="${i}">删除</button>
          </div>`).join("")}</div>` : ""}
        </div>
      </div>
      <div class="export-actions"><button class="btn primary" data-action="step" data-step="4">下一步：挑选表格样式</button></div>`;
  $("#styleText")?.addEventListener("input", () => {});
}

function confidenceLabel(key) {
  const map = {
    page: "页边距", title: "标题", h1: "一级标题", h2: "二级标题", body: "正文",
    lineSpacing: "行距", indent: "缩进", align: "对齐", table: "表格", tableStyle: "表格样式"
  };
  return map[key] || key;
}
function confValue(v) {
  return v === "high" ? "高" : v === "medium" ? "中" : "低";
}
function detectItem(label, value) {
  return `<div class="detect-item"><span>${esc(label)}</span><span>${esc(value)}</span></div>`;
}
function fontField(label, path) {
  return `<div class="style-field"><label>${esc(label)}</label>
    <input list="fontList" data-style-path="${path}" value="${esc(getPath(state.plan.style, path))}"></div>`;
}
function numField(label, path) {
  return `<div class="style-field"><label>${esc(label)}</label>
    <input type="number" step="0.1" data-style-type="number" data-style-path="${path}" value="${esc(getPath(state.plan.style, path))}"></div>`;
}

function applyPreset(id) {
  const preset = state.boot.stylePresets.presets.find((p) => p.id === id);
  if (!preset) return;
  state.plan.style = clone(preset);
  state.plan.styleRef = id;
  state.importedProfile = null;
  renderStyle();
  renderPreview();
  markDirty();
  toast(`已应用：${preset.name}`, "success");
}

async function uploadStyleFile(file) {
  if (!file.name.toLowerCase().endsWith(".docx")) {
    toast("请上传 .docx 格式的学校模板", "error");
    return;
  }
  const zone = $("#importZone");
  if (zone) zone.classList.add("dragover");
  try {
    const buffer = await file.arrayBuffer();
    const res = await fetch("/api/import-style", {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream", "X-Filename": encodeURIComponent(file.name) },
      body: buffer
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "识别失败");
    applyImportedProfile(data.profile);
    toast("已识别并应用学校格式", "success");
  } catch (err) {
    toast("识别失败：" + err.message, "error");
  } finally {
    if (zone) zone.classList.remove("dragover");
  }
}

function applyImportedProfile(profile) {
  state.importedProfile = profile;
  state.plan.style = deepMerge(state.plan.style, profile);
  if (profile.tableStyleGuess && tableStyleMap()[profile.tableStyleGuess]) {
    state.plan.tableStyles.global = profile.tableStyleGuess;
  }
  state.plan.styleRef = "school-import";
  renderStyle();
  renderPreview();
  markDirty();
}

async function parseStyleText() {
  const text = $("#styleText")?.value || "";
  if (!text.trim()) { toast("请先粘贴格式要求文字", "error"); return; }
  try {
    const res = await fetch("/api/parse-style", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text })
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "解析失败");
    applyImportedProfile(data.profile);
    toast("已解析并应用文字规范", "success");
  } catch (err) {
    toast("解析失败：" + err.message, "error");
  }
}

function loadProfiles() {
  try { return JSON.parse(localStorage.getItem("apb.schoolProfiles") || "[]"); } catch (e) { return []; }
}
function persistProfiles() {
  localStorage.setItem("apb.schoolProfiles", JSON.stringify(state.profiles));
}
function saveProfile() {
  const name = ($("#profileName")?.value || "").trim();
  if (!name) { toast("请先给格式起个名字", "error"); return; }
  const savedAt = new Date().toLocaleDateString("zh-CN");
  const style = clone(state.plan.style);
  const existing = state.profiles.findIndex((p) => p.name === name);
  const entry = { name, savedAt, style };
  if (existing >= 0) state.profiles[existing] = entry;
  else state.profiles.unshift(entry);
  persistProfiles();
  renderStyle();
  toast("已保存到“我的学校”", "success");
}
function applyProfile(index) {
  const entry = state.profiles[index];
  if (!entry) return;
  state.plan.style = deepMerge(state.plan.style, entry.style);
  state.plan.styleRef = "saved-profile";
  if (entry.style.tableStyleGuess && tableStyleMap()[entry.style.tableStyleGuess]) {
    state.plan.tableStyles.global = entry.style.tableStyleGuess;
  }
  renderStyle();
  renderPreview();
  markDirty();
  toast(`已应用：${entry.name}`, "success");
}
function deleteProfile(index) {
  state.profiles.splice(index, 1);
  persistProfiles();
  renderStyle();
}

/* ---------------- step 4: table styles ---------------- */
function tablesEnabled() {
  return (state.plan.tableStyles || {}).enabled !== false;
}

function renderTables() {
  const styles = state.boot.tableStyles.styles.filter((s) => VISIBLE_TABLE_STYLES.includes(s.id));
  const tablesOn = tablesEnabled();
  const byKind = state.plan.tableStyles.byKind || {};
  const globalId = state.plan.tableStyles.global || "three-line";
  const activeId = state.tableTarget === "global" ? globalId : (byKind[state.tableTarget] || globalId);
  const inherited = state.tableTarget !== "global" && !byKind[state.tableTarget];
  const legacy = !VISIBLE_TABLE_STYLES.includes(activeId);

  const targets = [{ id: "global", name: "全局" }, ...Object.entries(TABLE_KIND_LABELS).map(([id, name]) => ({ id, name }))];
  const cards = styles.map((style) => {
    const active = activeId === style.id;
    return `<div class="style-card ${active ? "active" : ""}" data-action="select-table-style" data-id="${style.id}">
      <div class="style-card-head"><strong>${esc(style.name)}</strong><span>${active ? "已应用" : ""}</span></div>
      ${miniTableHTML(style)}
      <p>${esc(style.description)}</p>
      <div class="style-tags">${(style.tags || []).map((t) => `<span># ${esc(t)}</span>`).join("")}</div>
    </div>`;
  }).join("");

  const toggleSection = `<div class="section">
      <div class="card pad table-toggle-card">
        <div>
          <h3 class="section-title">本次方案使用表格</h3>
          <p class="section-desc">活动流程、经费预算、报名表等以表格呈现。关闭后导出的 DOCX 只保留文字内容，正文表格与附件表格都不会出现。</p>
        </div>
        <label class="switch big">
          <input type="checkbox" data-tables-enabled ${tablesOn ? "checked" : ""}>
          <span class="track"></span>
        </label>
      </div>
    </div>`;

  const gallerySection = tablesOn ? `<div class="section">
        <div class="section-head"><div><h3 class="section-title">作用范围</h3><p class="section-desc">${state.tableTarget === "global" ? "当前设置会应用到所有未单独指定的表格。" : `当前设置：${esc(TABLE_KIND_LABELS[state.tableTarget] || state.tableTarget)}${inherited ? "（跟随全局）" : ""}`}</p></div>
          <div class="section-actions"><button class="btn ghost small" data-action="apply-all-tables">全部使用当前样式</button></div></div>
        <div class="style-targets">${targets.map((t) => `<button class="target-pill ${state.tableTarget === t.id ? "active" : ""}" data-table-target="${t.id}">${esc(t.name)}${t.id !== "global" && byKind[t.id] ? " ·" : ""}</button>`).join("")}</div>
        <div class="style-gallery">${cards}</div>
        ${legacy ? `<div class="notice"><div><strong>当前为旧版样式</strong><br>该方案之前选了“政务全框线”等旧样式，仅作兼容保留。选择下方任意样式即可替换。</div></div>` : ""}
      </div>
      <div class="section">
        <div class="notice"><div><strong>表格样式如何生效</strong><br>这里只展示结构不同的样式：三线表、无竖线横栏、时间轴、预算表与表单。每张表会优先使用所属分类的样式；没有单独指定时回退到全局样式。导出 DOCX 时会保留表头底纹、边框、金额右对齐与合计行。</div></div>
      </div>`
    : `<div class="section">
        <div class="notice"><div><strong>表格已关闭</strong><br>导出的文档将不含任何表格，活动流程、预算、报名表等内容只保留文字部分。需要表格时重新打开上方开关即可。</div></div>
      </div>`;

  $("#main").innerHTML = stepHead("STEP 04 / TABLES", "决定要不要表格，再选结构",
    "先确认这次方案是否需要表格；需要的话，从几种结构不同的样式中挑一套。可以全局统一，也可以只改预算、流程或报名表。")
    + toggleSection
    + gallerySection
    + `<div class="export-actions"><button class="btn primary" data-action="step" data-step="5">下一步：补全内容并生成</button></div>`;
}

function selectTableStyle(id) {
  if (state.tableTarget === "global") {
    state.plan.tableStyles.global = id;
  } else {
    state.plan.tableStyles.byKind[state.tableTarget] = id;
  }
  renderTables();
  renderPreview();
  markDirty();
}

function applyAllTables() {
  const id = state.tableTarget === "global"
    ? state.plan.tableStyles.global
    : (state.plan.tableStyles.byKind[state.tableTarget] || state.plan.tableStyles.global);
  state.plan.tableStyles.global = id;
  state.plan.tableStyles.byKind = {};
  renderTables();
  renderPreview();
  markDirty();
  toast("已统一为全局表格样式", "success");
}

/* ---------------- media/table rendering shared ---------------- */
function borderCSS(token) {
  if (!token || token.val === "nil" || token.val === "none" || !token.sz) return "none";
  return `${token.sz / 8}pt solid #${String(token.color || "1F1F1F").replace("#", "")}`;
}

function cellBorders(style, isHeader, rowIndex, lastRow, colIndex, lastCol) {
  const borders = style.borders || {};
  const top = rowIndex === 0 ? borderCSS(borders.top) : borderCSS(borders.insideH);
  const bottom = isHeader && style.headerBottom
    ? borderCSS(style.headerBottom)
    : (lastRow ? borderCSS(borders.bottom) : borderCSS(borders.insideH));
  const left = colIndex === 0 ? borderCSS(borders.left) : borderCSS(borders.insideV);
  const right = colIndex === lastCol ? borderCSS(borders.right) : borderCSS(borders.insideV);
  return `border-top:${top};border-bottom:${bottom};border-left:${left};border-right:${right};`;
}

function miniTableHTML(style) {
  const spec = {
    kind: "generic",
    headers: ["时间", "内容", "负责人"],
    widthsCm: [3.2, 7.2, 3.0],
    rows: [["19:00", "开场", "文体部"], ["19:10", "展演", "节目组"]],
    total: false
  };
  const table = tableHTML(spec, style);
  return `<div class="mini-table">${table}</div>`;
}

function tableHTML(spec, styleOverride) {
  if (!spec) return "";
  const kind = spec.kind || "generic";
  const style = styleOverride || resolveTableStyle(kind);
  const headers = (spec.headers || []).map(String);
  const rows = (spec.rows || []).map((r) => r.map(String));
  const ncols = Math.max(headers.length, ...rows.map((r) => r.length), 1);
  headers.forEach((_, i) => { if (!headers[i]) headers[i] = ""; });
  rows.forEach((r) => { while (r.length < ncols) r.push(""); });

  const grid = [];
  const isBudget = kind === "budget" && spec.total;
  let totalAmount = 0;
  if (isBudget) totalAmount = computeBudgetClient(spec).total;
  if (spec.title) grid.push({ title: true, cells: [{ text: spec.title, colspan: ncols }] });
  if (headers.some((h) => h.trim())) {
    grid.push({ header: true, cells: headers.map((h) => ({ text: h })) });
  }
  rows.forEach((row, ri) => {
    grid.push({ rowIndex: ri, cells: row.map((text) => ({ text })) });
  });
  if (isBudget) {
    const amountCol = Math.max(0, headers.findIndex((h) => h.includes("小计") || h.includes("金额")));
    const labelSpan = Math.max(1, amountCol);
    const valueSpan = ncols - labelSpan;
    grid.push({ total: true, cells: [
      { text: (spec.totalLabel || "总计") + "：", colspan: labelSpan, align: "center" },
      { text: formatMoney(totalAmount), colspan: valueSpan, align: "right" }
    ] });
  }

  const ranges = [];
  const offset = spec.title ? 1 : 0;
  (spec.merges || []).forEach((m) => {
    ranges.push({
      r1: Number(m.r || 0) + offset, c1: Number(m.c || 0),
      r2: Number(m.r || 0) + offset + Number(m.rowspan || 1) - 1,
      c2: Number(m.c || 0) + Number(m.colspan || 1) - 1
    });
  });
  if (spec.title) ranges.push({ r1: 0, c1: 0, r2: 0, c2: ncols - 1 });
  if (isBudget) {
    const totalRow = grid.length - 1;
    const amountCol = Math.max(0, headers.findIndex((h) => h.includes("小计") || h.includes("金额")));
    ranges.push({ r1: totalRow, c1: 0, r2: totalRow, c2: Math.max(0, amountCol - 1) });
    ranges.push({ r1: totalRow, c1: amountCol, r2: totalRow, c2: ncols - 1 });
  }

  const occupied = new Set();
  const spans = {};
  ranges.forEach((r) => {
    if (r.r1 < 0 || r.c1 < 0 || r.r2 >= grid.length || r.c2 >= ncols) return;
    for (let rr = r.r1; rr <= r.r2; rr += 1) {
      for (let cc = r.c1; cc <= r.c2; cc += 1) {
        if (rr !== r.r1 || cc !== r.c1) occupied.add(`${rr}:${cc}`);
      }
    }
    spans[`${r.r1}:${r.c1}`] = { rowspan: r.r2 - r.r1 + 1, colspan: r.c2 - r.c1 + 1 };
  });

  const tableStyle = `width:100%;border-collapse:collapse;table-layout:fixed;font-family:${fontStack(
    (state.plan.style.table || {}).fontEastAsia || "仿宋_GB2312", "Times New Roman")};font-size:${style.fontSizePt || 12}pt;`;
  const colgroup = spec.widthsCm && spec.widthsCm.length === ncols
    ? `<colgroup>${spec.widthsCm.map((w) => `<col style="width:${Number(w)}cm">`).join("")}</colgroup>` : "";

  const body = grid.map((row, ri) => {
    const cells = [];
    row.cells.forEach((cell, ci) => {
      if (occupied.has(`${ri}:${ci}`)) return;
      if (definitelyOccupied(row, ci, ri, grid, occupied)) return;
      const span = spans[`${ri}:${ci}`] || {};
      const isHeader = !!row.header;
      const isTitle = !!row.title;
      const isTotal = !!row.total;
      const isFirstCol = ci === 0 && !isTitle;
      let fill = "";
      let color = "#1f1f1f";
      let weight = 400;
      let align = (style.body && style.body.align) || "left";
      let fontSize = style.fontSizePt || 12;
      if (isTitle) {
        fill = style.titleRow?.fill || "";
        color = style.titleRow?.color || style.header?.color || color;
        weight = 700;
        align = "center";
        fontSize = style.titleRow?.fontSizePt || fontSize + 2;
      } else if (isHeader) {
        fill = style.header?.fill || "";
        color = style.header?.color || color;
        weight = style.header?.bold === false ? 400 : 700;
        align = style.header?.align || "center";
        fontSize = Number((state.plan.style.table || {}).headerSizePt || style.fontSizePt || 12);
      } else if (isTotal) {
        fill = style.totalRow?.fill || "";
        weight = style.totalRow?.bold === false ? 400 : 700;
        align = cell.align || "right";
      } else if (isFirstCol && style.firstCol?.fill) {
        fill = style.firstCol.fill;
        weight = style.firstCol.bold ? 700 : 400;
        align = style.firstCol.align || align;
        if (style.firstCol.color) color = style.firstCol.color;
      } else if (style.body?.zebraFill && row.rowIndex != null && row.rowIndex % 2 === 1) {
        fill = style.body.zebraFill;
      }
      if (!isTitle && !isHeader && ci > 0 && (style.numericAlign === "right")
          && isNumericCell(cell.text, headers[ci] || "", kind)) {
        align = "right";
      }
      const lastRow = ri === grid.length - 1;
      const borders = cellBorders(style, isHeader, ri, lastRow, ci, ncols - 1);
      const spanAttr = `${span.rowspan > 1 ? ` rowspan="${span.rowspan}"` : ""}${span.colspan > 1 ? ` colspan="${span.colspan}"` : ""}`;
      const tag = isHeader ? "th" : "td";
      cells.push(`<${tag}${spanAttr} style="${borders}padding:2.5pt 4pt;vertical-align:middle;text-align:${align};background:${fill || "transparent"};color:${color};font-weight:${weight};font-size:${fontSize}pt;line-height:1.35;">${esc(cell.text)}</${tag}>`);
    });
    return `<tr>${cells.join("")}</tr>`;
  }).join("");

  return `<table class="pv-table" style="${tableStyle}">${colgroup}<tbody>${body}</tbody></table>`;
}

function definitelyOccupied(row, ci, ri, grid, occupied) {
  return false;
}

function isNumericCell(text, header, kind) {
  if (/元|金额|单价|数量|小计|人数|数量/.test(header)) return true;
  const cleaned = String(text).replace(/[,，\s]/g, "");
  return /^-?\d+(\.\d+)?(元|人|个|份|台|套|分钟)?$/.test(cleaned) && cleaned !== "";
}

function resolveTableStyle(kind) {
  const mapping = state.plan.tableStyles.byKind || {};
  const id = mapping[kind] || state.plan.tableStyles.global || "three-line";
  return tableStyleMap()[id] || tableStyleMap()["three-line"] || state.boot.tableStyles.styles[0];
}

function fontStack(east, ascii) {
  const fallback = `"Songti SC","STSong","SimSun","Noto Serif SC",serif`;
  const parts = [];
  if (east) parts.push(`"${east}"`);
  if (ascii) parts.push(`"${ascii}"`);
  parts.push(fallback);
  return parts.join(",");
}

function formatMoney(value) {
  const num = Number(value) || 0;
  return Math.abs(num - Math.round(num)) < 0.005 ? `${Math.round(num)}元` : `${num.toFixed(2)}元`;
}

/* ---------------- step 5: content ---------------- */
function renderContent() {
  const result = validateClient();
  const mods = enabledModules();

  const editors = mods.map((mod, index) => {
    const expanded = state.expanded.has(mod.id);
    const src = catalogMap()[mod.id];
    const badgeTable = mod.table ? `<span class="badge table">表格</span>` : "";
    const badgeAgent = mod.needsAgent ? `<span class="badge key">待 Agent</span>` : "";
    return `<div class="module-editor" data-module="${mod.id}">
      <div class="editor-head ${expanded ? "open" : ""}">
        <span class="order-no">${index + 1}</span>
        <strong>${esc(mod.title)}</strong>
        <span class="mini-badges">${badgeTable}${badgeAgent}</span>
        <label class="inline-check" title="交给 Agent 补全"><input type="checkbox" data-needs-agent="${mod.id}" ${mod.needsAgent ? "checked" : ""}> Agent</label>
        <button class="toggle-caret" data-action="toggle-editor" data-id="${mod.id}">${expanded ? "▾" : "▸"}</button>
      </div>
      <div class="editor-body" ${expanded ? "" : "hidden"}>
        ${renderModuleBody(mod, src)}
      </div>
    </div>`;
  }).join("");

  $("#main").innerHTML = stepHead("STEP 05 / CONTENT", "补全内容，生成方案",
    "可以直接在这里改，也可以把空内容留给 Agent。点击“交给 Agent”后，回到对话窗口说“继续”，Agent 会按模块补全并生成 DOCX。")
    + `<div id="validationBlock">${validationHTML(result)}</div>
      <div class="section">
        <div class="section-head"><div><h3 class="section-title">正文结构（${mods.length} 个模块）</h3>
          <p class="section-desc">展开模块编辑内容；“Agent”勾选表示允许自动补全，取消后 Agent 不会改写。</p></div>
          <div class="section-actions"><button class="btn ghost small" data-action="expand-all">全部展开</button><button class="btn ghost small" data-action="collapse-all">全部收起</button></div></div>
        <div class="editor-outline">${editors || `<div class="empty-state"><strong>还没有启用模块</strong>回到第 2 步勾选需要的章节。</div>`}</div>
      </div>
      ${exportPanelHTML()}`;
}

function renderModuleBody(mod, src) {
  const tablesOn = tablesEnabled();
  const blocks = (mod.blocks || []).map((block, i) => blockEditorHTML(mod, block, i)).join("");
  const tableEditor = mod.table && tablesOn ? `<div class="section" style="margin-top:10px">
      <div class="section-head"><div><h3 class="section-title">模块表格</h3><p class="section-desc">${esc(TABLE_KIND_LABELS[mod.table.kind] || "表格")} · ${esc(mod.table.kind)}</p></div></div>
      ${tableEditorHTML(mod.table, `mod:${mod.id}`)}
    </div>` : "";
  const tableOffHint = mod.table && !tablesOn
    ? `<p class="small-note" style="margin-top:10px">表格已在第 4 步关闭，本模块的表格不会导出。</p>` : "";
  const attachments = (mod.attachments || []).map((att, ai) => tablesOn ? `<div class="section" style="margin-top:10px">
      <div class="section-head"><div><h3 class="section-title">附件 ${ai + 1}：${esc(att.title)}</h3><p class="section-desc">${esc(att.subtitle || "导出时自动另起一页")}</p></div></div>
      ${tableEditorHTML(att.table, `att:${mod.id}:${ai}`)}
    </div>` : "").join("");
  return `<div class="block-toolbar">
      <button data-action="add-block" data-id="${mod.id}" data-type="paragraph">+ 段落</button>
      <button data-action="add-block" data-id="${mod.id}" data-type="subheading">+ 小标题</button>
      <button data-action="add-block" data-id="${mod.id}" data-type="list">+ 列表</button>
      <button data-action="add-block" data-id="${mod.id}" data-type="table">+ 表格</button>
      <button data-action="add-block" data-id="${mod.id}" data-type="pagebreak">+ 分页</button>
    </div>
    ${blocks || `<div class="empty-state" style="margin-top:10px">该模块还没有内容，点击上面的按钮添加，或交给 Agent 补全。</div>`}
    ${tableEditor}${tableOffHint}${attachments}`;
}

function blockEditorHTML(mod, block, index) {
  const actions = `<div class="block-actions">
      <button data-action="move-block" data-id="${mod.id}" data-index="${index}" data-dir="-1" title="上移">↑</button>
      <button data-action="move-block" data-id="${mod.id}" data-index="${index}" data-dir="1" title="下移">↓</button>
      <button data-action="delete-block" data-id="${mod.id}" data-index="${index}" title="删除">×</button>
    </div>`;
  if (block.type === "paragraph" || block.type === "subheading" || block.type === "note") {
    const label = block.type === "paragraph" ? "正文段落" : block.type === "subheading" ? "小标题" : "注释";
    return `<div class="block"><div class="block-head"><span class="block-type">${label}</span>${actions}</div>
      <textarea data-block-text="${mod.id}:${index}">${esc(block.text || "")}</textarea></div>`;
  }
  if (block.type === "list") {
    return `<div class="block"><div class="block-head"><span class="block-type">列表</span>${actions}</div>
      <textarea data-block-list="${mod.id}:${index}" placeholder="一行一条">${esc((block.items || []).join("\n"))}</textarea>
      <label class="inline-check" style="margin-top:5px"><input type="checkbox" data-block-ordered="${mod.id}:${index}" ${block.ordered !== false ? "checked" : ""}> 使用数字编号</label></div>`;
  }
  if (block.type === "table") {
    if (!tablesEnabled()) {
      return `<div class="block"><div class="block-head"><span class="block-type">表格</span>${actions}</div>
        <p class="small-note">表格已在第 4 步关闭，此表格块不会导出。</p></div>`;
    }
    return `<div class="block"><div class="block-head"><span class="block-type">表格</span>${actions}</div>
      ${tableEditorHTML(block.table, `blk:${mod.id}:${index}`)}</div>`;
  }
  if (block.type === "pagebreak") {
    return `<div class="block"><div class="block-head"><span class="block-type">分页符</span>${actions}</div>
      <p class="small-note">导出 DOCX 时在此处另起一页。</p></div>`;
  }
  return "";
}

function tableEditorHTML(table, owner) {
  if (!table) return "";
  const headers = table.headers || [];
  const rows = table.rows || [];
  const ncols = Math.max(headers.length, ...rows.map((r) => r.length), 1);
  rows.forEach((r) => { while (r.length < ncols) r.push(""); });
  const hasHeader = headers.some((h) => String(h).trim());
  const headerRow = hasHeader ? `<thead><tr>${Array.from({ length: ncols }).map((_, c) => `<th><input data-table-cell
      data-owner="${owner}" data-kind="header" data-col="${c}" value="${esc(headers[c] || "")}"></th>`).join("")}</tr></thead>` : "";
  const bodyRows = rows.map((row, r) => `<tr>${Array.from({ length: ncols }).map((_, c) => `<td><input data-table-cell
      data-owner="${owner}" data-kind="body" data-row="${r}" data-col="${c}" value="${esc(row[c] || "")}"></td>`).join("")}
      <td style="width:28px"><button class="row-del" data-action="delete-table-row" data-owner="${owner}" data-row="${r}" title="删除本行">×</button></td></tr>`).join("");
  const total = table.kind === "budget" ? computeBudgetClient(table).total : null;
  return `<div class="editor-table-wrap"><table class="editor-table">${headerRow}<tbody>${bodyRows}</tbody></table></div>
    <div class="table-toolbar">
      <button data-action="add-table-row" data-owner="${owner}">+ 行</button>
      <button data-action="add-table-col" data-owner="${owner}">+ 列</button>
      <span class="total">${total == null ? "" : "合计：" + formatMoney(total)}</span>
    </div>`;
}

function computeBudgetClient(table) {
  const headers = (table.headers || []).map(String);
  const idx = (keys) => {
    for (const key of keys) {
      const i = headers.findIndex((h) => h.includes(key));
      if (i >= 0) return i;
    }
    return -1;
  };
  const priceI = idx(["单价", "价格"]);
  const qtyI = idx(["数量"]);
  const subI = idx(["小计", "金额"]);
  let total = 0;
  (table.rows || []).forEach((row) => {
    const price = parseNumber(row[priceI]);
    const qty = parseNumber(row[qtyI]);
    if (price != null && qty != null && subI >= 0) {
      const sub = Math.round(price * qty * 100) / 100;
      row[subI] = sub.toFixed(2);
      total += sub;
    } else {
      const sub = parseNumber(row[subI]);
      if (sub) total += sub;
    }
  });
  return { total: Math.round(total * 100) / 100 };
}

function parseNumber(value) {
  if (value == null) return null;
  const cleaned = String(value).replace(/[【】\[\],，\s元]/g, "").trim();
  if (!cleaned) return null;
  const num = Number(cleaned);
  return Number.isFinite(num) ? num : null;
}

function toggleEditor(id) {
  if (state.expanded.has(id)) state.expanded.delete(id);
  else state.expanded.add(id);
  const card = $(`.module-editor[data-module="${id}"]`);
  if (!card) { renderContent(); return; }
  const open = state.expanded.has(id);
  card.querySelector(".editor-head").classList.toggle("open", open);
  card.querySelector(".toggle-caret").textContent = open ? "▾" : "▸";
  card.querySelector(".editor-body").hidden = !open;
}

function addBlock(modId, type) {
  const mod = getModule(modId);
  if (!mod) return;
  mod.blocks = mod.blocks || [];
  if (type === "paragraph") mod.blocks.push({ type: "paragraph", text: "【待补充】" });
  else if (type === "subheading") mod.blocks.push({ type: "subheading", text: "（一）【小标题】" });
  else if (type === "list") mod.blocks.push({ type: "list", ordered: true, items: ["【待补充】"] });
  else if (type === "table") mod.blocks.push({ type: "table", table: { kind: "generic", headers: ["列1", "列2", "列3"], widthsCm: [4, 6, 5], rows: [["", "", ""]] } });
  else if (type === "pagebreak") mod.blocks.push({ type: "pagebreak" });
  renderContent();
  renderPreview();
  markDirty();
}

function deleteBlock(modId, index) {
  const mod = getModule(modId);
  if (!mod || !mod.blocks) return;
  mod.blocks.splice(index, 1);
  renderContent();
  renderPreview();
  markDirty();
}

function moveBlock(modId, index, dir) {
  const mod = getModule(modId);
  if (!mod || !mod.blocks) return;
  const target = index + dir;
  if (target < 0 || target >= mod.blocks.length) return;
  [mod.blocks[index], mod.blocks[target]] = [mod.blocks[target], mod.blocks[index]];
  renderContent();
  renderPreview();
  markDirty();
}

function tableByOwner(owner) {
  const parts = owner.split(":");
  if (parts[0] === "mod") return getModule(parts[1])?.table;
  if (parts[0] === "att") return getModule(parts[1])?.attachments?.[Number(parts[2])]?.table;
  if (parts[0] === "blk") {
    const mod = getModule(parts[1]);
    return mod?.blocks?.[Number(parts[2])]?.table;
  }
  return null;
}

function updateTableCell(el) {
  const table = tableByOwner(el.dataset.owner);
  if (!table) return;
  const col = Number(el.dataset.col);
  if (el.dataset.kind === "header") {
    table.headers = table.headers || [];
    while (table.headers.length <= col) table.headers.push("");
    table.headers[col] = el.value;
  } else {
    const row = Number(el.dataset.row);
    table.rows = table.rows || [];
    while (table.rows.length <= row) table.rows.push([]);
    while (table.rows[row].length <= col) table.rows[row].push("");
    table.rows[row][col] = el.value;
  }
  if (table.kind === "budget") {
    const result = computeBudgetClient(table);
    const rows = table.rows || [];
    $$(`[data-owner="${el.dataset.owner}"][data-kind="body"]`).forEach((input) => {
      const r = Number(input.dataset.row);
      const c = Number(input.dataset.col);
      if (rows[r] && input.value !== String(rows[r][c] ?? "")) input.value = rows[r][c] ?? "";
    });
    const totalEl = el.closest(".editor-body")?.querySelector(".table-toolbar .total");
    if (totalEl) totalEl.textContent = "合计：" + formatMoney(result.total);
  }
  markDirty();
  schedulePreview();
}

function addTableRow(owner) {
  const table = tableByOwner(owner);
  if (!table) return;
  const ncols = Math.max((table.headers || []).length, ...(table.rows || []).map((r) => r.length), 1);
  table.rows = table.rows || [];
  table.rows.push(Array(ncols).fill(""));
  renderContent();
  renderPreview();
  markDirty();
}

function addTableCol(owner) {
  const table = tableByOwner(owner);
  if (!table) return;
  if ((table.headers || []).some((h) => String(h).trim())) table.headers.push("新列");
  (table.rows || []).forEach((row) => row.push(""));
  table.widthsCm = table.widthsCm || [];
  table.widthsCm.push(3);
  renderContent();
  renderPreview();
  markDirty();
}

function deleteTableRow(owner, rowIndex) {
  const table = tableByOwner(owner);
  if (!table || !table.rows) return;
  table.rows.splice(rowIndex, 1);
  renderContent();
  renderPreview();
  markDirty();
}

/* ---------------- validation / meta ---------------- */
function validateClient() {
  const errors = [];
  const warnings = [];
  const e = state.plan.event || {};
  if (!e.title || /【/.test(e.title || "")) warnings.push("活动名称尚未填写完整。");
  if (!e.location) warnings.push("活动地点为空，建议补充到具体校区与场地。");
  if (!e.audience) warnings.push("活动对象为空。");
  if (!e.organizer) warnings.push("主办单位为空。");
  const mods = enabledModules();
  if (!mods.length) errors.push("至少需要启用一个模块。");
  mods.forEach((m) => {
    const has = (m.blocks && m.blocks.length) || m.table || (m.attachments && m.attachments.length);
    if (!has) errors.push(`模块“${m.title}”没有内容。`);
  });
  const budget = mods.find((m) => m.table && m.table.kind === "budget");
  if (budget) {
    const total = computeBudgetClient(budget.table).total;
    if (total <= 0) warnings.push("预算合计为 0，请检查单价与数量。");
  }
  const placeholders = placeholderCount();
  if (placeholders > 0) warnings.push(`仍有 ${placeholders} 处【待补充】占位符，可交给 Agent 补全。`);
  return { errors, warnings, placeholders, pages: estimatePages() };
}

function validationHTML(result) {
  const status = result.errors.length ? "需处理" : result.warnings.length ? "可完善" : "可生成";
  return `<div class="validation">
      <div class="val-card ${result.errors.length ? "error" : "ok"}"><strong>${result.errors.length}</strong><span>阻塞问题</span></div>
      <div class="val-card ${result.warnings.length ? "warn" : "ok"}"><strong>${result.warnings.length}</strong><span>提醒</span></div>
      <div class="val-card"><strong>${result.placeholders}</strong><span>占位符</span></div>
      <div class="val-card"><strong>${result.pages}</strong><span>预估页数</span></div>
    </div>
    <div class="val-list">
      <div class="val-item ${result.errors.length ? "error" : "ok"}">${esc(status)}：${result.errors.length ? esc(result.errors.join("；")) : "结构完整，可以生成 DOCX。"}</div>
      ${result.warnings.map((w) => `<div class="val-item warn">${esc(w)}</div>`).join("")}
    </div>`;
}

function refreshValidation() {
  const result = validateClient();
  const box = $("#validationBlock");
  if (box) box.innerHTML = validationHTML(result);
  updateMeta();
}

function estimatePages() {
  let chars = 0;
  let tables = 0;
  let mods = 0;
  enabledModules().forEach((m) => {
    mods += 1;
    (m.blocks || []).forEach((b) => {
      if (b.type === "paragraph") chars += String(b.text || "").length;
      else if (b.type === "subheading") chars += String(b.text || "").length;
      else if (b.type === "list") chars += (b.items || []).join("").length;
      else if (b.type === "table") tables += 1;
    });
    if (m.table) tables += 1;
    tables += (m.attachments || []).length;
  });
  return Math.max(1, Math.round((chars / 680 + tables * 0.55 + mods * 0.08) * 10) / 10);
}

function updateMeta() {
  const result = validateClient();
  const moduleCount = $("#moduleCount");
  if (moduleCount) moduleCount.textContent = `${enabledModules().length} 个模块`;
  const pages = $("#pageEstimate");
  if (pages) pages.textContent = `约 ${result.pages} 页`;
  const saveState = $("#saveState");
  if (saveState && !state.dirty) {
    saveState.textContent = state.buildResult ? "已生成" : "已载入";
    saveState.className = "save-state saved";
  }
}

function markDirty() {
  state.dirty = true;
  const saveState = $("#saveState");
  if (saveState) {
    saveState.textContent = "未保存改动";
    saveState.className = "save-state dirty";
  }
  clearTimeout(state.autosaveTimer);
  state.autosaveTimer = setTimeout(() => {
    try { localStorage.setItem("apb.autosave", JSON.stringify({ plan: state.plan, at: Date.now() })); } catch (e) {}
  }, 600);
  refreshValidationDebounced();
}

const refreshValidationDebounced = debounce(refreshValidation, 450);

/* ---------------- preview ---------------- */
function renderPreview() {
  const paper = $("#paper");
  if (!paper) return;
  const s = state.plan.style;
  const margins = s.page.marginsCm;
  paper.style.padding = `${margins.top}cm ${margins.right}cm ${margins.bottom}cm ${margins.left}cm`;
  paper.style.fontFamily = fontStack(s.body.eastAsia, s.body.ascii);
  paper.innerHTML = previewHTML();
  applyZoom();
}

function applyZoom() {
  const paper = $("#paper");
  if (paper) paper.style.zoom = state.zoom;
  const label = $("#zoomLabel");
  if (label) label.textContent = Math.round(state.zoom * 100) + "%";
}

function pStyle(cfg, options = {}) {
  const ls = cfg.lineSpacing || {};
  const lineHeight = ls.mode === "exact" ? `${ls.pt}pt` : String(ls.value || 1.5);
  const align = cfg.align || "justify";
  const indent = options.indent ? `${cfg.firstLineIndentChars || 0}em` : "0";
  return `margin:${cfg.spaceBeforePt || 0}pt 0 ${cfg.spaceAfterPt || 0}pt;text-align:${align};font-family:${fontStack(cfg.eastAsia, cfg.ascii)};font-size:${cfg.sizePt}pt;font-weight:${cfg.bold ? 700 : 400};line-height:${lineHeight};text-indent:${indent};`;
}

function previewHTML() {
  const s = state.plan.style;
  const parts = [];
  const lines = previewTitleLines();
  lines.forEach((line) => {
    parts.push(`<p class="pv-title-line" style="${pStyle(s.title)}">${esc(line)}</p>`);
  });
  parts.push(`<div style="height:10pt"></div>`);

  let number = 0;
  enabledModules().forEach((mod) => {
    if (mod.id === "signature" || mod.id === "attachment") return;
    number += 1;
    parts.push(`<p class="pv-h1" style="${pStyle(s.h1)}">${cnNumber(number)}、${esc(mod.title)}</p>`);
    (mod.blocks || []).forEach((block) => {
      parts.push(previewBlock(block));
    });
    if (mod.table && tablesEnabled()) parts.push(tableHTML(mod.table));
  });

  const sig = getModule("signature");
  if (sig && sig.enabled) {
    const items = (sig.blocks || []).filter((b) => b.type === "paragraph" && String(b.text || "").trim());
    if (items.length) {
      parts.push(`<div class="pv-signature" style="margin-top:24pt">`);
      items.forEach((b) => {
        const cfg = { ...s.body, align: "right" };
        parts.push(`<p style="${pStyle(cfg)}">${esc(b.text)}</p>`);
      });
      parts.push(`</div>`);
    }
  }

  const attMod = getModule("attachment");
  if (attMod && attMod.enabled && tablesEnabled() && (attMod.attachments || []).length) {
    attMod.attachments.forEach((att, i) => {
      parts.push(`<div style="break-before:page;page-break-before:always;border-top:1px dashed #ddd;margin:18pt 0 12pt"></div>`);
      parts.push(`<p class="pv-attachment-label" style="${pStyle(s.h1)}">附件${cnNumber(i + 1)}</p>`);
      parts.push(`<p class="pv-attachment-title" style="${pStyle(s.title)}">${esc(att.title)}</p>`);
      if (att.subtitle) parts.push(`<p class="pv-attachment-sub" style="${pStyle({ ...s.body, align: "center", eastAsia: "楷体_GB2312", sizePt: 14 })}">${esc(att.subtitle)}</p>`);
      if (att.table) parts.push(tableHTML(att.table));
    });
  }
  return parts.join("");
}

function previewTitleLines() {
  const e = state.plan.event || {};
  if (Array.isArray(e.titleLines) && e.titleLines.length) return e.titleLines.slice();
  let title = (e.title || "").trim() || "活动方案";
  if (!title.includes("方案") && !title.includes("策划")) title += "活动方案";
  const lines = [];
  const organizer = (e.organizer || "").trim();
  const theme = (e.theme || "").trim();
  if (organizer && !/【/.test(organizer)) lines.push(organizer);
  if (theme && !title.includes(theme) && !lines.includes(theme) && !/【/.test(theme)) lines.push(theme);
  if (!lines.includes(title)) lines.push(title);
  return lines;
}

function previewBlock(block) {
  const s = state.plan.style;
  if (block.type === "paragraph") {
    return `<p class="pv-p" style="${pStyle(s.body, { indent: true })}">${esc(block.text || "").replace(/\n/g, "<br>")}</p>`;
  }
  if (block.type === "subheading") {
    return `<p class="pv-h2" style="${pStyle(s.h2)}">${esc(block.text || "")}</p>`;
  }
  if (block.type === "list") {
    return (block.items || []).map((item, i) => {
      const prefix = block.ordered === false ? "· " : `${i + 1}.`;
      return `<p class="pv-p" style="${pStyle(s.body, { indent: true })}"><strong>${prefix}</strong> ${esc(item)}</p>`;
    }).join("");
  }
  if (block.type === "note") {
    const cfg = { ...s.body, eastAsia: "楷体_GB2312", sizePt: 14, color: "#444" };
    return `<p class="pv-note" style="${pStyle(cfg, { indent: true })}">${esc(block.text || "")}</p>`;
  }
  if (block.type === "table" && block.table && tablesEnabled()) return tableHTML(block.table);
  if (block.type === "pagebreak") {
    return `<div style="break-before:page;page-break-before:always;border-top:1px dashed #ddd;margin:18pt 0 12pt"></div>`;
  }
  return "";
}

/* ---------------- persistence & actions ---------------- */
async function saveDraft() {
  try {
    const res = await fetch("/api/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan: state.plan, handoff: false })
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "保存失败");
    state.plan = data.plan;
    state.dirty = false;
    const saveState = $("#saveState");
    saveState.textContent = "已保存";
    saveState.className = "save-state saved";
    toast("草稿已保存到 plan.json", "success");
  } catch (err) {
    toast("保存失败：" + err.message, "error");
  }
}

async function handoff() {
  try {
    const res = await fetch("/api/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan: state.plan, handoff: true })
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "提交失败");
    state.plan = data.plan;
    state.dirty = false;
    const result = validateClient();
    showModal("已交给 Agent",
      `配置已保存到：${state.boot.planPath}\n\n请回到对话窗口，对 Agent 说“继续”，它会补全剩余占位符并生成 DOCX。${result.placeholders ? `\n\n当前仍有 ${result.placeholders} 处占位符。` : ""}`,
      null);
    toast("已交给 Agent", "success");
  } catch (err) {
    toast("提交失败：" + err.message, "error");
  }
}

async function buildDocx() {
  const btn = $("[data-action='build']");
  if (btn) { btn.disabled = true; btn.textContent = "正在生成…"; }
  try {
    const res = await fetch("/api/build", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan: state.plan })
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "生成失败");
    state.buildResult = data;
    state.dirty = false;
    const saveState = $("#saveState");
    if (saveState) { saveState.textContent = "已生成"; saveState.className = "save-state saved"; }
    showModal("DOCX 已生成", `文件：${data.path}\n\n可以直接下载，也可以回到对话让 Agent 继续修改内容。`, data.download);
    toast("DOCX 已生成", "success");
    renderContent();
  } catch (err) {
    toast("生成失败：" + err.message, "error");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "生成 DOCX"; }
  }
}

function downloadJSON() {
  const blob = new Blob([JSON.stringify(state.plan, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = (state.plan.event.title || "活动方案").replace(/[\\/:*?"<>|]/g, "_") + ".plan.json";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function syncEvent(silent) {
  const dateText = state.plan.event.date;
  if (dateText) {
    const d = new Date(dateText + "T00:00:00");
    if (!Number.isNaN(d.getTime())) {
      const week = "日一二三四五六"[d.getDay()];
      state.plan.event.dateText = `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`;
      state.plan.event.weekday = `星期${week}`;
    }
  }
  try {
    const res = await fetch("/api/sync-event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan: state.plan })
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "同步失败");
    state.plan = data.plan;
    renderPreview();
    updateMeta();
    markDirty();
    if (!silent) toast("已同步到核心模块", "success");
  } catch (err) {
    // local fallback
    renderPreview();
    if (!silent) toast("已在本地预览中同步；保存时再写入服务端", "error");
  }
}

function exportPanelHTML() {
  const build = state.buildResult;
  return `<div class="export-panel">
    <div class="export-title"><h3>生成与交付</h3><span class="badge">${state.plan.meta?.status || "draft"}</span></div>
    <div class="export-actions">
      <button class="btn ghost" data-action="save-draft">保存草稿</button>
      <button class="btn primary" data-action="build">生成 DOCX</button>
      <button class="btn ghost" data-action="handoff">交给 Agent</button>
      <button class="btn ghost" data-action="download-json">下载 JSON</button>
      <button class="btn ghost" data-action="validate">重新校验</button>
    </div>
    ${build ? `<div class="build-result">已生成：${esc(build.path)} · <a href="${esc(build.download)}" download>下载 DOCX</a></div>` : ""}
  </div>`;
}

/* ---------------- toast & modal ---------------- */
function toast(message, type = "") {
  const el = $("#toast");
  if (!el) return;
  el.textContent = message;
  el.className = "toast " + type;
  el.hidden = false;
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => { el.hidden = true; }, 3200);
}

function showModal(title, body, downloadUrl) {
  $("#modalTitle").textContent = title;
  $("#modalBody").textContent = body;
  const link = $("#modalLink");
  if (downloadUrl) {
    link.href = downloadUrl;
    link.hidden = false;
  } else {
    link.hidden = true;
  }
  $("#modal").hidden = false;
}

function closeModal() {
  $("#modal").hidden = true;
}

/* ---------------- step specific bindings ---------------- */
function bindStepEvents() {
  const zone = $("#importZone");
  if (zone) {
    zone.addEventListener("dragover", (event) => {
      event.preventDefault();
      zone.classList.add("dragover");
    });
    zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));
    zone.addEventListener("drop", (event) => {
      event.preventDefault();
      zone.classList.remove("dragover");
      const file = event.dataTransfer.files && event.dataTransfer.files[0];
      if (file) uploadStyleFile(file);
    });
  }
  const search = $("#moduleSearch");
  if (search && state.search) {
    search.value = state.search;
    filterModuleCards(state.search);
  }
}

boot();

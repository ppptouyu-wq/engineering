"use strict";

const byId = (id) => document.getElementById(id);
const pages = {home: "工作台", resume: "简历优化", interview: "模拟面试", history: "历史记录", bookmarks: "复习题夹",
  versions: "简历版本", analytics: "训练统计", plan: "练习计划"};
const kinds = {resume: "简历诊断", interview: "模拟面试"};
const aiProviders = {deepseek: "DeepSeek", qwen: "千问"};
const dateFormat = new Intl.DateTimeFormat("zh-CN", {dateStyle: "medium", timeStyle: "short"});
const sample = [
  "教育背景",
  "某大学 · 软件工程硕士在读",
  "",
  "项目经历",
  "课程选课与候补平台",
  "我负责实现课程查询与候补 API，使用 Python 和 MySQL 管理选课记录。",
  "设计数据库索引，在 5000 条模拟记录上将查询耗时从 180 ms 降至 65 ms。",
  "编写并执行 18 个单元测试，覆盖重复报名、名额不足和候补转正。",
  "",
  "专业技能",
  "Python、MySQL、SQL、REST API、单元测试"
].join("\n");

let roles = new Map();
let records = [];
let historyError = "";
let filter = "all";
let interview = null;
let historyRequest = 0;
let routeRequest = 0;

function node(tag, text, classes) {
  const element = document.createElement(tag);
  if (text != null) element.textContent = text;
  if (classes) element.className = classes;
  return element;
}

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const use = document.createElementNS(svg.namespaceURI, "use");
  use.setAttribute("href", "/icons.svg#" + name);
  svg.setAttribute("aria-hidden", "true");
  svg.append(use);
  return svg;
}

async function api(path, method = "GET", payload) {
  let response;
  try {
    const options = {method};
    if (payload !== undefined) {
      options.headers = {"Content-Type": "application/json"};
      options.body = JSON.stringify(payload);
    }
    response = await fetch(path, options);
  } catch {
    throw new Error("无法连接本地服务，请确认服务仍在运行后重试。");
  }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "请求失败，请重试。");
  return data;
}

function errorAt(id, message = "") {
  const element = byId(id);
  element.textContent = message;
  element.hidden = !message;
}

async function withButton(button, errorId, work, pendingLabel = "处理中…") {
  if (button.disabled) return;
  errorAt(errorId);
  const label = [...button.childNodes];
  button.disabled = true;
  button.textContent = pendingLabel;
  try {
    await work();
  } catch (error) {
    errorAt(errorId, error.message);
  } finally {
    button.disabled = false;
    button.replaceChildren(...label);
  }
}

async function refreshHistory() {
  const request = ++historyRequest;
  try {
    const result = await api("/api/history");
    if (request !== historyRequest) return;
    records = result;
    historyError = "";
  } catch (error) {
    if (request !== historyRequest) return;
    historyError = error.message;
  }
  renderHistory();
}

function renderHistory() {
  byId("resume-total").textContent = historyError ? "—" : records.filter((item) => item.kind === "resume").length;
  byId("interview-total").textContent = historyError ? "—" : records.filter((item) => item.kind === "interview").length;
  byId("latest-score").textContent = historyError ? "—" : (records[0]?.score ?? "—");
  renderList(byId("recent-records"), records.slice(0, 3), false);
  renderList(byId("history-records"), records.filter((item) => filter === "all" || filter === item.kind), true);
}

function renderList(container, items, canDelete) {
  container.replaceChildren();
  container.classList.toggle("empty", Boolean(historyError) || items.length === 0);
  if (historyError || items.length === 0) {
    container.textContent = historyError || "暂无记录。完成一次诊断或面试后，报告会出现在这里。";
    return;
  }
  for (const item of items) {
    const row = node("div", null, "record-row");
    const info = node("div", null, "record-info");
    const badge = node("span", null, item.kind === "resume" ? "stat-icon purple" : "stat-icon blue");
    badge.append(icon(item.kind === "resume" ? "file" : "chat"));
    const summary = node("div");
    summary.append(node("strong", kinds[item.kind] + " · " + (roles.get(item.role) || item.role)));
    summary.append(node("small", dateFormat.format(new Date(item.created_at))));
    info.append(badge, summary);
    const actions = node("div", null, "record-actions");
    const open = node("a", "查看", "text-button");
    open.href = "#history/" + item.id;
    open.setAttribute("aria-label", "查看" + kinds[item.kind] + "报告");
    actions.append(node("span", item.score + " 分", "score-pill"), open);
    if (canDelete) {
      const remove = node("button", "删除", "text-button danger");
      remove.type = "button";
      remove.addEventListener("click", async () => {
        if (!window.confirm("删除这份报告？删除后无法恢复。")) return;
        remove.disabled = true;
        try {
          await api("/api/records/" + item.id, "DELETE");
          if (location.hash === open.hash) location.hash = "history";
          await refreshHistory();
        } catch (error) {
          window.alert(error.message);
          remove.disabled = false;
        }
      });
      actions.append(remove);
    }
    row.append(info, actions);
    container.append(row);
  }
}

function reportPanel(title) {
  const panel = node("section", null, "panel report-panel");
  if (title) panel.append(node("h3", title));
  return panel;
}

function showReport(container, kind, report, role) {
  container.replaceChildren();
  container.hidden = false;
  const overview = reportPanel();
  const head = node("div", null, "report-head row");
  const heading = node("div");
  let method = "规则评分";
  if (kind === "resume" && report.optimization === "deepseek") method += " · DeepSeek 优化";
  if (kind === "interview") {
    const questionProvider = aiProviders[report.question_source];
    const evaluationProvider = aiProviders[report.evaluation];
    const source = questionProvider ? questionProvider + "出题" : "本地题库";
    const evaluation = evaluationProvider ? evaluationProvider + "点评（" + report.model + "）" : "本地规则评分";
    method = source + " · " + evaluation;
    const difficulty = {basic: "基础", standard: "标准", advanced: "进阶"}[report.difficulty];
    if (difficulty) method += " · " + difficulty;
  }
  heading.append(node("h2", kinds[kind] + "报告"), node("p", (roles.get(role) || role) + " · " + method));
  if (report.notice) heading.append(node("p", report.notice, "hint"));
  const score = node("div", null, "report-score");
  score.append(node("strong", report.score), node("small", "/ 100 分"));
  head.append(heading, score);
  const dimensions = node("div", null, "dimensions");
  for (const item of report.dimensions) {
    const dimension = node("div", null, "dimension");
    const label = node("div", null, "row");
    label.append(node("strong", item.label), node("span", item.score + " / 100"));
    const meter = node("progress");
    meter.max = 100;
    meter.value = item.score;
    meter.setAttribute("aria-label", item.label);
    dimension.append(label, meter, node("small", item.detail));
    dimensions.append(dimension);
  }
  overview.append(head, dimensions);
  container.append(overview);
  if (kind === "resume") renderResumeReport(container, report, role);
  else renderInterviewReport(container, report, role);
  const actions = node("div", null, "button-row");
  const print = node("button", "打印 / 另存为 PDF", "button secondary");
  print.type = "button";
  print.addEventListener("click", () => {
    document.getElementById("print-area")?.remove();
    const area = node("div", null, "print-area");
    area.id = "print-area";
    const copy = container.cloneNode(true);
    copy.removeAttribute("id");
    copy.querySelectorAll("button, .button-row").forEach((item) => item.remove());
    copy.querySelectorAll("details").forEach((item) => { item.open = true; });
    area.append(copy);
    document.body.append(area);
    window.addEventListener("afterprint", () => area.remove(), {once: true});
    window.print();
  });
  actions.append(print);
  container.append(actions);
  if (container.getClientRects().length) container.focus();
}

function renderResumeReport(container, report, role) {
  const keywords = reportPanel("岗位关键词");
  for (const [label, terms, color] of [
    ["已覆盖", report.matched, "mint"],
    ["待核对", report.missing, "neutral"]
  ]) {
    const group = node("div", null, "tags");
    if (terms.length) {
      for (const term of terms) group.append(node("span", term, "tag " + color));
    } else {
      group.append(node("span", "无", "tag neutral"));
    }
    keywords.append(node("strong", label), group);
  }
  const advice = reportPanel("修改建议");
  const list = node("ol");
  for (const item of report.suggestions) {
    const entry = node("li");
    entry.append(node("strong", item.title), node("p", item.detail));
    const plan = node("button", "加入练习计划", "text-button");
    plan.type = "button";
    plan.addEventListener("click", () => addSuggestedTask(plan, role, item.title + "：" + item.detail));
    entry.append(plan);
    list.append(entry);
  }
  advice.append(list);
  const draft = reportPanel(report.optimization === "deepseek" ? "DeepSeek 简历优化稿" : "简历整理稿");
  const download = node("button", "下载 TXT", "button secondary");
  download.addEventListener("click", () => {
    const url = URL.createObjectURL(new Blob(["\uFEFF", report.draft], {type: "text/plain;charset=utf-8"}));
    const link = node("a");
    link.href = url;
    link.download = "简历整理稿.txt";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  draft.append(node("p", report.optimization === "deepseek"
    ? "根据岗位与原简历生成。请核对事实和措辞后使用。"
    : "整理项目要点的格式和句首措辞。提交前请结合上方建议补充真实经历。"),
    node("pre", report.draft, "draft"), download);
  const practice = node("button", "用这份简历准备面试", "button primary");
  practice.type = "button";
  practice.addEventListener("click", () => {
    if (byId("interview-context").value.trim() && !window.confirm("替换当前面试的个人经历？")) return;
    byId("interview-context").value = report.draft.slice(0, 4000);
    byId("interview-role").value = role;
    location.hash = "interview";
  });
  draft.append(practice);
  const saveVersion = node("button", "保存优化稿到版本库", "button secondary");
  saveVersion.type = "button";
  const saveStatus = node("p", "", "hint");
  saveStatus.setAttribute("role", "status");
  saveVersion.addEventListener("click", async () => {
    saveVersion.disabled = true;
    try {
      await saveResumeVersion((roles.get(role) || role) + " 优化稿", role, report.draft, report.description || "");
      saveStatus.textContent = "已保存到简历版本库，可与初稿比较。";
    } catch (error) {
      saveStatus.textContent = error.message;
      saveVersion.disabled = false;
    }
  });
  draft.append(saveVersion, saveStatus);
  container.append(keywords, advice, draft);
}

function renderInterviewReport(container, report, role) {
  const panel = reportPanel("逐题复盘");
  const provider = aiProviders[report.evaluation];
  const ai = Boolean(provider);
  panel.append(node("p", ai ? provider + "从切题程度、内容准确性与具体程度评估每个回答。"
    : "关键词命中用于提示展开角度。复盘时请同时检查回答的准确性与逻辑。"));
  report.feedback.forEach((item, index) => {
    const detail = node("details");
    detail.open = index === 0;
    detail.append(node("summary", "第 " + (index + 1) + " 题 · " + item.category + " · " + item.score + " 分"));
    detail.append(node("h4", item.question), node("pre", item.answer, "answer-copy"));
    if (ai) {
      const notes = node("dl", null, "feedback-notes");
      for (const [label, value] of [["点评", item.comment], ["做得好的地方", item.strength], ["下次可以这样改", item.improvement]]) {
        notes.append(node("dt", label), node("dd", value));
      }
      detail.append(notes);
    } else {
      const rubric = node("ul");
      for (const criterion of item.rubric) {
        rubric.append(node("li", (criterion.covered ? "已命中 · " : "建议展开 · ") + criterion.label,
          criterion.covered ? "rubric-hit" : "rubric-miss"));
      }
      detail.append(rubric);
    }
    const save = node("button", "收藏到复习题夹", "button secondary");
    save.type = "button";
    save.addEventListener("click", async () => {
      save.disabled = true;
      try {
        const note = ai ? item.improvement : item.rubric.filter((entry) => !entry.covered).map((entry) => entry.label).join("；");
        await api("/api/bookmarks", "POST", {role, question: item.question, answer: item.answer, note});
        save.textContent = "已收藏";
      } catch (error) {
        save.textContent = "收藏失败，点击重试";
        save.title = error.message;
        save.disabled = false;
      }
    });
    detail.append(save);
    panel.append(detail);
  });
  container.append(panel);
}

async function route() {
  const [target, recordId] = location.hash.slice(1).split("/");
  if (target === "main") return;
  const request = ++routeRequest;
  const page = Object.hasOwn(pages, target) ? target : "home";
  document.querySelectorAll("[data-page]").forEach((element) => { element.hidden = element.dataset.page !== page; });
  document.querySelectorAll("[data-nav]").forEach((link) => {
    if (link.dataset.nav === page) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  byId("breadcrumb").textContent = pages[page];
  byId("main").focus({preventScroll: true});
  window.scrollTo(0, 0);
  const detail = byId("history-detail");
  detail.hidden = true;
  if (page === "bookmarks") await renderBookmarks();
  if (typeof renderFeaturePage === "function") await renderFeaturePage(page);
  if (page !== "history" || !recordId) return;
  if (!/^[a-f0-9]{32}$/.test(recordId)) {
    detail.replaceChildren(node("p", "记录编号无效。", "form-error"));
    detail.hidden = false;
    return;
  }
  detail.replaceChildren(node("p", "正在读取报告…"));
  detail.hidden = false;
  try {
    const record = await api("/api/records/" + recordId);
    if (request === routeRequest) showReport(detail, record.kind, record.report, record.role);
  } catch (error) {
    if (request === routeRequest) detail.replaceChildren(node("p", error.message, "form-error"));
  }
}

async function renderBookmarks() {
  const container = byId("bookmark-list");
  container.replaceChildren(node("p", "正在读取收藏题目…"));
  try {
    const items = await api("/api/bookmarks");
    container.replaceChildren();
    const reviewFilter = byId("review-filter").value;
    const filtered = items.filter((item) => reviewFilter === "all" ||
      (reviewFilter === "reviewed" ? item.reviewed : !item.reviewed));
    if (!filtered.length) container.append(node("p", "当前筛选下没有题目。可在面试报告中收藏题目。", "panel report-panel"));
    for (const item of filtered) {
      const panel = reportPanel(roles.get(item.role) || item.role);
      panel.append(node("span", item.reviewed ? "已复习" : "待复习", item.reviewed ? "tag mint" : "tag purple"));
      panel.append(node("h4", item.question), node("pre", item.answer, "answer-copy"),
        node("p", item.note || "回顾本题的思路和验证方式，再尝试组织一次回答。"));
      const remove = node("button", "移出题夹", "text-button danger");
      remove.type = "button";
      remove.addEventListener("click", async () => {
        if (!window.confirm("将这道题移出复习题夹？")) return;
        remove.disabled = true;
        try {
          await api("/api/bookmarks/" + item.id, "DELETE");
          await renderBookmarks();
        } catch (error) {
          remove.disabled = false;
          remove.textContent = error.message + "，点击重试";
        }
      });
      panel.append(remove);
      const reviewForm = node("form", null, "review-form");
      const label = node("label", "重新组织一次回答");
      const answer = node("textarea");
      answer.id = "review-answer-" + item.id;
      label.htmlFor = answer.id;
      answer.required = true;
      answer.minLength = 10;
      answer.maxLength = 2500;
      answer.rows = 4;
      answer.value = item.review_answer || "";
      const save = node("button", "保存复习回答", "button secondary");
      save.type = "submit";
      const status = node("p", "", "hint");
      status.setAttribute("role", "status");
      reviewForm.append(label, answer, save, status);
      reviewForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        save.disabled = true;
        try {
          await api("/api/bookmarks/" + item.id, "PATCH", {reviewed: true, review_answer: answer.value.trim()});
          await renderBookmarks();
        } catch (error) {
          status.textContent = error.message;
          save.disabled = false;
        }
      });
      if (item.reviewed) {
        const reset = node("button", "标为待复习", "text-button");
        reset.type = "button";
        reset.addEventListener("click", async () => {
          reset.disabled = true;
          try {
            await api("/api/bookmarks/" + item.id, "PATCH", {reviewed: false});
            await renderBookmarks();
          } catch (error) {
            status.textContent = error.message;
            reset.disabled = false;
          }
        });
        reviewForm.append(reset);
      }
      panel.append(reviewForm);
      container.append(panel);
    }
  } catch (error) {
    container.replaceChildren(node("p", error.message, "form-error"));
  }
}

byId("resume-sample").addEventListener("click", () => {
  if (byId("resume-text").value.trim() && !window.confirm("用样例替换当前简历正文？")) return;
  byId("resume-text").value = sample;
  byId("import-status").textContent = "已填入演示样例。";
  byId("resume-role").value = "backend";
  errorAt("resume-error");
  byId("resume-text").focus();
});

byId("resume-file").addEventListener("change", async (event) => {
  const input = event.currentTarget;
  const file = input.files[0];
  if (!file) return;
  const submit = byId("resume-form").querySelector('[type="submit"]');
  input.disabled = submit.disabled = byId("resume-text").readOnly = true;
  byId("import-status").textContent = "正在读取并提取简历…";
  try {
    let content;
    if (/\.pdf$/i.test(file.name)) {
      if (file.size > 5 * 1024 * 1024) throw new Error("PDF 文件不能超过 5 MB。");
      const response = await fetch("/api/resumes/import", {
        method: "POST", headers: {"Content-Type": "application/pdf"}, body: file
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "PDF 提取失败。");
      content = result.text;
    } else {
      if (!/\.(txt|md)$/i.test(file.name) || file.size > 48003) throw new Error("请选择 PDF 或不超过 48 KB 的 .txt、.md 文件。");
      try {
        content = new TextDecoder("utf-8", {fatal: true}).decode(await file.arrayBuffer());
      } catch {
        throw new Error("读取失败，请确认文件使用 UTF-8 编码。");
      }
    }
    if (content.length > 12000) throw new Error("简历正文最多 12,000 字符。");
    if (byId("resume-text").value.trim() && !window.confirm("用导入内容替换当前简历正文？")) {
      byId("import-status").textContent = "已取消导入。";
      return;
    }
    byId("resume-text").value = content;
    byId("import-status").textContent = "已导入 " + file.name + "，共 " + content.length + " 字符。请核对后提交诊断。";
    errorAt("resume-error");
    byId("resume-text").focus();
  } catch (error) {
    byId("import-status").textContent = "导入未完成，当前简历内容已保留。";
    errorAt("resume-error", error.message);
  } finally {
    input.value = "";
    input.disabled = submit.disabled = byId("resume-text").readOnly = false;
  }
});

byId("resume-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const payload = Object.fromEntries(new FormData(event.currentTarget));
  payload.use_ai = payload.use_ai === "on" && !byId("resume-ai-choice").hidden;
  withButton(event.submitter, "resume-error", async () => {
    const result = await api("/api/resumes", "POST", payload);
    showReport(byId("resume-result"), "resume", result.report, payload.role);
    await refreshHistory();
  }, payload.use_ai ? "DeepSeek 正在优化简历…" : "正在生成诊断…");
});

function showQuestion() {
  const question = interview.questions[interview.index];
  const number = interview.index + 1;
  byId("interview-form").hidden = true;
  byId("answer-form").hidden = false;
  byId("question-category").textContent = question.category;
  byId("question-progress").textContent = "第 " + number + " / " + interview.questions.length + " 题";
  byId("question-meter").max = interview.questions.length;
  byId("question-meter").value = number;
  byId("question").textContent = question.text;
  byId("answer").value = interview.answers[interview.index];
  byId("previous-question").hidden = number === 1;
  byId("next-question").textContent = number === interview.questions.length ? "提交并查看报告" : "下一题";
  errorAt("answer-error");
  if (!byId("interview-page").hidden) byId("question").focus();
}

byId("interview-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const {role, count, use_ai, difficulty, description, context} = Object.fromEntries(new FormData(event.currentTarget));
  const useAI = use_ai === "on" && !byId("ai-choice").hidden;
  withButton(event.submitter, "interview-error", async () => {
    const result = await api("/api/interviews", "POST", {
      role, count: Number(count), use_ai: useAI, difficulty, description, context
    });
    interview = {...result, role, useAI, index: 0, answers: Array(result.questions.length).fill("")};
    byId("question-source").textContent = result.question_source === "deepseek"
      ? "题目由 DeepSeek 生成"
      : (useAI ? "DeepSeek 出题暂不可用，本场使用本地题库。" : "题目来自本地题库");
    byId("interview-result").hidden = true;
    showQuestion();
  }, useAI ? "DeepSeek 正在出题…" : "正在准备题目…");
});

byId("previous-question").addEventListener("click", () => {
  interview.answers[interview.index] = byId("answer").value;
  interview.index -= 1;
  showQuestion();
});

byId("answer-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const answer = byId("answer").value.trim();
  if (answer.length < 10) {
    errorAt("answer-error", "请填写至少 10 个有效字符。");
    return;
  }
  interview.answers[interview.index] = answer;
  if (interview.index < interview.questions.length - 1) {
    interview.index += 1;
    showQuestion();
    return;
  }
  const previous = byId("previous-question");
  const cancel = byId("cancel-interview");
  const input = byId("answer");
  const pendingLabel = interview.useAI ? "DeepSeek 正在点评…" : "正在生成报告…";
  withButton(event.submitter, "answer-error", async () => {
    previous.disabled = cancel.disabled = input.readOnly = true;
    try {
      const report = await api("/api/interviews/" + interview.id + "/finish", "POST", {answers: interview.answers});
      byId("answer-form").hidden = true;
      byId("interview-form").hidden = false;
      showReport(byId("interview-result"), "interview", report, interview.role);
      interview = null;
      await refreshHistory();
    } finally {
      previous.disabled = cancel.disabled = input.readOnly = false;
    }
  }, pendingLabel);
});

byId("cancel-interview").addEventListener("click", () => {
  if (!window.confirm("退出当前练习？本次回答将丢失。")) return;
  withButton(byId("cancel-interview"), "answer-error", async () => {
    await api("/api/records/" + interview.id, "DELETE");
    interview = null;
    byId("answer-form").hidden = true;
    byId("interview-form").hidden = false;
    byId("interview-role").focus();
  });
});

document.querySelectorAll("[data-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    filter = button.dataset.filter;
    document.querySelectorAll("[data-filter]").forEach((item) => {
      item.setAttribute("aria-pressed", String(item === button));
    });
    renderHistory();
  });
});

window.addEventListener("hashchange", route);
route();
(async () => {
  try {
    const [available, config] = await Promise.all([
      api("/api/roles"), api("/api/interviews/config").catch(() => null)
    ]);
    roles = new Map(available.map((item) => [item.id, item.label]));
    for (const select of [byId("resume-role"), byId("interview-role")]) {
      for (const role of available) select.add(new Option(role.label, role.id));
    }
    if (config?.ai_available) {
      byId("ai-choice").hidden = false;
      byId("resume-ai-choice").hidden = false;
      byId("ai-hint").textContent = "开启后，题目与作答会发送给 DeepSeek 生成点评。请使用去标识化的经历。";
    } else if (config === null) {
      byId("ai-hint").textContent = "无法读取 DeepSeek 配置状态，请确认服务已更新并刷新页面。当前可使用本地题库练习。";
    }
    await refreshHistory();
    if (location.hash.startsWith("#history/")) await route();
    if (location.hash === "#bookmarks") await renderBookmarks();
    window.dispatchEvent(new Event("career-ready"));
  } catch (error) {
    errorAt("resume-error", error.message);
    errorAt("interview-error", error.message);
    historyError = error.message;
    renderHistory();
  }
})();

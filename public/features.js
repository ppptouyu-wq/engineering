"use strict";

let analyticsGroups = [];
let taskFilter = "all";

function populateFeatureRoles() {
  const select = byId("task-role");
  const selected = select.value;
  select.replaceChildren();
  for (const [id, label] of roles) select.add(new Option(label, id));
  if (roles.has(selected)) select.value = selected;
}

async function saveResumeVersion(title, role, resume, description) {
  return api("/api/versions", "POST", {title, role, resume, description});
}

async function renderFeaturePage(page) {
  if (page === "versions") await renderVersions();
  if (page === "analytics") await renderAnalytics();
  if (page === "plan") await renderTasks();
}

byId("save-current-version").addEventListener("click", async () => {
  const button = byId("save-current-version");
  button.disabled = true;
  const status = byId("version-save-status");
  try {
    await saveResumeVersion(byId("resume-version-title").value.trim() || "简历初稿",
      byId("resume-role").value, byId("resume-text").value, byId("description").value);
    status.textContent = "版本已保存，可在「简历版本」中查看和比较。";
  } catch (error) {
    status.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

async function renderVersions() {
  const container = byId("version-list");
  container.textContent = "正在读取简历版本…";
  try {
    const versions = await api("/api/versions");
    container.replaceChildren();
    for (const id of ["compare-before", "compare-after"]) {
      const select = byId(id);
      const previous = select.value;
      select.replaceChildren();
      for (const version of versions) {
        select.add(new Option(version.title + " · " + (roles.get(version.role) || version.role), version.id));
      }
      if (versions.some((version) => version.id === previous)) select.value = previous;
    }
    if (versions.length > 1 && byId("compare-before").value === byId("compare-after").value) {
      byId("compare-before").selectedIndex = 1;
    }
    byId("compare-form").querySelector('button[type="submit"]').disabled = versions.length < 2;
    if (!versions.length) {
      container.append(node("p", "暂无版本。在简历页保存当前正文，或在诊断报告中保存优化稿。", "report-panel"));
    }
    for (const version of versions) {
      const row = node("div", null, "record-row");
      const info = node("div");
      info.append(node("strong", version.title),
        node("p", (roles.get(version.role) || version.role) + " · " + version.characters + " 字符 · " +
          dateFormat.format(new Date(version.created_at)), "hint"));
      const actions = node("div", null, "button-row");
      const restore = node("button", "载入编辑", "text-button");
      restore.type = "button";
      restore.addEventListener("click", async () => {
        restore.disabled = true;
        try {
          const detail = await api("/api/versions/" + version.id);
          if (byId("resume-text").value.trim() && !window.confirm("载入此版本并替换当前编辑区？")) return;
          byId("resume-role").value = detail.role;
          byId("resume-text").value = detail.resume;
          byId("description").value = detail.description;
          byId("resume-version-title").value = (detail.title + " 修改版").slice(0, 80);
          byId("import-status").textContent = "已载入保存的版本，请编辑后另存。";
          location.hash = "resume";
        } catch (error) {
          window.alert(error.message);
        } finally {
          restore.disabled = false;
        }
      });
      const remove = node("button", "删除", "text-button danger");
      remove.type = "button";
      remove.addEventListener("click", async () => {
        if (!window.confirm("删除这个简历版本？此操作无法恢复。")) return;
        remove.disabled = true;
        try {
          await api("/api/versions/" + version.id, "DELETE");
          byId("comparison-result").hidden = true;
          await renderVersions();
        } catch (error) {
          remove.disabled = false;
          window.alert(error.message);
        }
      });
      actions.append(restore, remove);
      row.append(info, actions);
      container.append(row);
    }
  } catch (error) {
    container.textContent = error.message;
  }
}

byId("compare-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const before = byId("compare-before").value;
  const after = byId("compare-after").value;
  if (before === after) {
    errorAt("compare-error", "请选择两个不同的版本。");
    return;
  }
  withButton(event.submitter, "compare-error", async () => {
    const result = await api("/api/versions/compare", "POST", {before, after});
    const container = byId("comparison-result");
    container.replaceChildren();
    container.hidden = false;
    const panel = reportPanel(result.before.title + " → " + result.after.title);
    panel.append(node("p", "统一按「" + roles.get(result.role) + "」诊断 · " +
      result.before_score + " → " + result.after_score + " 分。规则分用于检查表达与结构。"));
    if (result.description) panel.append(node("p", "比较采用的岗位描述：" + result.description));
    const dimensions = node("div", null, "comparison-grid");
    for (const item of result.dimensions) {
      dimensions.append(node("p", item.label + "　" + item.before + " → " + item.after));
    }
    const diff = node("div", null, "version-diff");
    diff.setAttribute("aria-label", "逐行差异，减号表示删除，加号表示新增");
    for (const line of result.lines) {
      diff.append(node("div", (line.type === " " ? "　" : line.type + " ") + line.text,
        line.type === "+" ? "diff-added" : line.type === "-" ? "diff-removed" : ""));
    }
    panel.append(dimensions, node("h3", "正文差异"), diff);
    container.append(panel);
    container.focus();
  });
});

async function renderAnalytics() {
  const content = byId("analytics-content");
  content.textContent = "正在统计训练记录…";
  try {
    const [result, tasks, bookmarks, versions] = await Promise.all([
      api("/api/analytics"), api("/api/tasks"), api("/api/bookmarks"), api("/api/versions")
    ]);
    const summary = byId("analytics-summary");
    summary.replaceChildren();
    for (const [label, value] of [
      ["已完成训练", result.total], ["简历版本", versions.length],
      ["计划完成", tasks.filter((task) => task.done).length + " / " + tasks.length],
      ["题目复习", bookmarks.filter((item) => item.reviewed).length + " / " + bookmarks.length]
    ]) {
      const stat = node("div", null, "stat");
      const inner = node("div");
      inner.append(node("span", label), node("strong", value));
      stat.append(inner);
      summary.append(stat);
    }
    analyticsGroups = result.groups;
    const select = byId("analytics-group");
    const previous = select.value;
    select.replaceChildren();
    analyticsGroups.forEach((group, index) => {
      const method = aiProviders[group.method] || "本地规则";
      const difficulty = {basic: "基础", standard: "标准", advanced: "进阶"}[group.difficulty] || "";
      select.add(new Option([roles.get(group.role), kinds[group.kind], method, difficulty].filter(Boolean).join(" · "), index));
    });
    if (Number(previous) < analyticsGroups.length && previous !== "") select.value = previous;
    renderAnalyticsGroup();
  } catch (error) {
    content.textContent = error.message;
  }
}

function renderAnalyticsGroup() {
  const container = byId("analytics-content");
  container.replaceChildren();
  const group = analyticsGroups[Number(byId("analytics-group").value)];
  if (!group) {
    container.append(node("p", "完成一次简历诊断或面试后，这里会显示训练统计。"));
    return;
  }
  container.append(node("h2", "同组训练 " + group.count + " 次"),
    node("p", "平均 " + group.average + " 分 · 最近 " + group.latest + " 分" +
      (group.change === null ? " · 再完成一次训练后可查看变化" :
        " · 相对首次 " + (group.change >= 0 ? "+" : "") + group.change + " 分")));
  container.append(node("h3", "最近十次成绩"));
  const series = node("div", null, "score-series");
  for (const point of group.series) {
    const row = node("div", null, "score-row");
    const open = node("a", dateFormat.format(new Date(point.created_at)), "text-button");
    open.href = "#history/" + point.id;
    const progress = node("progress");
    progress.max = 100;
    progress.value = point.score;
    progress.setAttribute("aria-label", point.score + " 分");
    row.append(open, progress, node("strong", point.score + " 分"));
    series.append(row);
  }
  container.append(series, node("h3", "维度复盘"));
  for (const dimension of [...group.dimensions].sort((a, b) => a.score - b.score)) {
    const row = node("div", null, "record-row");
    row.append(node("span", dimension.label + " · 平均 " + dimension.score + " 分"));
    const plan = node("button", "加入练习计划", "text-button");
    plan.type = "button";
    plan.addEventListener("click", () => addSuggestedTask(plan, group.role,
      "练习" + dimension.label + "，结合一个具体项目整理回答并验证改进"));
    row.append(plan);
    container.append(row);
  }
}

async function addSuggestedTask(button, role, title) {
  button.disabled = true;
  try {
    await api("/api/tasks", "POST", {role, title: title.slice(0, 200)});
    button.textContent = "已加入计划";
  } catch (error) {
    button.textContent = "添加失败，点击重试";
    button.title = error.message;
    button.disabled = false;
  }
}

byId("analytics-group").addEventListener("change", renderAnalyticsGroup);
byId("review-filter").addEventListener("change", renderBookmarks);

async function renderTasks() {
  const container = byId("task-list");
  container.replaceChildren(node("p", "正在读取计划…"));
  try {
    const all = await api("/api/tasks");
    const items = all.filter((item) => taskFilter === "all" || (taskFilter === "done" ? item.done : !item.done));
    container.replaceChildren(node("p", "已完成 " + all.filter((item) => item.done).length + " / " + all.length + " 项", "hint"));
    if (!items.length) container.append(node("p", "暂无符合筛选条件的计划。", "panel report-panel"));
    const today = new Date();
    const localDate = [today.getFullYear(), String(today.getMonth() + 1).padStart(2, "0"),
      String(today.getDate()).padStart(2, "0")].join("-");
    for (const item of items) {
      const row = node("div", null, "panel record-row");
      const info = node("div");
      info.append(node("strong", item.title), node("p",
        (roles.get(item.role) || item.role) + " · " + (item.due_date || "未设置日期") +
        (!item.done && item.due_date && item.due_date < localDate ? " · 已逾期" : ""), "hint"));
      const actions = node("div", null, "button-row");
      const toggle = node("button", item.done ? "恢复待办" : "标记完成", "button secondary");
      toggle.type = "button";
      toggle.addEventListener("click", async () => {
        toggle.disabled = true;
        try {
          await api("/api/tasks/" + item.id, "PATCH", {done: !item.done});
          await renderTasks();
        } catch (error) {
          toggle.disabled = false;
          window.alert(error.message);
        }
      });
      const remove = node("button", "删除", "text-button danger");
      remove.type = "button";
      remove.addEventListener("click", async () => {
        if (!window.confirm("删除这项计划？")) return;
        remove.disabled = true;
        try {
          await api("/api/tasks/" + item.id, "DELETE");
          await renderTasks();
        } catch (error) {
          remove.disabled = false;
          window.alert(error.message);
        }
      });
      actions.append(toggle, remove);
      row.append(info, actions);
      container.append(row);
    }
  } catch (error) {
    container.replaceChildren(node("p", error.message, "form-error"));
  }
}

byId("task-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form));
  withButton(event.submitter, "task-error", async () => {
    await api("/api/tasks", "POST", data);
    byId("task-title").value = "";
    await renderTasks();
  });
});

document.querySelectorAll("[data-task-filter]").forEach((button) => {
  button.addEventListener("click", () => {
    taskFilter = button.dataset.taskFilter;
    document.querySelectorAll("[data-task-filter]").forEach((item) => {
      item.setAttribute("aria-pressed", String(item === button));
    });
    renderTasks();
  });
});

window.addEventListener("career-ready", () => {
  populateFeatureRoles();
  renderFeaturePage(location.hash.slice(1).split("/")[0]);
});
populateFeatureRoles();
renderFeaturePage(location.hash.slice(1).split("/")[0]);

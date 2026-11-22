// 网页只负责收集输入和展示结果；实际工具、记忆和模型都在后端。
const $ = id => document.getElementById(id);
let sessionId = localStorage.getItem("research-session") || crypto.randomUUID();
let state = null;
let editingPaperId = "";
let busy = false;

async function api(path, method = "GET", body) {
  const response = await fetch(path, { method, headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "输入格式无效，请检查字段。");
  return data;
}

function text(parent, content, className = "") {
  const node = document.createElement("p");
  node.textContent = content;
  node.className = className;
  parent.append(node);
  return node;
}

// 防止上一条还未完成时重复发送或切换会话。
async function run(task) {
  if (busy) return;
  busy = true;
  const controls = [...document.querySelectorAll("button,input,textarea,select")];
  controls.forEach(node => node.disabled = true);
  try { await task(); }
  catch (error) { $("status").textContent = error.message; }
  finally { busy = false; controls.forEach(node => node.disabled = false); }
}

function showState(data) {
  state = data;
  $("session-id").textContent = `当前会话：${sessionId}`;
  for (const key of ["direction", "claim", "weeks", "compute", "dataset"]) $(key).value = state.facts[key] ?? "";
  $("messages").replaceChildren();
  for (const message of state.messages) text($("messages"), `${message.role === "user" ? "你" : "助手"}：${message.content}`, `message ${message.role}`);
  $("messages").scrollTop = $("messages").scrollHeight;
  $("evidence").replaceChildren();
  for (const row of state.evidence.rows || []) {
    text($("evidence"), `${row.title} · ${row.year || "年份未提供"}`);
    text($("evidence"), row.excerpt, "muted");
  }
  for (const gap of state.evidence.gaps || []) text($("evidence"), gap, "muted");
  $("trace").textContent = JSON.stringify(state.trace, null, 2);
  $("skill").value = state.skill || "research-dialogue";
  $("dialogue").replaceChildren();
  if (state.dialogue?.question) {
    text($("dialogue"), "当前问题：" + state.dialogue.question, "question");
    const options = document.createElement("div"); options.className = "option-cards";
    options.setAttribute("role", "group"); options.setAttribute("aria-label", "本轮选项");
    for (const option of state.dialogue.options) {
      const button = document.createElement("button"); button.type = "button";
      button.className = "option-card"; button.textContent = option.label;
      button.onclick = () => run(() => sendMessage(option.label, option.id));
      options.append(button);
    }
    $("dialogue").append(options);
  }
}

async function loadSkills() {
  $("skill").replaceChildren();
  for (const skill of await api("/api/skills")) {
    const option = document.createElement("option"); option.value = skill.id; option.textContent = skill.name;
    $("skill").append(option);
  }
}

async function loadSession() {
  showState(await api(`/api/sessions/${encodeURIComponent(sessionId)}`));
  localStorage.setItem("research-session", sessionId);
  $("status").textContent = "";
}

async function loadSessions() {
  const items = await api("/api/sessions");
  $("sessions").replaceChildren();
  if (!items.some(item => item.session_id === sessionId)) items.unshift({ session_id: sessionId, title: "新讨论" });
  for (const item of items) {
    const option = document.createElement("option");
    option.value = item.session_id; option.textContent = item.title;
    option.selected = item.session_id === sessionId; $("sessions").append(option);
  }
}

function paperButton(parent, label, task) {
  const button = document.createElement("button");
  button.textContent = label; button.className = "secondary";
  button.addEventListener("click", () => run(task)); parent.append(button);
}

async function loadLibrary() {
  $("library").replaceChildren();
  for (const paper of await api(`/api/library?q=${encodeURIComponent($("paper-search").value.trim())}`)) {
    const card = document.createElement("article"); card.className = "paper";
    text(card, paper.title);
    if (paper.notes) text(card, "笔记：" + paper.notes, "muted");
    paperButton(card, "编辑", async () => {
      const saved = await api(`/api/library/papers/${encodeURIComponent(paper.paper_id)}`);
      editingPaperId = saved.paper_id;
      for (const key of ["title", "year", "doi", "abstract", "notes"]) $("paper-" + key).value = saved[key] ?? "";
      $("paper-form").closest("details").open = true;
    });
    paperButton(card, "删除", async () => {
      await api(`/api/library/papers/${encodeURIComponent(paper.paper_id)}`, "DELETE");
      await loadLibrary(); $("status").textContent = "论文已删除；下次发送时重新整理材料。";
    });
    $("library").append(card);
  }
}

async function sendMessage(message, choiceId = null) {
    const facts = {};
    for (const key of ["direction", "claim", "compute", "weeks", "dataset"]) {
      const raw = $(key).value.trim();
      const value = raw ? (key === "weeks" ? Number(raw) : raw) : null;
      if (value !== (state.facts[key] ?? null)) facts[key] = value;
    }
    $("status").textContent = "正在执行工具和对话…";
    const data = await api("/api/chat", "POST", { session_id: sessionId, message,
      facts, search: $("search").value.trim() || null, use_model: $("use-model").checked,
      skill: $("skill").value, choice_id: choiceId });
    showState(data.state); await loadSessions();
    $("message").value = ""; $("search").value = "";
    $("status").textContent = `已保存 · 完整记录 ${data.state.messages.length} 条 · 模型近期上下文 ${data.state.history.length} 条`;
}
$("chat-form").addEventListener("submit", event => {
  event.preventDefault();
  run(() => sendMessage($("message").value.trim()));
});
$("new-session").onclick = () => run(async () => { sessionId = crypto.randomUUID(); await loadSession(); await loadSessions(); });
$("sessions").onchange = () => run(async () => { sessionId = $("sessions").value; await loadSession(); });
$("delete-session").onclick = () => run(async () => {
  await api(`/api/sessions/${encodeURIComponent(sessionId)}`, "DELETE");
  sessionId = crypto.randomUUID(); await loadSession(); await loadSessions();
});
$("paper-form").onsubmit = event => {
  event.preventDefault();
  run(async () => {
    const path = editingPaperId ? `/api/library/papers/${encodeURIComponent(editingPaperId)}` : "/api/library/papers";
    await api(path, editingPaperId ? "PUT" : "POST", { paper_id: editingPaperId, title: $("paper-title").value.trim(),
      year: $("paper-year").value ? Number($("paper-year").value) : null,
      doi: $("paper-doi").value.trim(), abstract: $("paper-abstract").value.trim(), notes: $("paper-notes").value.trim() });
    editingPaperId = ""; $("paper-form").reset(); await loadLibrary();
    $("status").textContent = "论文已保存；下次发送时重新整理材料。";
  });
};
$("paper-reset").onclick = () => { editingPaperId = ""; $("paper-form").reset(); };
$("import-papers").onchange = () => run(async () => {
  const file = $("import-papers").files[0]; if (!file) return;
  if (file.size > 5 * 1024 * 1024) throw new Error("论文 JSON 不能超过5MB");
  const data = JSON.parse(await file.text()); const papers = Array.isArray(data) ? data : data.papers;
  if (!Array.isArray(papers)) throw new Error("JSON 必须是论文列表，或包含 papers 列表的对象。");
  await api("/api/library/import", "POST", papers);
  await loadLibrary(); $("import-papers").value = ""; $("status").textContent = "材料已导入。";
});
$("find-papers").onclick = () => run(loadLibrary);
run(async () => {
  const health = await api("/api/health");
  $("health").textContent = health.model_configured ? "后端已连接 · 模型配置已填写（未验证连通性）" : "后端已连接 · 暂未配置模型";
  await loadSkills(); await loadSession(); await loadSessions(); await loadLibrary();
});

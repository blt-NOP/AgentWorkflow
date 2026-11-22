// 网页只负责收集输入和展示结果；实际工具、记忆和模型都在后端。
const $ = id => document.getElementById(id);
let sessionId = localStorage.getItem("research-session") || crypto.randomUUID();
let state = null;
let editingPaperId = "";
let parsedPaperId = "";
let busy = false;
let chatTimeoutMs = 180000, streamIdleMs = 45000;
const requests = new Map(); // 请求固定归属原会话；切换页面不会改变它。

function latestRequest(id = sessionId) {
  return [...requests.values()].reverse().find(request => request.session_id === id);
}

function refreshChatControls() {
  const pending = latestRequest()?.running;
  document.querySelectorAll("#chat-form button,#chat-form input,#chat-form textarea,#dialogue button,#direction,#claim,#weeks,#compute,#dataset,#skill,#use-model").forEach(node => node.disabled = busy || !!pending);
  $("delete-session").disabled = busy || !!pending;
  $("retry-chat").disabled = busy || !!pending;
}

async function api(path, method = "GET", body) {
  const multipart = body instanceof FormData;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30000);
  try {
    const response = await fetch(path, { method, headers: multipart ? {} : { "Content-Type": "application/json" },
      signal: controller.signal, body: multipart ? body : body === undefined ? undefined : JSON.stringify(body) });
    const data = await response.json();
    if (!response.ok) {
      const message = typeof data.detail === "string" ? data.detail : data.detail?.message || "输入格式无效，请检查字段。";
      throw new Error(message + (data.detail?.request_id ? `（请求 ${data.detail.request_id}）` : ""));
    }
    return data;
  } catch (error) {
    if (controller.signal.aborted) throw new Error("接口等待超过30秒，已停止等待；请检查后端后重试。");
    throw error;
  } finally { clearTimeout(timer); }
}

function text(parent, content, className = "") {
  const node = document.createElement("p");
  node.textContent = content;
  node.className = className;
  parent.append(node);
  return node;
}

// 普通短操作互斥；聊天单独按会话锁定，执行中允许新建/切换其他会话。
async function run(task) {
  if (busy) return;
  busy = true;
  const controls = [...document.querySelectorAll("button,input,textarea,select")];
  controls.forEach(node => node.disabled = true);
  try { await task(); }
  catch (error) { $("status").textContent = error.message; }
  finally { busy = false; controls.forEach(node => node.disabled = false); refreshChatControls(); }
}

function showState(data) {
  state = data;
  $("session-id").textContent = `当前会话：${sessionId}`;
  for (const key of ["direction", "claim", "weeks", "compute", "dataset"]) $(key).value = state.facts[key] ?? "";
  $("messages").replaceChildren();
  for (const message of state.messages) {
    const content = message.role === "assistant" ? message.content.replace(/^\[未调用模型\]\s*/, "") : message.content;
    text($("messages"), `${message.role === "user" ? "你" : "助手"}：${content}`, `message ${message.role}`);
  }
  $("messages").scrollTop = $("messages").scrollHeight;
  $("evidence").replaceChildren();
  for (const row of state.evidence.rows || []) {
    text($("evidence"), `${row.title} · ${row.year || "年份未提供"}`);
    text($("evidence"), row.excerpt, "muted");
  }
  for (const gap of state.evidence.gaps || []) text($("evidence"), gap, "muted");
  $("trace").textContent = JSON.stringify(state.trace, null, 2);
  const labels = { WAITING_USER: "等待补充或继续讨论", COMPLETED: "研究方案已完成", STOPPED: "本轮已停止" };
  $("execution-status").textContent = `${labels[state.status] || "尚未执行"}${state.request_id ? " · 请求 " + state.request_id : ""}${state.stop_reason ? " · " + state.stop_reason : ""}`;
  $("proposal").replaceChildren();
  if (state.proposal) {
    const fields = {research_question: "研究问题", hypothesis: "待验证假设", method: "方法路线", experiment: "实验设计", metrics: "评价指标", risks: "风险", next_steps: "下一步", references: "证据标识"};
    for (const [key, label] of Object.entries(fields)) text($("proposal"), `${label}：${Array.isArray(state.proposal[key]) ? state.proposal[key].join("；") : state.proposal[key]}`);
  }
  $("skill").value = state.skill || "research-dialogue";
  $("dialogue").replaceChildren();
  if (state.dialogue?.question) {
    text($("dialogue"), "当前问题：" + state.dialogue.question, "question");
    const options = document.createElement("div"); options.className = "option-cards";
    options.setAttribute("role", "group"); options.setAttribute("aria-label", "本轮选项");
    for (const option of state.dialogue.options) {
      const button = document.createElement("button"); button.type = "button";
      button.className = "option-card"; button.textContent = option.label;
      button.onclick = () => submitChat(option.label, option.id);
      options.append(button);
    }
    $("dialogue").append(options);
  }
  const request = latestRequest();
  if (request) renderRequest(request);
  else { $("progress").replaceChildren(); $("stream-preview").hidden = true; $("retry-chat").hidden = true; }
  refreshChatControls();
}

function renderRequest(request) {
  if (request.session_id !== sessionId || latestRequest()?.request_id !== request.request_id) return;
  $("progress").replaceChildren();
  $("retry-chat").hidden = !request.error || request.running;
  for (const item of request.progress) {
    const row = document.createElement("li"); row.textContent = item; $("progress").append(row);
  }
  $("progress").scrollTop = $("progress").scrollHeight;
  $("stream-preview").hidden = !request.running || !request.draft;
  $("stream-text").textContent = request.draft;
  $("stream-caption").textContent = request.ready ? "回复已校验，正在保存结果…" : "正在生成回复草稿，最终结果以校验完成后为准…";
  if (request.running) {
    for (const key of ["direction", "claim", "weeks", "compute", "dataset"]) $(key).value = request.facts[key] ?? "";
    $("execution-status").textContent = `正在执行 · 请求 ${request.request_id}`;
    $("status").textContent = request.progress.at(-1) || "正在连接…";
  } else if (request.error) {
    $("status").textContent = `${request.error}（请求 ${request.request_id}）`;
    $("execution-status").textContent = `本轮未成功 · 请求 ${request.request_id}`;
  }
}

function receiveEvent(request, event) {
  const data = event.data;
  const tools = {search_papers: "论文检索", build_evidence: "材料整理", research_dialogue: "交互追问"};
  const name = tools[data.tool] || data.tool;
  const lines = {
    started: "开始执行", model_started: `第 ${data.step} 次模型决策`,
    model_result: data.tool_names?.length ? "模型已选择下一步工具" : "模型回复已到达，正在校验",
    tool_started: `正在执行：${name}`, tool_result: `${name}已返回${data.duration_ms === undefined ? "" : `（${data.duration_ms} ms）`}`,
    tool_failed: `${name}失败，正在检查后续处理`, reply_ready: "回复校验通过，正在保存",
    completed: data.status === "COMPLETED" ? "研究方案已完成并保存" : data.status === "STOPPED" ? "达到执行上限，本轮已停止并保存" : "本轮已保存，等待补充",
    failed: `执行失败：${data.message}`
  };
  if (lines[event.type]) request.progress.push(lines[event.type]);
  if (event.type === "reply_reset") { request.draft = ""; request.ready = false; }
  if (event.type === "reply_delta") request.draft += data.text;
  if (event.type === "reply_ready") { request.draft = data.reply; request.ready = true; }
  if (event.type === "failed") { request.running = false; request.error = data.message; request.draft = ""; }
  if (event.type === "completed") {
    request.running = false; request.result = data; request.draft = "";
    if (sessionId === request.session_id && latestRequest()?.request_id === request.request_id) showState(data.state);
  }
  renderRequest(request); refreshChatControls();
}

async function loadSkills() {
  $("skill").replaceChildren();
  for (const skill of await api("/api/skills")) {
    const option = document.createElement("option"); option.value = skill.id; option.textContent = skill.name;
    $("skill").append(option);
  }
}

async function loadSession() {
  const target = sessionId;
  const loaded = await api(`/api/sessions/${encodeURIComponent(target)}`);
  if (sessionId !== target) return; // 晚到的会话读取也不能覆盖切换后的页面。
  if (loaded.session_id !== target) throw new Error("会话读取结果归属不匹配。");
  showState(loaded);
  localStorage.setItem("research-session", sessionId);
  $("status").textContent = "";
  if (latestRequest()) renderRequest(latestRequest());
  $("message").value = latestRequest()?.running ? latestRequest().inputMessage : "";
  $("search").value = latestRequest()?.running ? latestRequest().inputSearch : "";
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
      parsedPaperId = "";
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

async function sendMessage(message, choiceId = null, retryPayload = null, previousIds = []) {
    if (latestRequest()?.running) return; // 同一会话不重复提交。
    const facts = {};
    for (const key of ["direction", "claim", "compute", "weeks", "dataset"]) {
      const raw = $(key).value.trim();
      const value = raw ? (key === "weeks" ? Number(raw) : raw) : null;
      if (value !== (state.facts[key] ?? null)) facts[key] = value;
    }
    const payload = {...(retryPayload || {session_id: sessionId, message,
      facts, search: $("search").value.trim() || null, use_model: $("use-model").checked, skill: $("skill").value, choice_id: choiceId}), request_id: crypto.randomUUID()};
    const request = {request_id: payload.request_id, session_id: payload.session_id, running: true, progress: [], draft: "", ready: false,
      facts: {...state.facts, ...payload.facts}, payload, previousIds, inputMessage: $("message").value, inputSearch: $("search").value};
    const inputMessage = $("message").value, inputSearch = $("search").value;
    requests.set(request.request_id, request); refreshChatControls(); renderRequest(request);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), chatTimeoutMs);
    try {
      const response = await fetch("/api/chat/stream", {method: "POST", signal: controller.signal, headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
      if (!response.ok) {
        const data = await response.json();
        throw new Error(typeof data.detail === "string" ? data.detail : data.detail?.message || "请求无效，请检查输入。");
      }
      await ResearchStream.read(response, request, event => receiveEvent(request, event), streamIdleMs);
      clearTimeout(timer);
      if (request.error) throw new Error(request.error);
      await loadSessions();
      if (sessionId === request.session_id && latestRequest()?.request_id === request.request_id) {
        if ($("message").value === inputMessage) $("message").value = "";
        if ($("search").value === inputSearch) $("search").value = "";
        $("status").textContent = `${request.result.status} · 请求 ${request.request_id} · 结果已保存`;
      }
    } catch (error) {
      request.error = controller.signal.aborted ? `本轮等待超过 ${chatTimeoutMs / 1000} 秒，已停止等待。后端可能仍在执行，请点击重试核对原会话。` : error.message;
      request.draft = "";
    } finally { clearTimeout(timer); controller.abort(); request.running = false; renderRequest(request); refreshChatControls(); }
}

$("retry-chat").onclick = async () => {
  if (busy) return;
  const failed = latestRequest();
  if (!failed?.error || failed.running) return;
  const originalSession = failed.session_id;
  let retry = false;
  await run(async () => {
    const saved = await api(`/api/sessions/${encodeURIComponent(originalSession)}`);
    if (sessionId !== originalSession || latestRequest() !== failed) return;
    if (saved.session_id !== originalSession) throw new Error("会话读取结果归属不匹配。");
    // 超时不代表后端失败：已保存则直接恢复，避免重复消息和模型消耗。
    if ([failed.request_id, ...failed.previousIds].includes(saved.request_id)) {
      failed.error = null; failed.result = {state: saved};
      failed.progress.push("原请求已保存，已恢复结果，无需重复执行");
      showState(saved); $("status").textContent = "已恢复原请求的结果。";
      if ($("message").value === failed.inputMessage) $("message").value = "";
      if ($("search").value === failed.inputSearch) $("search").value = "";
      return;
    }
    retry = true;
  });
  if (retry && sessionId === originalSession && latestRequest() === failed)
    await sendMessage(failed.payload.message, failed.payload.choice_id, failed.payload, [...failed.previousIds, failed.request_id]);
};

async function submitChat(message, choiceId = null) {
  if (busy || latestRequest()?.running) return;
  if (!message.trim()) { $("status").textContent = "请输入本轮消息。"; return; }
  await sendMessage(message, choiceId);
}
$("chat-form").addEventListener("submit", event => {
  event.preventDefault();
  submitChat($("message").value.trim());
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
    await api(path, editingPaperId ? "PUT" : "POST", { paper_id: editingPaperId || parsedPaperId, title: $("paper-title").value.trim(),
      year: $("paper-year").value ? Number($("paper-year").value) : null,
      doi: $("paper-doi").value.trim(), abstract: $("paper-abstract").value.trim(), notes: $("paper-notes").value.trim() });
    editingPaperId = ""; parsedPaperId = ""; $("paper-form").reset(); await loadLibrary();
    $("status").textContent = "论文已保存；下次发送时重新整理材料。";
  });
};
$("paper-reset").onclick = () => { editingPaperId = ""; parsedPaperId = ""; $("paper-form").reset(); };
$("parse-pdf").onclick = () => run(async () => {
  const file = $("paper-pdf").files[0];
  if (!file) throw new Error("请先选择 PDF 文件。");
  if (file.size > 20 * 1024 * 1024) throw new Error("PDF 不能超过20 MiB，请拆分文件。");
  const form = new FormData(); form.append("file", file);
  form.append("start_page", $("pdf-start").value || "1");
  if ($("pdf-end").value) form.append("end_page", $("pdf-end").value);
  $("pdf-status").textContent = "正在解析 PDF…";
  try {
    const data = await api("/api/tools/parse-pdf", "POST", form);
    editingPaperId = ""; parsedPaperId = data.paper.paper_id;
    for (const key of ["title", "year", "doi", "abstract", "notes"]) $("paper-" + key).value = data.paper[key] ?? "";
    $("paper-form").closest("details").open = true;
    $("pdf-status").textContent = `已提取第 ${data.start_page}—${data.end_page} 页，共 ${data.total_pages} 页。${data.warnings.join(" ")} 请核对后保存论文。`;
  } catch (error) {
    $("pdf-status").textContent = error.message;
    throw error;
  }
});
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
  chatTimeoutMs = health.chat_timeout_seconds * 1000 || chatTimeoutMs;
  streamIdleMs = health.stream_idle_seconds * 1000 || streamIdleMs;
  $("use-model").checked = health.model_enabled;
  $("health").textContent = health.model_configured ? "后端已连接 · 模型配置已填写（未验证连通性）" : "后端已连接 · 暂未配置模型";
  await loadSkills(); await loadSession(); await loadSessions(); await loadLibrary();
});

"use strict";

const healthLabel = document.querySelector("#health");
const messages = document.querySelector("#messages");
const sessionLabel = document.querySelector("#session-label");
const input = document.querySelector("#message");
const sendButton = document.querySelector("#send");
const newSessionButton = document.querySelector("#new-session");
let sessionId;

function startSession() {
  sessionId = crypto.randomUUID();
  sessionLabel.textContent = `讨论编号：${sessionId}`;
  messages.replaceChildren();
  input.value = "";
}

function appendMessage(text, kind) {
  const paragraph = document.createElement("p");
  paragraph.className = `message ${kind}`;
  paragraph.textContent = text;
  messages.append(paragraph);
  messages.scrollTop = messages.scrollHeight;
}

async function checkHealth() {
  try {
    const response = await fetch("/api/health");
    if (!response.ok) throw new Error("health check failed");
    const data = await response.json();
    healthLabel.textContent = `后端已连接 · ${data.model_configured ? "模型配置已填写（未验证连通性）" : "模型配置未填写"}`;
  } catch {
    healthLabel.textContent = "后端未连接，请检查启动命令并刷新页面。";
  }
}

document.querySelector("#chat-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message || sendButton.disabled) return;
  appendMessage(`你：${message}`, "user");
  sendButton.disabled = true;
  newSessionButton.disabled = true;
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message }),
    });
    const data = await response.json();
    if (!response.ok) {
      const detail = data.detail;
      appendMessage(detail?.message || `请求未完成（HTTP ${response.status}）。`, "system");
      return;
    }
    appendMessage(data.message || "接口尚未提供回复内容。", "system");
    input.value = "";
  } catch {
    appendMessage("请求失败，请确认后端服务仍在运行后重试。", "system");
  } finally {
    sendButton.disabled = false;
    newSessionButton.disabled = false;
  }
});

newSessionButton.addEventListener("click", startSession);
startSession();
checkHealth();

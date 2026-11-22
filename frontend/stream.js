// 无依赖SSE读取器：处理UTF-8分片、事件边界、序号和请求归属。
const ResearchStream = {
  belongsTo(event, request) {
    return event.session_id === request.session_id && event.request_id === request.request_id;
  },
  async read(response, request, receive, idleMs = 45000) {
    if (!response.body) throw new Error("浏览器不支持流式读取。");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "", lastSeq = 0, terminal = false;
    function frame(value) {
      const data = value.split("\n").filter(line => line.startsWith("data:")).map(line => line.slice(5).trimStart()).join("\n");
      if (!data) return; // SSE心跳注释。
      const event = JSON.parse(data);
      if (!ResearchStream.belongsTo(event, request)) throw new Error("响应不属于本次会话或请求。");
      if (event.type === "completed" && (event.data?.request_id !== request.request_id || event.data?.state?.session_id !== request.session_id)) {
        throw new Error("最终结果不属于本次会话或请求。");
      }
      if (event.seq !== lastSeq + 1) throw new Error("事件顺序不完整，请重新打开原会话核对结果。");
      if (terminal) throw new Error("结束事件后收到额外数据。");
      lastSeq = event.seq;
      terminal = event.type === "completed" || event.type === "failed";
      receive(event);
    }
    try {
      while (true) {
        let timer;
        const { value, done } = await Promise.race([reader.read(), new Promise((_, reject) => {
          timer = setTimeout(() => reject(new Error("连接长时间没有数据，已停止等待；请重试核对原会话。")), idleMs);
        })]).finally(() => clearTimeout(timer));
        buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
        buffer = buffer.replace(/\r\n/g, "\n");
        let end;
        while ((end = buffer.indexOf("\n\n")) >= 0) {
          frame(buffer.slice(0, end)); buffer = buffer.slice(end + 2);
        }
        if (buffer.length > 8 * 1024 * 1024) throw new Error("单个事件过大，请重新打开会话查看结果。");
        if (terminal || done) break;
      }
      if (!terminal && buffer.trim()) frame(buffer);
      if (!terminal) throw new Error("连接已中断，尚未收到结束事件；请返回原会话核对是否已保存。");
    } catch (error) {
      await reader.cancel().catch(() => {});
      throw error;
    } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
  }
};
if (typeof module !== "undefined") module.exports = ResearchStream;

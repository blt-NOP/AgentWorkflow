// node tests/check_stream_frontend.js；不需要npm、浏览器或模型。
const assert = require("node:assert/strict");
const stream = require("../frontend/stream.js");
const request = {session_id: "A", request_id: "R"};
const make = (seq, type, data = {}) => ({...request, seq, type, data});
function response(events) {
  const wire = ": heartbeat\r\n\r\n" + events.map(event => `event: ${event.type}\r\ndata: ${JSON.stringify(event)}\r\n\r\n`).join("");
  const bytes = new TextEncoder().encode(wire);
  return new Response(new ReadableStream({start(controller) {
    // 一个字节一段，强制覆盖UTF-8字符与CRLF跨网络块。
    for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
    controller.close();
  }}));
}
(async () => {
  const received = [];
  await stream.read(response([make(1, "started"), make(2, "reply_delta", {text: "多轮😀\n对话"}), make(3, "completed", {request_id: "R", state: {session_id: "A"}})]), request, e => received.push(e));
  assert.equal(received[1].data.text, "多轮😀\n对话");
  console.log("PASS: UTF-8、CRLF、心跳及事件分片正确读取");
  await assert.rejects(stream.read(response([{...make(1, "started"), session_id: "B"}]), request, () => {}), /不属于/);
  console.log("PASS: 会话B的响应不能归入会话A");
  await assert.rejects(stream.read(response([{...make(1, "started"), request_id: "OLD"}]), request, () => {}), /不属于/);
  console.log("PASS: 同会话旧请求不能覆盖新请求");
  await assert.rejects(stream.read(response([make(1, "completed", {request_id: "R", state: {session_id: "B"}})]), request, () => {}), /最终结果不属于/);
  console.log("PASS: 最终状态的会话编号也必须匹配");
  await assert.rejects(stream.read(response([make(2, "started")]), request, () => {}), /顺序/);
  console.log("PASS: 拒绝事件序号缺失或乱序");
  await assert.rejects(stream.read(response([make(1, "started")]), request, () => {}), /中断/);
  console.log("PASS: 缺少结束事件时不误判成功");
  const failed = [];
  await stream.read(response([make(1, "started"), make(2, "failed", {message: "失败"})]), request, e => failed.push(e));
  assert.equal(failed.at(-1).type, "failed");
  console.log("PASS: 失败事件正常结束读取并交给页面处理");
  let cancelled = false;
  const stalled = new Response(new ReadableStream({cancel() { cancelled = true; }}));
  await assert.rejects(stream.read(stalled, request, () => {}, 20), /长时间没有数据/);
  assert.ok(cancelled);
  console.log("PASS: 无数据连接超时并取消读取，不无限等待");
  console.log("RESULT: PASS (8 checks)");
})().catch(error => { console.error(error); process.exitCode = 1; });

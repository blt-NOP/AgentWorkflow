"""真实HTTP事件验收；模型边界明确使用SSE替身，不调用前端或云模型。"""
import json
import os
from pathlib import Path
import socket
import sys
from threading import Event, Thread
import time
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / "data/model-check" / ("events-" + uuid4().hex[:8])
os.environ["DATA_DIR"] = str(OUTPUT)

import httpx
import uvicorn
from backend import memory, model, tools
from backend.main import app
from backend.tool_contracts import ToolError
from backend.events import reply_prefix

checks = []


def check(value, label):
    if not value:
        raise AssertionError(label)
    checks.append(label)
    print("PASS: " + label, flush=True)


def parse_events(response):
    for line in response.iter_lines():
        if line.startswith("data:"):
            yield json.loads(line[5:])


def provider(chunks, finish="stop"):
    records = [{"id": "synthetic-provider-id", "model": "explicit-sse-fixture", "choices": [
        {"index": 0, "delta": delta, "finish_reason": None}]} for delta in chunks]
    records += [{"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
                {"choices": [], "usage": {"total_tokens": 10}}]
    return "".join("data: " + json.dumps(item) + "\n\n" for item in records) + "data: [DONE]\n\n"


def final_chunks(reply, status="WAITING_USER", proposal=None):
    content = json.dumps({"status": status, "reply": reply, "proposal": proposal}, ensure_ascii=True)
    return [{"reasoning_content": "PRIVATE_REASONING_FIXTURE"}] + [{"content": content[i:i + 11]} for i in range(0, len(content), 11)]


def main():
    # 绑定系统分配端口，使用真实Uvicorn/HTTP连接验证不缓冲到任务结束。
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
    thread = Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 8
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    base = "http://127.0.0.1:" + str(sock.getsockname()[1])
    real_client = httpx.Client
    with real_client(base_url=base, timeout=10) as client:
        def request(name, session="A", **changes):
            payload = {"session_id": session, "request_id": name, "message": "继续讨论", "use_model": False, **changes}
            with client.stream("POST", "/api/chat/stream", json=payload) as response:
                check(response.status_code == 200 and "text/event-stream" in response.headers["content-type"], name + " 返回SSE")
                events = list(parse_events(response))
            memory.write_json(OUTPUT / f"{name}.json", {"arguments": payload, "events": events})
            check([e["seq"] for e in events] == list(range(1, len(events) + 1)) and
                  all(e["request_id"] == name and e["session_id"] == session for e in events), name + " 序号连续且归属一致")
            return events

        gate = Event()
        actual_build = tools.TOOL_REGISTRY["build_evidence"]
        def blocked(**arguments):
            assert gate.wait(5), "客户端应在工具结束前收到事件并释放测试门闩"
            return actual_build(**arguments)
        payload = {"session_id": "A", "request_id": "Gate", "message": "登记条件", "use_model": False,
                   "facts": {"direction": "模型压缩", "compute": "GPU", "weeks": 4, "dataset": "公开数据集"}}
        with patch.dict(tools.TOOL_REGISTRY, {"build_evidence": blocked}):
            with client.stream("POST", "/api/chat/stream", json=payload) as response:
                iterator = parse_events(response)
                first, second = next(iterator), next(iterator)
                check(first["type"] == "started" and second["type"] == "tool_started" and not gate.is_set(),
                      "工具尚未结束就收到开始/处理中事件，证明真实HTTP增量传输")
                gate.set()
                events = [first, second, *iterator]
        memory.write_json(OUTPUT / "Gate.json", {"arguments": payload, "events": events})
        check(events[-1]["type"] == "completed" and events[-1]["data"]["state"] == memory.load("A"),
              "最终事件交付已保存状态，页面结果可与磁盘核对")
        check([e["type"] for e in events] == ["started", "tool_started", "tool_result", "tool_started", "tool_result", "reply_ready", "completed"],
              "离线主任务的事件顺序完整")
        changed = request("Correction", facts={"compute": "CPU"})
        check(next(e for e in changed if e["type"] == "tool_result")["data"]["result"]["facts"]["compute"] == "CPU", "同会话更正后工具结果采用CPU")
        other = request("Isolation", session="B")
        check(other[-1]["data"]["state"]["facts"] == {} and client.get("/api/sessions/A").json()["facts"]["compute"] == "CPU", "切换A/B不会混入约束，返回A仍保留CPU")
        with patch.dict(tools.TOOL_REGISTRY, {"search_papers": lambda **kwargs: (_ for _ in ()).throw(ToolError("TIMEOUT", "测试检索超时", True))}):
            failed = request("ToolFault", session="Recovery", search="explicit-fault")
        check(failed[-1]["type"] == "failed" and failed[-1]["data"]["code"] == "TIMEOUT"
              and "tool_failed" in [e["type"] for e in failed] and not memory.session_path("Recovery").exists(),
              "工具失败有事件、清除草稿、不交付成功且不写半完成会话")
        check(request("Recovered", session="Recovery")[-1]["type"] == "completed", "故障恢复后同会话可再次成功")
        invalid = client.post("/api/chat/stream", json={"session_id": "A", "message": ""})
        check(invalid.status_code == 422 and invalid.json()["detail"]["code"] == "INVALID_INPUT", "无效输入在建流前返回422")

        native = provider([{"tool_calls": [{"index": 0, "id": "fixture-call", "function": {"name": "research_", "arguments": "{"}}]},
                           {"tool_calls": [{"index": 0, "function": {"name": "dialogue", "arguments": "}"}}]}], "tool_calls")
        sequences = [native, provider(final_chunks("第一段\n第二段😀"))]
        sent = []
        def respond(request):
            body = json.loads(request.content)
            assert body["stream"] and body["stream_options"]["include_usage"]
            sent.append(body)
            return httpx.Response(200, content=sequences.pop(0), headers={"Content-Type": "text/event-stream"})
        with patch.object(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(respond))):
            streamed = request("ModelStream", session="Model", use_model=True, facts={"direction": "模型压缩"})
        deltas = [e["data"]["text"] for e in streamed if e["type"] == "reply_delta"]
        check(len(deltas) >= 2 and "".join(deltas) == "第一段\n第二段😀", "真实模型协议分片转换为增量正文，正确处理换行与Unicode转义")
        check(sent[1]["messages"][-1]["role"] == "tool" and sent[1]["messages"][-1]["tool_call_id"] == "fixture-call", "流式工具名/参数重组后执行并回传同一调用ID")
        check("PRIVATE_REASONING_FIXTURE" not in json.dumps(streamed) and streamed[-1]["data"]["reply"] == "第一段\n第二段😀", "只发送正文草稿，不暴露私有推理，最终正文一致")

        state = memory.load("Complete")
        state["facts"] = {"direction": "模型压缩", "compute": "CPU", "weeks": 4, "dataset": "公开数据集"}
        state["answers"] = {"goal": "推理延迟", "baseline": "已有可复现基线"}
        state["papers"] = [{"title": "Synthetic event fixture", "doi": "10.0000/event-fixture", "abstract": "Synthetic test excerpt, not a real paper."}]
        memory.write_json(memory.session_path("Complete"), state)
        proposal = {key: "Synthetic " + key for key in ("research_question", "hypothesis", "method", "experiment", "metrics", "risks", "next_steps")}
        proposal["references"] = ["10.0000/event-fixture"]
        sequences[:] = [provider([{"tool_calls": [{"index": 0, "id": "complete-call", "function": {"name": "build_evidence", "arguments": "{}"}}]}], "tool_calls"),
                        provider(final_chunks("完整方案已生成", "COMPLETED", proposal))]
        with patch.object(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(respond))):
            completed = request("ModelComplete", session="Complete", use_model=True)
        check(completed[-1]["data"]["status"] == "COMPLETED" and completed[-1]["data"]["proposal"] == proposal
              and memory.load("Complete")["proposal"] == proposal, "完整研究方案通过守卫并保存后，作为结构化结果交付")

        # 模型先返回不合法的完成结果；页面必须收到清除草稿，再显示修正后回复。
        sequences[:] = [provider(final_chunks("错误草稿", "COMPLETED")), provider(final_chunks("已修正，请补充条件"))]
        with patch.object(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(respond))):
            corrected = request("RejectedDraft", session="Draft", use_model=True)
        rejected_index = next(i for i, e in enumerate(corrected) if e["type"] == "reply_reset" and e["data"]["reason"] == "VALIDATION_REJECTED")
        check(any(e["type"] == "reply_delta" for e in corrected[:rejected_index]) and corrected[-1]["data"]["reply"] == "已修正，请补充条件",
              "校验失败会撤销已展示草稿，修正结果才作为最终回复")
        check("错误草稿" not in memory.load("Draft")["messages"][-1]["content"], "未通过校验的草稿不进入正式聊天历史")

        class Interrupted(httpx.SyncByteStream):
            def __iter__(self):
                chunk = {"choices": [{"index": 0, "delta": {"content": '{"reply":"旧草稿'}, "finish_reason": None}]}
                yield ("data: " + json.dumps(chunk) + "\n\n").encode()
                raise httpx.ReadTimeout("explicit interrupted stream")
        attempts = []
        def interrupted(request):
            attempts.append(1)
            if len(attempts) == 1:
                return httpx.Response(200, stream=Interrupted(), headers={"Content-Type": "text/event-stream"})
            return httpx.Response(200, content=provider(final_chunks("重试成功")), headers={"Content-Type": "text/event-stream"})
        with patch.dict(os.environ, {"MODEL_RETRIES": "1"}), patch.object(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(interrupted))):
            retried = request("StreamRetry", session="Retry", use_model=True)
        check(len(attempts) == 2 and retried[-1]["data"]["reply"] == "重试成功"
              and sum(e["type"] == "reply_reset" and e["data"]["reason"] == "MODEL_ATTEMPT" for e in retried) == 2,
              "流中断后有限重试，清除旧草稿避免重复拼接")
        check(reply_prefix('{"reply":"\\u4f60\\u597d\\ud83d') == "你好" and reply_prefix('{"reply":"\\u4f60\\u597d\\ud83d\\ude00"}') == "你好😀", "不完整Unicode代理对等待后续字节")

    server.should_exit = True
    thread.join(timeout=5)
    memory.write_json(OUTPUT / "summary.json", {"result": "PASS", "count": len(checks), "checks": checks,
        "real_model_calls": 0, "transport": "real local HTTP + explicit upstream SSE fixtures", "artifacts": str(OUTPUT)})
    print(f"RESULT: PASS ({len(checks)} checks); real model calls=0")
    print("ARTIFACTS: " + str(OUTPUT))


if __name__ == "__main__":
    main()

"""命令行恢复验收：故障→原状态保留→恢复依赖→同会话成功；不调用云模型。"""
import json
import os
from pathlib import Path
import sys
from threading import Event, Thread
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / "data/model-check" / ("recovery-" + uuid4().hex[:8])
os.environ["DATA_DIR"] = str(OUTPUT)

from fastapi.testclient import TestClient
from backend import memory, tools
from backend.main import app
from backend.tool_contracts import ToolError


def main():
    records, checks = [], []
    client = TestClient(app)

    def check(value, label):
        assert value, label
        checks.append(label)
        print("PASS: " + label)

    def turn(request, **changes):
        payload = {"session_id": "RecoveryA", "request_id": request, "message": "根据当前条件继续", "use_model": False, **changes}
        response = client.post("/api/chat/stream", json=payload)
        events = [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:")]
        records.append({"arguments": payload, "events": events})
        return events

    turn("initial", facts={"direction": "模型压缩", "compute": "CPU"})
    before = memory.load("RecoveryA")
    actual = tools.TOOL_REGISTRY["build_evidence"]
    with patch.dict(tools.TOOL_REGISTRY, {"build_evidence": lambda **kw: (_ for _ in ()).throw(
            ToolError("TIMEOUT", "测试注入：依赖超时，恢复后可重试", True))}):
        failed = turn("failure", facts={"compute": "GPU"})
    check(failed[-1]["type"] == "failed" and failed[-1]["data"]["code"] == "TIMEOUT" and
          "依赖超时" in failed[-1]["data"]["message"], "失败结束事件给出可显示原因，不等待completed")
    check(memory.load("RecoveryA") == before, "失败不覆盖原会话事实或历史")
    recovered = turn("recovered", facts={"compute": "GPU"})
    state = memory.load("RecoveryA")
    check(recovered[-1]["type"] == "completed" and state["facts"]["compute"] == "GPU", "恢复依赖后原会话成功并更新条件")
    check(len(state["messages"]) == len(before["messages"]) + 2, "失败没有半条消息，恢复仅追加一轮")

    entered, release = Event(), Event()
    def blocked(**arguments):
        if not entered.is_set():
            entered.set()
            assert release.wait(5)
        return actual(**arguments)
    with patch.dict(tools.TOOL_REGISTRY, {"build_evidence": blocked}):
        worker = Thread(target=lambda: turn("inflight"))
        worker.start()
        assert entered.wait(3)
        try:
            busy = turn("retry-too-early")
            check(busy[-1]["type"] == "failed" and busy[-1]["data"]["code"] == "SESSION_BUSY", "尚在执行时拒绝同会话并发重试")
            other = turn("session-B", session_id="RecoveryB")
            check(other[-1]["type"] == "completed" and not other[-1]["data"]["state"]["facts"], "会话B独立执行且不读取A条件")
        finally:
            release.set()
            worker.join(5)
    check(memory.load("RecoveryA")["request_id"] == "inflight", "原请求完成后保存原会话，未被提前重试覆盖")
    check(turn("after-busy")[-1]["type"] == "completed", "锁释放后原会话可以继续成功交互")
    memory.write_json(OUTPUT / "summary.json", {"result": "PASS", "checks": checks, "records": records,
        "notice": "HTTP/TestClient恢复验收；页面证据另见tests/recovery_results，不把此测试称为浏览器测试。"})
    print(f"RESULT: PASS ({len(checks)} checks)\nARTIFACTS: {OUTPUT}")


if __name__ == "__main__":
    main()

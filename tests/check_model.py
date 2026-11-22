"""模型决策离线验收：明确使用模型/网络替身，不消耗真实额度。"""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / "data/model-check" / ("offline-" + uuid4().hex[:8])
os.environ["DATA_DIR"] = str(OUTPUT)

import httpx
from fastapi.testclient import TestClient
from backend import agent, memory, model, tools
from backend.tool_contracts import ToolError
from backend.main import app

PAPER = {"title": "Synthetic decision fixture", "doi": "10.0000/model-fixture", "year": 2025,
         "abstract": "Synthetic test evidence only: compare latency and memory on a small model."}
FACTS = {"direction": "模型压缩", "compute": "GPU", "weeks": 4, "dataset": "公开数据集"}
PROPOSAL = {key: "Synthetic test " + key for key in
            ("research_question", "hypothesis", "method", "experiment", "metrics", "risks", "next_steps")}
PROPOSAL["references"] = [PAPER["doi"]]
checks = []


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    checks.append(label)
    print("PASS: " + label)


def call(name, arguments=None):
    return {"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": "call-" + uuid4().hex[:8], "type": "function", "function": {
            "name": name, "arguments": json.dumps(arguments or {}, ensure_ascii=False)}}]},
        "usage": {"total_tokens": 10}, "model": "explicit-model-fixture"}


def final(status="WAITING_USER", proposal=None):
    return {"message": {"role": "assistant", "content": json.dumps({
        "status": status, "reply": "明确的教学测试响应，请补充条件或核对方案。", "proposal": proposal}, ensure_ascii=False)},
        "usage": {"total_tokens": 10}, "model": "explicit-model-fixture"}


def seed(session, complete=True):
    state = memory.load(session)
    if complete:
        state["facts"], state["answers"], state["papers"] = deepcopy(FACTS), {"goal": "推理延迟", "baseline": "已有可复现基线"}, [deepcopy(PAPER)]
    memory.write_json(memory.session_path(session), state)
    return state


def scripted(session, sequence, **kwargs):
    requests = []
    iterator = iter(sequence)
    def decision(messages, tools):
        requests.append({"messages": deepcopy(messages), "tools": deepcopy(tools)})
        return next(iterator)
    with patch.object(model, "chat", side_effect=decision):
        result = agent.run_turn(session, "继续当前任务", use_model=True, **kwargs)
    memory.write_json(OUTPUT / f"{session}.json", {"source": "explicit model fixture", "requests": requests, "returned": result})
    return result, requests


def main():
    seed("Chain", False)
    with patch.dict(tools.TOOL_REGISTRY, {"search_papers": lambda **kwargs: [deepcopy(PAPER)]}):
        result, requests = scripted("Chain", [call("search_papers", {"query": "fixture"}),
            call("build_evidence", {"paper_ids": [PAPER["doi"]]}), call("research_dialogue"), final()])
    check([t["tool"] for t in result["trace"]] == ["search_papers", "build_evidence", "research_dialogue"], "模型选择三步工具并执行")
    check(result["trace"][1]["arguments"]["papers"] == [PAPER], "后一步实参来自前一步实际返回")
    for request in requests[1:]:
        tool_messages = [m for m in request["messages"] if m["role"] == "tool"]
        check(bool(tool_messages) and bool(tool_messages[-1]["tool_call_id"]), "工具结果携带对应调用标识回传模型")
    check(result["status"] == "WAITING_USER" and result["dialogue"]["field"] == "direction", "缺条件时追问而不宣布完成")

    seed("Complete")
    result, _ = scripted("Complete", [call("build_evidence"), final("COMPLETED", PROPOSAL)])
    check(result["status"] == "COMPLETED" and result["proposal"]["references"] == [PAPER["doi"]], "真实材料整理后生成完整方案并结束")
    result, _ = scripted("Complete", [call("build_evidence"), final("COMPLETED", PROPOSAL)], facts={"compute": "CPU"})
    check(result["trace"][0]["arguments"]["facts"]["compute"] == "CPU", "已完成任务更正条件后重新执行，工具采用新值")
    check(len(memory.load("Complete")["messages"]) == 4, "完成状态不删除会话，下一轮继续原任务")

    seed("Premature", False)
    result, _ = scripted("Premature", [final("COMPLETED", PROPOSAL), call("research_dialogue"), final()])
    check(result["status"] == "WAITING_USER" and result["decisions"][0]["validation"] == "FINAL_REJECTED", "缺条件时后端拒绝模型过早完成")
    seed("BadReference")
    bad = dict(PROPOSAL, references=["invented-paper"])
    result, _ = scripted("BadReference", [call("build_evidence"), final("COMPLETED", bad), final()])
    check(result["status"] == "WAITING_USER" and result["proposal"] is None, "虚构证据标识不能通过完成校验")

    for session, invalid, code in [("Unknown", call("shell"), "UNKNOWN_TOOL"),
                                    ("BadArgs", call("search_papers", {"query": "x", "limit": 0}), "INVALID_INPUT")]:
        seed(session, False)
        result, requests = scripted(session, [invalid, call("research_dialogue"), final()])
        check(result["trace"][0]["error"]["code"] == code and result["trace"][1]["status"] == "SUCCEEDED", "非法工具或参数被拒绝，并允许模型修正：" + code)
    seed("Duplicate")
    result, _ = scripted("Duplicate", [call("build_evidence"), call("build_evidence"), final("COMPLETED", PROPOSAL)])
    check(result["trace"][1]["error"]["code"] == "DUPLICATE_CALL", "重复成功调用被阻止，不反复执行")
    seed("ChangedMaterials")
    changed_paper = dict(PAPER, title="Synthetic changed fixture", doi="10.0000/changed-model-fixture")
    with patch.dict(tools.TOOL_REGISTRY, {"search_papers": lambda **kwargs: [changed_paper]}):
        result, _ = scripted("ChangedMaterials", [call("build_evidence"), call("search_papers", {"query": "changed"}),
            call("build_evidence"), final("COMPLETED", dict(PROPOSAL, references=[changed_paper["doi"]]))])
    check(result["status"] == "COMPLETED" and result["trace"][2]["status"] == "SUCCEEDED", "实际材料改变后允许同参数重建证据")
    seed("Fenced")
    fenced = final("COMPLETED", PROPOSAL)
    fenced["message"]["content"] = "```json\n" + fenced["message"]["content"] + "\n```"
    result, _ = scripted("Fenced", [call("build_evidence"), fenced])
    check(result["status"] == "COMPLETED", "兼容JSON外层围栏，仍执行方案与来源校验")
    seed("Limit", False)
    with patch.dict(os.environ, {"AGENT_MAX_STEPS": "2"}):
        result, _ = scripted("Limit", [call("shell"), call("shell")])
    check(result["status"] == "STOPPED" and result["stop_reason"] == "STEP_LIMIT", "达到步数上限停止，不伪装完成")
    seed("Failure")
    old = memory.load("Failure")
    with patch.object(model, "chat", side_effect=ToolError("TIMEOUT", "测试超时", True)):
        with TestClient(app) as client:
            response = client.post("/api/chat", json={"session_id": "Failure", "message": "继续", "use_model": True})
    check(response.status_code == 504 and response.json()["detail"]["request_id"], "模型失败接口返回504与请求标识")
    failure = json.loads((OUTPUT / "logs/Failure.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    check(failure["status"] == "FAILED" and memory.load("Failure") == old, "失败轨迹落盘，未覆盖原会话")

    # 模型HTTP适配层单独验证重试上限及鉴权失败不重试。
    real_client = httpx.Client
    for status, expected_attempts in [(503, 2), (401, 1)]:
        counter = []
        def respond(request):
            counter.append(1)
            return httpx.Response(status, json={"error": {"message": "unsafe upstream details must not leak"}})
        with patch.dict(os.environ, {"MODEL_RETRIES": "1"}), patch.object(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(respond))):
            try:
                model.chat([{"role": "user", "content": "test"}])
                raise AssertionError("must fail")
            except ToolError as error:
                check(error.code == "MODEL_ERROR" and len(counter) == expected_attempts and "unsafe" not in str(error),
                      f"HTTP{status}尝试{expected_attempts}次且不泄漏原始错误")
    memory.write_json(OUTPUT / "summary.json", {"result": "PASS", "count": len(checks), "checks": checks,
                                              "live_model_calls": 0, "artifacts": str(OUTPUT)})
    print(f"RESULT: PASS ({len(checks)} checks); real model calls=0")
    print(f"ARTIFACTS: {OUTPUT}")


if __name__ == "__main__":
    main()

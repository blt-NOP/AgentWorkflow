"""统一条件规则验收：真实CLI四轮 + 完成守卫；无需前端、服务或模型。"""
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / "data/model-check" / ("conditions-" + uuid4().hex[:8])
os.environ["DATA_DIR"] = str(OUTPUT)

from backend import agent, memory, model, tools
from backend.tool_contracts import condition_is_valid

checks, rounds = [], []


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    checks.append(label)
    print("PASS: " + label, flush=True)


def cli(message, *arguments):
    command = [sys.executable, "-X", "utf8", "-m", "backend.cli", "--no-model",
               "--session", "ConditionDemo", "--message", message, *arguments]
    response = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / f"cli-{len(rounds) + 1}.log").write_text(response.stdout + response.stderr, encoding="utf-8")
    check(response.returncode == 0, f"第{len(rounds) + 1}轮CLI成功退出")
    state = memory.load("ConditionDemo")
    rounds.append({"arguments": command[1:], "returned_state": state})
    memory.write_json(OUTPUT / "cli-rounds.json", rounds)
    return state


def native(name):
    return {"message": {"role": "assistant", "content": None, "tool_calls": [{
        "id": "test-" + uuid4().hex[:8], "type": "function", "function": {"name": name, "arguments": "{}"}}]},
        "model": "explicit fixture", "usage": {}}


def final(status, proposal=None):
    return {"message": {"role": "assistant", "content": json.dumps({
        "status": status, "reply": "Synthetic test response", "proposal": proposal})},
        "model": "explicit fixture", "usage": {}}


def main():
    values = [(None, False), ("", False), ("  ", False), ("尚未确定", False), ("还不确定", False),
              ("不确定", False), ("未知", False), ("尚无数据", False), ("未确定", False),
              (" 尚未确定 ", False), ("CPU", True), (" GPU ", True), (True, False), ([], False)]
    for value, expected in values:
        check(condition_is_valid("compute", value) is expected, f"文本规则 {value!r} -> {expected}")
    for value, expected in [(1, True), (520, True), (0, False), (521, False), (True, False), ("4", False)]:
        check(condition_is_valid("weeks", value) is expected, f"周数规则 {value!r} -> {expected}")

    first = cli("登记已有条件", "--direction", "模型压缩", "--weeks", "4", "--dataset", "公开数据集")
    check(first["dialogue"]["field"] == "compute", "初始缺算力，提出算力问题")
    second = cli("算力尚未确定", "--choice", "compute-2")
    check(second["facts"]["compute"] == "尚未确定" and second["dialogue"]["field"] == "compute",
          "选择尚未确定后保留原回答，但继续询问算力")
    check("缺少算力条件" in second["evidence"]["gaps"], "材料工具同样识别算力条件未明确")
    third = cli("继续讨论")
    check(third["facts"]["compute"] == "尚未确定" and third["dialogue"]["field"] == "compute",
          "未补充信息时不跳过算力问题")
    fourth = cli("CPU")
    check(fourth["facts"]["compute"] == "CPU" and fourth["dialogue"]["field"] == "goal",
          "自由输入CPU覆盖未确定值，下一题进入研究目标")
    check(fourth["trace"][0]["arguments"]["facts"]["compute"] == "CPU"
          and fourth["trace"][0]["result"]["facts"]["compute"] == "CPU"
          and "缺少算力条件" not in fourth["evidence"]["gaps"], "工具实参和结果均使用CPU，算力缺项消失")

    # 其余条件、答案和证据全部满足，仅算力为未确定：隔离验证完成守卫。
    state = memory.load("GuardDemo")
    state["facts"] = {"direction": "模型压缩", "compute": " 未知 ", "weeks": 4, "dataset": "公开数据集"}
    state["answers"] = {"goal": "推理延迟", "baseline": "已有可复现基线"}
    state["papers"] = [{"title": "Synthetic condition fixture", "doi": "10.0000/condition-fixture",
                        "abstract": "Synthetic test excerpt, not an actual publication."}]
    memory.write_json(memory.session_path("GuardDemo"), state)
    proposal = {key: "Synthetic " + key for key in
                ("research_question", "hypothesis", "method", "experiment", "metrics", "risks", "next_steps")}
    proposal["references"] = ["10.0000/condition-fixture"]
    with patch.object(model, "chat", side_effect=[native("build_evidence"), final("COMPLETED", proposal),
                                                 native("research_dialogue"), final("WAITING_USER")]):
        rejected = agent.run_turn("GuardDemo", "继续讨论", use_model=True)
    check(rejected["status"] == "WAITING_USER" and rejected["dialogue"]["field"] == "compute"
          and rejected["decisions"][1]["validation"] == "FINAL_REJECTED", "模型即使宣布完成，未知算力也会被守卫拒绝并重新追问")
    with patch.object(model, "chat", side_effect=[native("build_evidence"), final("COMPLETED", proposal)]):
        completed = agent.run_turn("GuardDemo", "更正为CPU", facts={"compute": "CPU"}, use_model=True)
    check(completed["status"] == "COMPLETED" and completed["trace"][0]["arguments"]["facts"]["compute"] == "CPU",
          "明确更正为CPU且其他条件满足后，允许完成")
    memory.write_json(OUTPUT / "completion-guard.json", {"source": "explicit model fixture; no cloud call",
        "initial_state": state, "rejected": rejected, "completed": completed})
    memory.write_json(OUTPUT / "summary.json", {"result": "PASS", "count": len(checks), "checks": checks,
        "real_model_calls": 0, "artifacts": str(OUTPUT)})
    print(f"RESULT: PASS ({len(checks)} checks); real model calls=0")
    print(f"ARTIFACTS: {OUTPUT}")


if __name__ == "__main__":
    main()

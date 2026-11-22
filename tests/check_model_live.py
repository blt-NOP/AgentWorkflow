"""真实百炼四轮验收，会消耗额度；显式运行才执行，不属于离线工具测试。"""
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / "data/model-check" / ("live-" + uuid4().hex[:8])
os.environ["DATA_DIR"] = str(OUTPUT)

from backend import agent, library, memory


def main():
    paper = json.loads((ROOT / "data/model_papers.json").read_text(encoding="utf-8"))[0]
    library.save_paper(paper)
    session = "Live-" + uuid4().hex[:8]
    records = []

    def turn(message, **kwargs):
        arguments = {"session_id": session, "message": message, "use_model": True, **kwargs}
        result = agent.run_turn(**arguments)
        records.append({"arguments": arguments, "returned": result})
        memory.write_json(OUTPUT / "turns.json", records)
        print(f"LIVE TURN {len(records)}: {result['status']} / {result['stop_reason']}", flush=True)
        return result

    first = turn("只使用文库中的实际材料，不要检索。资源条件已填写，请先按Skill确认研究目标和基线，条件齐全后输出最小研究方案。",
                 facts={"direction": "小模型量化与边缘端推理", "compute": "GPU", "weeks": 4, "dataset": "公开数据集"})
    assert first["status"] == "WAITING_USER" and first["dialogue"]["field"] == "goal"
    second = turn("推理延迟", choice_id="goal-0")
    assert second["status"] == "WAITING_USER" and second["dialogue"]["field"] == "baseline"
    third = turn("已有可复现基线，请基于文库和当前条件给出完整方案，满足条件时结束本次任务。", choice_id="baseline-0")
    assert third["status"] == "COMPLETED" and third["proposal"]
    fourth = turn("更正算力：现在只有CPU。请重新调用材料工具，调整最小实验方案并说明变化，满足条件后结束。", facts={"compute": "CPU"})
    assert fourth["status"] == "COMPLETED" and fourth["proposal"]
    evidence = next(t for t in fourth["trace"] if t["tool"] == "build_evidence" and t["status"] == "SUCCEEDED")
    assert evidence["arguments"]["facts"]["compute"] == "CPU"
    summary = {"result": "PASS", "session_id": session, "rounds": len(records),
        "statuses": [r["returned"]["status"] for r in records],
        "request_ids": [r["returned"]["request_id"] for r in records],
        "tool_sequences": [[t["tool"] for t in r["returned"]["trace"]] for r in records],
        "total_tokens": sum(d.get("usage", {}).get("total_tokens", 0) for r in records for d in r["returned"]["decisions"]),
        "notice": "真实百炼模型；文库来自已核对的arXiv摘要要点转述。方案不是已验证的科研成果。", "artifacts": str(OUTPUT)}
    memory.write_json(OUTPUT / "summary.json", summary)
    print("RESULT: PASS (4 live rounds)")
    print("TOKENS: " + str(summary["total_tokens"]))
    print("ARTIFACTS: " + str(OUTPUT))


if __name__ == "__main__":
    main()

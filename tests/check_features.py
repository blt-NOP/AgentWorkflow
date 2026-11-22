"""从命令行验收 SQLite 和多轮交互；不启动前端、服务或真实模型。"""
import json
import os
from pathlib import Path
import sqlite3
import sys
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / "data/feature-check" / f"run-{uuid4().hex[:8]}"
OUTPUT.mkdir(parents=True)
os.environ["DATA_DIR"] = str(OUTPUT)
os.environ["HISTORY_LIMIT"] = "6"

import httpx
from fastapi.testclient import TestClient
from backend import dialogue, memory, tools
from backend.main import app

checks = []


def check(condition, name):
    if not condition:
        raise AssertionError(name)
    checks.append(name)
    print("PASS: " + name)


def main():
    fixture = {"paper_id": "legacy-test", "title": "Synthetic migration fixture", "doi": "10.0000/migration",
               "abstract": "Synthetic teaching material, not a real publication.", "notes": "legacy note"}
    memory.write_json(OUTPUT / "library.json", [fixture])
    responses = []
    with TestClient(app) as client:
        def call(method, path, data=None, status=200):
            response = client.request(method, path, json=data)
            if response.status_code != status:
                raise AssertionError(f"{method} {path}: {response.status_code} {response.text}")
            return response.json()

        check(call("GET", "/api/library")[0]["notes"] == "legacy note", "legacy JSON migrated to SQLite")
        call("DELETE", "/api/library/papers/legacy-test")
        check(call("GET", "/api/library") == [] and (OUTPUT / "library.json").exists(), "migration runs once; deleted paper stays deleted; original JSON retained")
        paper = {"title": "Synthetic compression fixture", "doi": "https://doi.org/10.0000/COURSE", "notes": "first note",
                 "abstract": "Synthetic teaching material: compare latency and memory."}
        saved = call("POST", "/api/library/papers", paper)
        repeated = call("POST", "/api/library/papers", paper)
        check(saved["paper_id"] == repeated["paper_id"] and len(call("GET", "/api/library")) == 1, "DOI normalization and duplicate save")
        changed = call("PUT", f"/api/library/papers/{saved['paper_id']}", dict(paper, notes="updated reading note"))
        check(changed["created_at"] == saved["created_at"] and changed["notes"] == "updated reading note", "paper edit preserves ID and creation time")
        check(len(call("GET", "/api/library?q=updated")) == 1, "SQLite search includes notes")
        check(call("GET", f"/api/library/papers/{saved['paper_id']}")["notes"] == "updated reading note", "paper detail endpoint")
        call("POST", "/api/library/import", [changed, {"title": "Synthetic second fixture", "doi": "10.0000/second"}])
        check(len(call("GET", "/api/library")) == 2, "batch import updates existing papers")
        call("POST", "/api/library/import", [{"title": "must roll back", "doi": "10.0000/rollback"},
             {"paper_id": "conflicting-id", "title": "conflict", "doi": "10.0000/course"}], status=400)
        check(len(call("GET", "/api/library")) == 2, "failed batch import rolls back")

        def turn(message, **fields):
            result = call("POST", "/api/chat", {"session_id": "A", "message": message, **fields})
            responses.append(result)
            return result

        first = turn("开始讨论", facts={"direction": "模型压缩"})
        check(first["dialogue"]["field"] == "compute" and len(first["state"]["evidence"]["rows"]) == 2, "chat reads SQLite and asks first missing fact")
        second = turn("只有 CPU", choice_id="compute-0")
        check(second["state"]["facts"]["compute"] == "CPU" and second["trace"][0]["arguments"]["facts"]["compute"] == "CPU", "option answer updates facts before evidence tool")
        check(second["dialogue"]["field"] == "weeks", "multi-turn question advances")
        third = turn("4 周")
        check(third["state"]["facts"]["weeks"] == 4, "typed answer recorded")
        turn("使用公开数据集", choice_id="dataset-0")
        fifth = turn("推理延迟", choice_id="goal-0")
        check(fifth["state"]["answers"]["goal"] == "推理延迟" and fifth["dialogue"]["field"] == "baseline", "research goal persists; next question is baseline")
        turn("需要先查找基线", choice_id="baseline-1")
        resumed = call("GET", "/api/sessions/A")
        check(resumed["answers"]["baseline"] == "需要先查找基线" and len(resumed["history"]) == 6, "dialogue and answers restored after history trimming")
        before = len(resumed["messages"])
        call("POST", "/api/chat", {"session_id": "A", "message": "过期选项", "choice_id": "compute-0"}, status=400)
        check(len(call("GET", "/api/sessions/A")["messages"]) == before, "expired choice rejected without saving")
        corrected = turn("改用 GPU", facts={"compute": "GPU"})
        check(corrected["trace"][0]["result"]["facts"]["compute"] == "GPU", "explicit correction used by next tool result")
        other = call("POST", "/api/chat", {"session_id": "B", "message": "新讨论"})
        check(other["state"]["facts"] == {} and other["state"]["answers"] == {}, "session B does not inherit A facts or answers")
        check([s["tool"] for s in corrected["trace"]] == ["build_evidence", "research_dialogue"], "new tool actually runs in agent chain")
        count = len(call("GET", "/api/sessions"))
        direct = call("POST", "/api/tools/dialogue", {"facts": {"direction": "模型压缩"}})
        check(direct["field"] == "compute" and len(call("GET", "/api/sessions")) == count, "independent dialogue endpoint has no session writes")

        # 用临时 Skill 验证配置确实改变提问顺序，而不是只在文档中声明。
        custom = OUTPUT / "skills/custom"
        custom.mkdir(parents=True)
        custom_config = {"questions": [{"target": "facts", "field": "weeks", "question": "测试策略：先确认周数？",
                          "options": [{"label": "2 周", "value": 2}]}], "final_question": "下一步？"}
        (custom / "SKILL.md").write_text("---\nname: custom\ndescription: Synthetic test\n---\n```json\n" + json.dumps(custom_config, ensure_ascii=False) + "\n```", encoding="utf-8")
        with patch.object(dialogue, "SKILLS", OUTPUT / "skills"):
            custom_result = call("POST", "/api/tools/dialogue", {"skill": "custom"})
            check(custom_result["field"] == "weeks" and "先确认周数" in custom_result["question"], "changing Skill changes question strategy")

        # 明确的 HTTP 替身，仅验证 Skill 被传给模型；不调用真实模型。
        actual_client = httpx.Client
        def model_response(request):
            prompt = json.loads(request.content)["messages"][0]["content"]
            check("questions" in prompt and "你可以使用哪些计算资源" in prompt, "model receives Skill instructions and selected question")
            return httpx.Response(200, json={"choices": [{"message": {"content": "Synthetic model analysis"}}]})
        with patch.dict(os.environ, {"MODEL_BASE_URL": "https://fixture.invalid/v1", "MODEL_NAME": "fixture", "MODEL_API_KEY": "test-only-key"}):
            with patch.object(httpx, "Client", lambda **kwargs: actual_client(transport=httpx.MockTransport(model_response))):
                generated = tools.research_dialogue({"facts": {"direction": "模型压缩"}, "answers": {}, "history": [],
                    "evidence": tools.build_evidence([], {})}, "开始讨论", use_model=True)
                check(generated["message"] == "Synthetic model analysis", "dialogue tool uses model response")

    with sqlite3.connect(OUTPUT / "library.sqlite3") as db:
        columns = [row[1] for row in db.execute("PRAGMA table_info(papers)")]
        check("notes" in columns and "created_at" in columns, "SQLite schema contains paper and reading fields")
    memory.write_json(OUTPUT / "responses.json", responses)
    memory.write_json(OUTPUT / "summary.json", {"result": "PASS", "checks": checks, "count": len(checks), "artifacts": str(OUTPUT)})
    print(f"RESULT: PASS ({len(checks)} checks)")
    print(f"ARTIFACTS: {OUTPUT}")


if __name__ == "__main__":
    main()

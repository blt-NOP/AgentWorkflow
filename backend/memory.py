"""会话和日志使用 JSON；论文库由 library.py 保存到 SQLite。"""
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv("DATA_DIR", "data"))
if not DATA.is_absolute():
    DATA = ROOT / DATA
HISTORY_LIMIT = max(2, int(os.getenv("HISTORY_LIMIT", "6")))


def session_path(session_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", session_id):
        raise ValueError("会话名只允许英文字母、数字、下划线和短横线，最长64位")
    return DATA / "sessions" / f"{session_id}.json"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def load(session_id):
    path = session_path(session_id)
    if path.exists():
        state = json.loads(path.read_text(encoding="utf-8"))
        state.setdefault("answers", {})
        state.setdefault("dialogue", {})
        state.setdefault("skill", "research-dialogue")
        return state
    return {"session_id": session_id, "facts": {}, "history": [], "messages": [],
            "papers": [], "evidence": {}, "reply": "", "trace": [],
            "answers": {}, "dialogue": {}, "skill": "research-dialogue"}


def save(state, log):
    write_json(session_path(state["session_id"]), state)
    path = DATA / "logs" / f"{state['session_id']}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(log, ensure_ascii=False) + "\n")


def list_sessions():
    paths = sorted((DATA / "sessions").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    result = []
    for path in paths:
        state = json.loads(path.read_text(encoding="utf-8"))
        result.append({"session_id": state["session_id"], "title": state["messages"][0]["content"][:40],
                       "message_count": len(state["messages"])})
    return result


def delete(session_id):
    session_path(session_id).unlink(missing_ok=True)
    (DATA / "logs" / f"{session_id}.jsonl").unlink(missing_ok=True)

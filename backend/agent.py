"""网页和CLI共用：读记忆 → 更新条件 → 模型决策或离线演示 → 保存结果。"""
from datetime import datetime
import json
from time import perf_counter
from uuid import uuid4
from . import memory, library, dialogue, tools, model


def offline_turn(state, message, search):
    """独立工具和记忆测试；不代表科研语义分析。"""
    trace = []
    if search:
        result = tools.TOOL_REGISTRY["search_papers"](search)
        state["papers"] = result
        trace.append({"tool": "search_papers", "arguments": {"query": search}, "result": result})
    arguments = {"papers": library.list_papers() + state["papers"], "facts": state["facts"].copy()}
    state["evidence"] = tools.TOOL_REGISTRY["build_evidence"](**arguments)
    trace.append({"tool": "build_evidence", "arguments": arguments, "result": state["evidence"]})
    interaction = tools.TOOL_REGISTRY["research_dialogue"](state, message, state["skill"], False)
    trace.append({"tool": "research_dialogue", "arguments": {"message": message, "facts": state["facts"].copy(),
        "answers": state["answers"].copy(), "skill": state["skill"], "use_model": False}, "result": interaction})
    state["trace"], state["decisions"] = trace, []
    return {"reply": interaction["message"] + "\n\n" + interaction["question"], "dialogue": interaction,
            "status": "WAITING_USER", "stop_reason": "OFFLINE_DEMO", "proposal": None}


def run_turn(session_id, message, facts=None, search=None, use_model=None, skill=None, choice_id=None):
    request_id = uuid4().hex
    started = perf_counter()
    use_model = model.enabled() if use_model is None else use_model
    state = memory.load(session_id)
    before = state["facts"].copy()
    state["trace"], state["decisions"] = [], []
    print(f"[开始] request={request_id} session={session_id} model={use_model}", flush=True)
    try:
        if not message.strip():
            raise ValueError("消息不能为空")
        selected = skill or state["skill"]
        dialogue.load_skill(selected)
        if selected != state["skill"]:
            state["dialogue"], state["answers"] = {}, {}
        state["skill"] = selected
        if choice_id or not facts:
            dialogue.accept_answer(state, message, choice_id)
        state["facts"].update(facts or {})
        if state["facts"] != before:
            state["evidence"] = {}  # 条件变化后不把旧证据矩阵当成本轮结果。
        print("[读记忆] " + json.dumps(before, ensure_ascii=False), flush=True)
        print("[当前条件] " + json.dumps(state["facts"], ensure_ascii=False), flush=True)
        if use_model:
            from .planner import run
            outcome = run(state, message, search, request_id)
        else:
            outcome = offline_turn(state, message, search)
        changes = [{"field": key, "before": before.get(key), "after": value}
                   for key, value in state["facts"].items() if before.get(key) != value]
        state.update(reply=outcome["reply"], dialogue=outcome["dialogue"], status=outcome["status"],
                     stop_reason=outcome["stop_reason"], proposal=outcome["proposal"], request_id=request_id)
        state["messages"] += [{"role": "user", "content": message}, {"role": "assistant", "content": outcome["reply"]}]
        state["history"] = state["messages"][-memory.HISTORY_LIMIT:]
        for item in state["trace"]:
            item.setdefault("request_id", request_id)
        log = {"at": datetime.now().isoformat(timespec="seconds"), "request_id": request_id, "session_id": session_id,
               "before": before, "changes": changes, "model_called": use_model, "status": outcome["status"],
               "stop_reason": outcome["stop_reason"], "duration_ms": round((perf_counter() - started) * 1000), "state": state}
        memory.save(state, log)
        print("[工具顺序] " + " → ".join(item["tool"] for item in state["trace"]), flush=True)
        print(f"[写记忆] {session_id}: recent={len(state['history'])}, full={len(state['messages'])}", flush=True)
        print(f"[结束] request={request_id} status={outcome['status']} reason={outcome['stop_reason']}", flush=True)
        print("[回答] " + outcome["reply"], flush=True)
        return {**outcome, "request_id": request_id, "state": state, "trace": state["trace"], "decisions": state["decisions"]}
    except Exception as error:
        # 失败也留轨迹；不保存半完成状态，不记录异常原文或凭据。
        record = {"at": datetime.now().isoformat(timespec="seconds"), "request_id": request_id, "session_id": session_id,
                  "status": "FAILED", "stop_reason": getattr(error, "code", "EXECUTION_ERROR"),
                  "error_type": type(error).__name__, "trace": state["trace"], "decisions": state["decisions"],
                  "duration_ms": round((perf_counter() - started) * 1000)}
        memory.append_log(session_id, record)
        print("[失败] " + json.dumps(record, ensure_ascii=False), flush=True)
        error.request_id = request_id
        raise

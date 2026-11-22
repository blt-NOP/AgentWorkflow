"""网页和CLI共用：读记忆 → 更新条件 → 模型决策或离线演示 → 保存结果。"""
from datetime import datetime
import json
from time import perf_counter
from uuid import uuid4
from . import memory, library, dialogue, tools, model


def offline_turn(state, message, search, emit):
    """独立工具和记忆测试；不代表科研语义分析。"""
    trace = []
    state["trace"] = trace

    def execute(name, arguments, trace_arguments=None):
        record = {"tool": name, "call_id": uuid4().hex, "arguments": arguments if trace_arguments is None else trace_arguments,
                  "status": "RUNNING"}
        trace.append(record)
        emit("tool_started", {"tool": name, "call_id": record["call_id"]})
        started = perf_counter()
        try:
            result = tools.TOOL_REGISTRY[name](**arguments)
            record.update(status="SUCCEEDED", result=result, duration_ms=round((perf_counter() - started) * 1000))
            emit("tool_result", {"tool": name, "call_id": record["call_id"], "result": result, "duration_ms": record["duration_ms"]})
            return result
        except Exception as error:
            record.update(status="FAILED", error={"code": getattr(error, "code", "EXECUTION_ERROR")},
                          duration_ms=round((perf_counter() - started) * 1000))
            emit("tool_failed", {"tool": name, "call_id": record["call_id"], "code": record["error"]["code"]})
            raise

    if search:
        result = execute("search_papers", {"query": search})
        state["papers"] = result
    arguments = {"papers": library.list_papers() + state["papers"], "facts": state["facts"].copy()}
    state["evidence"] = execute("build_evidence", arguments)
    interaction = execute("research_dialogue", {"state": state, "message": message, "skill_id": state["skill"], "use_model": False},
        {"message": message, "facts": state["facts"].copy(), "answers": state["answers"].copy(), "skill": state["skill"], "use_model": False})
    state["trace"], state["decisions"] = trace, []
    return {"reply": interaction["message"] + "\n\n" + interaction["question"], "dialogue": interaction,
            "status": "WAITING_USER", "stop_reason": "OFFLINE_DEMO", "proposal": None}


def run_turn(session_id, message, facts=None, search=None, use_model=None, skill=None, choice_id=None,
             request_id=None, on_event=None):
    request_id = request_id or uuid4().hex
    started = perf_counter()
    use_model = model.enabled() if use_model is None else use_model
    state = {"trace": [], "decisions": []}
    events = []

    def emit(kind, data=None):
        event = {"type": kind, "seq": len(events) + 1, "request_id": request_id, "session_id": session_id,
                 "at": datetime.now().isoformat(timespec="milliseconds"), "data": data or {}}
        events.append(event)
        if on_event is not None:
            on_event(event)

    print(f"[开始] request={request_id} session={session_id} model={use_model}", flush=True)
    try:
        emit("started", {"use_model": use_model})
        state = memory.load(session_id)
        before = state["facts"].copy()
        state["trace"], state["decisions"] = [], []
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
            outcome = run(state, message, search, request_id, emit=emit, stream_reply=on_event is not None)
        else:
            outcome = offline_turn(state, message, search, emit)
        emit("reply_ready", {"reply": outcome["reply"], "status": outcome["status"]})
        changes = [{"field": key, "before": before.get(key), "after": value}
                   for key, value in state["facts"].items() if before.get(key) != value]
        state.update(reply=outcome["reply"], dialogue=outcome["dialogue"], status=outcome["status"],
                     stop_reason=outcome["stop_reason"], proposal=outcome["proposal"], request_id=request_id)
        state["messages"] += [{"role": "user", "content": message}, {"role": "assistant", "content": outcome["reply"]}]
        state["history"] = state["messages"][-memory.HISTORY_LIMIT:]
        for item in state["trace"]:
            item.setdefault("request_id", request_id)
        state["events"] = events.copy()
        log = {"at": datetime.now().isoformat(timespec="seconds"), "request_id": request_id, "session_id": session_id,
               "before": before, "changes": changes, "model_called": use_model, "status": outcome["status"],
               "stop_reason": outcome["stop_reason"], "duration_ms": round((perf_counter() - started) * 1000), "state": state}
        memory.save(state, log)
        print("[工具顺序] " + " → ".join(item["tool"] for item in state["trace"]), flush=True)
        print(f"[写记忆] {session_id}: recent={len(state['history'])}, full={len(state['messages'])}", flush=True)
        print(f"[结束] request={request_id} status={outcome['status']} reason={outcome['stop_reason']}", flush=True)
        print("[回答] " + outcome["reply"], flush=True)
        result = {**outcome, "request_id": request_id, "state": state, "trace": state["trace"], "decisions": state["decisions"]}
        emit("completed", result)  # 记忆保存后才交付最终结果，state.events不递归包含终态。
        return result
    except Exception as error:
        # 失败也留轨迹；不保存半完成状态，不记录异常原文或凭据。
        code = getattr(error, "code", "INVALID_INPUT" if isinstance(error, ValueError) else "EXECUTION_ERROR")
        emit("reply_reset", {"reason": "FAILED"})
        emit("failed", {"code": code, "message": str(error) if isinstance(error, ValueError) else "本轮执行失败，请按请求编号查看日志后重试。",
                        "retryable": getattr(error, "retryable", False)})
        record = {"at": datetime.now().isoformat(timespec="seconds"), "request_id": request_id, "session_id": session_id,
                  "status": "FAILED", "stop_reason": getattr(error, "code", "EXECUTION_ERROR"),
                  "error_type": type(error).__name__, "trace": state["trace"], "decisions": state["decisions"],
                  "events": events,
                  "duration_ms": round((perf_counter() - started) * 1000)}
        memory.append_log(session_id, record)
        print("[失败] " + json.dumps(record, ensure_ascii=False), flush=True)
        error.request_id = request_id
        raise

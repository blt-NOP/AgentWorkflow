"""唯一对话流程：网页和命令行都调用 run_turn。"""
from datetime import datetime
import json
from . import memory, model, tools


def run_turn(session_id, message, facts=None, search=None, use_model=False):
    if not message.strip():
        raise ValueError("消息不能为空")
    # 1. 从文件加载当前会话。
    state = memory.load(session_id)
    before = state["facts"].copy()
    print(f"[读记忆] {session_id}: {before}", flush=True)

    # 2. 明确提供的新值覆盖旧值，未提供的字段保留。
    changes = []
    for key, value in (facts or {}).items():
        if state["facts"].get(key) != value:
            changes.append({"field": key, "before": state["facts"].get(key), "after": value})
        state["facts"][key] = value
    print("[条件变化] " + json.dumps(changes, ensure_ascii=False), flush=True)

    # 3. 按用户操作调用工具。检索结果保存到当前会话。
    trace = []
    if search:
        print(f"[工具] search_papers query={search}", flush=True)
        state["papers"] = tools.search_papers(search)
        trace.append({"tool": "search_papers", "arguments": {"query": search}, "result": state["papers"]})
    papers = memory.library() + state["papers"]
    state["evidence"] = tools.build_evidence(papers, state["facts"])
    trace.append({"tool": "build_evidence", "arguments": {"facts": state["facts"].copy(), "papers": papers},
                  "result": state["evidence"]})
    print("[工具] build_evidence facts=" + json.dumps(state["facts"], ensure_ascii=False), flush=True)
    print("[工具结果] " + json.dumps(state["evidence"], ensure_ascii=False), flush=True)

    # 4. 模型使用当前事实、工具结果和近期对话；关闭模型时明确标记。
    if use_model:
        print("[模型] 请求开始", flush=True)
        answer = model.reply(state, message)
    else:
        answer = "[未调用模型] 当前条件：" + json.dumps(state["facts"], ensure_ascii=False)
        answer += "\n待补充：" + ("；".join(state["evidence"]["gaps"]) or "请启用模型讨论研究思路。")

    # 5. 完整消息保留供查看，模型只读取最近若干条，facts 独立保留。
    state["messages"] += [{"role": "user", "content": message}, {"role": "assistant", "content": answer}]
    state["history"] = state["messages"][-memory.HISTORY_LIMIT:]
    state["reply"], state["trace"] = answer, trace
    log = {"at": datetime.now().isoformat(timespec="seconds"), "session_id": session_id,
           "before": before, "changes": changes, "model_called": use_model, "state": state}
    memory.save(state, log)
    print(f"[写记忆] {session_id}: recent={len(state['history'])}, full={len(state['messages'])}", flush=True)
    print("[回答] " + answer, flush=True)
    return {"reply": answer, "state": state, "trace": trace}

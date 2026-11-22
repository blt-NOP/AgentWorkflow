"""唯一对话流程：网页和命令行都调用 run_turn。"""
from datetime import datetime
import json
from . import memory, library, dialogue, tools


def run_turn(session_id, message, facts=None, search=None, use_model=False, skill=None, choice_id=None):
    if not message.strip():
        raise ValueError("消息不能为空")
    # 1. 从文件加载当前会话。
    state = memory.load(session_id)
    before = state["facts"].copy()
    print(f"[读记忆] {session_id}: {before}", flush=True)

    selected_skill = skill or state["skill"]
    dialogue.load_skill(selected_skill)
    if selected_skill != state["skill"]:
        state["dialogue"], state["answers"] = {}, {}
    state["skill"] = selected_skill
    # 上轮按钮/文字答案先写入；本轮显式条件随后覆盖，避免旧表单或建议污染事实。
    if choice_id or not facts:
        dialogue.accept_answer(state, message, choice_id)

    # 2. 明确提供的新值覆盖旧值，未提供的字段保留。
    changes = []
    state["facts"].update(facts or {})
    for key, value in state["facts"].items():
        if before.get(key) != value:
            changes.append({"field": key, "before": before.get(key), "after": value})
    print("[条件变化] " + json.dumps(changes, ensure_ascii=False), flush=True)

    # 3. 按用户操作调用工具。检索结果保存到当前会话。
    trace = []
    if search:
        print(f"[工具] search_papers query={search}", flush=True)
        state["papers"] = tools.search_papers(search)
        trace.append({"tool": "search_papers", "arguments": {"query": search}, "result": state["papers"]})
    papers = library.list_papers() + state["papers"]
    state["evidence"] = tools.build_evidence(papers, state["facts"])
    trace.append({"tool": "build_evidence", "arguments": {"facts": state["facts"].copy(), "papers": papers},
                  "result": state["evidence"]})
    print("[工具] build_evidence facts=" + json.dumps(state["facts"], ensure_ascii=False), flush=True)
    print("[工具结果] " + json.dumps(state["evidence"], ensure_ascii=False), flush=True)

    # 4. 多轮交互工具按 Skill 追问；启用模型时在工具内部生成研究分析。
    arguments = {"message": message, "facts": state["facts"].copy(), "answers": state["answers"].copy(),
                 "skill": selected_skill, "use_model": use_model, "choice_id": choice_id}
    interaction = tools.research_dialogue(state, message, selected_skill, use_model)
    trace.append({"tool": "research_dialogue", "arguments": arguments, "result": interaction})
    state["dialogue"] = interaction
    answer = interaction["message"] + "\n\n" + interaction["question"]
    print(f"[工具] research_dialogue skill={selected_skill}; stage={interaction['stage']}", flush=True)
    print("[追问] " + interaction["question"], flush=True)
    for option in interaction["options"]:
        print(f"[选项] {option['id']}: {option['label']}", flush=True)

    # 5. 完整消息保留供查看，模型只读取最近若干条，facts 独立保留。
    state["messages"] += [{"role": "user", "content": message}, {"role": "assistant", "content": answer}]
    state["history"] = state["messages"][-memory.HISTORY_LIMIT:]
    state["reply"], state["trace"] = answer, trace
    log = {"at": datetime.now().isoformat(timespec="seconds"), "session_id": session_id,
           "before": before, "changes": changes, "model_called": use_model, "state": state}
    memory.save(state, log)
    print(f"[写记忆] {session_id}: recent={len(state['history'])}, full={len(state['messages'])}", flush=True)
    print("[回答] " + answer, flush=True)
    return {"reply": answer, "state": state, "trace": trace, "dialogue": interaction}

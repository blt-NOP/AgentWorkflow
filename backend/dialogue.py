"""多轮交互工具：读取 Skill、接收上轮答案、给出本轮问题与选项。"""
import json
import re
from . import memory, model

SKILLS = memory.ROOT / "skills"


def load_skill(skill_id):
    if not re.fullmatch(r"[a-z0-9-]{1,64}", skill_id):
        raise ValueError("Skill 名称只能包含小写字母、数字和短横线")
    path = SKILLS / skill_id / "SKILL.md"
    if not path.exists():
        raise ValueError(f"找不到 Skill：{skill_id}")
    text = path.read_text(encoding="utf-8")
    match = re.search(r"```json\s*(.*?)```", text, re.S)
    if not match:
        raise ValueError("Skill 必须包含一个 JSON 提问策略块")
    config = json.loads(match[1])
    fields = set()
    for item in config["questions"]:
        if item["target"] not in ("facts", "answers") or item["field"] in fields:
            raise ValueError("Skill 的 target 无效或问题字段重复")
        if item["target"] == "facts" and item["field"] not in ("direction", "claim", "compute", "weeks", "dataset"):
            raise ValueError("Skill 使用了不支持的事实字段")
        fields.add(item["field"])
    return text, config


def list_skills():
    return [{"id": path.parent.name, "name": path.parent.name} for path in sorted(SKILLS.glob("*/SKILL.md"))]


def accept_answer(state, message, choice_id=None):
    """只接收当前会话上轮的问题。按钮传编号，打字也可回答当前问题。"""
    pending = state.get("dialogue") or {}
    if not pending.get("field"):
        if choice_id:
            raise ValueError("当前没有待回答的选项，请先发起讨论")
        return
    options = pending["options"]
    selected = next((o for o in options if o["id"] == choice_id), None) if choice_id else next(
        (o for o in options if o["label"] == message.strip()), None)
    if choice_id and not selected:
        raise ValueError("选项已过期或不属于当前问题，请刷新会话")
    value = selected["value"] if selected else message.strip()
    field = pending["field"]
    if not selected:
        if value in ("继续", "继续讨论", "返回A继续", "根据当前条件继续"):
            return
        if field == "weeks":
            found = re.fullmatch(r"(\d+)\s*周?", value)
            if not found or not 1 <= int(found[1]) <= 520:
                return
            value = int(found[1])
        if field == "compute" and not re.search(r"CPU|GPU|显卡|算力|计算|未确定", value, re.I):
            return
    if isinstance(value, str) and len(value) > 1000:
        raise ValueError("当前问题的答案不能超过1000字")
    state.setdefault(pending["target"], {})[field] = value


def research_dialogue(state, message, skill_id="research-dialogue", use_model=False):
    """独立工具入口，返回 message/question/options；调用方负责保存状态。"""
    instructions, config = load_skill(skill_id)
    current = next((item for item in config["questions"]
                    if not state.get(item["target"], {}).get(item["field"])), None)
    result = {"skill": skill_id, "stage": "discussion", "field": None, "target": None,
              "question": config["final_question"], "options": []}
    if current:
        result.update(stage=current["field"], field=current["field"], target=current["target"],
                      question=current["question"], options=[
                          {"id": f"{current['field']}-{index}", "label": item["label"], "value": item["value"]}
                          for index, item in enumerate(current["options"])])
    if use_model:
        result["message"] = model.reply(state, message, instructions, result["question"])
    else:
        result["message"] = "[未调用模型] 当前条件：" + json.dumps(state["facts"], ensure_ascii=False)
        if state.get("answers"):
            result["message"] += "\n讨论记录：" + json.dumps(state["answers"], ensure_ascii=False)
        if state["evidence"]["gaps"]:
            result["message"] += "\n材料缺项：" + "；".join(state["evidence"]["gaps"])
    return result

"""多轮交互工具：读取 Skill、接收上轮答案、给出本轮问题与选项。"""
import json
import re
import httpx
from . import memory, model
from .tool_contracts import ToolError, check_facts, condition_is_valid

SKILLS = memory.ROOT / "skills"


def load_skill(skill_id):
    if not isinstance(skill_id, str) or not re.fullmatch(r"[a-z0-9-]{1,64}", skill_id):
        raise ToolError("INVALID_INPUT", "Skill 名称只能包含小写字母、数字和短横线")
    path = SKILLS / skill_id / "SKILL.md"
    if not path.exists():
        raise ToolError("INVALID_INPUT", f"找不到 Skill：{skill_id}")
    try:
        text = path.read_text(encoding="utf-8")
        match = re.search(r"```json\s*(.*?)```", text, re.S)
        if not match:
            raise ValueError("缺少 JSON 提问策略块")
        config = json.loads(match[1])
        if not isinstance(config["questions"], list) or not isinstance(config["final_question"], str) or not config["final_question"].strip():
            raise ValueError("questions 或 final_question 无效")
        fields = set()
        for item in config["questions"]:
            if item["target"] not in ("facts", "answers") or not isinstance(item["field"], str) or item["field"] in fields:
                raise ValueError("target 无效或问题字段重复")
            if not isinstance(item["question"], str) or not item["question"].strip() or not isinstance(item["options"], list):
                raise ValueError("问题或选项列表无效")
            for option in item["options"]:
                if not isinstance(option["label"], str) or not option["label"].strip():
                    raise ValueError("选项标签无效")
                if item["target"] == "facts":
                    check_facts({item["field"]: option["value"]})
                elif not isinstance(option["value"], str):
                    raise ValueError("讨论答案选项必须为文本")
            if item["target"] == "facts":
                check_facts({item["field"]: None})
            fields.add(item["field"])
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ToolError("INVALID_SKILL", f"Skill 配置无效：{skill_id}；{error}") from error
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
    if not isinstance(state, dict) or not isinstance(message, str) or not message.strip() or len(message) > 10000 or type(use_model) is not bool:
        raise ToolError("INVALID_INPUT", "state、message 或 use_model 类型/长度无效")
    check_facts(state.get("facts"))
    state = dict(state, answers=state.get("answers", {}), history=state.get("history", []))
    evidence = state.get("evidence")
    if not isinstance(state["answers"], dict) or not isinstance(state["history"], list):
        raise ToolError("INVALID_INPUT", "answers 必须为对象，history 必须为消息列表")
    if not isinstance(evidence, dict) or not isinstance(evidence.get("rows"), list) or not isinstance(evidence.get("gaps"), list):
        raise ToolError("INVALID_INPUT", "evidence 必须包含 rows 和 gaps 列表")
    if any(not isinstance(gap, str) for gap in evidence["gaps"]):
        raise ToolError("INVALID_INPUT", "evidence.gaps 必须为文本列表")
    instructions, config = load_skill(skill_id)
    current = next((item for item in config["questions"]
                    if not condition_is_valid(item["field"], state.get(item["target"], {}).get(item["field"]))), None)
    result = {"skill": skill_id, "stage": "discussion", "field": None, "target": None,
              "question": config["final_question"], "options": []}
    if current:
        result.update(stage=current["field"], field=current["field"], target=current["target"],
                      question=current["question"], options=[
                          {"id": f"{current['field']}-{index}", "label": item["label"], "value": item["value"]}
                          for index, item in enumerate(current["options"])])
    if use_model:
        if not model.configured():
            raise ToolError("MODEL_NOT_CONFIGURED", "未配置模型，请填写环境变量或设置 use_model=false")
        try:
            result["message"] = model.reply(state, message, instructions, result["question"])
        except ToolError:
            raise
        except httpx.TimeoutException as error:
            raise ToolError("TIMEOUT", "模型请求超时", True) from error
        except httpx.RequestError as error:
            raise ToolError("NETWORK_ERROR", "模型网络请求失败", True) from error
        except (RuntimeError, ValueError, KeyError, TypeError) as error:
            raise ToolError("MODEL_ERROR", "模型返回失败或内容无效", True) from error
    else:
        result["message"] = "[未调用模型] 当前条件：" + json.dumps(state["facts"], ensure_ascii=False)
        if state.get("answers"):
            result["message"] += "\n讨论记录：" + json.dumps(state["answers"], ensure_ascii=False)
        if state["evidence"]["gaps"]:
            result["message"] += "\n材料缺项：" + "；".join(state["evidence"]["gaps"])
    return result

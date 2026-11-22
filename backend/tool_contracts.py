"""工具函数和 HTTP 接口共用的错误及事实校验。"""


class ToolError(ValueError):
    def __init__(self, code, message, retryable=False):
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable


UNRESOLVED = {"尚未确定", "还不确定", "不确定", "未知", "尚无数据", "未确定"}


def condition_is_valid(field, value):
    """判断条件是否已明确；允许保存未确定的回答，但不将其视为已满足。"""
    if field == "weeks":
        return type(value) is int and 1 <= value <= 520
    return isinstance(value, str) and bool(value.strip()) and value.strip() not in UNRESOLVED


def check_facts(facts):
    if not isinstance(facts, dict):
        raise ToolError("INVALID_INPUT", "facts 必须为对象")
    limits = {"direction": 1000, "claim": 2000, "compute": 1000, "dataset": 1000}
    for key, value in facts.items():
        if key == "weeks":
            if value is not None and (type(value) is not int or not 1 <= value <= 520):
                raise ToolError("INVALID_INPUT", "weeks 必须为1至520的整数或 null，单位为周")
        elif key not in limits or (value is not None and (not isinstance(value, str) or len(value) > limits[key])):
            raise ToolError("INVALID_INPUT", f"无效事实字段或类型：{key}")

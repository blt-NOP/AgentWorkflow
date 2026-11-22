"""SSE传输桥：后台执行原有run_turn，按产生顺序转发事件。"""
import json
from queue import Queue, Empty, Full
import re
from threading import Event, Thread


def reply_prefix(content):
    """从尚未完整的JSON中读取reply字符串已到达的部分，不泄漏其他字段或推理。"""
    found = re.search(r'"reply"\s*:\s*"', content)
    if not found:
        return ""
    value, index = [], found.end()
    escapes = {'"': '"', '\\': '\\', '/': '/', 'b': '\b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t'}
    while index < len(content):
        char = content[index]
        if char == '"':
            break
        if char == '\\':
            if index + 1 >= len(content):
                break
            code = content[index + 1]
            if code == 'u':
                size = 6
                if index + size > len(content):
                    break
                try:
                    number = int(content[index + 2:index + 6], 16)
                    if 0xD800 <= number <= 0xDBFF:
                        size = 12
                        if index + size > len(content) or content[index + 6:index + 8] != '\\u':
                            break
                        low = int(content[index + 8:index + 12], 16)
                        if not 0xDC00 <= low <= 0xDFFF:
                            break
                    elif 0xDC00 <= number <= 0xDFFF:
                        break
                    value.append(json.loads('"' + content[index:index + size] + '"'))
                except (ValueError, json.JSONDecodeError):
                    break
                index += size
                continue
            if code not in escapes:
                break
            value.append(escapes[code])
            index += 2
            continue
        if ord(char) < 32:
            break
        value.append(char)
        index += 1
    return "".join(value)


def stream_turn(arguments):
    """队列有界；断开连接后停止排队，执行仍可完成并按会话保存。"""
    from .agent import run_turn
    queue = Queue(maxsize=128)
    disconnected = Event()

    def send(value):
        while not disconnected.is_set():
            try:
                queue.put(value, timeout=0.2)
                return
            except Full:
                continue

    def execute():
        try:
            run_turn(**arguments, on_event=send)
        except Exception:
            # run_turn已经发出failed事件并写失败日志，不把异常/密钥再暴露给客户端。
            pass
        finally:
            send(None)

    Thread(target=execute, daemon=True).start()
    try:
        while True:
            try:
                event = queue.get(timeout=5)
            except Empty:
                yield ": heartbeat\n\n"
                continue
            if event is None:
                break
            yield f"id: {event['seq']}\nevent: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
    finally:
        disconnected.set()

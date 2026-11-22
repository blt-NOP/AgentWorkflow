"""页面恢复验收专用服务（无云模型）。仅本地测试，不导入生产服务。

python tests/recovery_server.py
控制文件 data/model-check/recovery-ui/fault.txt：ok / fail / slow。
fail模拟工具依赖超时；slow阻塞4秒，触发页面2秒总期限。
"""
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / "data/model-check/recovery-ui"
os.environ.update(DATA_DIR=str(OUTPUT), MODEL_ENABLED="false", CHAT_TIMEOUT_SECONDS="2", STREAM_IDLE_SECONDS="5")

from backend import tools
from backend.main import app
from backend.tool_contracts import ToolError

actual = tools.TOOL_REGISTRY["build_evidence"]


def controlled(**arguments):
    mode = (OUTPUT / "fault.txt").read_text(encoding="utf-8").strip()
    if mode == "fail":
        raise ToolError("TIMEOUT", "测试注入：文献依赖超时，请恢复依赖后重试。", True)
    if mode == "slow":
        time.sleep(4)
    return actual(**arguments)


tools.TOOL_REGISTRY["build_evidence"] = controlled

if __name__ == "__main__":
    import uvicorn
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "fault.txt").write_text("fail", encoding="utf-8")
    uvicorn.run(app, host="127.0.0.1", port=8014)

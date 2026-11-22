"""运行后端或测试，将本次终端输出同时保存到独立日志。"""
import os
import subprocess
import sys
from datetime import datetime

from .memory import DATA, ROOT


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # 原样转交 Python 参数；不传参数时启动网页/API 服务。
    arguments = sys.argv[1:] or [
        "-m", "uvicorn", "backend.main:app",
        "--host", "127.0.0.1", "--port", "8000", "--reload",
    ]
    folder = DATA / "logs" / "runs"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{datetime.now():%Y%m%d_%H%M%S_%f}_{os.getpid()}.log"
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    with path.open("w", encoding="utf-8") as log:
        def record(text):
            print(text, end="", flush=True)
            log.write(text)
            log.flush()

        record(f"[日志] {path}\n[开始] {datetime.now().isoformat(timespec='seconds')}\n")
        process = None
        code = 1
        try:
            process = subprocess.Popen(
                [sys.executable, "-u", "-X", "utf8", *arguments],
                cwd=ROOT, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            )
            for line in process.stdout:
                record(line)
            code = process.wait()
        except KeyboardInterrupt:
            # 同一终端的 Ctrl+C 也会发送给子进程，先让 Uvicorn 正常退出。
            record("\n[停止] 收到 Ctrl+C，等待程序退出。\n")
            if process is not None:
                try:
                    code = process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    code = process.wait()
                for line in process.stdout:
                    record(line)
        except OSError as error:
            record(f"[启动失败] {error}\n")
        finally:
            if process is not None and process.stdout is not None:
                process.stdout.close()
            record(f"[结束] {datetime.now().isoformat(timespec='seconds')} exit_code={code}\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())

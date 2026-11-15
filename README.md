# AgentWorkflow

论文 idea 讨论个人助手。结合用户的专业方向、已读论文、时间、算力和数据条件，通过论文解析、相关工作检索与多轮讨论，逐步形成有文献依据的研究问题、待验证的创新假设和最小实验方案。

当前是项目初始化框架：前端页面、配置加载、健康检查和 API 契约可运行；模型调用、论文工具、智能体执行与记忆持久化尚未实现。聊天接口当前返回明确的 `501` 提示，不生成模拟研究建议。

## 运行环境

- Python 3.10 及以上（建议 3.11 或 3.12）。
- 后端：FastAPI、Uvicorn；配置：python-dotenv。
- 前端：原生 HTML、CSS、JavaScript，使用现代浏览器，无需 Node.js 或 npm。
- 模型服务：后续按 OpenAI 兼容接口接入；当前启动不需要模型密钥。

## 目录结构

```text
AgentWorkflow/
├── backend/app/
│   ├── api/             # HTTP 路由、请求与响应结构
│   ├── agent/           # 追问、工具决策、执行循环（待实现）
│   ├── tools/           # 论文解析、论文检索、可行性检查接口
│   ├── memory/          # 会话状态与存储接口
│   ├── services/        # 模型服务适配入口
│   ├── config.py       # 从环境变量加载配置
│   └── main.py         # 应用入口，提供 API 和前端静态文件
├── frontend/           # 页面、样式与交互脚本
├── tests/              # 配置、健康检查和 API 契约测试
├── data/
│   ├── papers/         # 用户论文原文件（默认不提交）
│   ├── samples/        # 可分发的样例输入
│   ├── sessions/       # 会话状态（默认不提交）
│   └── logs/           # 执行日志（默认不提交）
├── docs/               # 架构、接口、开发任务与验收说明
├── .env.example        # 环境变量样例，仅占位值
├── requirements.txt
└── requirements-dev.txt
```

## 首次启动（Conda 环境）

以下命令均在项目根目录执行：

```powershell
Set-Location 'D:\Learning_materials\西工大\课程\边云智能实践\AgentWorkflow'
conda create -n agentworkflow python=3.11 pip -y
conda activate agentworkflow
python -m pip install -r requirements.txt
if (-not (Test-Path -LiteralPath .env)) {
    Copy-Item -LiteralPath .env.example -Destination .env
}
python -m uvicorn backend.app.main:app
```

如果使用已有 Conda 环境，跳过创建命令，将激活命令改为 `conda activate 你的环境名`，确保 Python 版本至少为 3.10。无需再创建或使用 `.venv`。上述配置复制命令会保留已有 `.env`。

命令可在支持 Conda 的 PowerShell 中执行；如果 `conda activate` 不可用，可使用 Anaconda PowerShell Prompt。需要开发测试依赖时执行 `python -m pip install -r requirements-dev.txt`，该文件已包含运行依赖。

浏览器打开：

- 页面：<http://127.0.0.1:8000/>
- 接口文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/api/health>

前端由后端同源提供，请通过上述地址访问；无需单独运行前端服务。

## 环境变量

在本机 `.env` 中填写配置；已有系统环境变量优先于 `.env`。配置文件从项目根目录读取，不依赖当前工作目录。

| 变量 | 用途 |
| --- | --- |
| `MODEL_BASE_URL` | 模型 API 基础地址，例如服务商提供的兼容地址（通常以 `/v1` 结尾） |
| `MODEL_NAME` | 服务商实际支持的模型标识 |
| `MODEL_API_KEY` | 模型服务密钥，仅保存在本机环境变量或 `.env` |
| `MODEL_TIMEOUT_SECONDS` | 未来模型请求超时秒数，默认 60 |
| `AGENT_MAX_STEPS` | 未来智能体执行步数上限，默认 8 |
| `TOOL_TIMEOUT_SECONDS` | 未来工具调用超时秒数，默认 30 |
| `DATA_DIR` | 数据目录，默认 `data`；相对路径按项目根目录解析 |

目前仅加载配置，尚未实现模型和工具调用，因此执行上限和超时配置尚未接入执行器。健康检查只报告模型配置是否填写完整，不验证模型服务连通性，也不返回密钥。`.env.example` 只含空值和非敏感默认值，真实配置与运行数据已加入 `.gitignore`。

## 验证

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

测试不调用模型服务、不需要真实密钥，覆盖配置优先级、数据路径、密钥不泄露、页面加载和待实现接口的明确响应。

## 后续开发

先实现可独立测试的论文解析与检索工具，再接入模型决策、追问与工具执行循环，最后加入会话记忆和可行性评估。设计与验收入口见 `docs/architecture.md`、`docs/api.md` 和 `docs/development.md`。

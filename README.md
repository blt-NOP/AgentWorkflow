# 论文 idea 讨论助手
## 1. 目录与阅读顺序

```text
AgentWorkflow/
  backend/
    agent.py       核心对话流程，先读这个文件
    tools.py       论文检索、材料整理两个工具
    memory.py      JSON 会话、个人文献库、日志
    model.py       一次模型 HTTP 请求
    main.py        前端调用的 FastAPI 接口
    cli.py         命令行入口，同样调用 agent.run_turn
    __init__.py    读取根目录 .env
  frontend/
    index.html     页面结构和输入框
    app.js         调用后端接口、展示回答与状态
    styles.css     页面样式
  data/
    sample_papers.json   明确标记为虚构的测试论文
    library.json         运行后生成，个人已读材料
    sessions/A.json      运行后生成，会话 A 的记忆
    logs/A.jsonl         运行后生成，每轮追加一条执行日志
  tests/check_memory.ps1 命令行逐轮演示
  requirements.txt
  .env.example
  README.md
```

## 2. 启动前后端

Python 3.10+，使用已有 Conda 环境即可，例如 `conda activate intro`。前端为原生 HTML/JS，不需要 npm。

```powershell
Set-Location 'D:\Learning_materials\西工大\课程\边云智能实践\AgentWorkflow'
conda activate intro
python -m pip install -r requirements.txt
# 已有 .env 就直接沿用，不覆盖它。
if (-not (Test-Path -LiteralPath .env)) {
    Copy-Item -LiteralPath .env.example -Destination .env
}
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

浏览器访问 <http://127.0.0.1:8000>。**这一条命令同时提供网页和 API**；接口文档为 <http://127.0.0.1:8000/docs>。

如果还运行着旧服务，先在它的终端按 Ctrl+C，再运行上面的新入口。旧的 `backend.app.main` 已归档，不再使用。

在 `.env` 填写：

```dotenv
MODEL_BASE_URL=https://你的模型服务地址/v1
MODEL_NAME=你的模型名称
MODEL_API_KEY=你的密钥
MODEL_TIMEOUT_SECONDS=60
OUTBOUND_PROXY=
DATA_DIR=data
HISTORY_LIMIT=6
```

地址、模型名和密钥只在后端读取。已有 `.env` 中多余的旧变量不会影响新代码。`HISTORY_LIMIT` 是消息条数，6 条通常约 3 轮；已有环境变量优先于 `.env`。

## 3. 一次对话到底做了什么

```text
网页发送 /api/chat ─┐
                   ├─ agent.run_turn
命令行 backend.cli ┘       ↓
                     读本会话 JSON
                           ↓
                     更新明确给出的条件
                           ↓
                     有检索词才检索论文
                           ↓
                     按当前条件整理材料
                           ↓
                     启用模型时请求模型
                           ↓
                     保存会话、打印并追加日志
```

`agent.py` 的五段注释与这条流程对应。`main.py` 和 `cli.py` 只负责接收参数，不另写一套对话逻辑。

工具由用户操作触发：网页填写检索关键词或命令行传 `--search` 才检索；材料整理每轮执行。模型负责根据材料讨论研究思路、提出追问；目前没有额外的模型自动规划或自动选择工具层。

关闭模型时，回答明确标记为“未调用模型”，只展示事实与缺项，供工具/记忆验收；它不生成科研建议。模型请求失败会报错，不伪装成功。

## 4. 网页如何使用

1. 在左侧登记已有论文，或选择 `data/sample_papers.json` 测试 JSON 导入。样例是虚构材料，不能当作科研依据。
2. 填写专业方向、命题和资源条件，输入消息后发送。
3. 要检索新论文，填写本轮检索关键词。需要研究讨论时勾选“调用已配置模型”。
4. 要更正条件，修改对应输入框，再发送消息。下方可展开本轮工具实参和结果。
5. 左侧新建、切换、查看或删除讨论。论文库由个人各会话共享，算力等事实按会话隔离。

为保持简单，**资源条件通过输入框或命令行参数明确修改**，不从聊天文本中自动猜测。前端只发送变动的字段，清空字段会发送 null；省略字段表示沿用旧值。

## 5. 只测试后端：不启动网页或服务

在项目根目录逐条执行：

```powershell
# A 写入约束
python -X utf8 -m backend.cli --session A --message "研究模型压缩" --direction "模型压缩" --compute GPU --weeks 4 --dataset "公开数据集"
# A 追问
python -X utf8 -m backend.cli --session A --message "继续讨论"
# A 明确更正
python -X utf8 -m backend.cli --session A --message "更正为CPU" --compute CPU
# 下一轮工具实参和结果应采用 CPU
python -X utf8 -m backend.cli --session A --message "根据当前条件继续"
# B 不提供约束
python -X utf8 -m backend.cli --session B --message "开始新的讨论"
# 返回 A，仍保留 CPU
python -X utf8 -m backend.cli --session A --message "返回原会话继续"
# 查看真正保存的记忆和日志
python -X utf8 -m backend.cli --session A --show
Get-Content data/sessions/A.json -Encoding UTF8
Get-Content data/logs/A.jsonl -Encoding UTF8 | Select-Object -Last 1
```

这组命令默认不调用模型、不检索网络。网页和 CLI 默认读写同一个 DATA_DIR，因此用 CLI 创建的 A 也能从网页打开。

继续执行 A 直到消息数超过 HISTORY_LIMIT，终端会显示近期条数不再增长，但完整消息数继续增加；事实仍保留。为了不依赖你已有的 `.env` 和日常数据，下面的脚本固定历史上限为 6、使用 `data/cli-check`、生成新的 A/B 测试标识：

```powershell
powershell -NoProfile -File tests/check_memory.ps1
```

真实检索和模型测试：

```powershell
# 真实联网检索 -> 材料整理 -> 写回记忆，不调用模型
python -X utf8 -m backend.cli --session Research --message "请整理相关论文" --search "edge inference model compression"
# 追加 --model 才实际调用模型
python -X utf8 -m backend.cli --session Research --message "我只有CPU，能否给出一个最小验证思路并追问缺失条件？" --compute CPU --model
```

预期工具顺序为 `search_papers → build_evidence`；无检索关键词则只运行 `build_evidence`。模型在工具执行后读取当前事实、实际材料、近期历史和本轮消息。

## 6. 记忆分类与覆盖规则

| 状态 | 写入时机 | 读取位置 | 清除或替换条件 |
| --- | --- | --- | --- |
| `facts`：方向、命题、算力、时间、数据 | 本轮明确给出字段时更新，轮末保存 | 工具实参、模型系统消息 | 新值覆盖旧值，null 清空，省略保留；不随历史裁剪；删会话清除 |
| `history`：模型近期历史 | 每轮从完整消息取最近 N 条 | 下一轮模型请求 | 超长裁掉最旧条目；删会话清除 |
| `messages`：完整聊天记录 | 每轮追加用户和助手消息 | 网页恢复、命令行查看 | 不随 history 裁剪；删会话清除 |
| `papers`：本会话检索资料 | 检索完成后保存 | 下轮材料整理 | 下次检索整体替换；删会话清除 |
| `evidence`：材料整理结果 | 每轮按当前事实、文献库及检索资料重算 | 模型、网页、日志 | 每轮替换；删会话清除。文献库改动在下一次请求重算 |
| `trace`：最新工具实参和结果 | 每轮工具完成后保存 | 网页展开、CLI 日志 | 下一轮替换；删会话清除 |
| `logs/*.jsonl`：逐轮执行档案 | 每轮成功后追加一行 | 命令行人工查看 | 不裁剪；删会话时同步清除 |
| `library.json`：个人已读材料 | 登记、编辑或导入论文 | 每轮材料整理 | 可单独删除论文；不随会话删除 |

选择“近期历史 + 独立事实”的理由：控制模型上下文长度，同时使仍有效的条件不随旧消息消失。日志记录 before、changes 和执行后的 state；不记录密钥。

这是单人、顺序请求的课程原型，不增加登录、数据库、并发事务、快照回滚或单条消息删除。网页仍能查看完整消息、切换和删除整个会话。

## 7. 前后端接口对应

| 网页操作 | 接口 | 后端实际调用 |
| --- | --- | --- |
| 服务状态 | GET /api/health | model.configured |
| 发送消息 | POST /api/chat | agent.run_turn |
| 历史讨论列表 | GET /api/sessions | memory.list_sessions |
| 打开讨论 | GET /api/sessions/{id} | memory.load |
| 删除讨论及日志 | DELETE /api/sessions/{id} | memory.delete |
| 已读论文列表 | GET /api/library | memory.library |
| 登记、编辑论文 | POST /api/library/papers | memory.save_library |
| 删除论文 | DELETE /api/library/papers/{id} | memory.save_library |

聊天请求示例：`{"session_id":"A","message":"更正为CPU","facts":{"compute":"CPU"},"use_model":false}`。返回 `reply`、`state`、`trace`。网页按同一字段渲染，不使用旧版接口。

## 8. 本次实际验证

2026-11-22 已验证：

- 浏览器实际登记论文、发送消息、修改 GPU→CPU、新建 B、返回 A 继续对话；刷新恢复使用同一套 JSON。网页 A 为 `eb8e8fef-b893-4306-98d6-3f0912dfb6b5`，B 为 `b767e4e8-247b-420e-abb4-85694688318c`；结果保存在 `data/api-check`（测试服务使用独立数据目录）。
- 命令行连续 8 次执行，A 为 `A-aeee9d2e`，B 为 `B-aeee9d2e`；实测 `PASS: A=CPU; recent=6; full=14; B has no compute; switched back to A`。完整控制台记录：[tests/last_memory_output.txt](tests/last_memory_output.txt)。
- 真实 Crossref 检索返回 3 篇文献，并继续调用材料工具。完整输出：[tests/last_search_output.txt](tests/last_search_output.txt)。
- 模型 HTTP 请求组装和响应解析已用明确的本地 HTTP 替身验证；本次没有调用真实模型。模型效果需要使用你自己的配置运行 `--model` 验收。

测试 JSON、日志不包含模型密钥；本次只使用虚构论文、测试条件和随机会话标识。日常运行仍默认使用 `data`，不会读到隔离测试目录中的会话。

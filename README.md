# 论文 idea 讨论助手
## 1. 目录与阅读顺序

```text
AgentWorkflow/
  backend/
    agent.py       核心对话流程，先读这个文件
    tools.py       论文检索、材料整理，导出多轮交互工具
    dialogue.py    多轮交互：读取 Skill、接收答案、生成问题/选项
    library.py     SQLite 论文库的查询、保存、导入、删除
    memory.py      JSON 会话和日志
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
    library.sqlite3      运行后生成，个人论文数据库
    sessions/A.json      运行后生成，会话 A 的记忆
    logs/A.jsonl         运行后生成，每轮追加一条执行日志
  skills/research-dialogue/SKILL.md   可配置提问策略
  tests/check_memory.ps1 命令行逐轮记忆演示
  tests/check_features.py SQLite 和交互工具离线验收
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
                     多轮交互工具按 Skill 追问，启用模型时生成分析
                           ↓
                     保存会话、打印并追加日志
```

`agent.py` 的五段注释与这条流程对应。`main.py` 和 `cli.py` 只负责接收参数，不另写一套对话逻辑。

检索由用户操作触发：网页填写检索关键词或命令行传 `--search` 才检索；材料整理和多轮交互每轮执行。`research_dialogue` 按 Skill 选择当前问题、生成选项；启用模型时将同一份 Skill、材料和历史交给模型生成分析。没有额外的模型自动规划层。

关闭模型时，回答明确标记为“未调用模型”，展示事实、缺项和 Skill 配置的追问；点击选项仍会真正更新条件或讨论答案，推进下一轮。它不代替模型进行科研语义分析。模型请求失败会报错，不伪装成功。

## 4. 网页如何使用

1. 在左侧登记已有论文，或选择 `data/sample_papers.json` 测试 JSON 导入。样例是虚构材料，不能当作科研依据。
2. 填写专业方向、命题和资源条件，输入消息后发送。
3. 要检索新论文，填写本轮检索关键词。需要研究讨论时勾选“调用已配置模型”。
4. 当前科研问题会显示在聊天中，下方有可点击选项卡；点击会直接发送答案并提出下一问题，也可输入文字回答。
5. 要更正条件，修改对应输入框，再发送消息。下方可展开本轮工具实参和结果。
6. 左侧新建、切换、查看或删除讨论。论文库由个人各会话共享，算力等事实、讨论答案和待答问题按会话隔离。

资源条件可通过输入框/命令行参数明确修改，也可回答工具当前提出的资源问题。程序只把文字当作当前待答问题的答案，不对任意聊天做通用条件抽取；显式参数优先于选项或文字答案。前端只发送变动字段，清空字段发送 null；省略字段沿用旧值。

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

预期工具顺序为 `search_papers → build_evidence → research_dialogue`；无检索关键词则为 `build_evidence → research_dialogue`。第三项工具在启用模型时调用 `model.reply`。

## 6. 记忆分类与覆盖规则

| 状态 | 写入时机 | 读取位置 | 清除或替换条件 |
| --- | --- | --- | --- |
| `facts`：方向、命题、算力、时间、数据 | 本轮明确给出字段时更新，轮末保存 | 工具实参、模型系统消息 | 新值覆盖旧值，null 清空，省略保留；不随历史裁剪；删会话清除 |
| `history`：模型近期历史 | 每轮从完整消息取最近 N 条 | 下一轮模型请求 | 超长裁掉最旧条目；删会话清除 |
| `messages`：完整聊天记录 | 每轮追加用户和助手消息 | 网页恢复、命令行查看 | 不随 history 裁剪；删会话清除 |
| `answers`：研究目标、基线等讨论答案 | 回答当前科研问题时保存 | 后续 Skill 问题选择、模型分析 | 切换 Skill 时重置；删会话清除；不随 history 裁剪 |
| `dialogue` 与 `skill`：待答问题、选项及策略名 | 每轮交互工具执行后保存 | 选项反馈、会话恢复 | 新轮问题替换；切换 Skill 重置问题；删会话清除 |
| `papers`：本会话检索资料 | 检索完成后保存 | 下轮材料整理 | 下次检索整体替换；删会话清除 |
| `evidence`：材料整理结果 | 每轮按当前事实、文献库及检索资料重算 | 模型、网页、日志 | 每轮替换；删会话清除。文献库改动在下一次请求重算 |
| `trace`：最新工具实参和结果 | 每轮工具完成后保存 | 网页展开、CLI 日志 | 下一轮替换；删会话清除 |
| `logs/*.jsonl`：逐轮执行档案 | 每轮成功后追加一行 | 命令行人工查看 | 不裁剪；删会话时同步清除 |
| `library.sqlite3`：个人已读材料 | 登记、编辑或导入论文 | 每轮材料整理、论文列表与详情 | SQL 删除论文；不随会话删除 |

选择“近期历史 + 独立事实”的理由：控制模型上下文长度，同时使仍有效的条件不随旧消息消失。日志记录 before、changes 和执行后的 state；不记录密钥。

这是单人、顺序请求的课程原型。仅论文库使用 SQLite，会话继续使用 JSON；不增加登录、快照回滚或单条消息删除。网页仍能查看完整消息、切换和删除整个会话。

## 7. 前后端接口对应

| 网页操作 | 接口 | 后端实际调用 |
| --- | --- | --- |
| 服务状态 | GET /api/health | model.configured |
| 发送消息 | POST /api/chat | agent.run_turn |
| 历史讨论列表 | GET /api/sessions | memory.list_sessions |
| 打开讨论 | GET /api/sessions/{id} | memory.load |
| 删除讨论及日志 | DELETE /api/sessions/{id} | memory.delete |
| 论文列表/查找 | GET /api/library?q=关键词 | library.list_papers |
| 论文详情 | GET /api/library/papers/{id} | library.get_paper |
| 登记论文 | POST /api/library/papers | library.save_paper |
| 编辑论文 | PUT /api/library/papers/{id} | library.save_paper |
| JSON 批量导入 | POST /api/library/import | library.import_papers |
| 删除论文 | DELETE /api/library/papers/{id} | library.delete_paper |
| 可选提问策略 | GET /api/skills | dialogue.list_skills |
| 独立测试交互工具 | POST /api/tools/dialogue | tools.research_dialogue |

聊天请求示例：`{"session_id":"A","message":"更正为CPU","facts":{"compute":"CPU"},"use_model":false}`。返回 `reply`、`state`、`trace`、`dialogue`。选项回答还可以传 `choice_id`，策略可传 `skill`。

## 8. SQLite 论文库

数据库位于 `DATA_DIR/library.sqlite3`，默认是 `data/library.sqlite3`，使用 Python 内置 sqlite3，无需安装数据库服务。只有一张业务表 `papers`：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| paper_id | TEXT 主键 | 论文唯一编号 |
| title | TEXT | 标题 |
| year | INTEGER | 年份，可空 |
| doi | TEXT | DOI，去掉 doi.org 地址前缀并统一小写；重复 DOI 保存为同一条记录 |
| abstract | TEXT | 摘要或已读原文段落 |
| notes | TEXT | 用户阅读笔记，和论文原文分开保存 |
| created_at | TEXT | 首次添加时间 |
| updated_at | TEXT | 最近修改时间 |

前端新增使用 POST，编辑使用 PUT，导入一次提交论文列表；后端使用 SQL 增删改查，不再读取/覆盖整份 JSON 文库。`agent.py` 每轮从 SQLite 读取个人文献。

如果当前 DATA_DIR 存在旧 `library.json`，首次访问文库时自动迁入 SQLite，保留原文件作备份。数据库用 `PRAGMA user_version=1` 标记迁移已完成，不会在删除论文后从旧 JSON 再导回来。迁移和批量导入遇到错误会回滚。

## 9. 新增工具：research_dialogue 与 Skill

目前共有三项工具：

| 工具入口 | 输入与返回 | 数据/失败行为 |
| --- | --- | --- |
| tools.search_papers | query、limit → 实际论文列表 | Crossref，HTTP 超时30秒；失败报错，不伪造论文 |
| tools.build_evidence | papers、facts → facts、rows、gaps | 读取实际材料，纯本地整理 |
| tools.research_dialogue | state、message、skill_id、use_model → message、question、options、stage、field、target、skill | 读取 Skill 和本会话状态；错误 Skill/过期选项明确报错；启用模型时使用模型超时配置 |

多轮交互的实际入口实现在 `backend/dialogue.py`，由 `tools.py` 导出，并已在 `agent.run_turn` 每轮调用、写入 trace。`accept_answer` 在材料工具执行前接收上一轮答案，因此选中 CPU 后，本轮材料工具就会收到 CPU。

- `facts` 保存算力、时间等条件；`answers` 保存研究目标和基线等讨论答案。
- `dialogue` 保存当前问题和选项，网页恢复会话后仍可点击。
- 选项只能回答当前会话当前问题，失效编号返回错误；本轮明确给出的条件优先。
- 仅更改事实不会自动把这条“更正”消息当作另一个科研问题的答案。

提问策略为项目内的 [skills/research-dialogue/SKILL.md](skills/research-dialogue/SKILL.md)，不是全局 Codex 配置。应用每次请求直接读取它。

Skill 的 Markdown 指令影响模型分析方式；JSON 块中的 `questions` 控制实际问题顺序，`target` 指向 facts 或 answers，`field` 指定保存位置，`options` 定义按钮标签和保存值。问题顺序默认是方向 → 算力 → 时间 → 数据 → 研究目标 → 对照基线；已回答的跳过。

例如，将 weeks 问题放到 compute 前面，下次遇到同时缺少时间和算力的会话，就会先问时间。修改 question 可改变问题文本；修改 options 可改变选项。调整后无需重启服务。增加策略时新建 `skills/策略名/SKILL.md`，网页重新加载后可选，CLI 可用 `--skill 策略名`。

直接从命令行连续使用新工具：

```powershell
# 第一次会询问算力，并打印 compute-0 等选项编号；重复演示时换一个新会话名。
python -X utf8 -m backend.cli --session IdeaDemo --direction "模型压缩" --message "请帮助我确定选题" --skill research-dialogue
# 选 CPU，随后自动询问时间；选择值会进入 facts
python -X utf8 -m backend.cli --session IdeaDemo --message "只有 CPU" --choice compute-0
# 再选4周，自动进入数据问题
python -X utf8 -m backend.cli --session IdeaDemo --message "4 周" --choice weeks-1
```

网页点击选项就是发送相同的 message 和 choice_id。开启模型后，Skill 先确定追问，模型负责基于真实材料分析，工具将分析、问题和选项一并返回。

独立工具接口 `POST /api/tools/dialogue` 不写会话；例如请求 `{"facts":{"direction":"模型压缩"},"use_model":false}`，返回算力问题与选项，可用于单独复测。

## 10. 当前版本实际验证

```powershell
python -X utf8 tests/check_features.py
powershell -NoProfile -File tests/check_memory.ps1
```

2026-11-22 新功能离线验收实际输出 `RESULT: PASS (23 checks)`。覆盖旧文库迁移及不重复迁移、增删改查、DOI 去重、批量导入回滚、读取 SQLite 进入工具、多轮按钮/文字回答、历史裁剪、条件更正、会话隔离、替换 Skill 改变提问顺序、Skill 传入模型请求。控制台记录：[tests/last_features_output.txt](tests/last_features_output.txt)。详细响应与摘要：`data/feature-check/run-76dbef54/responses.json` 和 `summary.json`。

浏览器实际验证了新增/编辑论文笔记、点击 CPU → 4周 → 公开数据集 → 推理延迟、下一问推进到基线、切换会话后恢复选项。测试数据为虚构材料，独立 SQLite 位于 `data/feature-check/ui-20261122/library.sqlite3`。本次未调用真实模型；模型请求的 Skill 和消息组装由明确 HTTP 替身验证。Skill 格式校验输出 `Skill is valid!`。

原有记忆命令行演示也已复测：A=`A-7379cf8b`，B=`B-7379cf8b`；输出 `PASS: A=CPU; recent=6; full=14; B has no compute; switched back to A`，并确认 trace 中实际包含新工具。控制台记录：[tests/last_memory_output.txt](tests/last_memory_output.txt)。

真实 Crossref 检索返回 3 篇文献，接着实际执行 `build_evidence → research_dialogue` 并给出算力选项。控制台记录：[tests/last_search_output.txt](tests/last_search_output.txt)。

验收脚本可能显示现有 Starlette TestClient 的 httpx 弃用提示，本次23项检查均通过。测试日志不包含模型密钥。日常运行默认使用 `data`，不会读到隔离测试目录中的会话。

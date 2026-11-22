# 百炼模型接入与工具决策

当前默认使用本地.env中的qwen3.7-plus，通过百炼OpenAI兼容Chat Completions接口调用。不安装模型SDK，不增加智能体框架。密钥仅保存在被Git忽略的.env，前端不接收密钥。MODEL_BASE_URL为北京兼容地址；地域与账号权限不同可自行修改，不自动切换到其他计费端点或模型。

## 阅读代码的顺序

1. `backend/model.py`：统一HTTP适配，发送messages/tools，返回模型消息和usage；处理超时、响应校验、输出截断、有限重试。不输出Authorization、原始上游错误和推理过程。
2. `backend/planner.py`：一个有上限的for循环。模型通过原生tool_calls选择工具，Pydantic校验工具参数，注册表中的真实函数执行，随后以相同tool_call_id回传结果。模型可以继续选工具或返回最终JSON。
3. `backend/agent.py`：加载会话、接收选项与明确条件、更正事实、调用决策循环、写回会话和日志。use_model=false时走显式离线演示，不伪装为模型分析。
4. `backend/main.py`与`backend/cli.py`：网页和CLI调用同一个run_turn。前端显示状态、请求编号和结构化方案。

## 配置

```dotenv
MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL_NAME=qwen3.7-plus
MODEL_API_KEY=在本地填写
MODEL_ENABLED=true
MODEL_MAX_TOKENS=4096
MODEL_TIMEOUT_SECONDS=60
MODEL_RETRIES=1
AGENT_MAX_STEPS=6
```

qwen3.7系列发送enable_thinking=true；模型推理内容仅在必要的同轮协议中往返，不写历史或测试证据。max_tokens包含模型受限制的输出，出现finish_reason=length明确报MODEL_OUTPUT_LIMIT，不把截断结果当作成功。模型配额1M不等于每次输出1M；本程序记录usage，不查询账号剩余额度，也不保证一定走赠送额度，实际计费以百炼控制台为准。

默认最多6次决策请求、6项工具调用。每次模型请求可因网络、超时、429或5xx额外重试1次；401/403等不可重试错误立即返回。MODEL_RETRIES允许0—2，AGENT_MAX_STEPS限制1—12；这是有限次数和网络操作超时，不是整个请求墙钟时间保证。论文检索失败回传错误，模型可在剩余步骤内调整或请用户补充。相同状态与参数的成功工具调用不重复执行；材料变化后允许重建证据。

## 模型如何选择工具

| 入口 | 模型看到的参数 | 后端实际执行 |
| --- | --- | --- |
| search_papers | query、limit | 调用注册检索函数，实际结果写入本轮会话papers |
| build_evidence | paper_ids；空列表表示全部材料 | 将ID解析成文库/检索中的真实论文，再使用当前会话facts调用原函数；模型不能传入虚构论文或旧资源条件 |
| research_dialogue | 空对象 | 注入本会话facts、answers、evidence、history及Skill，返回待答问题和选项；本工具在决策循环中use_model=false，避免重复嵌套模型调用，最终分析由外层真实模型生成 |
| parse_paper_pdf | 用户通过上传接口提供文件与页码 | 仍在统一注册表；PDF二进制由上传入口执行，不作为可任意读取服务器路径的聊天工具。解析并核对入库后，模型可选择其材料 |

模型请求必须引用前面实际返回的论文标识。每项trace同时记录model_arguments与实际arguments，解释ID如何变为真实论文、facts如何取当前记忆。没有资料时可以先追问；有资料且条件齐全时可以只整理材料并完成，不要求每轮固定调用全部工具。

显式条件优先：页面资源字段、CLI参数和上一轮问题的答案用于更新facts。当前版本不对任意聊天自动抽取并覆盖所有资源字段；只在聊天里说“更正为CPU”但未回答算力问题时，应同步修改条件字段或使用--compute CPU。

## 任务结束判断

模型返回JSON：`{"status":"WAITING_USER或COMPLETED","reply":"正文","proposal":null或方案对象}`。支持去除外层Markdown JSON围栏，但不会用自由文本猜测完成状态；校验不通过时反馈模型，在同一预算内修正。

| 状态 | 判断与保存 |
| --- | --- |
| WAITING_USER | 需要用户补充、选择或提供材料；保存当前问题及选项，下轮继续同一session_id |
| COMPLETED | Skill所需信息已填写且不是“尚未确定/尚无数据/还不确定”；本轮成功执行build_evidence；存在原文或摘要摘录；proposal字段完整，引用全部属于本轮有文字证据的row.id |
| STOPPED | 达到步数/工具数上限，stop_reason=STEP_LIMIT；不宣称完成，可在原会话继续 |
| FAILED | 模型网络等异常；返回错误和request_id，保存失败轨迹，不覆盖原会话状态 |

完整proposal包含research_question、hypothesis、method、experiment、metrics、risks、next_steps七个非空字符串，以及references证据ID列表。后端验证结构和来源归属，不自动证明方案在科学上成立、引用充分或创新性已验证。点击“尚未确定”并不会通过完成守卫；用户仍需更正相应条件。

COMPLETED只结束本次任务，不清理会话。更正条件后再次执行时重新决策和检查材料，不直接返回旧方案。回复与proposal、执行轨迹一起保存；近期模型历史继续受HISTORY_LIMIT限制。

### 统一判断条件是否有效

`backend/tool_contracts.py::condition_is_valid(field, value)`是唯一判断入口，追问工具、材料缺项检查和完成守卫共同使用，不再分别判断字符串是否非空。

| 值 | 是否已明确 |
| --- | --- |
| 缺失、null、空字符串或纯空白 | 否 |
| 尚未确定、还不确定、不确定、未知、尚无数据、未确定（忽略首尾空白） | 否，允许保存在记忆中，但不能跳过问题或通过完成守卫 |
| CPU、GPU等其他非空文本 | 是；这只表示回答明确，不证明资源或方案已经核实 |
| weeks为1—520的整数 | 是；布尔值、字符串和越界值不算有效周数 |

例如选择compute-2后，facts.compute仍保存“尚未确定”，dialogue.field仍为compute，evidence.gaps仍含“缺少算力条件”。用户在当前问题输入CPU或选择compute-0后，值覆盖为CPU，缺项消失，其他资源齐全时下一题转为goal。只填CPU不代表任务立即完成，还需满足其他Skill问题和真实证据要求。

独立复现：`python -m backend.run tests/check_conditions.py`。实际32项通过，无前端、服务或真实模型调用。覆盖规则边界、真实CLI四轮、工具实参与返回值、未知条件阻止完成、明确更正后允许完成。结果位于`data/model-check/conditions-27bff624/`；固定证据见`tests/model_results/conditions/`，包括cli-rounds.json、completion-guard.json、summary.json、四轮CLI输出和整次运行日志。模型守卫部分使用明确的模型替身；真实CLI部分显式--no-model，不消耗百炼额度。

## 接口与日志

`POST /api/chat`保留原字段：session_id、message、facts、search、use_model、skill、choice_id。use_model省略时使用MODEL_ENABLED，显式false可离线；不传密钥。返回新增request_id、status、stop_reason、proposal、decisions，并保留reply/state/trace/dialogue。

```json
{"session_id":"QwenDemo","message":"请根据CPU条件重新评估方案","facts":{"compute":"CPU"},"use_model":true}
```

成功和失败日志均在`DATA_DIR/logs/会话ID.jsonl`，以request_id串联。工具记录call_id、名称、模型参数、实际参数、状态、结果/错误、duration_ms；decisions记录模型轮次、usage、服务请求ID、耗时、尝试次数和格式校验结果，不保存私有推理过程。使用backend.run时另保存整次终端日志到`data/logs/runs/`。HTTP异常detail包含code、message、retryable和request_id；请求体在进入agent前校验失败时request_id可能为空。

## 复现命令

```powershell
# 日常启动，网页默认启用模型
python -m backend.run
# 不启动服务和网页，直接真实对话；资源缺失应追问
python -m backend.run -m backend.cli --session QwenDemo --direction "模型压缩" --message "请先确认我的资源条件" --model
# 按上一轮打印的选项回复，编号必须属于当前问题
python -m backend.run -m backend.cli --session QwenDemo --message "只有CPU" --choice compute-0 --model
# 明确更正
python -m backend.run -m backend.cli --session QwenDemo --message "算力改为GPU，请重新评估" --compute GPU --model
# 仅做离线记忆/工具演示
python -m backend.run -m backend.cli --session OfflineDemo --message "开始讨论" --no-model
# 模型决策协议离线验收，使用明确替身，不消耗模型额度
python -m backend.run tests/check_model.py
# 原工具、记忆和文库回归，不调用真实模型
python -m backend.run tests/check_tools.py
powershell -NoProfile -File tests/check_memory.ps1
python -m backend.run tests/check_features.py
# 显式真实模型四轮验收，会消耗额度，使用隔离文库和新会话
python -m backend.run tests/check_model_live.py
```

离线决策用例覆盖实际三步依赖、调用标识回传、缺条件追问、完整方案结束、更正后重算、提前完成拒绝、虚构引用拒绝、非法工具/参数纠错、重复调用阻止、步数上限、失败不覆盖会话、HTTP重试与错误脱敏。生成的脚本模型输出只是教学测试数据，不计入真实模型效果。

## 已取得的真实证据

2026-11-22最小请求成功返回OK，usage.total_tokens=191。真实四轮验收使用`data/model_papers.json`中的GPTQ摘要要点转述（来源为arXiv实际页面，并明确不是全文/逐字引文），不使用虚构论文充当真实研究材料。

会话Live-8ef68532：

| 轮次 | 输入 | 实际工具顺序 | 状态 |
| --- | --- | --- | --- |
| 1 | 已知GPU/4周/公开数据，先确认目标与基线 | build_evidence → research_dialogue | WAITING_USER，追问goal |
| 2 | 选择推理延迟 | research_dialogue | WAITING_USER，追问baseline |
| 3 | 确认已有基线，请生成方案 | build_evidence | COMPLETED |
| 4 | 将GPU更正为CPU，重新评估 | build_evidence，实参compute=CPU | COMPLETED |

四轮记录usage.total_tokens合计39300（含重复输入与缓存计数，非账户实际扣减余额）。`data/model-check/live-a56dc0ea/turns.json`保存每轮实参与实际响应，summary.json保存请求ID、工具顺序和用量；会话history最终6条、完整messages8条。第一轮/第二轮发生过最终JSON校验反馈，模型在步骤预算内修正，记录不是一次成形的理想输出。最新代码兼容外层JSON围栏并记录校验字段位置，固定四轮证据保留实际当时的结果。

最终离线决策实际21项通过（含材料变更重建与JSON围栏兼容）；四工具42项通过；原SQLite与交互23项通过；记忆回归A/B隔离、CPU更正及history=6/messages=14通过。最终提示词改为提供合法的WAITING_USER JSON示例，避免示例中的“或”被原样输出；最终真实冒烟FinalSmoke在两次模型请求后成功WAITING_USER，没有格式校验重试，usage合计4122。固定证据整理在`tests/model_results/`，其中final-smoke保存最后一次实际状态和终端输出；不包含.env、密钥、数据库、Authorization或私有推理内容。

依据：[百炼兼容接口及地域地址](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)、[Chat Completions与tool_call_id](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions/)、[GPTQ原始来源](https://arxiv.org/abs/2210.17323)。

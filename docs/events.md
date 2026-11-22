# 后端事件与前端执行进度

对应任务五第2项和任务六第2项：执行阶段实时可见、文本真实增量展示、最终结构化结果在校验和保存后交付、每次响应固定归属原会话与请求。

## 实现与入口

新增 `POST /api/chat/stream`（SSE），原 `POST /api/chat`（完整JSON）继续兼容。两个入口都调用 `agent.run_turn`，没有另写一套智能体。依赖清单不变，不引入前端框架或消息服务。

| 文件 | 职责 |
| --- | --- |
| backend/agent.py | 产生带请求编号、会话编号、序号的事件；成功后保存状态再发送completed，失败时发送failed并保留日志 |
| backend/planner.py | 发出模型与工具阶段事件，校验草稿；模型模式可选择真实流式HTTP |
| backend/model.py | 向百炼发送stream=true、stream_options.include_usage=true，拼装流式工具名/参数和完整消息；仅正文进入回调，私有推理不进入事件 |
| backend/events.py | 有界队列连接后台执行与SSE；提供JSON reply字段的增量读取，正确处理转义和Unicode分片 |
| frontend/stream.js | fetch响应流读取、UTF-8与SSE边界处理、序号及归属验证，无npm依赖 |
| frontend/app.js | 请求快照、按会话互斥、进度列表、回复草稿、最终状态，以及切换会话后的结果归属 |

服务中的有界队列只是同步智能体与HTTP流之间的传输桥，不是额外的任务调度系统。等待期间每5秒发送SSE心跳注释，不伪造执行阶段或百分比。

## 请求与事件协议

请求为JSON，字段沿用聊天接口；新增可选request_id（1—64位字母、数字、下划线、短横线）。前端发送前用crypto.randomUUID生成并保存，省略时由后端生成。session_id、message必填；facts仅发送变化字段，use_model=false可独立离线测试。

```json
{
  "session_id": "EventDemo",
  "request_id": "EventDemo-1",
  "message": "请先确认我的资源条件",
  "facts": {"direction": "模型压缩"},
  "use_model": true
}
```

响应为 `text/event-stream; charset=utf-8`。每个事件的data是JSON，包含type、seq（本次请求从1连续递增）、request_id、session_id、at、data。SSE的id字段等于seq。

```text
id: 1
event: started
data: {"type":"started","seq":1,"request_id":"EventDemo-1","session_id":"EventDemo","at":"时间戳","data":{"use_model":true}}

```

| 事件 | 含义及主要数据 | 页面行为 |
| --- | --- | --- |
| started | 已开始处理；use_model | 显示开始与请求编号 |
| model_started | 第step次模型决策 | 显示正在决策 |
| model_result | 模型响应已到；tool_names、duration_ms | 显示已选工具或正在校验回复 |
| tool_started | 工具即将执行；tool、call_id、step | 显示对应工具处理中 |
| tool_result | 工具返回；result、duration_ms及调用编号 | 显示该步骤已返回，最终结果仍待整轮结束 |
| tool_failed | 本步失败；error/code及调用编号 | 显示失败，模型可在预算内修正 |
| reply_reset | 新决策、重试、校验拒绝或整轮失败 | 清除上一段草稿，避免重复或无效内容留在界面 |
| reply_delta | 来自百炼实际content分片中的reply正文；text、draft=true | 逐步追加正文，标注“尚未确认” |
| reply_ready | 完整回复已通过后端流程；reply、status | 用已确认正文替换草稿，等待保存 |
| completed | 已保存的完整聊天响应，包含status/stop_reason/state/trace等 | 展示最终消息、方案或待答选项，解锁原会话 |
| failed | 整轮失败；code、message、retryable | 清除草稿、显示错误与请求编号、解锁原会话 |

completed表示“本次请求已结束并保存”，不等于研究任务一定完成；data.status可能为WAITING_USER、COMPLETED或STOPPED。必须查看status和stop_reason。failed是终止事件，之后没有completed。

文本增量来自真正的模型SSE，不是在结果完成后加sleep模拟打字。模型最终输出是JSON，因此只提取其中reply字符串已经到达的部分；完整方案仍待校验。草稿可能被撤回，不写入正式messages。正常记录的state.events保留已发进度和草稿事件；completed的完整状态不递归嵌入自己的events列表。日志顶层status/stop_reason及同一request_id记录最终结论。

离线模式不调用模型，真实工具阶段仍即时推送，现成的规则回复在reply_ready一次交付，不声称离线回复也是模型token流。

参数或会话标识在建流前无效，返回正常HTTP400/422 JSON。流已经建立后不能更改HTTP状态：工具/模型失败通过HTTP200响应内的failed事件表示，客户端不能只凭HTTP200判成功。私有推理和Authorization不出现在事件或证据中。

## 会话与请求归属

发送前将request_id、session_id、请求实参快照固定到前端Map。后续事件使用该快照，不能读取已切换的全局sessionId替换请求归属。

- 同一浏览器中同一会话的请求未结束时，发送、选项及资源修改被禁用，防止快速重复提交。
- 允许执行中创建或切换其他会话；旧请求继续存入原请求记录，只在当前选择的会话和最新请求均匹配时更新页面。
- 返回原会话时恢复仍在执行的进度或从后端载入已保存的结果。
- 读取器同时检查事件顶层编号、连续序号和completed.state.session_id，拒绝错会话、错请求或不完整响应。
- SSE连接意外结束且没有completed/failed时显示中断，不误判成功，不自动重发。浏览器关闭/断线后后台可能继续完成，用户应重新打开原会话核对；当前未实现服务端取消、断点续传或请求幂等缓存，request_id仅为关联标识。

同一浏览器可在不同会话分别执行；本课程原型仍不提供跨浏览器同会话并发写入保护。

## 可执行复现

```powershell
# 正常启动，网页发送消息自动走新事件接口
python -m backend.run
# 后端真实HTTP协议验收：脚本临时启动本机后端，不打开前端、不调用云模型
python -m backend.run tests/check_events.py
# 前端读取协议验收，不启动服务或浏览器，无需npm
node tests/check_stream_frontend.js
```

命令行直接观察事件时，先运行服务，再新开终端：

```powershell
$body = @{ session_id='EventDemo'; request_id=('Event-' + [guid]::NewGuid().ToString('N')); message='开始讨论'; facts=@{direction='模型压缩'}; use_model=$false } | ConvertTo-Json -Depth 10
$body | Set-Content -LiteralPath data/event-input.json -Encoding utf8
curl.exe -N -X POST http://127.0.0.1:8000/api/chat/stream -H "Content-Type: application/json" --data-binary '@data/event-input.json'
```

预期离线顺序：started → tool_started(build_evidence) → tool_result → tool_started(research_dialogue) → tool_result → reply_ready → completed。改用use_model=true时，实际工具顺序由模型决定，同时出现model_started/model_result及真实reply_delta。可在/docs查看SSE接口请求结构。

## 实际测试与证据

2026-11-22：

| 验证 | 实际结果 |
| --- | --- |
| check_events.py | PASS，32项；真实本机HTTP，模型边界为明确的SSE替身 |
| check_stream_frontend.js | PASS，7项；UTF-8单字节分片、CRLF、心跳、归属、序号、中断及失败 |
| 既有回归 | 四工具42项、模型决策21项、SQLite与交互23项通过；统一条件32项在事件改造后通过 |
| 浏览器真实模型 | request=25582790-05a2-4249-bb25-27449733ed02，原会话6d58891b-7e21-431f-9b96-d06d02687fc9；收到15个正文增量，最终WAITING_USER；usage合计4098 |
| 浏览器切换 | 模型执行期间新建会话a2a02ca6-9512-4c30-a90e-4fadcee33210，其页面没有原会话事实或回复；返回原会话显示对应进度、回复和算力选项 |
| 浏览器继续 | 关闭模型后点击CPU，request=e1333849-1ebb-47d9-a1c9-beb0471d380c；显示材料与追问进度，facts.compute=CPU，下一问题为weeks |

HTTP测试使用门闩阻止材料工具结束：客户端先收到started与tool_started后才释放工具，证明事件并非任务结束后集中返回。另覆盖更正条件、A/B隔离、工具超时与恢复、流式工具参数拼接、正文与Unicode、撤销无效草稿、模型流中断有限重试及不输出私有推理。节点脚本使用合成响应，不代表浏览器完整端到端测试。

固定证据：`tests/event_results/http/`保存实参、逐项事件与汇总；`frontend-output.txt`保存前端协议测试输出；`ui/live-state.json`保存真实模型状态，`ui/cpu-state.json`保存页面继续后的状态，`ui/progress.png`为实际截图。运行日志在`data/logs/runs/`，隔离原始数据在`data/model-check/events-4b5c6347/`和`events-ui/`。本次验证覆盖本任务的进度和归属，不宣称已完成任务七全部窄屏、故障和源码复现验收。

依据：[百炼流式输出协议](https://help.aliyun.com/zh/model-studio/stream)。

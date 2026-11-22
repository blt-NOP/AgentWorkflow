# 超时、重试和完整恢复验收

## 实现

- 前端聊天总期限默认180秒（`CHAT_TIMEOUT_SECONDS`），覆盖连接、工具和正文生成；无网络数据期限默认45秒（`STREAM_IDLE_SECONDS`），心跳不能延长总期限。普通接口（含PDF上传）前端30秒。超时取消HTTP读取、清除草稿、解除发送锁，显示原因、原请求编号及“核对原会话并重试”。不自动无限重试。
- 重试先GET原会话：若`state.request_id`属于本次重试链的请求编号，直接恢复已保存结果，不再POST；否则用新请求编号发送原始消息、事实修改、选项、检索词、Skill与模型开关。修改表单不会改变重试输入；用新输入请直接发送新消息。
- 后端`agent.py`对同一会话使用非阻塞锁，原任务仍在执行时返回`SESSION_BUSY`，稍后再核对。成功和失败后均释放锁。用于当前单进程课程服务，不提供跨多进程锁或完整幂等请求账本。
- 事件、最终JSON、会话GET均核对归属；A的晚到事件或超时不会改变B页面，返回A可恢复其重试入口。收到终态即结束读取，不等连接关闭。
- `pdf_parser.py::parse_paper_pdf`仍是注册入口，实际pypdf解析在独立spawn进程执行。`PDF_TIMEOUT_SECONDS`默认20秒，上限120秒。到期终止并回收子进程，抛出`ToolError('TIMEOUT', 原因, True)`；上传接口返回HTTP504与`detail.code/message/retryable`。解析不写库，恢复期限或更换文件/页码后可独立复测。20MiB、500总页/20选中页、48000字符限制继续生效。

前端停止等待不等于后端撤销任务，后端可继续保存原会话结果。刷新后进度及重试对象不跨刷新保留，已保存历史仍可读取。核对结果匹配当前会话最后的request_id，不把后续其他请求的结果冒充原请求。PDF进程启动和解析共用期限，清理可能有少量调度开销，不是对操作系统进程创建本身的实时保证。

## 命令与实际输出

在项目根目录、已安装requirements的Conda环境执行：

```powershell
python -m backend.run tests/check_tools.py
python -m backend.run tests/check_recovery.py
python -m backend.run tests/check_events.py
node tests/check_stream_frontend.js
node tests/check_frontend_recovery.js
```

| 命令 | 实际输出 | 判定重点 |
| --- | --- | --- |
| check_tools.py | PASS 45/45 | 4项工具；PDF超时、HTTP504、恢复期限后同文件成功 |
| check_recovery.py | PASS 8 checks | 故障→原状态保留→恢复依赖→原会话成功；同会话并发拒绝后可继续；B隔离 |
| check_events.py | PASS 32 checks | 真实HTTP事件、增量正文、错误终态、流重试与归属回归 |
| check_stream_frontend.js | PASS 8 checks | 序号、归属、断流、UTF8、无数据超时取消读取 |
| check_frontend_recovery.js | PASS 8 checks | 真实app.js配最小DOM/HTTP替身；超时解锁、固定输入重试、原结果恢复、晚到事件 |

命令行测试不代替真实浏览器验收。`backend.run`每次保存终端输出到`data/logs/runs/`，脚本输出ARTIFACTS指向当次实参、事件、返回值和判定记录。固定归档位于`tests/recovery_results/`。

## 浏览器完整恢复过程（2026-11-22）

使用独立服务`tests/recovery_server.py`，未调用云模型。只替换材料工具依赖边界，前端、SSE、保存和重试为生产代码。服务仅用于隔离验收：

```powershell
python -m backend.run tests/recovery_server.py
# 浏览器打开 http://127.0.0.1:8014；在新终端恢复依赖：
Set-Content -LiteralPath data/model-check/recovery-ui/fault.txt -Value ok -Encoding utf8
# 或制造页面超时（工具4秒返回，测试页面总期限2秒）：
Set-Content -LiteralPath data/model-check/recovery-ui/fault.txt -Value slow -Encoding utf8
```

1. 启动默认`fail`：方向“模型压缩”、算力“CPU”、消息“根据当前条件继续”。发送后页面显示“测试注入：文献依赖超时，请恢复依赖后重试”，发送按钮恢复、重试按钮出现。失败request_id=`acabee88-6823-4d7f-aabb-d7293dbc79c0`。
2. 控制文件改`ok`，点击重试。原会话`8d8897b3-03fc-41ee-935c-99d9998eac17`成功，request_id=`ff79ccb7-1d5b-41aa-b466-5af656124bd3`，保存CPU并追问周数。见`failure.png`→`recovered.png`及对应UI文本。
3. 改`slow`再次发送。页面实际显示“本轮等待超过2秒，已停止等待”，恢复控件和重试入口。request_id=`2a8f23bb-7f4e-43f7-b525-921d4656f151`，见`timeout.png`。
4. 后端4秒后成功，再点击重试。页面显示“原请求已保存，已恢复结果，无需重复执行”，request_id仍相同，原请求只写入一轮，没有重新POST。见`late-recovered.png`、状态和日志。
5. 再发慢请求并立即新建B `928f3135-8230-4987-915f-e5363efe79ac`。A超时后B仍为空，无CPU、A回复或A重试入口；返回A能核对原结果。见`session-b-ui.txt`与`session-return-ui.txt`。

故障开关只存在于测试脚本，生产接口不提供故障注入入口。结束后Ctrl+C退出测试服务，正常服务仍使用`python -m backend.run`。

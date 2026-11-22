# 四项工具的实现、接口与独立测试

本说明对应当前统一前后端版本。工具是四个普通 Python 函数；会话管理、论文库 CRUD 和模型 HTTP 适配是支撑模块，不另计为工具。第四项PDF解析的完整四行说明表、接口、命令和验收见 [pdf_tool.md](pdf_tool.md)。模型自主选择工具、有限重试和完成守卫见 [model_agent.md](model_agent.md)；本文件的独立测试仍默认不调用模型。下文原三工具27项历史验收记录保留，不代表新增PDF后的总检查数。

## 一、后端注册与明确入口

唯一注册表为 `backend/tools.py::TOOL_REGISTRY`。`agent.run_turn`、独立工具接口和测试均从该表取得同一函数。`GET /api/tools` 返回注册名称及函数入口：

| 工具名 | 可直接调用的函数 | 独立后端接口 |
| --- | --- | --- |
| search_papers | backend.tools.search_papers | POST /api/tools/search |
| build_evidence | backend.tools.build_evidence | POST /api/tools/evidence |
| research_dialogue | backend.dialogue.research_dialogue，由 tools.py 导出 | POST /api/tools/dialogue |
| parse_paper_pdf | backend.pdf_parser.parse_paper_pdf，由 tools.py 导出 | POST /api/tools/parse-pdf，multipart上传 |

测试文件为 `tests/check_tools.py`。它直接调用注册函数，并用 TestClient 验证真实接口映射；不运行 Uvicorn、不打开前端，也不调用模型。所有用例中的 `model.reply` 都被禁止调用，并在 summary 记录 `model_calls=0`。

## 二、按任务表填写的工具说明

### 工具1：论文检索 search_papers

| 工具说明项 | 本项目实现 |
| --- | --- |
| 用途与选择条件 | 用于从检索关键词获取相关论文题录；适合补充候选材料，需要关键词与可用网络。已有足够材料时可跳过。Crossref 可能不提供摘要，也不保证全文；本工具不判断论文结论或选题创新性。职责是“获取材料”，与第二项“整理材料”区分。 |
| 参数与返回 | `query: str` 必填，非空白、1–500字符；`limit: int` 可选，默认3，范围1–20，单位“篇”。返回论文列表，每篇包含 `title: str`、`year: int或null`、`doi: str`、`abstract: str`；缺失摘要为 `""`，缺失年份为null。DOI 是外部文献标识。第二工具读取论文的 title、doi、year、abstract。函数额外有仅供测试注入的 keyword-only `transport`，默认None，不通过HTTP接口暴露。 |
| 数据与副作用 | 数据来自真实 Crossref `/works`。函数不写数据库、会话或日志，不修改输入；重复调用会再次检索，外部数据与排序可能变化。完整聊天流程另由 agent 保存结果。离线测试明确使用虚构 HTTP 响应，真实联网模式单独标明，不使用静默假数据兜底。 |
| 失败行为 | 参数无效抛 `ToolError(code=INVALID_INPUT, retryable=false)`；无结果成功返回 `[]`。超时为 TIMEOUT，连接失败为 NETWORK_ERROR，上游非200为 EXTERNAL_ERROR，响应结构异常为 INVALID_RESPONSE。网络/超时/格式异常可重试；HTTP429或5xx可重试，其他上游状态不标记可重试。httpx 连接、读取、写入等单次网络操作超时均设30秒，未实现整个工作流的墙钟总超时，不自动重试。 |

### 工具2：材料整理 build_evidence

| 工具说明项 | 本项目实现 |
| --- | --- |
| 用途与选择条件 | 把检索或已读论文转成可展示、可传给交互工具的证据材料，检查资源缺项；每轮按当前事实重新运行。只整理输入，不联网、不做模型语义判断；仅有题名时不能推断研究效果。职责是“材料标准化与缺项检查”。 |
| 参数与返回 | `papers: list[dict]` 必填，可为空；每篇必填非空白 `title`（1–1000字符），可选 `year`（1000–2200或null）、`doi`（≤1000字符）、`abstract`（≤50000字符）、`notes`（≤10000字符）。`facts: dict` 必填，可为空，支持 direction、claim、compute、weeks、dataset；weeks为1–520的整数或null，单位周，其他为文本或null（claim≤2000，其余≤1000）。返回 `facts`副本、`rows`列表、`gaps`文本列表。每行含 id、title、year、doi、notes、excerpt。id 优先取 DOI，缺失时取题名；按同一输入标识去重。第三工具读取整个返回值作为 state.evidence。 |
| 数据与副作用 | 输入来自第一工具的实际返回或 SQLite 已读材料。函数纯本地执行，不写入存储、不修改输入；相同输入得到相同输出。DOI 字符串的规范化由文库写入层负责，本工具仅按收到的 DOI/题名比较。notes 与原文摘录分开保留。 |
| 失败行为 | 论文缺 title、papers不是列表、字段类型或范围无效，抛 INVALID_INPUT，retryable=false。空论文列表是正常结果：rows=[]，gaps含“暂无论文，请导入已有论文或检索”。缺少 compute/weeks/dataset 时分别增加缺项，不当作执行失败；缺摘要在 excerpt 中说明。没有外部调用，无网络等待。 |

### 工具3：科研多轮交互 research_dialogue

| 工具说明项 | 本项目实现 |
| --- | --- |
| 用途与选择条件 | 将科研问题呈现为一句追问与可点击选项，按 Skill 优先补资源条件，再问研究目标和基线。适合逐轮澄清，不替代实验验证或创新性判断。关闭模型仍可独立执行规则追问；启用模型才生成语义分析。职责是“讨论推进”，与检索/材料整理区分。 |
| 参数与返回 | 函数必填 `state: dict`、`message: str`（非空白、1–10000字符）；可选 `skill_id: str` 默认 research-dialogue，须为1–64位小写字母/数字/短横线，且对应 Skill 存在；`use_model: bool` 默认false。state必含facts及evidence（rows、gaps列表），answers对象、history消息列表可省略，默认空。facts规则同第二工具。返回 message、question、options、stage、field、target、skill。每个选项含 id（如goal-0）、label、value，值可以是文本或周数整数。HTTP接口用 facts/answers/history/evidence 四字段组装state，策略参数名为 skill。前端展示 question/options；下一轮通过 choice_id 反馈选项。 |
| 数据与副作用 | 读取本地 `skills/名称/SKILL.md` 和本会话传入的事实、答案、证据、历史。工具本身不保存会话或论文；默认不调用模型，相同状态/Skill得到相同问题。`accept_answer` 在完整 agent 中负责接收当前选项，再由 agent 写回会话。单独工具接口在传入 evidence 时不读取 SQLite；省略 evidence 时会从当前文库整理材料，可能触发建表/旧JSON迁移，但不写会话。启用模型时会访问配置的模型地址，正文可能变化。 |
| 失败行为 | 非法/不存在的Skill、非法state/message/use_model为 INVALID_INPUT；已存在但配置损坏的Skill为 INVALID_SKILL，不可自动重试。没有论文仍提示缺项并追问；全部配置问题答完返回 stage=discussion、options=[]及开放问题，不是失败。未配置模型却启用时为 MODEL_NOT_CONFIGURED；模型网络/超时/失败分别为 NETWORK_ERROR、TIMEOUT、MODEL_ERROR。默认模型网络操作超时60秒，由MODEL_TIMEOUT_SECONDS配置；启用模型时使用统一适配层，暂时性错误按MODEL_RETRIES有限重试，默认额外1次。独立工具测试全部use_model=false。 |

### 工具4：论文PDF解析 parse_paper_pdf

| 工具说明项 | 本项目实现 |
| --- | --- |
| 用途与选择条件 | 提取用户上传的文字型论文PDF原文、页码和元数据，为材料整理、文库保存及研究讨论提供真实输入。要求未加密且具有可提取文字；不执行OCR、论文总结、表格或公式识别，不判断创新性。 |
| 参数与返回 | `content: bytes`必填，非空且最多20MiB；`filename: str`默认paper.pdf，最长255字符且以.pdf结尾；`start_page: int`默认1；`end_page: int或None`默认None。页码从1开始、闭区间、每次最多20页；结束页省略时从起始页读取最多20页。文件最多500页，最多提取48000字符，截断时明确标记。返回filename、sha256、total_pages、start_page、end_page、pages（page_number/text/truncated）、text、truncated、warnings、metadata（title/author）、paper。第二工具直接读取 `papers=[result.paper]`，其中paper.abstract为带页码的PDF原文摘录，明确标注“非自动摘要”。 |
| 数据与副作用 | 来源为上传文件实际字节和元数据；不猜测年份或DOI。解析不保存原文件、不写会话或数据库；相同输入返回一致。paper_id由文件SHA256生成。核对后通过POST /api/library/papers显式保存到SQLite；同ID重复保存更新原记录，不新增；不同页码保存同文件会替换旧摘录，提交字段会覆盖旧值，不自动合并。 |
| 失败行为 | 空文件/非法页码为INVALID_INPUT；格式不符或损坏为INVALID_PDF；加密为ENCRYPTED_PDF；所选页无文字为NO_TEXT并提示OCR或更换页码；超20MiB为FILE_TOO_LARGE；超过500页为PDF_LIMIT。均retryable=false，修正输入后再试。HTTP分别为400/422、400、400、422、413、413。无外部调用或自动重试；尚未实现本地解析进程的墙钟超时。 |

完整用例、接口请求与实测记录见 [PDF工具报告](pdf_tool.md)。

## 三、接口说明与复现输入

前三项工具HTTP请求为JSON；PDF上传接口为multipart/form-data。成功响应均为JSON、HTTP200。参数在HTTP层校验失败为422；进入函数后发现非法值通常为400。PDF超限为413、无文字为422。工具错误统一为：

```json
{
  "detail": {
    "code": "INVALID_INPUT",
    "message": "query 必须为1至500字符的非空文本",
    "retryable": false
  }
}
```

网络/上游/模型失败映射为502，TIMEOUT映射为504，损坏的本地Skill配置为500。Python直接调用时抛出ToolError，可读取 `.code`、`.message`、`.retryable`，没有HTTP包装。

### 1. POST /api/tools/search

输入：

```json
{"query":"edge inference model compression","limit":1}
```

成功返回论文数组。没有匹配时仍为200和 `[]`；不能把它与400或502混淆。

### 2. POST /api/tools/evidence

输入：

```json
{
  "papers":[{"title":"明确标记的虚构教学材料","year":2025,"doi":"","abstract":"仅用于验收，无真实实验结论。"}],
  "facts":{"direction":"模型压缩","compute":"CPU","weeks":4,"dataset":"公开数据集"}
}
```

成功返回 `{"facts":{...},"rows":[...],"gaps":[]}`。只把compute改为null，论文行应保持相同，gaps变为 `["缺少算力条件"]`。

### 3. POST /api/tools/dialogue

输入：

```json
{
  "facts":{"direction":"模型压缩","compute":"CPU","weeks":4,"dataset":"公开数据集"},
  "answers":{},
  "evidence":{"rows":[],"gaps":["暂无论文，请导入已有论文或检索"]},
  "message":"请继续讨论研究选题",
  "skill":"research-dialogue",
  "use_model":false
}
```

预期 field/stage 为 goal，question 为“你希望优先改善哪个可测量的指标？”，options为推理延迟/模型效果/内存占用。保持其他参数不变，只把answers改为 `{"goal":"推理延迟"}`，预期field/stage变为baseline，追问可复现基线。

该接口生成一轮问题，不保存选项反馈；要连续聊天和持久化，使用 `/api/chat` 或 `backend.cli --choice`。单独接口与完整聊天调用的工具函数相同。

### 4. POST /api/tools/parse-pdf

上传字段：`file`必填，`start_page`默认1，`end_page`可省略。服务启动后执行：

```powershell
curl.exe -sS -X POST http://127.0.0.1:8000/api/tools/parse-pdf -F "file=@data/sample_paper.pdf;type=application/pdf" -F "start_page=1" -F "end_page=1"
```

两页教学样例的关键返回是 `total_pages=2`、`start_page=1`、`end_page=1`、`pages[0].page_number=1`，原文包含 `Synthetic page one: CPU latency baseline.`。仅将end_page改为2，结果新增第2页的 `Synthetic page two: compare memory usage.`。完整返回还包含可直接传给材料工具或文库接口的paper。

## 四、可执行测试命令及实测输出

PDF已加入 `tests/check_tools.py`：默认all会执行PDF用例，`--tool pdf`只执行PDF及注册检查，具体用例在 `tests/pdf_cases.py`。无需启动前端、服务或模型：

```powershell
python -m backend.run tests/check_tools.py --tool pdf
# RESULT: PASS (16/16 checks)
python -m backend.run tests/check_tools.py
# RESULT: PASS (42/42 checks)
```

以上为新增PDF后的实测计数；下文27项为原三工具的历史记录。

在项目根目录、已激活的Conda环境运行；只需现有 requirements.txt：

```powershell
python -m pip install -r requirements.txt
# 一次验收四项工具、异常、单参数变化、真实返回对象传递和接口注册
python -X utf8 tests/check_tools.py
# 分别独立复测
python -X utf8 tests/check_tools.py --tool search --output data/tool-check/search-only
python -X utf8 tests/check_tools.py --tool evidence --output data/tool-check/evidence-only
python -X utf8 tests/check_tools.py --tool dialogue --output data/tool-check/dialogue-only
# 正常检索/数量变化及后续链使用真实 Crossref；不调用模型
python -X utf8 tests/check_tools.py --live --output data/tool-check/live
```

不需要先启动前端、Uvicorn或模型服务。默认检索HTTP替身为明确的虚构教学数据；search函数实际执行。`--live`模式只有两次正常检索使用真实HTTP，其余空结果、网络故障等仍是明确注入，以保证可复现；API协议检查的检索也使用明确替身。每条记录的 data_source 指明来源。

2026-11-22实际输出：

| 命令 | 最后一行结果 | 本次本地输出位置 |
| --- | --- | --- |
| check_tools.py | RESULT: PASS (27/27 checks) | data/tool-check/run-3b00995d |
| --tool search | RESULT: PASS (11/11 checks) | data/tool-check/search-only/run-c0b8174d |
| --tool evidence | RESULT: PASS (8/8 checks) | data/tool-check/evidence-only/run-3d26b677 |
| --tool dialogue | RESULT: PASS (8/8 checks) | data/tool-check/dialogue-only/run-d78d6984 |
| --live | RESULT: PASS (27/27 checks) | data/tool-check/live/run-a2d2e08e |

每次新建run目录，终端打印ARTIFACTS，父目录latest.json记录最新结果；所有通过时退出码0，有判定不符时退出码1。已有Starlette TestClient可能打印httpx弃用提示，本次检查通过；测试过程不调用模型。

本地 data/tool-check 被Git忽略，本次完整证据副本已随源码保存：

- [离线证据](../tests/tool_results/offline/summary.json)
- [真实检索证据](../tests/tool_results/live/summary.json)
- [离线控制台](../tests/tool_results/offline/console.txt) / [联网控制台](../tests/tool_results/live/console.txt)

每项工具目录下都有 normal.json、invalid.json、changed.json，另外保存额外边界和接口用例。每个JSON包含：

```text
arguments          本次实际业务实参
returned           实际返回值，异常时为null
error              实际错误code/message/retryable/type，成功时为null
passed             是否满足判定
basis              判定依据
data_source        真实HTTP、明确替身、本地材料等来源
changed_parameter  唯一变化字段与前后值
```

transport是外部HTTP测试边界，不是业务输入；替身/故障类型由data_source和用例名标明，原业务实参完整保存在arguments。
API用例的returned是`{status, body}`：HTTP400/422本身也是实际响应，错误原因保存在`returned.body.detail`，此时error仍为null；只有Python调用抛异常时才写入error。

## 五、逐项测试情况：正常、失败与预期输出

| 工具/用例 | 实参或条件 | 预期输出和判定 | 本次 |
| --- | --- | --- | --- |
| 检索正常 | query非空，limit=1 | 返回1篇，包含title/year/doi/abstract | PASS |
| 检索异常 | query为空白 | INVALID_INPUT；在HTTP调用前拒绝 | PASS |
| 检索单参数 | limit从1改3，query不变 | 数量1→3，不要求两次排序一致 | PASS |
| 检索无结果 | HTTP200，items=[] | 返回[]，不是异常 | PASS |
| 检索超时 | 明确注入ReadTimeout | TIMEOUT、retryable=true | PASS |
| 检索断网 | 明确注入ConnectError | NETWORK_ERROR、retryable=true | PASS |
| 上游失败 | 明确注入HTTP503 | EXTERNAL_ERROR、retryable=true | PASS |
| 响应损坏 | HTTP200但缺message.items | INVALID_RESPONSE、retryable=true | PASS |
| 证据正常 | 有标题/摘要，资源完整 | 1行材料，gaps=[] | PASS |
| 证据异常 | 论文缺title | INVALID_INPUT | PASS |
| 证据单参数 | facts.compute: CPU→null | rows不变，新增“缺少算力条件” | PASS |
| 证据无材料 | papers=[] | rows=[]，gaps含“暂无论文…” | PASS |
| 时间越界 | facts.weeks=0 | INVALID_INPUT | PASS |
| 交互正常 | 资源完整，answers={} | field=goal，3个选项 | PASS |
| 交互异常 | skill_id=../invalid | INVALID_INPUT | PASS |
| 交互单参数 | 只添加answers.goal=推理延迟 | field从goal变baseline | PASS |
| 交互无待选项 | goal/baseline已回答 | stage=discussion，options=[]，开放问题非空 | PASS |
| 交互状态错误 | history不是列表 | INVALID_INPUT | PASS |
| 三项API正常 | 有效请求 | 各HTTP200 | PASS |
| 三项API非法 | limit=0、title为空、非法Skill | 400/422，detail.code=INVALID_INPUT | PASS |
| 注册及链式传参 | 注册表与实际返回对象 | 三工具可查；实际字段精确传递 | PASS |

超时用例通过立即注入超时异常检验分支，并检查正常HTTP请求的read timeout配置为30秒；它不声称实际等待了30秒。模型未配置、模型超时、损坏Skill等条件的错误码已实现，但本套27项测试不把真实模型故障计为已经联网验证。

## 六、成功返回如何真正交给第二项工具

联网运行从 `search_papers/normal.json` 的 returned[0] 取出完整论文对象，直接传入第二工具的 papers[0]，不重造字段。此次实际返回：

```json
{
  "title":"Model compression for on-device inference",
  "year":2022,
  "doi":"10.1016/b978-0-12-823817-2.00015-2",
  "abstract":""
}
```

第二工具对应 rows[0].title 与该title完全相同，rows[0].id等于该doi；原论文无摘要，因此输出明确提示缺摘要。测试再把第二工具的完整返回传到第三工具的state.evidence。

核对文件：

1. [真实检索返回](../tests/tool_results/live/search_papers/normal.json)：returned[0]。
2. [第二工具实参与结果](../tests/tool_results/live/chain/search_to_evidence.json)：arguments.papers[0]及returned.rows[0]。
3. [第三工具实参与结果](../tests/tool_results/live/chain/evidence_to_dialogue.json)：arguments.state.evidence。
4. [字段传递判定](../tests/tool_results/live/chain.json)：exact_match=true。

这些检查验证的是实际数据传递和规则变化，不代表模型分析质量或科研选题创新性已经得到验证。

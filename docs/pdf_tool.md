# 论文 PDF 解析工具与验收

工具名 `parse_paper_pdf`；实现 `backend/pdf_parser.py`，由 `backend/tools.py::TOOL_REGISTRY` 注册。它在用户上传 PDF 时执行，聊天阶段通过 SQLite 文库读取已保存的解析材料，不会每轮重复解析。

## 工具说明表

| 工具说明项 | 实现要求与本项目行为 |
| --- | --- |
| 用途与选择条件 | 从用户实际提供的文字型论文 PDF 提取原文和元数据，供核对、保存和后续研究讨论。需要未加密的 PDF；不执行 OCR、语义总结、公式识别或版面还原，不根据文件名编造论文结论。文字顺序和表格、公式可能失真，应对照原文。 |
| 参数与返回 | 函数 `parse_paper_pdf(content: bytes, filename: str="paper.pdf", start_page: int=1, end_page: int或None=None)`。内容必填、非空、最多20 MiB；文件名最长255字符且以.pdf结尾。页码为从1开始的闭区间，单次最多20页；不填结束页时读取起始页起最多20页。文件最多500页。返回 filename、sha256、total_pages、start_page、end_page、pages（page_number/text/truncated）、text、truncated、warnings、metadata（title/author）和 paper。paper 兼容现有 Paper 接口及 build_evidence；其中 abstract 明确标注为带页码的PDF原文摘录，不是真正的摘要或模型生成内容。未核实的 year 为null、doi为空，不猜测。 |
| 数据与副作用 | 数据来自本次PDF字节及其元数据；标题优先使用元数据，缺失时使用文件名，作者仅来自元数据。纯解析函数不保存原始PDF、不写会话或数据库。相同文件的SHA256相同，paper_id=`pdf-`加完整SHA256。核对后可通过现有 POST /api/library/papers 保存；同一paper_id重复保存更新同一记录，不新增。选择不同页码后保存同一文件将替换其旧摘录，不自动合并。重复解析本身不会修改已保存的笔记；显式保存时提交的字段会覆盖旧字段，请先核对。 |
| 失败行为 | INVALID_INPUT：空内容、文件名/页码错误，HTTP400或参数校验422；INVALID_PDF：格式不符、损坏或解析失败，400；ENCRYPTED_PDF：加密文件，400；NO_TEXT：所选页面无可提取文字，422，提示先OCR或换页；FILE_TOO_LARGE：超过20MiB，413；PDF_LIMIT：超过500页，413。均retryable=false，应修改文件或参数后重试。另有TIMEOUT：独立解析进程超过默认20秒（PDF_TIMEOUT_SECONDS），终止并回收后返回HTTP504、retryable=true。没有外部网络调用或自动重试；保留大小、页数、文字量限制。超时与恢复测试见[恢复验收](recovery.md)。 |

全文提取最多返回48000字符，超过后截断并在页面及顶层标记 `truncated=true`。空白页允许夹在有文字的页中；所选页全部无文字才返回 NO_TEXT。默认最多20页不代表已读取整篇论文，warnings会提示未包含全文。元数据可能由文件作者填写错误，界面允许人工修改。

## HTTP 接口

`POST /api/tools/parse-pdf`，请求类型为 `multipart/form-data`，不是JSON。

| 字段 | 类型 | 必填/默认 |
| --- | --- | --- |
| file | PDF文件 | 必填 |
| start_page | 整数表单字段 | 默认1 |
| end_page | 整数表单字段 | 可省略 |

服务启动后，在项目根目录执行（不需要打开网页或模型）：

```powershell
curl.exe -sS -X POST http://127.0.0.1:8000/api/tools/parse-pdf -F "file=@data/sample_paper.pdf;type=application/pdf" -F "start_page=1" -F "end_page=1" -o data/pdf-result.json
$parsed = Get-Content data/pdf-result.json -Raw -Encoding UTF8 | ConvertFrom-Json
$parsed.pages
# 将实际返回paper作为第二项工具输入
$body = @{ papers = @($parsed.paper); facts = @{ compute = 'CPU' } } | ConvertTo-Json -Depth 20
Invoke-RestMethod http://127.0.0.1:8000/api/tools/evidence -Method Post -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body))
# 核对后显式保存到SQLite；可选，不是解析的隐含副作用
$body = $parsed.paper | ConvertTo-Json -Depth 10
Invoke-RestMethod http://127.0.0.1:8000/api/library/papers -Method Post -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body))
```

成功响应关键字段示例：

```json
{
  "total_pages": 2,
  "start_page": 1,
  "end_page": 1,
  "pages": [{"page_number": 1, "text": "Synthetic page one: CPU latency baseline.", "truncated": false}],
  "truncated": false
}
```

实际响应还包含完整 text、warnings、metadata、sha256和paper。错误沿用统一协议：`{"detail":{"code":"NO_TEXT","message":"所选页面没有可提取文字，可能是扫描件；请先 OCR 或更换页码","retryable":false}}`。GET /api/tools 和 /docs 均可查看新注册入口与上传字段。当前应用仅供本地单人课程演示，无鉴权；上传不接受服务器文件路径或远程URL。

## 命令行与前端入口

```powershell
python -m pip install -r requirements.txt
# 不启动服务、前端或模型，实际解析示例PDF；每次输出同时保存运行日志
python -m backend.run -m backend.pdf_parser --file data/sample_paper.pdf --start-page 1 --end-page 1
# 只改一个参数，第二页将出现在pages和text中
python -m backend.run -m backend.pdf_parser --file data/sample_paper.pdf --start-page 1 --end-page 2
# 独立验收新工具
python -m backend.run tests/check_tools.py --tool pdf
# 验收全部四项工具
python -m backend.run tests/check_tools.py
```

网页“已有论文 → 解析论文 PDF”：上传、选择页码、解析到论文表单；核对标题和“摘要/已读段落”后点击“保存论文”。后续聊天从SQLite读取该材料进入build_evidence。无需开启模型即可解析与保存。

`data/sample_paper.pdf` 为程序生成的两页英文教学样例，不是真实论文；准备方法见 `tests/pdf_cases.py::make_pdf`，元数据标题为 Synthetic PDF teaching fixture。固定基准：第1页CPU latency baseline，第2页compare memory usage。内容版本随Git提交固定；测试同时记录实际文件字节数和SHA256，避免使用浮动网络内容作为基准。此测试不证明复杂双栏、中文字体编码、扫描论文的解析质量。

## 测试覆盖与证据

测试实现：`tests/check_tools.py` 中选择 pdf，调用 `tests/pdf_cases.py`。直接从注册表取得函数，用TestClient调用真实路由；不启动前端、Uvicorn或模型。正常结果中的真实paper原样作为材料工具输入，另通过文库接口写入并读回SQLite。测试用库位于独立目录，不修改日常文库。

| 用例 | 预期与判定依据 |
| --- | --- |
| 注册入口 | GET /api/tools包含全部四个真实函数 |
| 正常解析 | 总页数2，选择第1页仅含CPU latency，页码为1 |
| 参数变化 | 仅end_page从1改2，结果增加第2页和memory usage文字 |
| 格式错误/损坏 | 返回INVALID_PDF，不伪造成功 |
| 加密PDF | 返回ENCRYPTED_PDF |
| 无文字页面 | 返回NO_TEXT并提示OCR |
| 超过大小上限 | 返回FILE_TOO_LARGE |
| 页码越界 | 返回INVALID_INPUT |
| 重复解析 | 同字节和参数返回一致，无入库副作用 |
| PDF→材料工具 | rows[0].excerpt与解析返回paper.abstract完全一致 |
| 上传正常/错误 | 实际接口200或400 INVALID_PDF |
| 上传无文字 | 实际接口422 NO_TEXT |
| 表单页码0 | 实际接口422 INVALID_INPUT |
| PDF→SQLite | 保存、重试、读取均200，同ID仍为1条且原文一致 |

每项保存 `arguments`、`returned`、`error`、`passed`、`basis`、`data_source`、`changed_parameter`。二进制参数使用content_ref、size_bytes和sha256标识，fixtures保留原始小文件；超限样例由生成规则复现，不提交20MiB冗余文件。HTTP错误测试返回值包装为status/body，按HTTP状态和detail.code判定。

运行证据位于 `data/tool-check/run-.../`；summary.json记录通过数，parse_paper_pdf目录保存逐项结果，chain目录保存跨工具与入库证据，fixtures保存样例，console.txt保存测试输出。统一运行入口额外生成 `data/logs/runs/时间戳_进程号.log`。固定交付证据见 `tests/tool_results/pdf/`。

2026-11-22实际结果：PDF独立验收 `PASS (16/16 checks)`（含1项注册检查），四工具完整离线验收 `PASS (42/42 checks)`，原SQLite及交互回归 `PASS (23 checks)`。完整运行目录为 `data/tool-check/run-94620484`；PDF独立运行目录为 `data/tool-check/run-8f53fa39`。固定证据保留PDF相关逐项记录、两条PDF链路以及完整42项汇总/控制台记录；原三工具历史逐项记录仍在offline目录。`cli-output.log` 是真实执行两页解析命令的终端记录。上传接口经进程内TestClient实测；前端上传入口已接线并检查JS语法，本轮未进行浏览器手动验收。无真实模型调用。

可分发的 `data/sample_paper.pdf` SHA256：`34625d92a8503b98af970fec17a33a47ae5c1d753944ce12ee4dda5703abb208`。每次测试会重新生成同内容的教学PDF，其二进制标识可能不同，以各测试记录中的SHA256为准。

实现依据：[pypdf文字提取文档](https://github.com/py-pdf/pypdf/blob/main/docs/user/extract-text.md)。pypdf不执行OCR，本项目不将图像PDF的空文字结果视为成功解析。

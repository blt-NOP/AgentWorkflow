"""PDF工具用例；明确生成的两页教学样例，不是真实论文。"""
from hashlib import sha256
from io import BytesIO

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject


def make_pdf(texts, encrypted=False):
    writer = PdfWriter()
    writer.add_metadata({"/Title": "Synthetic PDF teaching fixture", "/Author": "Course test"})
    for value in texts:
        page = writer.add_blank_page(width=600, height=800)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                 NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"):
            DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 40 740 Td ({value}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("test-only-password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def run_pdf_checks(run, case, client, tools):
    from unittest.mock import patch
    from backend.pdf_parser import MAX_BYTES
    sample = make_pdf(["Synthetic page one: CPU latency baseline.", "Synthetic page two: compare memory usage."])
    fixtures = run / "fixtures"
    fixtures.mkdir(exist_ok=True)
    (fixtures / "sample_paper.pdf").write_bytes(sample)
    inputs = {"sample_paper.pdf": sample, "broken.pdf": b"%PDF-1.4\nbroken",
              "blank.pdf": make_pdf([""]), "encrypted.pdf": make_pdf(["Secret"], True),
              "wrong.pdf": b"not pdf", "large.pdf": b"%PDF-" + b" " * MAX_BYTES}
    # bytes 用文件名、字节数、SHA256标识保存，原始样例也落盘，可独立核对。
    def arguments(name="sample_paper.pdf", **changes):
        value = inputs[name]
        result = {"filename": name, "content_ref": name, "size_bytes": len(value),
                  "sha256": sha256(value).hexdigest(), "start_page": 1, "end_page": 1}
        result.update(changes)
        return result

    def parse(content_ref, filename, size_bytes, sha256, start_page, end_page):
        return tools.TOOL_REGISTRY["parse_paper_pdf"](inputs[content_ref], filename, start_page, end_page)

    def error_is(code):
        return lambda value, error: error is not None and error["code"] == code

    for name, content in inputs.items():
        if name != "large.pdf":
            (fixtures / name).write_bytes(content)
    normal = case("parse_paper_pdf", "normal", arguments(), parse,
        lambda value, error: error is None and value["total_pages"] == 2 and len(value["pages"]) == 1
            and "CPU latency" in value["text"] and "memory usage" not in value["text"],
        "两页PDF只选择第1页，提取实际文字和页码", "generated PDF teaching fixture")
    case("parse_paper_pdf", "changed", arguments(end_page=2), parse,
         lambda value, error: error is None and len(value["pages"]) == 2 and "memory usage" in value["text"],
         "仅end_page由1改2，新增第2页原文", change={"path": "end_page", "before": 1, "after": 2})
    for name, source, code in [("invalid", "wrong.pdf", "INVALID_PDF"),
                               ("corrupt", "broken.pdf", "INVALID_PDF"),
                               ("encrypted", "encrypted.pdf", "ENCRYPTED_PDF"),
                               ("no_text", "blank.pdf", "NO_TEXT"),
                               ("oversize", "large.pdf", "FILE_TOO_LARGE")]:
        case("parse_paper_pdf", name, arguments(source), parse, error_is(code), f"返回{code}，不伪造解析结果")
    case("parse_paper_pdf", "invalid_range", arguments(start_page=3, end_page=3), parse,
         error_is("INVALID_INPUT"), "页码超出文件范围时明确失败")
    case("parse_paper_pdf", "repeat", arguments(), parse,
         lambda value, error: error is None and value == normal, "相同PDF及参数返回一致，不写入数据库")
    if normal is not None:
        case("chain", "pdf_to_evidence", {"papers": [normal["paper"]], "facts": {}},
             tools.TOOL_REGISTRY["build_evidence"],
             lambda value, error: error is None and value["rows"][0]["excerpt"] == normal["paper"]["abstract"],
             "parse_paper_pdf真实返回paper原样传入build_evidence；原文和页码保留")

    def api(content_ref, start_page=1, end_page=1):
        response = client.post("/api/tools/parse-pdf", files={"file":
            (content_ref, inputs[content_ref], "application/pdf")},
            data={"start_page": str(start_page), "end_page": str(end_page)})
        return {"status": response.status_code, "body": response.json()}

    case("parse_paper_pdf", "api_normal", {"content_ref": "sample_paper.pdf"}, api,
         lambda value, error: error is None and value["status"] == 200 and "CPU latency" in value["body"]["text"],
         "multipart接口返回200及实际解析文本")
    case("parse_paper_pdf", "api_invalid", {"content_ref": "wrong.pdf"}, api,
         lambda value, error: error is None and value["status"] == 400 and value["body"]["detail"]["code"] == "INVALID_PDF",
         "非PDF上传返回400 INVALID_PDF")
    case("parse_paper_pdf", "api_no_text", {"content_ref": "blank.pdf"}, api,
         lambda value, error: error is None and value["status"] == 422 and value["body"]["detail"]["code"] == "NO_TEXT",
         "无文字页面返回422并提示OCR")
    case("parse_paper_pdf", "api_invalid_range", {"content_ref": "sample_paper.pdf", "start_page": 0}, api,
         lambda value, error: error is None and value["status"] == 422 and value["body"]["detail"]["code"] == "INVALID_INPUT",
         "表单页码0返回422参数校验错误")
    with patch.dict("os.environ", {"PDF_TIMEOUT_SECONDS": "0.001"}):
        case("parse_paper_pdf", "timeout", arguments(), parse, error_is("TIMEOUT"),
             "解析期限缩短到1毫秒，独立进程被终止并返回可重试TIMEOUT")
        case("parse_paper_pdf", "api_timeout", {"content_ref": "sample_paper.pdf"}, api,
             lambda value, error: error is None and value["status"] == 504 and
                 value["body"]["detail"]["code"] == "TIMEOUT" and value["body"]["detail"]["retryable"],
             "解析超时返回HTTP504、明确原因和retryable=true")
    case("parse_paper_pdf", "timeout_recovery", arguments(), parse,
         lambda value, error: error is None and value == normal,
         "恢复默认期限后相同文件与页码成功，输出与故障前一致")
    # 同一个返回对象通过现有文库接口持久化；相同paper_id重试不会新增记录。
    def store(paper):
        first = client.post("/api/library/papers", json=paper)
        second = client.post("/api/library/papers", json=paper)
        read = client.get("/api/library/papers/" + paper["paper_id"])
        return {"statuses": [first.status_code, second.status_code, read.status_code], "paper": read.json(),
                "count": len(client.get("/api/library").json())}
    if normal is not None:
        case("chain", "pdf_to_library", {"paper": normal["paper"]}, store,
             lambda value, error: error is None and value["statuses"] == [200, 200, 200]
                 and value["count"] == 1 and value["paper"]["abstract"] == normal["paper"]["abstract"],
             "真实paper经现有接口写入并读取SQLite；重复保存同一ID仍为1篇")

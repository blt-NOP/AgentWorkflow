"""论文 PDF 文字提取；不调用模型、不执行 OCR、不自动写入文库。"""
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

from .tool_contracts import ToolError

MAX_BYTES = 20 * 1024 * 1024


def parse_paper_pdf(content, filename="paper.pdf", start_page=1, end_page=None):
    """content 为 PDF bytes；页码从1开始，闭区间，单次最多20页。"""
    if not isinstance(content, bytes) or not content:
        raise ToolError("INVALID_INPUT", "请上传非空 PDF 文件")
    if len(content) > MAX_BYTES:
        raise ToolError("FILE_TOO_LARGE", "PDF 不能超过20 MiB，请拆分文件")
    if not isinstance(filename, str) or not filename.lower().endswith(".pdf") or len(filename) > 255:
        raise ToolError("INVALID_INPUT", "filename 必须为255字符以内的 .pdf 文件名")
    if not content.startswith(b"%PDF-"):
        raise ToolError("INVALID_PDF", "文件内容不是 PDF，请检查文件格式")
    if type(start_page) is not int or start_page < 1 or (end_page is not None and
            (type(end_page) is not int or end_page < start_page)):
        raise ToolError("INVALID_INPUT", "页码必须为从1开始的整数，end_page 不小于 start_page")
    try:
        reader = PdfReader(BytesIO(content), strict=False)
        if reader.is_encrypted:
            raise ToolError("ENCRYPTED_PDF", "不支持加密 PDF，请先提供未加密的副本")
        total = len(reader.pages)
        if total > 500:
            raise ToolError("PDF_LIMIT", "文件超过500页，请先拆分")
        last = min(total, start_page + 19) if end_page is None else end_page
        if start_page > total or last > total or last - start_page + 1 > 20:
            raise ToolError("INVALID_INPUT", "页码超出文件范围，或单次选择超过20页")
        pages, remaining, truncated = [], 48000, False
        for index in range(start_page - 1, last):
            original = (reader.pages[index].extract_text() or "").strip()
            # 限制返回文本总量，并显式告知调用方是否发生截断。
            value = original[:remaining]
            cut = len(value) < len(original)
            truncated = truncated or cut
            remaining -= len(value)
            pages.append({"page_number": index + 1, "text": value, "truncated": cut})
        metadata = reader.metadata
        title = str(metadata.title or "").strip() if metadata else ""
        author = str(metadata.author or "").strip() if metadata else ""
    except ToolError:
        raise
    except Exception as error:
        raise ToolError("INVALID_PDF", "PDF 损坏或无法解析，请更换文件或重新导出") from error
    if not any(page["text"] for page in pages):
        raise ToolError("NO_TEXT", "所选页面没有可提取文字，可能是扫描件；请先 OCR 或更换页码")
    filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    title = (title or Path(filename).stem)[:1000]
    text = "\n\n".join(f"[PDF第{page['page_number']}页]\n{page['text']}" for page in pages if page["text"])
    digest = sha256(content).hexdigest()
    warnings = ["仅提取文字，版面顺序、公式和表格需对照原文核查；不判断创新性。",
                "paper.abstract 为带页码的原文摘录兼容字段，不是论文摘要或模型总结。"]
    if last < total or start_page > 1:
        warnings.append("仅解析所选页码范围，未包含全文。")
    if truncated:
        warnings.append("原文超过48000字符，返回内容已截断。")
    return {"filename": filename, "sha256": digest, "total_pages": total,
            "start_page": start_page, "end_page": last, "pages": pages,
            "text": text, "truncated": truncated, "warnings": warnings,
            "metadata": {"title": title, "author": author},
            "paper": {"paper_id": "pdf-" + digest, "title": title, "year": None, "doi": "",
                      "abstract": "[PDF原文摘录，非自动摘要]\n" + text, "notes": ""}}


def main():
    import argparse
    import json
    from .tools import TOOL_REGISTRY

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--end-page", type=int)
    args = parser.parse_args()
    try:
        with args.file.open("rb") as file:
            content = file.read(MAX_BYTES + 1)
        result = TOOL_REGISTRY["parse_paper_pdf"](content, args.file.name, args.start_page, args.end_page)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ToolError) as error:
        print(json.dumps({"error": {"code": getattr(error, "code", "FILE_ERROR"),
                                   "message": str(error), "retryable": False}}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

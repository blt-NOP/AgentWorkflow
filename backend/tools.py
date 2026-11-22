"""三项工具：论文检索、材料整理、多轮科研交互。"""
import os
import httpx
from .dialogue import research_dialogue
from .tool_contracts import ToolError, check_facts


def search_papers(query, limit=3, *, transport=None):
    """真实检索 Crossref；只返回实际题录，有摘要才返回摘要。"""
    if not isinstance(query, str) or not query.strip() or len(query) > 500:
        raise ToolError("INVALID_INPUT", "query 必须为1至500字符的非空文本")
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ToolError("INVALID_INPUT", "limit 必须为1至20的整数，单位为篇")
    try:
        with httpx.Client(timeout=30, proxy=(os.getenv("OUTBOUND_PROXY") or None) if transport is None else None,
                          transport=transport) as client:
            response = client.get("https://api.crossref.org/works",
                                  params={"query.bibliographic": query, "rows": limit})
    except httpx.TimeoutException as error:
        raise ToolError("TIMEOUT", "Crossref 请求超时（单次网络操作上限30秒）", True) from error
    except httpx.RequestError as error:
        raise ToolError("NETWORK_ERROR", "无法连接 Crossref，请检查网络或代理", True) from error
    if response.status_code != 200:
        raise ToolError("EXTERNAL_ERROR", f"Crossref 返回 HTTP {response.status_code}", response.status_code == 429 or response.status_code >= 500)
    papers = []
    try:
        items = response.json()["message"]["items"]
        if not isinstance(items, list):
            raise ValueError("items is not a list")
        for item in items[:limit]:
            dates = item.get("published", {}).get("date-parts", [[None]])
            papers.append({"title": (item.get("title") or ["无题名"])[0],
                           "year": dates[0][0], "doi": item.get("DOI", "") or "",
                           "abstract": item.get("abstract", "") or ""})
    except (ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
        raise ToolError("INVALID_RESPONSE", "Crossref 响应格式无效", True) from error
    return papers


def build_evidence(papers, facts):
    """整理实际材料与缺项，不根据题名编造实验结论。"""
    check_facts(facts)
    if not isinstance(papers, list):
        raise ToolError("INVALID_INPUT", "papers 必须为论文列表，允许空列表")
    for paper in papers:
        if not isinstance(paper, dict) or not isinstance(paper.get("title"), str) or not paper["title"].strip() or len(paper["title"]) > 1000:
            raise ToolError("INVALID_INPUT", "每篇论文必须有1至1000字符的非空 title")
        for field, maximum in (("doi", 1000), ("abstract", 50000), ("notes", 10000)):
            if field in paper and (not isinstance(paper[field], str) or len(paper[field]) > maximum):
                raise ToolError("INVALID_INPUT", f"论文 {field} 类型或长度无效")
        year = paper.get("year")
        if year is not None and (type(year) is not int or not 1000 <= year <= 2200):
            raise ToolError("INVALID_INPUT", "year 必须为1000至2200的整数或 null")
    rows = []
    for paper in papers:
        identity = paper.get("doi") or paper["title"]
        if any(row["id"] == identity for row in rows):
            continue
        rows.append({"id": identity, "title": paper["title"], "year": paper.get("year"),
                     "doi": paper.get("doi", ""), "notes": paper.get("notes", ""),
                     "excerpt": paper.get("abstract") or "缺少摘要，不能据题名推断结论。"})
    gaps = [label for key, label in (("compute", "缺少算力条件"), ("weeks", "缺少可用时间"),
                                    ("dataset", "缺少数据条件")) if not facts.get(key)]
    if not rows:
        gaps.append("暂无论文，请导入已有论文或检索")
    return {"facts": facts.copy(), "rows": rows, "gaps": gaps}


# 唯一工具注册表。对话流程、独立接口和测试都从这里取得同一函数。
TOOL_REGISTRY = {"search_papers": search_papers, "build_evidence": build_evidence,
                 "research_dialogue": research_dialogue}

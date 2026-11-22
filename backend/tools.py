"""两项工具都是普通函数，可被命令行或网页调用。"""
import os
import httpx


def search_papers(query, limit=3):
    """真实检索 Crossref；只返回实际题录，有摘要才返回摘要。"""
    with httpx.Client(timeout=30, proxy=os.getenv("OUTBOUND_PROXY") or None) as client:
        response = client.get("https://api.crossref.org/works",
                              params={"query.bibliographic": query, "rows": limit})
    if response.status_code != 200:
        raise RuntimeError(f"论文检索失败，HTTP {response.status_code}")
    papers = []
    for item in response.json()["message"]["items"]:
        dates = item.get("published", {}).get("date-parts", [[None]])
        papers.append({"title": (item.get("title") or ["无题名"])[0],
                       "year": dates[0][0], "doi": item.get("DOI", ""),
                       "abstract": item.get("abstract", "")})
    return papers


def build_evidence(papers, facts):
    """整理实际材料与缺项，不根据题名编造实验结论。"""
    rows = []
    for paper in papers:
        identity = paper.get("doi") or paper["title"]
        if any(row["id"] == identity for row in rows):
            continue
        rows.append({"id": identity, "title": paper["title"], "year": paper.get("year"),
                     "doi": paper.get("doi", ""), "excerpt": paper.get("abstract") or "缺少摘要，不能据题名推断结论。"})
    gaps = [label for key, label in (("compute", "缺少算力条件"), ("weeks", "缺少可用时间"),
                                    ("dataset", "缺少数据条件")) if not facts.get(key)]
    if not rows:
        gaps.append("暂无论文，请导入已有论文或检索")
    return {"facts": facts.copy(), "rows": rows, "gaps": gaps}

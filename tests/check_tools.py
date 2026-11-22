"""四工具独立验收：保存实参、实际返回/错误、判定依据和单参数对比。"""
import argparse
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", choices=["all", "search", "evidence", "dialogue", "pdf"], default="all")
    parser.add_argument("--live", action="store_true", help="正常/单参数检索访问真实 Crossref；其他故障仍明确注入")
    parser.add_argument("--output", type=Path, default=ROOT / "data/tool-check")
    args = parser.parse_args()
    if args.live and args.tool not in ("all", "search"):
        parser.error("--live 只适用于 all 或 search")
    run = args.output.resolve() / f"run-{uuid4().hex[:8]}"
    run.mkdir(parents=True)
    os.environ["DATA_DIR"] = str(run / "isolated-data")
    import httpx
    from fastapi.testclient import TestClient
    from backend import tools, model
    from backend.main import app

    def save(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    cases, console = [], []

    def report(line):
        console.append(line)
        print(line)

    def case(tool, name, arguments, call, judge, basis, source="local", change=None):
        value, error = None, None
        try:
            value = call(**deepcopy(arguments))
        except Exception as exc:
            error = {"code": getattr(exc, "code", "UNEXPECTED_ERROR"), "message": str(exc),
                     "retryable": getattr(exc, "retryable", False), "type": type(exc).__name__}
        passed = bool(judge(value, error))
        record = {"tool": tool, "case": name, "arguments": arguments, "returned": value, "error": error,
                  "passed": passed, "basis": basis, "data_source": source, "changed_parameter": change}
        cases.append(record)
        save(run / tool / f"{name}.json", record)
        report(f"{'PASS' if passed else 'FAIL'} {tool}.{name}: {basis}")
        return value

    def is_error(code):
        return lambda value, error: error is not None and error["code"] == code

    # HTTP 替身只模拟网络边界，实际 search_papers 仍执行解析与校验。
    fixture_items = [{"title": [f"Synthetic teaching fixture {i} - not a real paper"],
                      "DOI": f"10.0000/tool-fixture-{i}", "published": {"date-parts": [[2025]]},
                      "abstract": f"Synthetic excerpt {i}: compare latency and memory."} for i in range(1, 4)]

    def fixture_response(request):
        assert request.extensions["timeout"]["read"] == 30
        rows = int(request.url.params["rows"])
        items = [] if request.url.params["query.bibliographic"] == "empty-fixture" else fixture_items[:rows]
        return httpx.Response(200, json={"message": {"items": items}})

    fixture = httpx.MockTransport(fixture_response)

    def search_fixture(**kwargs):
        return tools.TOOL_REGISTRY["search_papers"](**kwargs, transport=fixture)

    selected = args.tool
    facts = {"direction": "模型压缩", "compute": "CPU", "weeks": 4, "dataset": "公开数据集"}
    papers = [{"title": "Synthetic evidence fixture", "year": 2025, "doi": "10.0000/evidence-fixture",
               "abstract": "Synthetic teaching material: compare a baseline and one variant."}]
    normal_search, normal_evidence = None, None
    report(f"MODE: {'live_crossref' if args.live else 'offline_http_fixture'}; frontend/server/model=disabled")
    with patch.object(model, "reply", side_effect=AssertionError("本测试禁止调用模型")) as model_call:
        if selected in ("all", "search"):
            call_search = tools.TOOL_REGISTRY["search_papers"] if args.live else search_fixture
            source = "real Crossref HTTP" if args.live else "explicit synthetic HTTP fixture"
            base = {"query": "edge inference model compression", "limit": 1}
            normal_search = case("search_papers", "normal", base, call_search,
                lambda value, error: error is None and len(value) == 1 and bool(value[0]["title"]),
                "limit=1 返回1篇，包含实际解析的 title/doi/year/abstract", source)
            changed = dict(base, limit=3)
            case("search_papers", "changed", changed, call_search,
                lambda value, error: error is None and normal_search is not None and len(normal_search) == 1 and len(value) == 3,
                "仅 limit 从1变3，返回数量从1变3；排序/论文内容由数据源决定", source,
                {"path": "limit", "before": 1, "after": 3})
            case("search_papers", "invalid", {"query": " ", "limit": 1}, search_fixture,
                 is_error("INVALID_INPUT"), "空白 query 在发起HTTP前被拒绝")
            case("search_papers", "empty", {"query": "empty-fixture", "limit": 1}, search_fixture,
                 lambda value, error: error is None and value == [], "无结果返回 []，与调用失败区分", "explicit empty HTTP fixture")

            def timeout(request):
                raise httpx.ReadTimeout("synthetic timeout", request=request)

            def disconnected(request):
                raise httpx.ConnectError("synthetic network failure", request=request)

            for name, transport, code in (
                ("timeout", httpx.MockTransport(timeout), "TIMEOUT"),
                ("network", httpx.MockTransport(disconnected), "NETWORK_ERROR"),
                ("http_error", httpx.MockTransport(lambda request: httpx.Response(503)), "EXTERNAL_ERROR"),
                ("invalid_response", httpx.MockTransport(lambda request: httpx.Response(200, json={})), "INVALID_RESPONSE")):
                case("search_papers", name, base, lambda **kwargs: tools.search_papers(**kwargs, transport=transport),
                     is_error(code), f"明确注入故障，返回 {code}，可重试", "explicit HTTP fault fixture")

        if selected in ("all", "evidence"):
            base = {"papers": papers, "facts": facts}
            normal_evidence = case("build_evidence", "normal", base, tools.TOOL_REGISTRY["build_evidence"],
                lambda value, error: error is None and len(value["rows"]) == 1 and value["gaps"] == [],
                "1篇有摘要材料+完整条件，返回1行证据且无条件缺项", "explicit synthetic papers")
            case("build_evidence", "invalid", {"papers": [{"abstract": "missing title"}], "facts": facts}, tools.build_evidence,
                 is_error("INVALID_INPUT"), "缺少必填 title，返回 INVALID_INPUT")
            changed = deepcopy(base)
            changed["facts"]["compute"] = None
            case("build_evidence", "changed", changed, tools.build_evidence,
                lambda value, error: error is None and normal_evidence is not None and value["rows"] == normal_evidence["rows"]
                    and value["gaps"] == ["缺少算力条件"],
                "仅 facts.compute 从CPU变null；论文行不变，新增算力缺项", "explicit synthetic papers",
                {"path": "facts.compute", "before": "CPU", "after": None})
            case("build_evidence", "empty", {"papers": [], "facts": facts}, tools.build_evidence,
                 lambda value, error: error is None and value["rows"] == [] and "暂无论文，请导入已有论文或检索" in value["gaps"],
                 "无论文仍成功返回空行与材料缺项")
            case("build_evidence", "invalid_weeks", {"papers": papers, "facts": {"weeks": 0}}, tools.build_evidence,
                 is_error("INVALID_INPUT"), "weeks=0 超出1至520周范围")

        matrix = normal_evidence or {"facts": facts, "rows": [], "gaps": ["暂无论文，请导入已有论文或检索"]}
        state = {"facts": facts, "answers": {}, "history": [], "evidence": matrix}
        dialogue_args = {"state": state, "message": "请继续讨论研究选题", "skill_id": "research-dialogue", "use_model": False}
        if selected in ("all", "dialogue"):
            normal = case("research_dialogue", "normal", dialogue_args, tools.TOOL_REGISTRY["research_dialogue"],
                lambda value, error: error is None and value["field"] == "goal" and len(value["options"]) == 3,
                "资源条件完整、研究目标未答：追问目标并返回3个选项")
            case("research_dialogue", "invalid", dict(dialogue_args, skill_id="../invalid"), tools.research_dialogue,
                 is_error("INVALID_INPUT"), "非法 Skill 名称被拒绝，不读取目录外文件")
            changed = deepcopy(dialogue_args)
            changed["state"]["answers"]["goal"] = "推理延迟"
            case("research_dialogue", "changed", changed, tools.research_dialogue,
                lambda value, error: error is None and normal is not None and normal["field"] == "goal" and value["field"] == "baseline",
                "仅添加 state.answers.goal，问题从研究目标推进到对照基线", "local Skill + synthetic state",
                {"path": "state.answers.goal", "before": "absent", "after": "推理延迟"})
            answered = deepcopy(changed)
            answered["state"]["answers"]["baseline"] = "已有可复现基线"
            case("research_dialogue", "all_answered", answered, tools.research_dialogue,
                 lambda value, error: error is None and value["stage"] == "discussion" and value["options"] == [] and bool(value["question"]),
                 "配置问题全部回答后进入开放讨论；无选项不是失败")
            invalid = deepcopy(dialogue_args)
            invalid["state"]["history"] = "not a list"
            case("research_dialogue", "invalid_state", invalid, tools.research_dialogue,
                 is_error("INVALID_INPUT"), "history 类型错误时返回 INVALID_INPUT")

        # 正常检索真正返回的对象，直接进入第二项工具；不重造 DOI 或题名。
        if selected == "all":
            chain_args = {"papers": normal_search[:1] if normal_search else [], "facts": facts}
            evidence = case("chain", "search_to_evidence", chain_args, tools.TOOL_REGISTRY["build_evidence"],
                lambda value, error: error is None and bool(normal_search) and value["rows"][0]["title"] == normal_search[0]["title"]
                    and value["rows"][0]["id"] == (normal_search[0]["doi"] or normal_search[0]["title"]),
                "search_papers.normal.returned[0] 原样传入 papers[0]，验证真实 title/doi 标识", source)
            next_args = deepcopy(dialogue_args)
            next_args["state"]["evidence"] = evidence
            case("chain", "evidence_to_dialogue", next_args, tools.TOOL_REGISTRY["research_dialogue"],
                 lambda value, error: error is None and bool(normal_search) and value["field"] == "goal",
                 "第二工具实际 evidence 返回作为第三工具 state.evidence", source)
            save(run / "chain.json", {"source_file": "search_papers/normal.json", "source_field": "returned[0]",
                "target_file": "chain/search_to_evidence.json", "target_field": "arguments.papers[0]",
                "exact_match": bool(normal_search) and chain_args["papers"][0] == normal_search[0],
                "next_target": "chain/evidence_to_dialogue.json:arguments.state.evidence"})

        # 用真实后端路由做协议检查；TestClient 不启动服务器和前端。
        with TestClient(app) as client:
            def http_call(method, path, payload=None):
                response = client.request(method, path, json=payload)
                return {"status": response.status_code, "body": response.json()}

            case("registration", "registry", {}, lambda: http_call("GET", "/api/tools"),
                 lambda value, error: error is None and {item["name"] for item in value["body"]} == set(tools.TOOL_REGISTRY),
                 "GET /api/tools 列出全部真实函数入口")

            if selected in ("all", "pdf"):
                from pdf_cases import run_pdf_checks
                run_pdf_checks(run, case, client, tools)

            def api_fixture(query, limit=3):
                return tools.search_papers(query, limit, transport=fixture)

            definitions = {
                "search": ("search_papers", "/api/tools/search", {"query": "edge inference", "limit": 1}, {"query": "edge", "limit": 0}),
                "evidence": ("build_evidence", "/api/tools/evidence", {"papers": papers, "facts": facts}, {"papers": [{"title": ""}], "facts": facts}),
                "dialogue": ("research_dialogue", "/api/tools/dialogue", {"facts": facts, "evidence": matrix}, {"facts": facts, "skill": "../invalid", "evidence": matrix})}
            with patch.dict(tools.TOOL_REGISTRY, {"search_papers": api_fixture}):
                for alias, (tool, path, valid, invalid) in definitions.items():
                    if selected not in ("all", alias):
                        continue
                    case(tool, "api_normal", {"method": "POST", "path": path, "payload": valid}, http_call,
                         lambda value, error: error is None and value["status"] == 200, "独立后端入口返回 HTTP 200", "in-process API; search HTTP fixture")
                    case(tool, "api_invalid", {"method": "POST", "path": path, "payload": invalid}, http_call,
                         lambda value, error: error is None and value["status"] in (400, 422) and value["body"]["detail"]["code"] == "INVALID_INPUT",
                         "非法参数返回400/422及 INVALID_INPUT，不冒充无结果", "in-process API")
        if model_call.call_count:
            raise AssertionError("测试不允许调用模型")
    summary = {"result": "PASS" if all(c["passed"] for c in cases) else "FAIL", "mode": "live_crossref" if args.live else "offline_http_fixture",
               "tool": selected, "count": len(cases), "passed": sum(c["passed"] for c in cases), "model_calls": 0,
               "at": datetime.now().isoformat(timespec="seconds"), "artifacts": str(run),
               "notice": "Default search uses explicit synthetic HTTP fixtures; --live uses real Crossref only for normal/changed and their chain. Faults are injected.",
               "cases": [{"tool": c["tool"], "case": c["case"], "passed": c["passed"], "basis": c["basis"]} for c in cases]}
    save(run / "summary.json", summary)
    save(args.output.resolve() / "latest.json", summary)
    report(f"RESULT: {summary['result']} ({summary['passed']}/{len(cases)} checks)")
    report(f"ARTIFACTS: {run}")
    (run / "console.txt").write_text("\n".join(console) + "\n", encoding="utf-8")
    return 0 if summary["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

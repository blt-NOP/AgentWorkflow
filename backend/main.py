"""网页入口：只做参数校验、接口映射和静态文件服务。"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from . import agent, memory, model, library, dialogue, tools
from .tool_contracts import ToolError

app = FastAPI(title="论文 idea 助手")


class Facts(BaseModel):
    model_config = {"extra": "forbid"}
    direction: str | None = Field(default=None, max_length=1000)
    claim: str | None = Field(default=None, max_length=2000)
    compute: str | None = Field(default=None, max_length=1000)
    weeks: int | None = Field(default=None, ge=1, le=520)
    dataset: str | None = Field(default=None, max_length=1000)


class ChatInput(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=10000)
    facts: Facts = Field(default_factory=Facts)
    search: str | None = Field(default=None, max_length=500)
    use_model: bool = False
    skill: str | None = None
    choice_id: str | None = None


class Paper(BaseModel):
    paper_id: str = ""
    title: str = Field(min_length=1, max_length=1000)
    year: int | None = Field(default=None, ge=1000, le=2200)
    doi: str = Field(default="", max_length=1000)
    abstract: str = Field(default="", max_length=50000)
    notes: str = Field(default="", max_length=10000)


class DialogueInput(BaseModel):
    facts: Facts = Field(default_factory=Facts)
    answers: dict[str, str] = Field(default_factory=dict)
    message: str = Field(default="讨论科研选题", min_length=1, max_length=10000)
    skill: str = "research-dialogue"
    use_model: bool = False
    evidence: dict | None = None
    history: list[dict] = Field(default_factory=list)


class SearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=3, ge=1, le=20)


class EvidenceInput(BaseModel):
    papers: list[Paper]
    facts: Facts = Field(default_factory=Facts)


@app.exception_handler(ToolError)
def tool_error(request: Request, error: ToolError):
    status = {"TIMEOUT": 504, "NETWORK_ERROR": 502, "EXTERNAL_ERROR": 502,
              "INVALID_RESPONSE": 502, "MODEL_ERROR": 502, "INVALID_SKILL": 500}.get(error.code, 400)
    return JSONResponse(status_code=status, content={"detail": {
        "code": error.code, "message": error.message, "retryable": error.retryable}})


@app.exception_handler(RequestValidationError)
def invalid_schema(request: Request, error: RequestValidationError):
    first = error.errors()[0]
    field = ".".join(str(part) for part in first["loc"])
    return JSONResponse(status_code=422, content={"detail": {
        "code": "INVALID_INPUT", "message": f"{field}: {first['msg']}", "retryable": False}})


@app.exception_handler(ValueError)
def invalid_input(request: Request, error: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(error)})


@app.get("/api/health")
def health():
    return {"status": "ok", "model_configured": model.configured()}


@app.post("/api/chat")
def chat(data: ChatInput):
    try:
        return agent.run_turn(data.session_id, data.message, data.facts.model_dump(exclude_unset=True),
                              data.search, data.use_model, skill=data.skill, choice_id=data.choice_id)
    except ValueError:
        raise
    except Exception as error:
        print(f"[失败] {type(error).__name__}", flush=True)
        raise HTTPException(502, "本轮执行失败，请检查终端日志、网络及 .env 配置。") from error


@app.get("/api/sessions")
def sessions():
    return memory.list_sessions()


@app.get("/api/sessions/{session_id}")
def session(session_id: str):
    return memory.load(session_id)


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    memory.delete(session_id)
    return {"deleted": session_id}


@app.get("/api/library")
def list_library(q: str = ""):
    return library.list_papers(q)


@app.get("/api/library/papers/{paper_id}")
def get_paper(paper_id: str):
    paper = library.get_paper(paper_id)
    if paper is None:
        raise HTTPException(404, "论文不存在")
    return paper


@app.post("/api/library/papers")
def save_paper(paper: Paper):
    return library.save_paper(paper.model_dump())


@app.put("/api/library/papers/{paper_id}")
def update_paper(paper_id: str, paper: Paper):
    if library.get_paper(paper_id) is None:
        raise HTTPException(404, "论文不存在")
    return library.save_paper(dict(paper.model_dump(), paper_id=paper_id))


@app.post("/api/library/import")
def import_papers(papers: list[Paper]):
    return library.import_papers([paper.model_dump() for paper in papers])


@app.delete("/api/library/papers/{paper_id}")
def delete_paper(paper_id: str):
    if not library.delete_paper(paper_id):
        raise HTTPException(404, "论文不存在")
    return {"deleted": paper_id}


@app.get("/api/skills")
def skills():
    return dialogue.list_skills()


@app.post("/api/tools/dialogue")
def dialogue_tool(data: DialogueInput):
    # 无会话副作用的工具测试入口，可不启动前端或模型。
    facts = data.facts.model_dump(exclude_unset=True)
    evidence = data.evidence if data.evidence is not None else tools.TOOL_REGISTRY["build_evidence"](library.list_papers(), facts)
    state = {"facts": facts, "answers": data.answers, "history": data.history, "evidence": evidence}
    return tools.TOOL_REGISTRY["research_dialogue"](state, data.message, data.skill, data.use_model)


@app.get("/api/tools")
def registered_tools():
    return [{"name": name, "entry": f"{function.__module__}.{function.__name__}"}
            for name, function in tools.TOOL_REGISTRY.items()]


@app.post("/api/tools/search")
def search_tool(data: SearchInput):
    return tools.TOOL_REGISTRY["search_papers"](data.query, data.limit)


@app.post("/api/tools/evidence")
def evidence_tool(data: EvidenceInput):
    return tools.TOOL_REGISTRY["build_evidence"]([paper.model_dump() for paper in data.papers],
                                                data.facts.model_dump(exclude_unset=True))


app.mount("/static", StaticFiles(directory=memory.ROOT / "frontend"), name="static")


@app.get("/")
def index():
    return FileResponse(memory.ROOT / "frontend" / "index.html")

"""网页入口：只做参数校验、接口映射和静态文件服务。"""
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
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
    request_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    session_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=10000)
    facts: Facts = Field(default_factory=Facts)
    search: str | None = Field(default=None, max_length=500)
    use_model: bool | None = None
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
              "INVALID_RESPONSE": 502, "MODEL_ERROR": 502, "INVALID_SKILL": 500,
              "FILE_TOO_LARGE": 413, "PDF_LIMIT": 413, "NO_TEXT": 422}.get(error.code, 400)
    return JSONResponse(status_code=status, content={"detail": {
        "code": error.code, "message": error.message, "retryable": error.retryable,
        "request_id": getattr(error, "request_id", None)}})


@app.exception_handler(RequestValidationError)
def invalid_schema(request: Request, error: RequestValidationError):
    first = error.errors()[0]
    field = ".".join(str(part) for part in first["loc"])
    return JSONResponse(status_code=422, content={"detail": {
        "code": "INVALID_INPUT", "message": f"{field}: {first['msg']}", "retryable": False}})


@app.exception_handler(ValueError)
def invalid_input(request: Request, error: ValueError):
    return JSONResponse(status_code=400, content={"detail": {"code": "INVALID_INPUT", "message": str(error),
        "retryable": False, "request_id": getattr(error, "request_id", None)}})


@app.get("/api/health")
def health():
    return {"status": "ok", "model_configured": model.configured(), "model_enabled": model.enabled()}


@app.post("/api/chat")
def chat(data: ChatInput):
    try:
        return agent.run_turn(data.session_id, data.message, data.facts.model_dump(exclude_unset=True),
                              data.search, data.use_model, skill=data.skill, choice_id=data.choice_id, request_id=data.request_id)
    except ValueError:
        raise
    except Exception as error:
        print(f"[失败] {type(error).__name__}", flush=True)
        raise HTTPException(502, {"code": "EXECUTION_ERROR", "message": "本轮执行失败，请按request_id检查日志后重试。",
                                   "request_id": getattr(error, "request_id", None), "retryable": True}) from error


@app.post("/api/chat/stream", response_class=StreamingResponse, responses={200: {
    "description": "按顺序发送SSE事件，completed交付最终JSON状态，failed表示执行失败",
    "content": {"text/event-stream": {"schema": {"type": "string"}}}}})
def chat_stream(data: ChatInput):
    """SSE：运行期间推送阶段事件和模型reply草稿，completed交付已保存的最终状态。"""
    from .events import stream_turn
    memory.session_path(data.session_id)
    if not data.message.strip():
        raise ValueError("消息不能为空")
    arguments = data.model_dump(exclude={"facts"})
    arguments["facts"] = data.facts.model_dump(exclude_unset=True)
    return StreamingResponse(stream_turn(arguments), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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


@app.post("/api/tools/parse-pdf")
def parse_pdf_tool(file: UploadFile = File(...), start_page: int = Form(1, ge=1),
                   end_page: int | None = Form(None, ge=1)):
    """multipart 上传 PDF，返回带页码原文和可供文库/材料工具使用的 paper；不自动入库。"""
    from .pdf_parser import MAX_BYTES
    try:
        content = file.file.read(MAX_BYTES + 1)
        return tools.TOOL_REGISTRY["parse_paper_pdf"](content, file.filename or "paper.pdf", start_page, end_page)
    finally:
        file.file.close()


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

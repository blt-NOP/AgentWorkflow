"""网页入口：只做参数校验、接口映射和静态文件服务。"""
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from . import agent, memory, model

app = FastAPI(title="论文 idea 助手")


class Facts(BaseModel):
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


class Paper(BaseModel):
    paper_id: str = ""
    title: str = Field(min_length=1, max_length=1000)
    year: int | None = None
    doi: str = ""
    abstract: str = Field(default="", max_length=50000)


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
                              data.search, data.use_model)
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
def library():
    return memory.library()


@app.post("/api/library/papers")
def save_paper(paper: Paper):
    data = paper.model_dump()
    data["paper_id"] = data["paper_id"] or str(uuid4())
    papers = [p for p in memory.library() if p["paper_id"] != data["paper_id"]]
    memory.save_library(papers + [data])
    return data


@app.delete("/api/library/papers/{paper_id}")
def delete_paper(paper_id: str):
    memory.save_library([p for p in memory.library() if p["paper_id"] != paper_id])
    return {"deleted": paper_id}


app.mount("/static", StaticFiles(directory=memory.ROOT / "frontend"), name="static")


@app.get("/")
def index():
    return FileResponse(memory.ROOT / "frontend" / "index.html")

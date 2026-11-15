from fastapi import APIRouter, HTTPException, Request

from .schemas import ChatRequest, HealthResponse

router = APIRouter(prefix="/api")


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    return HealthResponse(
        status="ok",
        stage="scaffold",
        model_configured=request.app.state.settings.model_configured,
    )


@router.post("/chat", status_code=501)
def chat(payload: ChatRequest) -> None:
    # Keep the future API contract visible without fabricating agent output.
    raise HTTPException(
        status_code=501,
        detail={
            "code": "AGENT_NOT_IMPLEMENTED",
            "message": "项目框架已就绪，模型、工具与多轮记忆尚未接入；本次消息未保存。",
            "session_id": str(payload.session_id),
        },
    )

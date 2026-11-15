from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    session_id: UUID
    message: str = Field(min_length=1, max_length=10000)

    @field_validator("message")
    @classmethod
    def reject_blank_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value.strip()


class HealthResponse(BaseModel):
    status: str
    stage: str
    model_configured: bool

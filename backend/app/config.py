"""Local configuration. Never serialize Settings into public responses."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


@dataclass(frozen=True)
class Settings:
    model_base_url: str
    model_name: str
    model_api_key: str = field(repr=False)
    model_timeout_seconds: int
    agent_max_steps: int
    tool_timeout_seconds: int
    data_dir: Path

    @property
    def model_configured(self) -> bool:
        return all((self.model_base_url, self.model_name, self.model_api_key))


def load_settings(env_file: Path | None = None) -> Settings:
    load_dotenv(env_file if env_file is not None else PROJECT_ROOT / ".env", override=False)
    data_dir = Path(os.getenv("DATA_DIR", "data"))
    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / data_dir
    return Settings(
        model_base_url=os.getenv("MODEL_BASE_URL", "").strip(),
        model_name=os.getenv("MODEL_NAME", "").strip(),
        model_api_key=os.getenv("MODEL_API_KEY", "").strip(),
        model_timeout_seconds=positive_int("MODEL_TIMEOUT_SECONDS", 60),
        agent_max_steps=positive_int("AGENT_MAX_STEPS", 8),
        tool_timeout_seconds=positive_int("TOOL_TIMEOUT_SECONDS", 30),
        data_dir=data_dir.resolve(),
    )
